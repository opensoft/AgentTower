/// JSON helper utilities shared across providers.
///
/// Swarm-review H-G3: previously `_withAsOf` was duplicated across
/// `features/agent_ops/providers.dart`, `features/project_specs/providers.dart`,
/// `features/project_specs/handoff/providers.dart`, and
/// `features/project_specs/drift/providers.dart`. Three of the four
/// only checked the `as_of` wire key; agent_ops also checked the
/// (incorrect, never-emitted-by-daemon) camelCase `asOf` key. The
/// single canonical helper here drops the camelCase variant — the
/// daemon contract is snake_case-only per FEAT-011.

Map<String, dynamic> withAsOfDefault(Map<String, dynamic> raw, DateTime asOf) {
  if (raw.containsKey('as_of')) return raw;
  return {...raw, 'as_of': asOf.toIso8601String()};
}
