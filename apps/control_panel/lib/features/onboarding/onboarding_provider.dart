import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../domain/models/common_enums.dart';
import '../../features/shell/runtime_state_provider.dart';
import '../agent_ops/providers.dart';

/// Onboarding state + persistence + auto-detection wiring.
/// T077-T079 (Phase 3 US1) + review fix C9.
///
/// The 8 milestones in [OnboardingMilestone] each have an
/// automatically-detectable completion criterion (per FR-010 + F11).
/// This Notifier `ref.watch`es every provider it depends on; whenever
/// any watched provider re-emits, [build] recomputes which milestones
/// are now satisfied and merges them into the persisted set.
///
/// Auto-detection rules:
///
///   daemonReachable        — runtime kind ∈ {runtimeHealthyEmpty,
///                            runtimeHealthyPopulated, runtimeDegraded}
///   benchContainerCheck    — containerListProvider has ≥1 row
///   paneDiscoveryCheck     — paneListProvider has ≥1 row
///   firstPaneAdoption      — any pane state == discoveredAndRegistered
///   firstAgentRegistration — agentListProvider has ≥1 row
///   firstLogAttachment     — any agent.logAttachment == active
///   firstDirectSend        — queueListProvider has ≥1 row
///   firstRouteCreation     — routeListProvider has ≥1 row
///
/// Per FR-010 the milestones are append-only (once auto-detected, they
/// stay completed even if the underlying state regresses — e.g.
/// removing an adopted agent doesn't un-tick "firstPaneAdoption").
///
/// Completion state is persisted via [UxStateRepository] under the
/// `onboarding` key per data-model §2.1, scoped per-OS-user.
class OnboardingProgressNotifier
    extends Notifier<Set<OnboardingMilestone>> {
  bool _skipped = false;
  Set<OnboardingMilestone> _persistedSnapshot = const {};

  @override
  Set<OnboardingMilestone> build() {
    // Load persisted state once per build.
    final repo = ref.read(uxStateRepositoryProvider);
    final raw = (repo.current?['onboarding'] as Map<String, dynamic>?) ??
        const <String, dynamic>{};
    final wireValues = (raw['completed_milestones'] as List?)
            ?.whereType<String>()
            .toList() ??
        const <String>[];
    _skipped = raw['skipped'] as bool? ?? false;
    final persisted = <OnboardingMilestone>{
      for (final w in wireValues)
        if (OnboardingMilestone.values.any((m) => m.wireValue == w))
          OnboardingMilestone.fromWire(w),
    };
    _persistedSnapshot = Set.of(persisted);

    // Watch every provider that drives a milestone. Each `ref.watch` here
    // re-runs `build` whenever the watched value changes — the union of
    // persisted milestones + freshly-detected ones is what we expose. The
    // freshly-detected delta is persisted in a microtask so reentrancy
    // during `build` doesn't trigger a second rebuild.
    final autoDetected = _detect();
    final union = {...persisted, ...autoDetected};
    if (autoDetected.difference(persisted).isNotEmpty) {
      // Schedule the persist outside `build` to avoid mutating state mid-build.
      Future<void>.microtask(() {
        if (!ref.mounted) return;
        _persistIfChanged(union);
      });
    }
    return union;
  }

  bool get skipped => _skipped;

  bool isComplete(OnboardingMilestone m) => state.contains(m);

  /// Explicit operator-driven mark-complete (used by future "I did this"
  /// affordances on the Onboarding view). The auto-detection in [build]
  /// covers the common path.
  void markComplete(OnboardingMilestone m) {
    if (state.contains(m)) return;
    final next = {...state, m};
    state = next;
    _persistIfChanged(next);
  }

  /// Mark all 8 milestones complete; used by the "Skip" affordance. The
  /// `skipped` flag stays distinct from natural completion so the
  /// dashboard nudge can render different copy ("you skipped onboarding"
  /// vs "you finished onboarding").
  void skip() {
    _skipped = true;
    final next = OnboardingMilestone.values.toSet();
    state = next;
    _persistIfChanged(next);
  }

  /// Computes the currently-satisfied milestones from the watched
  /// providers. Each provider is read via `ref.read` after `ref.watch`
  /// subscribed in `build`; the cached AsyncValue is consulted so we
  /// never block the milestone update on an in-flight fetch.
  Set<OnboardingMilestone> _detect() {
    final detected = <OnboardingMilestone>{};

    final runtime = ref.watch(runtimeStateProvider);
    if (runtime.kind == RuntimeStateKind.runtimeHealthyEmpty ||
        runtime.kind == RuntimeStateKind.runtimeHealthyPopulated ||
        runtime.kind == RuntimeStateKind.runtimeDegraded) {
      detected.add(OnboardingMilestone.daemonReachable);
    }

    final containers = ref.watch(containerListProvider);
    if (containers.asData?.value.isNotEmpty ?? false) {
      detected.add(OnboardingMilestone.benchContainerCheck);
    }

    final panes = ref.watch(paneListProvider);
    final paneRows = panes.asData?.value ?? const [];
    if (paneRows.isNotEmpty) {
      detected.add(OnboardingMilestone.paneDiscoveryCheck);
    }
    if (paneRows.any((p) => p.state == PaneState.discoveredAndRegistered)) {
      detected.add(OnboardingMilestone.firstPaneAdoption);
    }

    final agents = ref.watch(agentListProvider);
    final agentRows = agents.asData?.value ?? const [];
    if (agentRows.isNotEmpty) {
      detected.add(OnboardingMilestone.firstAgentRegistration);
    }
    if (agentRows.any((a) => a.logAttachment == LogAttachmentState.active)) {
      detected.add(OnboardingMilestone.firstLogAttachment);
    }

    final queue = ref.watch(queueListProvider);
    if (queue.asData?.value.isNotEmpty ?? false) {
      detected.add(OnboardingMilestone.firstDirectSend);
    }

    final routes = ref.watch(routeListProvider);
    if (routes.asData?.value.isNotEmpty ?? false) {
      detected.add(OnboardingMilestone.firstRouteCreation);
    }

    return detected;
  }

  /// Atomic persist via read-modify-write. The merge defends against
  /// concurrent UX-state writers (theme, project switcher) by re-reading
  /// `repo.current` at write time rather than persisting a stale snapshot
  /// (review fix H1 — onboarding _persist race).
  void _persistIfChanged(Set<OnboardingMilestone> next) {
    if (next.length == _persistedSnapshot.length &&
        next.containsAll(_persistedSnapshot) &&
        _persistedSnapshot.containsAll(next)) {
      return;
    }
    final repo = ref.read(uxStateRepositoryProvider);
    final current = Map<String, dynamic>.from(repo.current ?? const {});
    current['onboarding'] = {
      'completed_milestones':
          next.map((m) => m.wireValue).toList(growable: false),
      'skipped': _skipped,
    };
    repo.update(current);
    _persistedSnapshot = Set.of(next);
  }
}

final onboardingProgressProvider = NotifierProvider<
    OnboardingProgressNotifier, Set<OnboardingMilestone>>(
  OnboardingProgressNotifier.new,
);
