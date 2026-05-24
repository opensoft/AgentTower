import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers.dart';
import 'models/adopted_agent.dart';
import 'models/common_enums.dart';

/// FR-071 master qualification — fetch the daemon's master-class
/// capability set once per session and cache it. T086 (Phase 4 US2).
///
/// Per data-model.md §1.3 + FR-071, a `MasterSummary` is constructable
/// only when its underlying [AdoptedAgent] satisfies BOTH:
///   (a) `role == master`, AND
///   (b) `capability` is in the master-class set returned by the
///       FEAT-011 capability registry.
///
/// The registry is fetched once per session and cached; the contract
/// states it is stable for the daemon's lifetime, so the cache lives
/// for the [DaemonSession] lifetime and is invalidated on reconnect
/// (via the existing `appClientProvider` rebuild).
///
/// Per research R-19 caveat: if `app.capability.registry` is not
/// present in the deployed FEAT-011 version, the provider yields an
/// empty set — meaning NO agent qualifies and every "Master" row
/// renders as the plain Agent fallback. That degrades cleanly without
/// throwing, consistent with FR-002 contract-version-incompatible
/// behavior on the surfaces that consume this provider.
/// Result type that distinguishes "the daemon returned an empty set"
/// from "the daemon does not yet expose the registry method". Phase 4
/// surfaces consume the boolean degraded flag (H-G2) to render a
/// banner / log entry rather than silently failing every Master row.
class MasterClassCapabilities {
  const MasterClassCapabilities({
    required this.capabilities,
    required this.degraded,
    this.degradedReason,
  });

  final Set<String> capabilities;
  final bool degraded;
  final String? degradedReason;

  /// Convenience for places that just need the Set.
  bool contains(String capability) => capabilities.contains(capability);
  bool get isEmpty => capabilities.isEmpty;
}

final masterClassCapabilitiesProvider =
    FutureProvider<MasterClassCapabilities>((ref) async {
  try {
    final result = await ref.watch(appClientProvider).capabilityRegistry();
    final raw = result['master_class'] ?? const <dynamic>[];
    if (raw is! Iterable) {
      // The daemon answered but the shape is wrong — surface as
      // degraded so the operator sees a banner.
      return const MasterClassCapabilities(
        capabilities: <String>{},
        degraded: true,
        degradedReason:
            'app.capability.registry returned a malformed master_class field',
      );
    }
    return MasterClassCapabilities(
      capabilities: raw.whereType<String>().toSet(),
      degraded: false,
    );
  } catch (e) {
    // Swarm-review H-G2: previously silent. Now we attach a reason
    // so surfaces (Agents view, Project card master strip) can render
    // a banner naming the missing method.
    return MasterClassCapabilities(
      capabilities: const <String>{},
      degraded: true,
      degradedReason:
          'app.capability.registry unavailable ($e); all Master qualifications '
          'will fail until the daemon exposes the v1.x registry method (R-19).',
    );
  }
});

/// Returns `true` iff [agent] passes the FR-071 master qualification
/// test against [masterClassCapabilities]. Synchronous because callers
/// typically watch [masterClassCapabilitiesProvider] separately and
/// pass the resolved set in.
bool qualifiesAsMaster(
  AdoptedAgent agent,
  Set<String> masterClassCapabilities,
) {
  if (agent.role != AgentRole.master) return false;
  if (masterClassCapabilities.isEmpty) return false;
  return masterClassCapabilities.contains(agent.capability);
}

/// Overload accepting a [MasterClassCapabilities] envelope (H-G2 path).
bool qualifiesAsMasterEnvelope(
  AdoptedAgent agent,
  MasterClassCapabilities envelope,
) {
  return qualifiesAsMaster(agent, envelope.capabilities);
}
