import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/common_enums.dart';
import 'onboarding_provider.dart';

/// Dashboard nudge tile. T078 (Phase 3 US1) + FR-010 + clarify Q24.
///
/// Visually distinct from the FR-012 recommended-next-action tile
/// (different leading icon + secondary chip color) so the operator can
/// tell at a glance that this is "onboarding wants your attention"
/// vs. "the daemon recommends this next action right now".
///
/// Shows the FIRST incomplete milestone. If all 8 are complete (or the
/// operator skipped), renders nothing.
class DashboardNudges extends ConsumerWidget {
  const DashboardNudges({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final completed = ref.watch(onboardingProgressProvider);
    final pending = OnboardingMilestone.values.firstWhere(
      (m) => !completed.contains(m),
      orElse: () => OnboardingMilestone.firstRouteCreation, // unreachable
    );
    if (completed.length == OnboardingMilestone.values.length) {
      return const SizedBox.shrink();
    }
    final scheme = Theme.of(context).colorScheme;
    return Card(
      color: scheme.secondaryContainer,
      child: ListTile(
        leading: const Icon(Icons.flag_outlined),
        title: Text('Onboarding: ${_label(pending)}'),
        subtitle: Text(
          '${completed.length} of ${OnboardingMilestone.values.length} '
          'milestones complete',
        ),
        trailing: const Chip(label: Text('onboarding')),
        onTap: () => Navigator.of(context).pushNamed('/onboarding'),
      ),
    );
  }

  static String _label(OnboardingMilestone m) => switch (m) {
        OnboardingMilestone.daemonReachable => 'Connect to the daemon',
        OnboardingMilestone.benchContainerCheck => 'See a bench container',
        OnboardingMilestone.paneDiscoveryCheck => 'See a tmux pane',
        OnboardingMilestone.firstPaneAdoption => 'Adopt your first pane',
        OnboardingMilestone.firstAgentRegistration => 'See agent in Agents view',
        OnboardingMilestone.firstLogAttachment => 'Attach a log',
        OnboardingMilestone.firstDirectSend => 'Send your first prompt',
        OnboardingMilestone.firstRouteCreation => 'Create your first route',
      };
}
