import 'package:flutter/material.dart';

/// Global command palette opened with Ctrl/Cmd+K. T035 + research R-20.
///
/// Per FR-075 + R-20, the palette MUST cover at minimum:
///   - Project switching
///   - Workspace switching
///   - Sub-view jumping
///   - Doctor invocation
///   - Every documented primary action
///
/// MVP implementation: typed command registry + fuzzy-match filter +
/// keyboard-navigable list. Concrete commands are registered by each
/// feature module via [CommandRegistry.register] and live-update as
/// new modules load.
class CommandRegistry {
  CommandRegistry._();

  static final List<PaletteCommand> _commands = [];

  static void register(PaletteCommand command) {
    _commands.removeWhere((c) => c.id == command.id);
    _commands.add(command);
  }

  static void unregister(String id) {
    _commands.removeWhere((c) => c.id == id);
  }

  static List<PaletteCommand> snapshot() => List.unmodifiable(_commands);
}

/// A single command surfaced in the palette.
class PaletteCommand {
  const PaletteCommand({
    required this.id,
    required this.label,
    required this.category,
    required this.invoke,
    this.shortcut,
    this.contextual = false,
  });

  final String id;
  final String label;
  final String category;
  final Future<void> Function(BuildContext context) invoke;
  final String? shortcut;

  /// If true, the command is only shown in contexts where it's relevant
  /// (e.g. "Run current entrypoint" only when a project + entrypoint is
  /// active). Per `keyboard-navigation.md` CHK008.
  final bool contextual;
}

/// Command palette dialog.
class CommandPalette extends StatefulWidget {
  const CommandPalette({super.key});

  static Future<void> show(BuildContext context) async {
    await showDialog<void>(
      context: context,
      builder: (_) => const Dialog(child: CommandPalette()),
    );
  }

  @override
  State<CommandPalette> createState() => _CommandPaletteState();
}

class _CommandPaletteState extends State<CommandPalette> {
  final _controller = TextEditingController();
  late List<PaletteCommand> _all;
  late List<PaletteCommand> _filtered;

  @override
  void initState() {
    super.initState();
    _all = CommandRegistry.snapshot();
    _filtered = _all;
    _controller.addListener(_onQueryChanged);
  }

  @override
  void dispose() {
    _controller.removeListener(_onQueryChanged);
    _controller.dispose();
    super.dispose();
  }

  void _onQueryChanged() {
    final q = _controller.text.toLowerCase().trim();
    setState(() {
      if (q.isEmpty) {
        _filtered = _all;
      } else {
        _filtered = _all.where((c) => _fuzzyMatch(c, q)).toList();
      }
    });
  }

  bool _fuzzyMatch(PaletteCommand c, String q) {
    final hay = '${c.label} ${c.category} ${c.id}'.toLowerCase();
    var qi = 0;
    for (var i = 0; i < hay.length && qi < q.length; i++) {
      if (hay[i] == q[qi]) qi++;
    }
    return qi == q.length;
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 560,
      height: 420,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _controller,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'Type a command…',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              itemCount: _filtered.length,
              itemBuilder: (context, i) {
                final cmd = _filtered[i];
                return ListTile(
                  title: Text(cmd.label),
                  subtitle: Text(cmd.category),
                  trailing: cmd.shortcut == null
                      ? null
                      : Text(cmd.shortcut!,
                          style: Theme.of(context).textTheme.bodySmall),
                  onTap: () async {
                    Navigator.of(context).pop();
                    await cmd.invoke(context);
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
