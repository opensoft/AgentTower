# Phase 1 Data Model — FEAT-012 Flutter Desktop Control Panel

**Status**: All operator-facing entities, app-side persisted state, and lifecycles enumerated. Reference for code generation under `apps/control_panel/lib/domain/models/`.
**Date**: 2026-05-23
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

This document specifies the field/type/lifecycle shape of every entity the desktop app surfaces. Entities split into two layers:

1. **Daemon-owned entities** (most of Key Entities) — read from FEAT-011's `app.*` namespace, mirrored as immutable Dart `freezed` classes under `lib/domain/models/`. The app **never persists** these to disk per FR-005 / FR-069.
2. **App-owned persisted state** — the single Workspace Selection entity (FR-070 / FR-069), held in the local UX-state JSON file. The only entity the app writes to disk.

All daemon-owned models include an `as_of: DateTime` field stamped from the daemon response timestamp (or wall-clock at receipt if absent) so freshness can be reasoned about across reconnects per FR-003.

---

## 1. Daemon-owned entities (read-only mirrors of FEAT-011 responses)

### 1.1 Project

**Source**: `app.project.list` / `app.project.detail` (FEAT-011 v1.0+).
**Identity** (per spec Key Entities + clarify): daemon-issued `project_id`, derived from canonicalized repository absolute path. Same path → same id.

```dart
@freezed
class Project with _$Project {
  const factory Project({
    required String projectId,                 // daemon-issued, stable
    required String label,                     // operator-visible name
    required String repositoryPath,            // canonicalized absolute path
    required RepoStateBadge repoState,
    required BranchWorktreeBadge activeBranch,
    String? activeFeatureChangeId,             // FR-025 — primary feature/change ref
    String? currentFeatureChangePhaseLabel,    // FR-025 / CR-10 — human-readable phase ("Engineering / Active") for card-level SC-002 attribution
    String? currentDrivingMasterAgentId,
    String? currentDrivingHandoffId,           // FR-029 / CR-10 — completes the canonical "X is driving FEAT-N under handoff H" sentence on the card
    required ValidationBadge validationBadge,
    DateTime? validationLastRunAt,
    required DriftBadge driftBadge,
    DriftSource? driftSource,                  // FR-033 source enum
    DateTime? driftAge,
    required AttentionSummary attentionSummary,
    required int unreadNotificationCount,
    required DateTime lastActivityAt,
    required DateTime asOf,
  }) = _Project;
  factory Project.fromJson(Map<String, dynamic> json) => _$ProjectFromJson(json);
}
```

