import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/app_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
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
        title: Text(l10n.onboardingNudgeTitle(_label(l10n, pending))),
        subtitle: Text(
          l10n.onboardingNudgeProgress(
            completed.length,
            OnboardingMilestone.values.length,
          ),
        ),
        trailing: Chip(label: Text(l10n.onboardingNudgeChipLabel)),
        onTap: () => Navigator.of(context).pushNamed('/onboarding'),
      ),
    );
  }

  static String _label(AppLocalizations l10n, OnboardingMilestone m) =>
      switch (m) {
        OnboardingMilestone.daemonReachable =>
          l10n.onboardingNudgeLabelDaemonReachable,
        OnboardingMilestone.benchContainerCheck =>
          l10n.onboardingNudgeLabelBenchContainer,
        OnboardingMilestone.paneDiscoveryCheck =>
          l10n.onboardingNudgeLabelPaneDiscovery,
        OnboardingMilestone.firstPaneAdoption =>
          l10n.onboardingNudgeLabelFirstPaneAdoption,
        OnboardingMilestone.firstAgentRegistration =>
          l10n.onboardingNudgeLabelFirstAgentRegistration,
        OnboardingMilestone.firstLogAttachment =>
          l10n.onboardingNudgeLabelFirstLogAttachment,
        OnboardingMilestone.firstDirectSend =>
          l10n.onboardingNudgeLabelFirstDirectSend,
        OnboardingMilestone.firstRouteCreation =>
          l10n.onboardingNudgeLabelFirstRouteCreation,
      };
}
