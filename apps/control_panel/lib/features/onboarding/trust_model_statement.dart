import 'package:flutter/material.dart';

import '../../core/l10n/app_localizations.dart';

/// First-launch trust-model statement. T080 (Phase 3 US1) + FR-061.
///
/// Verbatim statement of the local-only trust boundary so an operator
/// understands what AgentTower trusts before adopting any agent.
/// Reachable from:
///   - Onboarding flow (first-launch overlay)
///   - Settings → Privacy (post-onboarding lookup)
///
/// Spec text is captured here rather than in an external i18n bundle
/// because the security posture must remain readable even if the
/// localization layer fails.
class TrustModelStatement extends StatelessWidget {
  const TrustModelStatement({super.key, this.embedded = false});

  /// If true, the widget renders inline (no Scaffold). Used when the
  /// statement is dropped into Settings → Privacy.
  final bool embedded;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final body = Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l10n.onboardingTrustLocalOnlyHeading,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          Text(
            l10n.onboardingTrustStatementBody,
            style: Theme.of(context).textTheme.bodyLarge,
          ),
        ],
      ),
    );
    if (embedded) return body;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.onboardingTrustModel)),
      body: body,
    );
  }
}
