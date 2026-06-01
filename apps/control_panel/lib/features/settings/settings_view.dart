import 'dart:io';

// Hide Material's ThemeMode to disambiguate from our wire-aligned
// domain ThemeMode in common_enums.dart. Settings code uses ours.
import 'package:flutter/material.dart' hide ThemeMode;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/l10n/app_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
    final settings = ref.watch(settingsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.settingsTitle)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SectionHeader(l10n.settingsGroupDisplay, key: _displayKey),
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

          _SectionHeader(l10n.settingsGroupNotifications,
              key: _notificationsKey),
          SwitchListTile(
            title: Text(l10n.settingsGroupSimilarLabel),
            subtitle: Text(l10n.settingsGroupSimilarSubtitle),
            value: settings.notificationsGrouping,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(notificationsGrouping: v),
                    ),
          ),
          SwitchListTile(
            title: Text(l10n.settingsOsNativeLabel),
            subtitle: Text(l10n.settingsOsNativeSubtitle),
            value: settings.osNativeNotifications,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(osNativeNotifications: v),
                    ),
          ),
          const Divider(height: 32),

          _SectionHeader(l10n.settingsGroupConnection, key: _connectionKey),
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

          _SectionHeader(l10n.settingsGroupPrivacy, key: _privacyKey),
          SwitchListTile(
            title: Text(l10n.settingsDebugLoggingLabel),
            subtitle: Text(l10n.settingsDebugLoggingSubtitle),
            value: settings.debugLogging,
            onChanged: (v) =>
                ref.read(settingsProvider.notifier).update(
                      (s) => s.copyWith(debugLogging: v),
                    ),
          ),
          ListTile(
            leading: const Icon(Icons.folder_open),
            title: Text(l10n.settingsOpenLogFolder),
            subtitle: Text(l10n.settingsOpenLogFolderSubtitle),
            onTap: () => _onOpenLogFolder(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.archive),
            title: Text(l10n.settingsCopyDiagnostics),
            subtitle: Text(l10n.settingsCopyDiagnosticsSubtitle),
            onTap: () => _onCopyDiagnostics(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.medical_services_outlined),
            title: Text(l10n.settingsRunDoctor),
            subtitle: Text(l10n.settingsRunDoctorSubtitle),
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
    final l10n = AppLocalizations.of(context);
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
        title: Text(l10n.settingsDiagnosticsPreviewTitle),
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
            child: Text(l10n.settingsClose),
          ),
          FilledButton(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: previewText));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(l10n.settingsBundlePreviewCopied)),
                );
                Navigator.of(context).pop();
              }
            },
            child: Text(l10n.settingsCopyPreviewToClipboard),
          ),
        ],
      ),
    );
  }

  Future<void> _onRunDoctor(BuildContext context, WidgetRef ref) async {
    final l10n = AppLocalizations.of(context);
    final paths = ref.read(appPathsProvider);
    final report = await _runDoctor(ref, paths);
    if (!context.mounted) return;
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(l10n.settingsDoctorReportTitle),
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
            child: Text(l10n.settingsClose),
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
    final l10n = AppLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          const SizedBox(width: 16),
          Text(l10n.settingsThemeLabel),
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
    final l10n = AppLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          const SizedBox(width: 16),
          Text(l10n.settingsDensityLabel),
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
    final l10n = AppLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: TextField(
        controller: _ctrl,
        decoration: InputDecoration(
          labelText: l10n.settingsDaemonSocketPathLabel,
          helperText: l10n.settingsDaemonSocketPathHelper,
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
    final l10n = AppLocalizations.of(context);
    final compat = ref.watch(runtimeStateProvider).contractCompat;
    final daemonV = compat?.daemonVersion.toString() ?? 'unknown';
    final appMin = compat?.appMinimum.toString() ?? '1.0';
    return ListTile(
      leading: const Icon(Icons.handshake_outlined),
      title: Text(l10n.settingsContractVersionLabel),
      subtitle: Text(
        l10n.settingsContractVersionValue(daemonV, appMin) +
            (compat == null ? l10n.settingsContractVersionBootstrapPending : ''),
      ),
    );
  }
}
