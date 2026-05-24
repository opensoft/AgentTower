// Shared enums for FEAT-012. Wire-format values use spec-canonical
// hyphenated/snake_case strings (matching spec.md FR-014 etc.); Dart
// identifiers use camelCase per Dart convention. Each enum exposes
// `.wireValue` for serialization and `fromWire()` for deserialization.
//
// T038 (Phase 2 Foundational). Source of truth for state vocabularies
// is spec.md and data-model.md.
//
// **Codegen contract (swarm-review CR-1):** every enum carries
// `@JsonEnum(valueField: 'wireValue')` so `json_serializable` emits
// the snake_case / hyphenated wire string (the `wireValue` field on
// each enum value) instead of the Dart identifier. Without this,
// `fromJson` on any payload containing a multi-word enum throws
// `CheckedFromJsonException`.

import 'package:json_annotation/json_annotation.dart';

/// Role assigned at adopt time (FR-016) — drives FR-071 master qualification.
@JsonEnum(valueField: 'wireValue')
enum AgentRole {
  master('master'),
  slave('slave'),
  shell('shell');

  const AgentRole(this.wireValue);
  final String wireValue;
  static AgentRole fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Adopted agent operational states (FR-015).
@JsonEnum(valueField: 'wireValue')
enum AgentState {
  active('active'),
  inactive('inactive'),
  partiallyConfigured('partially_configured'),
  logAttached('log-attached'),
  logDetached('log-detached');

  const AgentState(this.wireValue);
  final String wireValue;
  static AgentState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Master-summary current status (FR-030) — projects over [AgentState] per
/// data-model.md §1.3 + Round-3 R-22.
@JsonEnum(valueField: 'wireValue')
enum MasterStatus {
  active('active'),
  waitingForInput('waiting_for_input'),
  blocked('blocked'),
  reviewing('reviewing'),
  idle('idle'),
  offline('offline'),
  degraded('degraded');

  const MasterStatus(this.wireValue);
  final String wireValue;
  static MasterStatus fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Pane discovery + registration states (FR-014). Spec uses hyphenated form;
/// wire format reflects that exactly.
@JsonEnum(valueField: 'wireValue')
enum PaneState {
  discoveredAndUnmanaged('discovered-and-unmanaged'),
  discoveredAndRegistered('discovered-and-registered'),
  inactiveOrStale('inactive/stale'),
  discoveryDegraded('discovery-degraded');

  const PaneState(this.wireValue);
  final String wireValue;
  static PaneState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Feature/change stage (FR-028, including `deferred` per F7-a).
@JsonEnum(valueField: 'wireValue')
enum Stage {
  definition('definition'),
  specReady('spec_ready'),
  engineering('engineering'),
  review('review'),
  validation('validation'),
  mergeReady('merge_ready'),
  merged('merged'),
  deferred('deferred'),
  driftRepair('drift_repair');

  const Stage(this.wireValue);
  final String wireValue;
  static Stage fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Feature/change execution status (FR-028).
@JsonEnum(valueField: 'wireValue')
enum ExecutionStatus {
  notStarted('not_started'),
  active('active'),
  waiting('waiting'),
  blocked('blocked'),
  atRisk('at_risk'),
  complete('complete');

  const ExecutionStatus(this.wireValue);
  final String wireValue;
  static ExecutionStatus fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Handoff assignment-state lifecycle (FR-044).
@JsonEnum(valueField: 'wireValue')
enum AssignmentState {
  drafted('drafted'),
  submitted('submitted'),
  accepted('accepted'),
  active('active'),
  waiting('waiting'),
  blocked('blocked'),
  completed('completed'),
  cancelled('cancelled'),
  superseded('superseded');

  const AssignmentState(this.wireValue);
  final String wireValue;
  static AssignmentState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);

  bool get isTerminal =>
      this == completed || this == cancelled || this == superseded;
}

/// Validation-run lifecycle (FR-048).
@JsonEnum(valueField: 'wireValue')
enum RunState {
  queued('queued'),
  running('running'),
  completed('completed'),
  cancelled('cancelled'),
  failedToStart('failed_to_start');

  const RunState(this.wireValue);
  final String wireValue;
  static RunState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);

  bool get isTerminal =>
      this == completed || this == cancelled || this == failedToStart;
}

/// Validation-run result (FR-048). Only meaningful in terminal [RunState].
@JsonEnum(valueField: 'wireValue')
enum RunResult {
  pass('pass'),
  fail('fail'),
  partial('partial'),
  error('error'),
  cancelled('cancelled');

  const RunResult(this.wireValue);
  final String wireValue;
  static RunResult fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Drift lifecycle states (FR-034). `accepted_as_built` + `dismissed` are
/// terminal alternatives to `resolved`.
@JsonEnum(valueField: 'wireValue')
enum DriftStatus {
  newFinding('new'),
  reviewNeeded('review_needed'),
  confirmed('confirmed'),
  repairPlanned('repair_planned'),
  resolved('resolved'),
  acceptedAsBuilt('accepted_as_built'),
  dismissed('dismissed');

