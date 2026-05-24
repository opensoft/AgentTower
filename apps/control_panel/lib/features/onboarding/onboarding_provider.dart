import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../domain/models/common_enums.dart';

/// Onboarding state + persistence wiring. T077-T079 (Phase 3 US1).
///
/// The 8 milestones in [OnboardingMilestone] each have an
/// automatically-detectable completion criterion (per F11):
///
///   daemonReachable        — `runtimeStateProvider` shows healthy
///   benchContainerCheck    — `containerListProvider` has ≥1 row
///   paneDiscoveryCheck     — `paneListProvider` has ≥1 row
///   firstPaneAdoption      — any pane in `discovered-and-registered`
///   firstAgentRegistration — `agentListProvider` has ≥1 row
///   firstLogAttachment     — any agent with `logAttachment == active`
///   firstDirectSend        — any queue row with sourceAgentId from app
///   firstRouteCreation     — `routeListProvider` has ≥1 row
///
/// Detection is best-effort and lives in [OnboardingProgressNotifier.
/// recheck], called whenever any of the watched providers updates.
/// Completion state is persisted via [UxStateRepository] under the
/// `onboarding` key per data-model §2.1.
class OnboardingProgressNotifier
    extends Notifier<Set<OnboardingMilestone>> {
  bool _skipped = false;

  @override
  Set<OnboardingMilestone> build() {
    final repo = ref.read(uxStateRepositoryProvider);
    final raw = (repo.current?['onboarding'] as Map<String, dynamic>?) ?? {};
    final wireValues = (raw['completed_milestones'] as List?)
            ?.whereType<String>()
            .toList() ??
        const <String>[];
    _skipped = raw['skipped'] as bool? ?? false;
    return {
      for (final w in wireValues)
        if (OnboardingMilestone.values.any((m) => m.wireValue == w))
          OnboardingMilestone.fromWire(w),
    };
  }

  bool get skipped => _skipped;

  bool isComplete(OnboardingMilestone m) => state.contains(m);

  void markComplete(OnboardingMilestone m) {
    if (state.contains(m)) return;
    state = {...state, m};
    _persist();
  }

  /// Mark all 8 milestones complete; used by the "Skip" affordance. The
  /// `skipped` flag stays distinct from natural completion so the FR-010
  /// nudges + dashboard tile can render different copy ("you skipped
  /// onboarding" vs "you finished onboarding").
  void skip() {
    _skipped = true;
    state = OnboardingMilestone.values.toSet();
    _persist();
  }

  void _persist() {
    final repo = ref.read(uxStateRepositoryProvider);
    final current = Map<String, dynamic>.from(repo.current ?? const {});
    current['onboarding'] = {
      'completed_milestones':
          state.map((m) => m.wireValue).toList(growable: false),
      'skipped': _skipped,
    };
    repo.update(current);
  }
}

final onboardingProgressProvider = NotifierProvider<
    OnboardingProgressNotifier, Set<OnboardingMilestone>>(
  OnboardingProgressNotifier.new,
);
