import 'dart:io';

// Hide Material's ThemeMode to disambiguate from our wire-aligned
// domain ThemeMode in common_enums.dart. Settings code uses ours.
import 'package:flutter/material.dart' hide ThemeMode;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/persistence/paths.dart';
import '../../core/providers.dart';
import '../../core/update/release_feed_check.dart';
import '../../domain/models/common_enums.dart';
import '../../ui/widgets/safe_url_launcher.dart';
import '../shell/runtime_state_provider.dart';
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
///
/// Round-4 analyze U-N1 (2026-05-24): SettingsView is now
/// stateful so `initialSection` can drive a `Scrollable.ensureVisible`
/// to the matching section after first frame, instead of always
/// landing the operator at the top of the page.
class SettingsView extends ConsumerStatefulWidget {
  const SettingsView({super.key, this.initialSection = 'display'});

  final String initialSection;

  @override
  ConsumerState<SettingsView> createState() => _SettingsViewState();
}

class _SettingsViewState extends ConsumerState<SettingsView> {
  final _displayKey = GlobalKey();
  final _notificationsKey = GlobalKey();
  final _connectionKey = GlobalKey();
  final _privacyKey = GlobalKey();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToInitial());
  }

  void _scrollToInitial() {
    final key = switch (widget.initialSection) {
      'notifications' => _notificationsKey,
      'connection' => _connectionKey,
      'privacy' || 'diagnostics' => _privacyKey,
      _ => _displayKey,
    };
    final ctx = key.currentContext;
    if (ctx != null) {
      Scrollable.ensureVisible(
        ctx,
        duration: const Duration(milliseconds: 250),
        alignment: 0.0,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SectionHeader('Display', key: _displayKey),
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

          _SectionHeader('Notifications', key: _notificationsKey),
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

          _SectionHeader('Connection', key: _connectionKey),
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

          _SectionHeader('Privacy + diagnostics', key: _privacyKey),
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
    // Round-3 analyze I1: read live app version + daemon contract
    // version instead of hardcoding. installedAppVersionProvider is
    // the single source of truth for the FR-068 version string.
    final installedVersion = ref.read(installedAppVersionProvider);
    final compat = ref.read(runtimeStateProvider).contractCompat;
    final daemonContract =
        compat?.daemonVersion ?? const ContractVersion(1, 0);
    final bundle = DiagnosticsBundle(
      paths: paths,
      appVersion: installedVersion,
      contractVersion: daemonContract,
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
  const _SectionHeader(this.title, {super.key});
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

class _ContractVersionDisplay extends ConsumerWidget {
  const _ContractVersionDisplay();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Round-3 analyze I2: read live runtime contract-compat so
    // operators can diagnose mismatches from Settings instead of
    // having to navigate back to the Dashboard.
    final compat = ref.watch(runtimeStateProvider).contractCompat;
    final daemonV = compat?.daemonVersion.toString() ?? 'unknown';
    final appMin = compat?.appMinimum.toString() ?? '1.0';
    return ListTile(
      leading: const Icon(Icons.handshake_outlined),
      title: const Text('Contract version'),
      subtitle: Text(
        'Daemon advertises: $daemonV · App requires ≥ $appMin'
        '${compat == null ? " (bootstrap pending or unreachable)" : ""}',
      ),
    );
  }
}
