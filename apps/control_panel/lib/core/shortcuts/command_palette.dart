import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Global command palette opened with Ctrl/Cmd+K. T035 + research R-20.
///
/// Per FR-075 + R-20, the palette MUST cover at minimum:
///   - Project switching
///   - Workspace switching
///   - Sub-view jumping
///   - Doctor invocation
///   - Every documented primary action
///
/// Implementation: feature modules call
/// `ref.read(commandRegistryProvider.notifier).register(cmd)` during their
/// own `build()` (typically inside a `Consumer` at workspace mount time).
/// The palette dialog reads the current list via `ref.watch(commandRegistry
/// Provider)` so a new module's commands appear without a hot-restart.
///
/// The previous implementation used a process-static mutable list, which
/// review finding A3 flagged as: (a) untracked by Riverpod (palette would
/// not re-render when commands changed), and (b) leaky across widget tests
/// in the same isolate. Both are fixed here.

/// Riverpod-managed command registry. Read the current list with
/// `ref.watch(commandRegistryProvider)`; mutate via
/// `ref.read(commandRegistryProvider.notifier).register(...)`.
final commandRegistryProvider =
    NotifierProvider<CommandRegistryNotifier, List<PaletteCommand>>(
  CommandRegistryNotifier.new,
);

class CommandRegistryNotifier extends Notifier<List<PaletteCommand>> {
  @override
  List<PaletteCommand> build() => const [];

  /// Idempotent on `id` — a re-registration with the same id replaces
  /// the previous entry (useful when a feature widget rebuilds).
  void register(PaletteCommand command) {
    final without = state.where((c) => c.id != command.id).toList(growable: true)
      ..add(command);
    state = List.unmodifiable(without);
  }

  void unregister(String id) {
    state = List.unmodifiable(state.where((c) => c.id != id));
  }

  void clear() {
    state = const [];
  }
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
class CommandPalette extends ConsumerStatefulWidget {
  const CommandPalette({super.key});

  /// Convenience opener — feature modules trigger this from the Ctrl/Cmd+K
  /// keyboard shortcut binding in `shortcuts.dart`.
  static Future<void> show(BuildContext context) async {
    await showDialog<void>(
      context: context,
      builder: (_) => const Dialog(child: CommandPalette()),
    );
  }

  @override
  ConsumerState<CommandPalette> createState() => _CommandPaletteState();
}

class _CommandPaletteState extends ConsumerState<CommandPalette> {
  final _controller = TextEditingController();
  String _query = '';

  @override
  void initState() {
    super.initState();
    _controller.addListener(_onQueryChanged);
  }

  @override
  void dispose() {
    _controller.removeListener(_onQueryChanged);
    _controller.dispose();
    super.dispose();
  }

  void _onQueryChanged() {
    setState(() => _query = _controller.text.toLowerCase().trim());
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
    final all = ref.watch(commandRegistryProvider);
    final filtered = _query.isEmpty
        ? all
        : all.where((c) => _fuzzyMatch(c, _query)).toList(growable: false);
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
              itemCount: filtered.length,
              itemBuilder: (context, i) {
                final cmd = filtered[i];
                return ListTile(
                  title: Text(cmd.label),
                  subtitle: Text(cmd.category),
                  trailing: cmd.shortcut == null
                      ? null
                      : Text(
                          cmd.shortcut!,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                  onTap: () async {
                    // Capture the Navigator BEFORE the awaited gap so we
                    // never reuse a `BuildContext` that may have been
                    // detached by the time `invoke` returns (D3 lint).
                    final nav = Navigator.of(context);
                    final paletteContext = context;
                    nav.pop();
                    if (!paletteContext.mounted) return;
                    await cmd.invoke(paletteContext);
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