  const DriftStatus(this.wireValue);
  final String wireValue;
  static DriftStatus fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);

  bool get isTerminal =>
      this == resolved || this == acceptedAsBuilt || this == dismissed;
}

@JsonEnum(valueField: 'wireValue')
enum DriftSeverity {
  info('info'),
  warning('warning'),
  high('high'),
  critical('critical');

  const DriftSeverity(this.wireValue);
  final String wireValue;
  static DriftSeverity fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

@JsonEnum(valueField: 'wireValue')
enum DriftSource {
  staticCheck('static_check'),
  agentReview('agent_review'),
  operatorReport('operator_report'),
  testResult('test_result');

  const DriftSource(this.wireValue);
  final String wireValue;
  static DriftSource fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

@JsonEnum(valueField: 'wireValue')
enum DriftConfidence {
  low('low'),
  medium('medium'),
  high('high');

  const DriftConfidence(this.wireValue);
  final String wireValue;
  static DriftConfidence fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Validation entrypoint types (FR-047).
@JsonEnum(valueField: 'wireValue')
enum EntrypointType {
  unitTest('unit_test'),
  integrationTest('integration_test'),
  contractTest('contract_test'),
  smoke('smoke'),
  e2e('e2e'),
  demoFlow('demo_flow'),
  doctor('doctor');

  const EntrypointType(this.wireValue);
  final String wireValue;
  static EntrypointType fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

@JsonEnum(valueField: 'wireValue')
enum BlockingLevel {
  informational('informational'),
  recommended('recommended'),
  required('required');

  const BlockingLevel(this.wireValue);
  final String wireValue;
  static BlockingLevel fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Demo readiness overall state (FR-050).
@JsonEnum(valueField: 'wireValue')
enum DemoReadinessState {
  unknown('unknown'),
  notReady('not_ready'),
  atRisk('at_risk'),
  ready('ready');

  const DemoReadinessState(this.wireValue);
  final String wireValue;
  static DemoReadinessState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Attention item severity (FR-052) — shares palette with drift severity per R-15.
@JsonEnum(valueField: 'wireValue')
enum AttentionSeverity {
  info('info'),
  warning('warning'),
  high('high'),
  critical('critical');

  const AttentionSeverity(this.wireValue);
  final String wireValue;
  static AttentionSeverity fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Notification severity (FR-057) — shares palette with attention/drift per R-15.
@JsonEnum(valueField: 'wireValue')
enum NotificationSeverity {
  info('info'),
  warning('warning'),
  high('high'),
  critical('critical');

  const NotificationSeverity(this.wireValue);
  final String wireValue;
  static NotificationSeverity fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);

  /// Per Round-3 R-33: high + critical never grouped by FR-057.
  bool get groupable => this == info || this == warning;
}

/// Attention item class (FR-052).
@JsonEnum(valueField: 'wireValue')
enum AttentionClass {
  blockedQueueRow('blocked_queue_row'),
  routeSkip('route_skip'),
  degradedSubsystem('degraded_subsystem'),
  driftConfirmed('drift_confirmed'),
  validationFailed('validation_failed');

  const AttentionClass(this.wireValue);
  final String wireValue;
  static AttentionClass fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Handoff mode (FR-036).
@JsonEnum(valueField: 'wireValue')
enum HandoffMode {
  specRefinement('spec_refinement'),
  engineeringExecution('engineering_execution'),
  driftRepair('drift_repair'),
  validationDemoPrep('validation_demo_prep');

  const HandoffMode(this.wireValue);
  final String wireValue;
  static HandoffMode fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

@JsonEnum(valueField: 'wireValue')
enum HandoffPriority {
  low('low'),
  normal('normal'),
  high('high');

  const HandoffPriority(this.wireValue);
  final String wireValue;
  static HandoffPriority fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Helper-policy origin (FR-038a + Round-3 helper-policy contract).
@JsonEnum(valueField: 'wireValue')
enum PolicySource {
  bakedDefault('baked_default'),
  operatorOverride('operator_override'),
  repoOverride('repo_override');

  const PolicySource(this.wireValue);
  final String wireValue;
  static PolicySource fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Exclusion reason for a resolved work item (F7-c).
@JsonEnum(valueField: 'wireValue')
enum ResolvedExclusion {
  deferred('deferred'),
  merged('merged');

  const ResolvedExclusion(this.wireValue);
  final String wireValue;
  static ResolvedExclusion fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Work-item kind (FR-036).
@JsonEnum(valueField: 'wireValue')
enum WorkItemKind {
  feature('feature'),
  change('change');

