import 'dart:io';

// Hide Material's ThemeMode to disambiguate from our wire-aligned
// domain ThemeMode in common_enums.dart. Settings code uses ours.
import 'package:flutter/material.dart' hide ThemeMode;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/persistence/paths.dart';
import '../../core/providers.dart';
import '../../domain/models/common_enums.dart';
import '../../ui/widgets/safe_url_launcher.dart';
import '../shell/version_display.dart';
import 'diagnostics_bundle.dart';
import 'doctor.dart';
import 'providers.dart';

/// FR-009 Settings surface. T143 (Phase 9).
///
/// Aggregates every required entry: daemon socket path, contract
/// version display, notifications grouping toggle, OS-native
/// notification integration toggle, theme + density, "Open log
/// folder" + "Copy diagnostics bundle" affordances, and the
/// doctor / preflight action.
///
/// One Settings widget is registered for all 5 sub-view routes
/// (display / notifications / connection / privacy / diagnostics)
/// — the page renders all sections inline and the sub-view id
/// drives the initial section scroll target.
class SettingsView extends ConsumerWidget {
  const SettingsView({super.key, this.initialSection = 'display'});

  final String initialSection;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SectionHeader('Display'),
          _ThemeSelector(value: settings.theme, onChanged: (v) {
            ref.read(settingsProvider.notifier).update(
                  (s) => s.copyWith(theme: v),
                );
          }),
          _DensitySelector(value: settings.density, onChanged: (v) {
            ref.read(settingsProvider.notifier).update(
                  (s) => s.copyWith(density: v),
                );
          }),
          const Divider(height: 32),

          _SectionHeader('Notifications'),
          SwitchListTile(
            title: const Text('Group similar notifications'),
            subtitle: const Text(
              'FR-057: collapse N ≥ 3 consecutive low-severity '
              'notifications sharing event_class + agent_id within '
              '60 s. High and critical never grouped.',
            ),
            value: settings.notificationsGrouping,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(notificationsGrouping: v),
                    ),
          ),
          SwitchListTile(
            title: const Text('OS-native notifications'),
            subtitle: const Text(
              'FR-058: opt-in. When enabled, the app may fire a '
              'system notification for high/critical severities.',
            ),
            value: settings.osNativeNotifications,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(osNativeNotifications: v),
                    ),
          ),
          const Divider(height: 32),

          _SectionHeader('Connection'),
          _SocketPathField(
            value: settings.daemonSocketPath,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(daemonSocketPath: v),
                    ),
          ),
          const SizedBox(height: 8),
          const _ContractVersionDisplay(),
          const SizedBox(height: 8),
          const VersionDisplayTile(),
          const Divider(height: 32),

          _SectionHeader('Privacy + diagnostics'),
          SwitchListTile(
            title: const Text('Debug logging'),
            subtitle: const Text(
              'R-26: when enabled, debug-level events are written '
              'to the rotating log file. Always local, never uploaded.',
            ),
            value: settings.debugLogging,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(debugLogging: v),
                    ),
          ),
          ListTile(
            leading: const Icon(Icons.folder_open),
            title: const Text('Open log folder'),
            subtitle: const Text('FR-074: rotating log file location.'),
            onTap: () => _onOpenLogFolder(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.archive),
            title: const Text('Copy diagnostics bundle'),
            subtitle: const Text(
              'FR-074 + R-31: zips logs (redacted) + doctor report + '
              'context. Operator picks save destination via OS picker.',
            ),
            onTap: () => _onCopyDiagnostics(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.medical_services_outlined),
            title: const Text('Run doctor / preflight'),
            subtitle: const Text(
              'FR-009: six checks (socket reachable, peer UID, '
              'contract version, app-data writable, log file '
              'writable, OS notification permission).',
            ),
            onTap: () => _onRunDoctor(context, ref),
          ),
        ],
      ),
    );
  }

  Future<void> _onOpenLogFolder(BuildContext context, WidgetRef ref) async {
    final paths = ref.read(appPathsProvider);
    await SafeUrlLauncher.openFile(context, paths.logsDir.path);
  }

  Future<void> _onCopyDiagnostics(BuildContext context, WidgetRef ref) async {
    final paths = ref.read(appPathsProvider);
    final doctor = await _runDoctor(ref, paths);
    final bundle = DiagnosticsBundle(
      paths: paths,
      appVersion: '0.1.0+1',
      contractVersion: const ContractVersion(1, 0),
      socketPath: ref.read(settingsProvider).daemonSocketPath,
      osUser: Platform.environment['USER'] ?? 'unknown',
      doctorReport: doctor,
      sessionStart: DateTime.now().toUtc(),
    );
    final preview = await bundle.buildPreview();
    if (!context.mounted) return;
    final previewText = preview.toString();
    await showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Diagnostics bundle preview'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Text(
              previewText,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
          FilledButton(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: previewText));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Bundle preview copied')),
                );
                Navigator.of(context).pop();
              }
            },
            child: const Text('Copy preview to clipboard'),
          ),
        ],
      ),
    );
  }

  Future<void> _onRunDoctor(BuildContext context, WidgetRef ref) async {
    final paths = ref.read(appPathsProvider);
    final report = await _runDoctor(ref, paths);
    if (!context.mounted) return;
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Doctor report'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Text(
              report.toString(),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  Future<DoctorReport> _runDoctor(WidgetRef ref, AppPaths paths) {
    return Doctor(
      paths: paths,
      settingsRepo: ref.read(settingsRepositoryProvider),
      runtimeCompat: null,
      osNotificationsEnabled: ref.read(settingsProvider).osNativeNotifications,
    ).run();
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);
  final String title;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(title, style: Theme.of(context).textTheme.titleMedium),
    );
  }
}

