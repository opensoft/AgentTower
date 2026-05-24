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
final masterClassCapabilitiesProvider =
    FutureProvider<Set<String>>((ref) async {
  try {
    final result = await ref.watch(appClientProvider).capabilityRegistry();
    final raw = result['master_class'] ?? const <dynamic>[];
    if (raw is! Iterable) return const <String>{};
    return raw.whereType<String>().toSet();
  } catch (_) {
    // Method missing or other failure — degrade silently per R-19.
    return const <String>{};
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
