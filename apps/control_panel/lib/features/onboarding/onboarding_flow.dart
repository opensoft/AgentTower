import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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

  static const _milestoneCopy = {
    OnboardingMilestone.daemonReachable: (
      label: 'Connect to the daemon',
      hint: 'Make sure `agenttowerd` is running on this host.',
    ),
    OnboardingMilestone.benchContainerCheck: (
      label: 'See a bench container',
      hint: 'Launch any bench container — it will appear in the Containers view.',
    ),
    OnboardingMilestone.paneDiscoveryCheck: (
      label: 'See a tmux pane',
      hint: 'Start a tmux pane inside the container — Panes view will list it.',
    ),
    OnboardingMilestone.firstPaneAdoption: (
      label: 'Adopt your first pane',
      hint: 'From Panes → Adopt, give the pane a label, role, and capability.',
    ),
    OnboardingMilestone.firstAgentRegistration: (
      label: 'See your agent on the Agents view',
      hint: 'The newly-adopted pane shows up as a registered agent.',
    ),
    OnboardingMilestone.firstLogAttachment: (
      label: 'Attach a log',
      hint: 'From the agent row, click "Attach log" — events start flowing.',
    ),
    OnboardingMilestone.firstDirectSend: (
      label: 'Send your first prompt',
      hint: 'Use the "Send" button on the agent row to push a prompt.',
    ),
    OnboardingMilestone.firstRouteCreation: (
      label: 'Create your first route',
      hint: 'From Routes → Add route, wire one event class to a target.',
    ),
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final completed = ref.watch(onboardingProgressProvider);
    final notifier = ref.read(onboardingProgressProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Onboarding'),
        actions: [
          TextButton(
            onPressed: () {
              notifier.skip();
              Navigator.of(context).maybePop();
            },
            child: const Text('Skip'),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Walk through these 8 milestones to confirm AgentTower is wired '
            'end-to-end on this machine. Each step ticks itself the moment we '
            'detect it — you never need to manually mark progress.',
            style: Theme.of(context).textTheme.bodyLarge,
          ),
          const SizedBox(height: 16),
          for (final m in OnboardingMilestone.values)
            _MilestoneTile(
              milestone: m,
              completed: completed.contains(m),
              label: _milestoneCopy[m]!.label,
              hint: _milestoneCopy[m]!.hint,
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
