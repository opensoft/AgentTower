/// JSON helper utilities shared across providers.
///
/// Swarm-review H-G3: previously `_withAsOf` was duplicated across
/// `features/agent_ops/providers.dart`, `features/project_specs/providers.dart`,
/// `features/project_specs/handoff/submit_flow.dart`, and
/// `features/project_specs/drift/providers.dart`. The snake_case-only
/// copies checked just the `as_of` wire key; agent_ops also checked the
/// (incorrect, never-emitted-by-daemon) camelCase `asOf` key. The
/// single canonical helper here drops the camelCase variant — the
/// daemon contract is snake_case-only per FEAT-011.
///
/// Migration status: COMPLETE. Every former call site —
/// `project_specs/providers.dart`, `project_specs/handoff/providers.dart`,
/// `project_specs/drift/providers.dart`, `agent_ops/providers.dart`, and
/// `project_specs/handoff/submit_flow.dart` — now imports this file and
/// calls `withAsOfDefault`. No local `_withAsOf` copies remain.

Map<String, dynamic> withAsOfDefault(Map<String, dynamic> raw, DateTime asOf) {
  // Guard on a *usable* value, not mere key presence: a present-but-null,
  // empty, or whitespace `as_of` would otherwise pass through to the
  // freezed `DateTime.parse(v as String)` and throw, surfacing as an error
  // AsyncValue for the whole page instead of degrading to a stamped default.
  final existing = raw['as_of'];
  if (existing is String && existing.trim().isNotEmpty) return raw;
  return {...raw, 'as_of': asOf.toIso8601String()};
}