class _ThemeSelector extends StatelessWidget {
  const _ThemeSelector({required this.value, required this.onChanged});
  final ThemeMode value;
  final ValueChanged<ThemeMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          const SizedBox(width: 16),
          const Text('Theme'),
          const SizedBox(width: 24),
          for (final m in ThemeMode.values)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(m.wireValue),
                selected: value == m,
                onSelected: (_) => onChanged(m),
              ),
            ),
        ],
      ),
    );
  }
}

class _DensitySelector extends StatelessWidget {
  const _DensitySelector({required this.value, required this.onChanged});
  final DensityMode value;
  final ValueChanged<DensityMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          const SizedBox(width: 16),
          const Text('Density'),
          const SizedBox(width: 24),
          for (final m in DensityMode.values)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(m.wireValue),
                selected: value == m,
                onSelected: (_) => onChanged(m),
              ),
            ),
        ],
      ),
    );
  }
}

class _SocketPathField extends StatefulWidget {
  const _SocketPathField({required this.value, required this.onChanged});
  final String value;
  final ValueChanged<String> onChanged;

  @override
  State<_SocketPathField> createState() => _SocketPathFieldState();
}

class _SocketPathFieldState extends State<_SocketPathField> {
  late final TextEditingController _ctrl =
      TextEditingController(text: widget.value);

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: TextField(
        controller: _ctrl,
        decoration: const InputDecoration(
          labelText: 'Daemon socket path',
          helperText:
              'FR-001: local Unix socket only. Restart required to apply.',
        ),
        onSubmitted: widget.onChanged,
      ),
    );
  }
}

class _ContractVersionDisplay extends StatelessWidget {
  const _ContractVersionDisplay();

  @override
  Widget build(BuildContext context) {
    // Real `app_contract_version` lives on DaemonSession.bootstrap;
    // for the MVP Settings page we display the app's compiled-in
    // minimum. The live daemon version surfaces in the Dashboard
    // banner + per-surface degradation states (FR-002).
    return const ListTile(
      leading: Icon(Icons.handshake_outlined),
      title: Text('Contract version'),
      subtitle: Text(
        'App minimum: 1.0 (per ContractCompatMap.appMinimum). '
        'Live daemon version shown on the Dashboard.',
      ),
    );
  }
}
