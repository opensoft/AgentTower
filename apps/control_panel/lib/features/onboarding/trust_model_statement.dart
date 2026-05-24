import 'package:flutter/material.dart';

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

  static const _body = '''
AgentTower runs entirely on this machine.

  • The desktop app talks to the daemon over a local Unix socket.
    There is no network listener and no remote service.
  • The daemon enforces a same-host-user check: only your OS account
    can issue commands. The app's "peer-UID match" doctor check
    confirms this at every launch.
  • The app's only outbound network call is a once-per-launch fetch
    of `releases.opensoft.one/.../latest.json` to see whether a newer
    Control Panel is published. The release-feed URL is hard-coded to
    HTTPS, follows no redirects, and never sends a session token.
  • No telemetry, no analytics, no log upload. Diagnostics bundles
    are saved only to a folder you pick.
''';

  @override
  Widget build(BuildContext context) {
    final body = Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Local-only trust',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          Text(_body, style: Theme.of(context).textTheme.bodyLarge),
        ],
      ),
    );
    if (embedded) return body;
    return Scaffold(
      appBar: AppBar(title: const Text('Trust model')),
      body: body,
    );
  }
}