  const WorkItemKind(this.wireValue);
  final String wireValue;
  static WorkItemKind fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Onboarding milestones (FR-010 with F11 enumeration).
@JsonEnum(valueField: 'wireValue')
enum OnboardingMilestone {
  daemonReachable('daemon_reachable'),
  benchContainerCheck('bench_container_check'),
  paneDiscoveryCheck('pane_discovery_check'),
  firstPaneAdoption('first_pane_adoption'),
  firstAgentRegistration('first_agent_registration'),
  firstLogAttachment('first_log_attachment'),
  firstDirectSend('first_direct_send'),
  firstRouteCreation('first_route_creation');

  const OnboardingMilestone(this.wireValue);
  final String wireValue;
  static OnboardingMilestone fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Top-level workspace (FR-006).
@JsonEnum(valueField: 'wireValue')
enum Workspace {
  agentOps('agent_ops'),
  projectSpecs('project_specs'),
  testingDemo('testing_demo'),
  settings('settings');

  const Workspace(this.wireValue);
  final String wireValue;
  static Workspace fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Theme mode (FR-009 + Q12).
@JsonEnum(valueField: 'wireValue')
enum ThemeMode {
  light('light'),
  dark('dark'),
  system('system');

  const ThemeMode(this.wireValue);
  final String wireValue;
  static ThemeMode fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Density mode (FR-009 + Q12).
@JsonEnum(valueField: 'wireValue')
enum DensityMode {
  comfortable('comfortable'),
  compact('compact');

  const DensityMode(this.wireValue);
  final String wireValue;
  static DensityMode fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// List sort direction (FR-078).
@JsonEnum(valueField: 'wireValue')
enum SortDirection {
  asc('asc'),
  desc('desc');

  const SortDirection(this.wireValue);
  final String wireValue;
  static SortDirection fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Five runtime states distinguished on every live-data surface (FR-004).
@JsonEnum(valueField: 'wireValue')
enum RuntimeStateKind {
  runtimeUnreachable('runtime-unreachable'),
  contractVersionIncompatible('contract-version-incompatible'),
  runtimeHealthyEmpty('runtime-healthy-empty'),
  runtimeHealthyPopulated('runtime-healthy-populated'),
  runtimeDegraded('runtime-degraded');

  const RuntimeStateKind(this.wireValue);
  final String wireValue;
  static RuntimeStateKind fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Notification lifecycle stages (FR-056).
@JsonEnum(valueField: 'wireValue')
enum NotificationLifecycle {
  incoming('incoming'),
  processed('processed'),
  inHistory('in_history');

  const NotificationLifecycle(this.wireValue);
  final String wireValue;
  static NotificationLifecycle fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Operator history entry kind (FR-055).
@JsonEnum(valueField: 'wireValue')
enum HistoryEntryKind {
  resolvedAttention('resolved_attention'),
  completedWorkflow('completed_workflow'),
  other('other');

  const HistoryEntryKind(this.wireValue);
  final String wireValue;
  static HistoryEntryKind fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// FR-017 — log-attachment lifecycle for an [AdoptedAgent]. Data-model §1.2.
@JsonEnum(valueField: 'wireValue')
enum LogAttachmentState {
  active('active'),
  superseded('superseded'),
  stale('stale'),
  detached('detached');

  const LogAttachmentState(this.wireValue);
  final String wireValue;
  static LogAttachmentState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

/// Discovered class of a pane prior to adoption (FR-014). The daemon
/// classifies each tmux pane by what process appears to be driving it;
/// the operator may still adopt with a different `capability` so this
/// enum is a hint, not a constraint.
@JsonEnum(valueField: 'wireValue')
enum PaneDiscoveredClass {
  claude('claude'),
  codex('codex'),
  gemini('gemini'),
  opencode('opencode'),
  shell('shell'),
  unknown('unknown');

  const PaneDiscoveredClass(this.wireValue);
  final String wireValue;
  static PaneDiscoveredClass fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => PaneDiscoveredClass.unknown,
      );
}

/// FR-020 — 5-state vocabulary for the safe-prompt queue. Data-model §1.16.
@JsonEnum(valueField: 'wireValue')
enum QueueRowState {
  queued('queued'),
  blocked('blocked'),
  delivered('delivered'),
  canceled('canceled'),
  failed('failed');

  const QueueRowState(this.wireValue);
  final String wireValue;
  static QueueRowState fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);

  /// `delivered`, `canceled`, and `failed` are terminal — they cannot
  /// transition further. Used by the Queue view to disable per-row
  /// actions appropriately.
  bool get isTerminal => switch (this) {
        QueueRowState.delivered ||
        QueueRowState.canceled ||
        QueueRowState.failed =>
          true,
        QueueRowState.queued || QueueRowState.blocked => false,
      };
}

/// FEAT-011 high-level container lifecycle. The daemon may report
/// additional values; consumers MUST handle [unknown] gracefully.
@JsonEnum(valueField: 'wireValue')
enum ContainerState {
  running('running'),
  exited('exited'),
  paused('paused'),
  restarting('restarting'),
  unknown('unknown');

  const ContainerState(this.wireValue);
  final String wireValue;
  static ContainerState fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => ContainerState.unknown,
      );
}
