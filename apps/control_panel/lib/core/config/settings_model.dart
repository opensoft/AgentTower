import '../../domain/models/common_enums.dart';

/// Settings model. T024 (Phase 2 Foundational).
///
/// Matches data-model.md §2.1 SettingsValues. Per Round-3 R-25, Settings
/// surface is grouped into 5 sections:
///   Display | Notifications | Connection | Privacy | Diagnostics
///
/// Mutations apply live (no restart). Socket-path change triggers
/// immediate re-bootstrap of the daemon session. OS-native notification
/// first-enable invokes the platform permission prompt.
///
/// Persisted via [UxStateRepository] under `settings:` key. No separate
/// settings file — Settings live inside the single `ux-state.json`.
class Settings {
  const Settings({
    required this.daemonSocketPath,
    required this.theme,
    required this.density,
    required this.notificationsGrouping,
    required this.osNativeNotifications,
    required this.debugLogging,
  });

  /// FR-009 + Round-3 R-25 default values.
  factory Settings.defaults({required String defaultSocketPath}) => Settings(
        daemonSocketPath: defaultSocketPath,
        theme: ThemeMode.system,
        density: DensityMode.comfortable,
        notificationsGrouping: true, // FR-057 default
        osNativeNotifications: false, // FR-058 opt-in
        debugLogging: false, // R-26: debug toggleable from Settings
      );

  factory Settings.fromJson(Map<String, dynamic> json) {
    return Settings(
      daemonSocketPath: json['daemon_socket_path'] as String,
      theme: ThemeMode.fromWire(json['theme'] as String),
      density: DensityMode.fromWire(json['density'] as String),
      notificationsGrouping: json['notifications_grouping'] as bool,
      osNativeNotifications: json['os_native_notifications'] as bool,
      debugLogging: (json['debug_logging'] as bool?) ?? false,
    );
  }

  final String daemonSocketPath;
  final ThemeMode theme;
  final DensityMode density;
  final bool notificationsGrouping;
  final bool osNativeNotifications;
  final bool debugLogging;

  Map<String, dynamic> toJson() => {
        'daemon_socket_path': daemonSocketPath,
        'theme': theme.wireValue,
        'density': density.wireValue,
        'notifications_grouping': notificationsGrouping,
        'os_native_notifications': osNativeNotifications,
        'debug_logging': debugLogging,
      };

  Settings copyWith({
    String? daemonSocketPath,
    ThemeMode? theme,
    DensityMode? density,
    bool? notificationsGrouping,
    bool? osNativeNotifications,
    bool? debugLogging,
  }) =>
      Settings(
        daemonSocketPath: daemonSocketPath ?? this.daemonSocketPath,
        theme: theme ?? this.theme,
        density: density ?? this.density,
        notificationsGrouping:
            notificationsGrouping ?? this.notificationsGrouping,
        osNativeNotifications:
            osNativeNotifications ?? this.osNativeNotifications,
        debugLogging: debugLogging ?? this.debugLogging,
      );
}