**Relationships**:
- 1 Project → 0..N Adopted Agents (via `agent.project_path` matching `repositoryPath`).
- 1 Project → 0..N Feature/Changes (the daemon's project-state owns these; the app derives counts and the primary `activeFeatureChangeId`).
- 1 Project → 0..N Drift Signals (FR-033 scope `project`).
- 1 Project → 0..N Validation Entrypoints / Runs (FR-047 scope `project`).

### 1.2 Adopted Agent

**Source**: `app.agent.list` / `app.agent.detail`.
**Identity**: daemon-issued `agent_id`; operator-supplied `label` is mutable and not identity-bearing.

```dart
@freezed
class AdoptedAgent with _$AdoptedAgent {
  const factory AdoptedAgent({
    required String agentId,                   // daemon-issued
    required String label,
    required AgentRole role,                   // master | slave | shell | …
    required String capability,                // claude | codex | gemini | opencode | shell | …
    required String projectPath,
    required AgentState state,                 // active | inactive | partially_configured | log-attached | log-detached
    String? parentAgentId,                     // sub-agent tree (max 2 visible levels per FR-015)
    int? descendantsBeyondVisible,             // "+N descendants" affordance
    required String containerId,
    required String paneId,
    LogAttachmentState? logAttachment,         // active | superseded | stale | detached
    String? currentGoal,
    String? currentTask,
    DateTime? lastMeaningfulActivityAt,
    required DateTime asOf,
  }) = _AdoptedAgent;
  factory AdoptedAgent.fromJson(Map<String, dynamic> json) => _$AdoptedAgentFromJson(json);
}
```

### 1.3 Master Summary (view over AdoptedAgent + FR-071)

**Source**: derived in-app from AdoptedAgent + a FEAT-011 capability-class lookup; the daemon does not return a separate "master" object. A view, not a separate entity.
**Identity**: the underlying AdoptedAgent's `agentId`.

```dart
@freezed
class MasterSummary with _$MasterSummary {
  const factory MasterSummary({
    required String agentId,                   // = AdoptedAgent.agentId
    required String label,
    required String capability,                // must be master-class per FR-071
    required AgentRole role,                   // == master
    required ActiveInactiveBadge activeBadge,
    required MasterStatus currentStatus,       // FR-030: active | waiting_for_input | blocked | reviewing | idle | offline | degraded
    required String assignedProjectId,
    String? primaryAssignedFeatureChangeId,
    int? primaryAssignedOverflowCount,         // "+ N more"
    required WorkflowPhase workflowPhase,      // human label + optional underlying token
    required SubAgentRollup subAgentRollup,    // count + state summary
    required AttentionSeverity attentionSeverity,
    required int openActionableCount,
    DateTime? lastMeaningfulActivityAt,
    required CompactValidationBadge validationBadge,
    required DateTime asOf,
  }) = _MasterSummary;
}
```

**FR-071 invariant**: a Master Summary is **only constructed** when the underlying AdoptedAgent satisfies both (a) `role == master` AND (b) `capability ∈ masterClassCapabilities` (resolved against the FEAT-011 master-class enumeration). The view layer otherwise renders a plain Agent row.

**FR-030 status-projection invariant**: `currentStatus` (`active | waiting_for_input | blocked | reviewing | idle | offline | degraded`) is a master-specific operational projection over the underlying AdoptedAgent's `agentState`, not a parallel state machine. Every master is, by FR-071, an AdoptedAgent in the `active` agentState; `currentStatus` adds the operational dimension (waiting_for_input, blocked, reviewing, idle, offline, degraded) that is only meaningful for agents satisfying the master criteria. When the underlying AdoptedAgent leaves the `active` agentState (e.g. inactive, log-detached) the MasterSummary projection is no longer constructed and the view layer falls back to the plain Agent row per the FR-071 invariant above.

### 1.4 Pane

**Source**: `app.pane.list` / `app.pane.detail`.
**Identity**: daemon-issued `pane_id`. The full 6-field tuple
`(container_id, tmux_socket, tmux_session_name, tmux_window_index,
tmux_pane_index, pane_id)` is required as input to
`app.agent.register_from_pane` and is matched byte-for-byte (FR-028a).

```dart
@freezed
class Pane with _$Pane {
  const factory Pane({
    required String paneId,
    required String containerId,
    required String tmuxSocket,
    required String tmuxSessionName,
    required int tmuxWindowIndex,              // int per FEAT-011 contract
    required int tmuxPaneIndex,                // int per FEAT-011 contract
    required PaneState state,                  // FR-014: discovered-and-unmanaged | discovered-and-registered | inactive/stale | discovery-degraded
    String? registeredAgentId,                 // populated iff state == discovered-and-registered
    PaneDiscoveredClass? discoveredClass,      // claude | codex | shell | …
    DateTime? lastSeenAt,
    required DateTime asOf,
  }) = _Pane;
}
```

**Allowed transitions** (per F3 sub-edit, FR-014): `discovered-and-unmanaged ↔ discovered-and-registered` (adoption / de-adoption); any state may transition to `inactive/stale` on pane disappearance and may return to its prior state on rediscovery; any state may transition to `discovery-degraded` on probe failure and back on recovery. No terminal pane states.

### 1.5 Feature/Change Status

**Source**: derived from `app.project.detail` (per-feature breakdown) or `app.feature.list` / `.detail` if FEAT-011 exposes it.
**Identity**: daemon-issued `feature_change_id`.

```dart
@freezed
class FeatureChangeStatus with _$FeatureChangeStatus {
  const factory FeatureChangeStatus({
    required String featureChangeId,
    required String displayId,                 // e.g. "FEAT-012"
    required Stage stage,                      // FR-028 + F7: definition | spec_ready | engineering | review | validation | merge_ready | merged | deferred | drift_repair
    required ExecutionStatus executionStatus,  // not_started | active | waiting | blocked | at_risk | complete
    String? subphaseToken,
    required String humanReadableLabel,        // e.g. "Engineering / Active"
    required String projectId,
    String? drivingMasterAgentId,
    String? drivingHandoffId,
    required DateTime asOf,
  }) = _FeatureChangeStatus;
}
```

**Allowed transitions for `deferred` stage** (per F7 sub-edit b): `deferred` may transition back to `definition` or `spec_ready` via an explicit un-defer action. No other transitions from `deferred` are allowed. The `featureChangeId` is preserved across un-defer.

### 1.6 Handoff

**Source**: `app.handoff.list` / `app.handoff.detail` / `app.handoff.create` (the FR-038a helper-policy methods may or may not yet exist in FEAT-011 v1.0; see research R-19).
**Identity**: daemon-issued `handoff_id` assigned at submission time; drafts before submission have a transient client-side `draft_id`.

```dart
@freezed
class Handoff with _$Handoff {
  const factory Handoff({
    String? handoffId,                         // null while in `drafted` pre-submission
    String? draftId,                           // client-side, non-null for drafts
    required DateTime createdAt,
    required DateTime updatedAt,
    required String operatorLabel,             // FR-061a per-OS-user
    required String targetMasterAgentId,
    required String targetMasterLabel,
    required String projectId,
    required String projectLabel,
    required HandoffMode mode,                 // spec_refinement | engineering_execution | drift_repair | validation_demo_prep
    HandoffPriority? priority,
    DateTime? deadline,
    required AssignmentState assignmentState,  // FR-044: drafted | submitted | accepted | active | waiting | blocked | completed | cancelled | superseded
    required List<WorkItemRef> selectedWorkItems,
    required List<ResolvedWorkItem> resolvedWorkItems,  // with FR-039 annotations
    required WorkItemRef primaryWorkItem,
    required List<String> linkedFeatureIds,
    required List<String> linkedChangeIds,
    required HandoffContextBundle contextBundle,
    required String helperPolicyId,
    required HelperPolicySnapshot helperPolicySnapshot,  // FR-038a
    required String generatedPromptText,
    String? operatorNotes,
    DateTime? submittedAt,
    DateTime? acceptedAt,
    DateTime? completedAt,
    DateTime? cancelledAt,
    String? supersededByHandoffId,
    String? supersedesHandoffId,                          // back-reference
    HandoffDeliveryStatus? deliveryStatus,                // null on happy path; populated per FR-072(b)
    HandoffFailureContext? failureContext,                // populated per FR-072(a)
    required DateTime asOf,
  }) = _Handoff;
}
```

**Allowed transitions** (per F3 sub-edit, FR-044): `drafted → submitted → accepted → active`; from `active` → {`waiting`, `blocked`, `completed`, `cancelled`}; `waiting` and `blocked` ↔ `active`; `submitted` and `accepted` → {`cancelled`, `superseded`}; `completed` / `cancelled` / `superseded` are terminal.

### 1.7 Resolved Work Item (per FR-039 + F7 sub-edit c)

```dart
@freezed
class ResolvedWorkItem with _$ResolvedWorkItem {
  const factory ResolvedWorkItem({
    required String displayId,                            // "FEAT-N" or "CHG-N"
    required WorkItemKind kind,                           // feature | change
    required ResolvedExclusion? exclusion,                // null = included; deferred | merged = excluded
    String? note,                                         // human annotation in the prompt
  }) = _ResolvedWorkItem;
}

enum ResolvedExclusion { deferred, merged }
```

Excluded items appear in `Handoff.resolvedWorkItems` with `exclusion != null` and are rendered as `"FEAT-N (excluded: deferred)"` / `"FEAT-N (excluded: merged)"` per F7-c.

### 1.8 Helper Policy + Snapshot (FR-038a)

**Source**: `app.helper_policies.resolve` (per R-19).
**Identity**: `policy_id` stable string.

```dart
@freezed
class HelperPolicy with _$HelperPolicy {
  const factory HelperPolicy({
    required String policyId,
    required Set<String> allowedHelperCapabilities,
    required String defaultHelperCapability,
    required PolicySource policySource,                   // baked_default | operator_override | repo_override
  }) = _HelperPolicy;
}

@freezed
class HelperPolicySnapshot with _$HelperPolicySnapshot {
  const factory HelperPolicySnapshot({
    required HelperPolicy resolvedPolicy,
    required DateTime snapshottedAt,
    String? operatorOverrideOfPolicyId,                   // when policy_source = operator_override
    String? repoOverridePath,                             // e.g. "agenttower/helper-policy.yaml"
  }) = _HelperPolicySnapshot;
}
```

### 1.9 Drift Signal

**Source**: `app.drift.list` / `app.drift.detail` / `app.drift.transition`.
**Identity**: daemon-issued `finding_id`, stable across lifecycle transitions.

```dart
@freezed
class DriftSignal with _$DriftSignal {
  const factory DriftSignal({
    required String findingId,
    required DriftStatus status,                          // FR-034 lifecycle
    required DriftSource source,                          // static_check | agent_review | operator_report | test_result
    required DriftSeverity severity,                      // info | warning | high | critical
    required DriftConfidence confidence,                  // low | medium | high
    required DateTime ageStartedAt,
    required DriftScope scope,
    required String summary,
    required String recommendedAction,
    required List<DriftEvidence> evidence,
    List<String>? linkedFeatureIds,
    List<String>? linkedChangeIds,
    String? linkedBranch,
    String? linkedWorktree,
    required DateTime asOf,
  }) = _DriftSignal;
}
```

**Allowed transitions** (per F3 sub-edit, FR-034): `new → review_needed → confirmed → repair_planned → resolved` canonical forward path; any non-terminal state may transition to `accepted_as_built` or `dismissed`; `resolved` / `accepted_as_built` / `dismissed` are terminal. No skipping forward states except into the terminal pair.

### 1.10 Validation Entrypoint

**Source**: `app.validation.entrypoint.list`.
**Identity**: daemon-issued `entrypoint_id`, stable per project.

```dart
@freezed
class ValidationEntrypoint with _$ValidationEntrypoint {
  const factory ValidationEntrypoint({
    required String entrypointId,
    required String label,
    required EntrypointType type,                         // FR-047: unit_test | integration_test | contract_test | smoke | e2e | demo_flow | doctor
    required EntrypointScope scope,
    required String description,
    String? recommendedWhen,
    required Duration estimatedDuration,
    required BlockingLevel blockingLevel,                 // informational | recommended | required
    required List<String> tags,
    required bool enabled,
    required DateTime asOf,
  }) = _ValidationEntrypoint;
}
```

### 1.11 Validation Run

**Source**: `app.validation.run.list` / `app.validation.run.detail` / `app.validation.run.trigger` / `app.validation.run.cancel`.
**Identity**: daemon-issued `run_id`, unique per execution. Cancel + re-trigger produces a new id.

```dart
@freezed
class ValidationRun with _$ValidationRun {
  const factory ValidationRun({
    required String runId,
    required String entrypointId,
    required ValidationTarget target,
    required RunState state,                              // FR-048: queued | running | completed | cancelled | failed_to_start
    RunResult? result,                                    // FR-048: pass | fail | partial | error | cancelled — only set in terminal states
    DateTime? startedAt,
    DateTime? completedAt,
    required String summary,
    String? logReference,
    List<RunArtifact>? artifacts,
    required String triggeredBy,
    List<String>? linkedFeatureIds,
    List<String>? linkedChangeIds,
    required DateTime asOf,
  }) = _ValidationRun;
}
```

**Allowed transitions** (per F3 sub-edit, FR-048): `queued → running → completed`; from `queued` or `running` → `cancelled`; from `queued` only → `failed_to_start`. Result field meaningful only in terminal states. `completed` / `cancelled` / `failed_to_start` are terminal.

### 1.12 Demo Readiness Summary

**Source**: `app.demo_readiness.detail` (per-branch).

```dart
@freezed
class DemoReadinessSummary with _$DemoReadinessSummary {
  const factory DemoReadinessSummary({
    required String projectId,
    required String branch,
    required DateTime updatedAt,
    required DemoReadinessState overallState,             // FR-050: unknown | not_ready | at_risk | ready
    required String summary,
    required List<BlockingFinding> blockingFindings,
    required List<RecommendedNextRun> recommendedNextRuns,
    required List<String> recentRunIds,
    required List<String> linkedFeatureIds,
    required DateTime asOf,
  }) = _DemoReadinessSummary;
}
```

**Invariant**: `overallState` MAY be at most `at_risk` if any `required` entrypoint has not run on `branch` (per FR-050).

### 1.13 Attention Item

**Source**: `app.attention.list` / `app.attention.detail`.

```dart
@freezed
class AttentionItem with _$AttentionItem {
  const factory AttentionItem({
    required String attentionId,
    required AttentionClass attentionClass,               // blocked_queue_row | route_skip | degraded_subsystem | drift_confirmed | validation_failed
    required IconData icon,
    required AttentionSeverity severity,                  // info | warning | high | critical
    required DateTime ageStartedAt,
    required String oneLineSummary,
    required ResolutionTarget resolutionTarget,           // typed pointer to the resolution surface
    required DateTime asOf,
  }) = _AttentionItem;
}

@freezed
sealed class ResolutionTarget with _$ResolutionTarget {
  const factory ResolutionTarget.queueRow(String queueRowId) = _QueueRow;
  const factory ResolutionTarget.healthSubsystem(String subsystemId) = _HealthSubsystem;
  const factory ResolutionTarget.driftFinding(String findingId) = _DriftFinding;
  const factory ResolutionTarget.validationRun(String runId) = _ValidationRun;
}
```

### 1.14 Notification

**Source**: `app.notification.list` / `app.notification.history` / `app.notification.acknowledge`.

```dart
@freezed
class Notification with _$Notification {
  const factory Notification({
    required String notificationId,
    required String eventClass,                           // sourced from daemon classifier (R-19 / FR-019)
    required String agentId,
    required NotificationSeverity severity,               // info | warning | high | critical
    required DateTime emittedAt,
    required String summary,
    String? sourceEventId,                                // back-link to underlying event for nav
    required NotificationLifecycle lifecycle,             // incoming | processed | in_history
    required DateTime asOf,
  }) = _Notification;
}
```

**FR-057 grouping rule** is applied as a view-layer projection over a list of Notifications; it does NOT mutate the underlying objects. The projection collapses `N ≥ 3` consecutive Notifications sharing `eventClass` AND `agentId` AND `severity ≤ warning` within a rolling 60-second window into a single grouped row showing count + most-recent timestamp. `high` / `critical` are never grouped.

### 1.15 Operator History Entry

**Source**: `app.operator_history.list` / per-agent rollup endpoint.

```dart
@freezed
class OperatorHistoryEntry with _$OperatorHistoryEntry {
  const factory OperatorHistoryEntry({
    required String entryId,
    required HistoryEntryKind kind,                       // resolved_attention | completed_workflow | other
    required DateTime occurredAt,
    required String parentAgentId,                        // for rollup
    String? subAgentId,                                   // nested per FR-055 + FR-015 2-level cap
    required String summary,
    Map<String, dynamic>? details,
    required DateTime asOf,
  }) = _OperatorHistoryEntry;
}
```

### 1.16 Other read-surface entities (Container, Queue Row, Route, Event)

The remaining FEAT-011 read-surface entities are mirrored 1:1 as freezed classes with the same `asOf` discipline. They follow FEAT-011's documented response shapes byte-for-byte and add no app-side fields. Listed for completeness:

- **Container** — `containerId`, `name`, `discoveredAt`, `projectPath`, `state` (running | exited | …)
- **QueueRow** — `messageId` (daemon-issued; matches the `message_id` wire field used by `app.queue.{detail,approve,delay,cancel}`), `state` (`queued` | `blocked` | `delivered` | `canceled` | `failed`), `payload` (structured `Map<String, dynamic>` — the same shape `app.send_input` accepts, `{"text": "..."}` by convention), `sourceAgentId`, `targetAgentId`, `routeId?`, `createdAt`, `terminalAt?`
- **Route** — `routeId`, `sourceScope`, `template` (FEAT-010 operation template, e.g. `forward_event_to`), `target`, `masterRule`, `enabled`, `recentSkipExplanation?`, `recentMatchSummary?`
- **Event** — `eventId`, `observedAt`, `eventType`, `agentId`, `excerpt`, `linkedQueueRowId?`

---

## 2. App-owned persisted state

### 2.1 Workspace Selection (the only app-persisted entity)

**Location**: `<app-data>/agenttower-control-panel/ux-state.json` (per R-05 + R-06).
**Identity**: per-OS-user singleton (per FR-061a). One Workspace Selection per OS user.
**Persistence**: per FR-069, the enumerated fields below are persisted; nothing else. Per FR-070, the state is restored only on a "compatible app launch" (same app major + same `app_contract_version` major); on mismatch the state is dropped and onboarding/Dashboard is shown.

```dart
@freezed
class WorkspaceSelection with _$WorkspaceSelection {
  const factory WorkspaceSelection({
    required int schemaVersion,                           // currently 1 (per R-21)
    required AppVersionStamp lastWrittenBy,               // app major + app_contract_version major
    required WindowGeometry windowGeometry,
    required ThemeMode themeMode,                         // light | dark | system
    required DensityMode densityMode,                     // comfortable | compact
    required bool notificationsGroupingEnabled,           // default true
    required bool osNativeNotificationsEnabled,           // default false per FR-058
    required Workspace lastActiveWorkspace,               // agent_ops | project_specs | testing_demo | settings
    required Map<Workspace, String> lastActiveSubViewPerWorkspace,  // workspace → sub-view id
    String? lastActiveProjectId,
    required Map<String, ListSortFilterState> listSortFilterGlobal,         // for non-project-scoped views
    required Map<String, Map<String, ListSortFilterState>> listSortFilterPerProject,  // projectId → viewId → state
    required SettingsValues settings,                     // FR-009 toggles, sockets path, etc.
    required Map<OnboardingMilestone, bool> onboardingMilestoneCompletion,
  }) = _WorkspaceSelection;
  factory WorkspaceSelection.fromJson(Map<String, dynamic> json) => _$WorkspaceSelectionFromJson(json);
}
```

#### Supporting types

```dart
@freezed
class AppVersionStamp with _$AppVersionStamp {
  const factory AppVersionStamp({
    required int appMajor,
    required int contractMajor,                           // app_contract_version major
  }) = _AppVersionStamp;
}

@freezed
class WindowGeometry with _$WindowGeometry {
  const factory WindowGeometry({
    required double x, required double y,
    required double width, required double height,
    required bool maximized,
  }) = _WindowGeometry;
}

@freezed
class ListSortFilterState with _$ListSortFilterState {
  const factory ListSortFilterState({
    required String sortField,
    required SortDirection sortDirection,
    required Map<String, dynamic> filters,                // typed-dynamic; deserialized per view registry
  }) = _ListSortFilterState;
}

@freezed
class SettingsValues with _$SettingsValues {
  const factory SettingsValues({
    required String daemonSocketPath,
    required ThemeMode theme,
    required DensityMode density,
    required bool notificationsGrouping,
    required bool osNativeNotifications,
  }) = _SettingsValues;
}

enum OnboardingMilestone {
  daemonReachable,
  benchContainerCheck,
  paneDiscoveryCheck,
  firstPaneAdoption,
  firstAgentRegistration,
  firstLogAttachment,
  firstDirectSend,
  firstRouteCreation,
}
```

#### Persistence write rules

- **Atomic**: write to `ux-state.json.tmp`, `fsync`, `rename` to `ux-state.json`. Per R-05.
- **Cadence**: debounced 250 ms after any UX-state-affecting change; immediate-flush on FR-082 window close (with a 500 ms cap before the close proceeds regardless).
- **Compatibility check**: on read, if `schemaVersion` is older, apply forward-only migrations (R-21); if newer or `lastWrittenBy` major mismatches, drop and reset to defaults (FR-070).
- **Defaults**: a fresh install (no file present) initializes the file with `themeMode = system`, `densityMode = comfortable`, `notificationsGroupingEnabled = true`, `osNativeNotificationsEnabled = false`, empty per-view filter maps, all onboarding milestones `false`, and `lastActiveWorkspace = agentOps`.

#### What is NOT persisted

Per FR-069, the following MUST NOT appear in `ux-state.json` (or any other file the app writes):

- Daemon session token (per FR-003).
- Any domain-owned entity from §1 (Project, Adopted Agent, Master Summary, Pane, Feature/Change Status, Handoff, Helper Policy / Snapshot, Drift Signal, Validation Entrypoint, Validation Run, Demo Readiness, Attention Item, Notification, Operator History Entry, Container, Queue Row, Route, Event).
- Handoff drafts that are pre-`submitted` (these live in app memory; a draft lost on app close is not recoverable — this is intentional per the FR-072(a) "drafted + error attached" being the persistence boundary; pre-submit drafts are not yet on the daemon).

---

## 3. Cross-cutting invariants

- **Identity stability**: every daemon-owned entity uses the daemon-issued id. The app never mints, mutates, or relabels these ids (FR-005).
- **`asOf` discipline**: every daemon-owned model carries `asOf` so reconnect logic (FR-003) can detect stale views without persisting them. Live-update subscriptions update `asOf` on each event.
- **Lifecycle validation**: state transitions for Pane (FR-014), Drift (FR-034), Handoff (FR-044), Validation Run (FR-048), and Feature/Change `deferred` stage (F7-b) are encoded as `LifecycleValidator` functions under `lib/domain/lifecycles/` and asserted in unit tests. The app refuses to render a state-transition outcome that does not match the validator.
- **Master qualification (FR-071)**: the `MasterSummary` projection from an `AdoptedAgent` is gated on both `role == master` AND `capability ∈ masterClassCapabilities`. The master-class set is fetched from the daemon (R-19) and cached for the session.
- **Workspace Selection durability**: writes go through a single `WorkspaceSelectionRepository` that owns the JSON file path resolution (per OS, per FR-061a), the atomic-write, the schema-version migration, and the FR-070 compatibility gate. Tests of this repository do not require Flutter — they're pure-Dart unit tests with an in-memory file backend.
