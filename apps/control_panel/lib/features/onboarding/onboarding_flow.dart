import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/app_localizations.dart';
import '../../domain/models/common_enums.dart';
import 'onboarding_provider.dart';

/// 8-milestone onboarding overlay. T077 (Phase 3 US1) + FR-010.
///
/// Renders a checklist of all 8 milestones with a "current" pointer at
/// the first incomplete step. Each step's completion is detected
/// automatically by the providers it watches (per F11), so the operator
/// never has to manually click "I did this" — they just go do the work
/// and the milestone ticks itself.
///
/// "Skip onboarding" available from every step. Reachable from the
/// app shell on first launch and from Settings later.
class OnboardingFlow extends ConsumerWidget {
  const OnboardingFlow({super.key});

  static String _milestoneLabel(AppLocalizations l10n, OnboardingMilestone m) =>
      switch (m) {
        OnboardingMilestone.daemonReachable =>
          l10n.onboardingMilestoneDaemonReachableLabel,
        OnboardingMilestone.benchContainerCheck =>
          l10n.onboardingMilestoneBenchContainerLabel,
        OnboardingMilestone.paneDiscoveryCheck =>
          l10n.onboardingMilestonePaneDiscoveryLabel,
        OnboardingMilestone.firstPaneAdoption =>
          l10n.onboardingMilestoneFirstPaneAdoptionLabel,
        OnboardingMilestone.firstAgentRegistration =>
          l10n.onboardingMilestoneFirstAgentRegistrationLabel,
        OnboardingMilestone.firstLogAttachment =>
          l10n.onboardingMilestoneFirstLogAttachmentLabel,
        OnboardingMilestone.firstDirectSend =>
          l10n.onboardingMilestoneFirstDirectSendLabel,
        OnboardingMilestone.firstRouteCreation =>
          l10n.onboardingMilestoneFirstRouteCreationLabel,
      };

  static String _milestoneHint(AppLocalizations l10n, OnboardingMilestone m) =>
      switch (m) {
        OnboardingMilestone.daemonReachable =>
          l10n.onboardingMilestoneDaemonReachableHint,
        OnboardingMilestone.benchContainerCheck =>
          l10n.onboardingMilestoneBenchContainerHint,
        OnboardingMilestone.paneDiscoveryCheck =>
          l10n.onboardingMilestonePaneDiscoveryHint,
        OnboardingMilestone.firstPaneAdoption =>
          l10n.onboardingMilestoneFirstPaneAdoptionHint,
        OnboardingMilestone.firstAgentRegistration =>
          l10n.onboardingMilestoneFirstAgentRegistrationHint,
        OnboardingMilestone.firstLogAttachment =>
          l10n.onboardingMilestoneFirstLogAttachmentHint,
        OnboardingMilestone.firstDirectSend =>
          l10n.onboardingMilestoneFirstDirectSendHint,
        OnboardingMilestone.firstRouteCreation =>
          l10n.onboardingMilestoneFirstRouteCreationHint,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final completed = ref.watch(onboardingProgressProvider);
    final notifier = ref.read(onboardingProgressProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.onboardingTitle),
        actions: [
          TextButton(
            onPressed: () {
              notifier.skip();
              Navigator.of(context).maybePop();
            },
            child: Text(l10n.onboardingSkip),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            l10n.onboardingIntro,
            style: Theme.of(context).textTheme.bodyLarge,
          ),
          const SizedBox(height: 16),
          for (final m in OnboardingMilestone.values)
            _MilestoneTile(
              milestone: m,
              completed: completed.contains(m),
              label: _milestoneLabel(l10n, m),
              hint: _milestoneHint(l10n, m),
            ),
        ],
      ),
    );
  }
}

class _MilestoneTile extends StatelessWidget {
  const _MilestoneTile({
    required this.milestone,
    required this.completed,
    required this.label,
    required this.hint,
  });

  final OnboardingMilestone milestone;
  final bool completed;
  final String label;
  final String hint;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: ListTile(
        leading: Icon(
          completed ? Icons.check_circle : Icons.circle_outlined,
          color: completed ? scheme.primary : scheme.outline,
        ),
        title: Text(
          label,
          style: TextStyle(
            decoration: completed ? TextDecoration.lineThrough : null,
          ),
        ),
        subtitle: completed ? null : Text(hint),
      ),
    );
  }
}
