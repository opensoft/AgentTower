import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/settings_model.dart';
import '../../core/providers.dart';
import 'settings_repository.dart';

/// Riverpod providers for the Settings surface. T143 (Phase 9).

final settingsRepositoryProvider = Provider<SettingsRepository>((ref) {
  // Built once per process — wraps the shared UxStateRepository. The default
  // socket path comes from defaultSocketPathProvider (overridden in main.dart
  // with the bootstrap-resolved path) so a fresh-install Settings value + the
  // FR-009 Doctor check target the SAME socket the app actually connects to —
  // not the old hard-coded `/var/run/agenttower/app.sock` that disagreed with
  // both the bootstrap path and the CLI/daemon default.
  return SettingsRepository(
    uxState: ref.read(uxStateRepositoryProvider),
    defaultSocketPath: ref.read(defaultSocketPathProvider),
  );
});

/// Live settings — operator edits flow through this Notifier so the
/// MaterialApp + Notifications panel + other surfaces react to
/// changes immediately without waiting for the next launch.
final settingsProvider =
    NotifierProvider<SettingsNotifier, Settings>(SettingsNotifier.new);

class SettingsNotifier extends Notifier<Settings> {
  @override
  Settings build() {
    return ref.read(settingsRepositoryProvider).load();
  }

  void update(Settings Function(Settings) mutate) {
    final next = mutate(state);
    state = next;
    ref.read(settingsRepositoryProvider).save(next);
  }
}
