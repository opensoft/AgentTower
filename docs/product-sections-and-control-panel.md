# AgentTower Product Workspaces and UX Outline

Status: Draft productization note  
Date: 2026-05-22

This document reframes AgentTower as a local-first operator system with three
primary workspaces:

1. Agent Operations
2. Project and Specs
3. Testing and Demo

The intent is to define the operator UX first and let the later UI follow from
that.

## 1. Major Product Sections

### 1.1 Core runtime and control plane

The host daemon and local data model remain the source of truth.

Includes:

- `agenttowerd`
- local Unix socket protocol
- SQLite state
- JSONL event history
- Docker bench-container discovery
- tmux pane discovery
- agent registration, roles, and capabilities
- safe queueing and prompt delivery
- routing and arbitration

This is the system underneath every other product layer.

### 1.2 App backend contract

This is the structured app-facing surface over the daemon.

Includes:

- versioned `app.*` namespace
- bootstrap and readiness methods
- structured list/detail responses
- structured mutation responses
- closed-set error codes
- host-only app access policy
- pagination, ordering, filtering, and idempotency rules

The desktop app should talk to this layer, not parse human CLI output.

### 1.3 Desktop operator product

This is the end-user product surface.

The preferred implementation path is a local Flutter desktop app for Windows,
macOS, and Linux that talks only to the local daemon.

The product should be organized into three operator workspaces:

- Agent Operations
- Project and Specs
- Testing and Demo

### 1.4 Packaging and install experience

Includes:

- installer/bootstrap flow
- daemon setup
- socket and mount contract checks
- local state initialization
- desktop app packaging
- config doctor and preflight tooling
- upgrade and migration handling

### 1.5 Operational hardening

Includes:

- restart recovery
- duplicate suppression
- degraded-state handling
- log rotation and file replacement handling
- cleanup of dead sessions and stale processes
- lock/contention behavior
- audit durability and outage behavior
- repeatable smoke validation

### 1.6 Validation and release discipline

Includes:

- daemon and app contract tests
- integration and end-to-end tests
- restart/load drills
- packaging/install smoke tests
- compatibility checks across app and daemon versions
- review and CI quality gates

## 2. Product Workspace Model

AgentTower should not be treated as a single control panel with a handful of
tabs. It should be treated as three related but distinct operator workspaces.

### 2.1 Agent Operations workspace

This is the live control-tower side of AgentTower.

It answers:

- what agents exist
- what they are doing
- what is blocked
- what needs intervention
- which agent can drive which other agent
- what happened recently in live operations

### 2.2 Project and Specs workspace

This is the product-definition side of AgentTower.

This is expected to be where the operator spends a large share of their time.

It answers:

- which project am I looking at
- what specs, PRDs, and architecture documents define it
- which feature or change is active now
- which agent is driving that feature
- where did we leave off
- where is spec drift emerging

This workspace is essential because the operator will often forget the exact
state of a given project if juggling several projects at once.

### 2.3 Testing and Demo workspace

This is the validation-control side of AgentTower.

It answers:

- what tests and demos are available
- what should be run now
- what ran recently
- what passed or failed
- whether the current branch or project state is demo-ready

This workspace is not a test authoring system and not a simulation framework.
It is an operator surface for seeing available validation and controlling it.

## 3. Agent Operations UX Model

This workspace defines the live operational experience for running agents.

### 3.1 Primary operator questions

The workspace should answer:

1. Is AgentTower healthy enough to use right now?
2. What containers and panes exist?
3. Which panes are unmanaged versus managed?
4. Which registered agents are active, idle, blocked, or degraded?
5. Which agents can safely receive prompts?
6. What just happened?
7. What needs operator action now?
8. Which routes exist, and what will they do?

### 3.2 Core user states

The operator moves through a small set of recognizable states:

- runtime unavailable
- runtime healthy, no bench containers
- containers found, no panes
- panes found, not yet adopted
- agents registered, logs not attached
- managed and operational
- degraded but usable

The UX must distinguish these states clearly instead of collapsing them into
"empty" or "error" in a generic way.

### 3.3 Core entity states

The UI should make these distinctions first-class:

#### Pane state

- discovered and unmanaged
- discovered and registered
- inactive/stale
- discovery-degraded

#### Agent state

- active
- inactive
- partially configured
- log-attached or not
- parent/child swarm relationship where applicable

#### Queue state

- pending
- in_flight
- blocked
- expired
- cancelled
- delivered

#### Route state

- enabled
- disabled
- healthy
- recently skipped
- target/match context understandable

### 3.4 Primary workflows

The first release should optimize for four top-level workflows:

#### Workflow 1: Bootstrap and understand the runtime

The user needs to know:

- is the runtime reachable?
- are containers present?
- are panes discoverable?
- is anything already managed?
- what is the next action?

#### Workflow 2: Adopt an existing pane into management

The user already has a live tmux pane and wants AgentTower to own it as an
agent.

The flow must keep these values explicit:

- label
- role
- capability
- project path
- whether to attach a log now

#### Workflow 3: Observe live operations and diagnose problems

The user wants to see:

- what happened recently
- which agents are asking for attention
- which deliveries are blocked
- whether routes are firing
- whether a subsystem is degraded

#### Workflow 4: Intervene

The user needs to act:

- send direct input
- approve/delay/cancel queued input
- add/remove/enable/disable route
- attach/detach log
- update role/capability/label

The first round intentionally does not add heavy confirmation/warning UX for
all risky actions. That can be added later.

### 3.5 Attention queue and operator history

The first control-panel release should include a dedicated operator attention
queue.

This queue is the primary answer to:

- what needs action now
- what changed since I last looked
- what can wait

Requirements:

- every queue item has a class, severity, and age
- queue items use icon + color consistently:
  - icon communicates issue class
  - color communicates severity/priority
- each queue item must be directly clickable into its resolution surface
- the queue must show how long the issue has existed
- the queue should use a severity/priority indicator that is visible at a
  glance without requiring text-only scanning

Stability rule:

- avoid aggressive auto-reordering while the operator is actively interacting
  with the queue
- live updates must not make it difficult to click or inspect the intended item

The app should also maintain a durable operator history and resolution flow.

The model should be:

- active queue for unresolved/actionable items
- history for processed/acknowledged/completed items

History requirements:

- durable and reviewable
- default presentation rolled up by agent
- sub-agent histories shown beneath parent agents

### 3.6 Agent-first workspace model

The UX should treat the agent and its current goal or task as the primary
operational unit, not the raw pane.

The mental model should be:

- agent
- agent goal or current task
- sub-agents beneath that agent

This implies a tree-oriented experience with rollups and group management.

### 3.7 Relationship UX

The first release should make current relationships explicit.

Focus in the first round:

- show which agents are currently connected
- show parent/child relationships
- show current route relationships
- show current operational linkage between agents

The first release should also include a graph view for current relationships.

Deferred:

- speculative or future-relationship planning as a first-class concept

### 3.8 Noise management and AI-assisted prioritization

The system should not force the operator to manually sift through every event
with equal weight.

First-release direction:

- AgentTower should actively reduce noise for the user
- AI-assisted filtering/prioritization is allowed and desirable
- the user may tune or override the result, but the default product
  responsibility is to surface signal over noise

Deferred:

- raw-mode / log-inspector UX as a first-class surface

### 3.9 Guided onboarding

The first release should include guided onboarding and progressive setup.

The app should guide the operator through at least:

- daemon reachable
- bench container found
- panes found
- first pane adopted
- first agent registered
- first log attached
- first direct send
- first route created

### 3.10 Multi-container and project orientation

The first release should optimize primarily for multi-container operation.

The default operator lens should be project-centered across one or more
containers.

Rule:

- container boundaries are explicit in the Containers view
- elsewhere, container identity appears as supporting context rather than the
  primary navigation model

### 3.11 Explainability UX

The app should make system behavior explainable in human terms.

The operator should be able to answer:

- what happened
- why it happened
- what source caused it
- what route, rule, or permission gate applied

The first release should include explainability surfaces for:

- route match
- route skip
- blocked queue item
- degraded subsystem state

### 3.12 Notifications and notification history

The first release should include an in-app notifications panel.

Requirements:

- notifications appear in a scrollable list/panel
- after the operator clicks or processes a notification, it should move to
  notification history
- notification history should remain reviewable

Recommended split:

- attention queue = actionable operational items
- notifications panel = incoming surfaced changes/events
- notification history = processed notification trail

OS-native notification integration should be optional via config.

## 4. Project and Specs UX Model

This workspace is centered on the project definition, not the live terminal
surface.

The primary unit here is the project and its defining documents:

- PRD
- architecture
- roadmap
- Spec Kit feature specs
- OpenSpec proposed changes

### 4.1 Primary operator questions

This workspace should answer:

1. Which project am I looking at?
2. What is the current intended shape of this project?
3. What feature or change is active right now?
4. Which agent is driving that feature or change?
5. What phase is that feature or change in?
6. Where are the relevant docs?
7. What changed since I last worked on this project?
8. Where is spec drift emerging?

### 4.2 Core UX goals

- make project context recoverable quickly after time away
- make the active feature/change obvious
- make the relevant documents one click away
- connect agents to spec work explicitly
- let the operator refine the spec without repo spelunking

### 4.3 Primary entities

The workspace should center on:

- project
- feature spec
- OpenSpec change/proposal
- document set
- agent assignment against a feature/change
- current workflow phase/state

#### Project definition

For the first release, define a project as a repository.

That means:

- one project maps to one repository
- the project/specs workspace is repo-centered
- worktrees, branches, active features, and validation are subordinate context
  beneath the repository

#### Feature/change driving status model

Each feature or change should carry a shared status model used across:

- project cards
- master summaries
- project/specs workspace
- development workflow workspace
- testing/demo workspace
- drift handling

The model should have three layers:

1. stage
2. status
3. optional subphase

Lifecycle stages:

- `definition`
- `spec_ready`
- `engineering`
- `review`
- `validation`
- `merge_ready`
- `merged`
- `drift_repair`

Execution statuses:

- `not_started`
- `active`
- `waiting`
- `blocked`
- `at_risk`
- `complete`

Subphase is optional and captures the more specific workflow token/detail.

Examples:

- `openspec.propose`
- `speckit.specify`
- `speckit.plan`
- `speckit.implement`
- `pr_review_round_2`
- `validation_integration`
- `awaiting_merge`

Display rule:

- show a human-readable combined label first
- allow the underlying token/detail to be visible as supporting context

Examples:

- `Engineering / Active`
- `Review / Waiting`
- `Validation / At Risk`
- `Drift Repair / Active`

Semantics:

- `waiting` = progress can continue later without a hard fault
- `blocked` = work cannot proceed without intervention
- `at_risk` = work is proceeding but a meaningful issue threatens progress

`drift_repair` stage is used when implementation/spec mismatch has been
confirmed strongly enough that corrective planning and engineering work are
required.

Multiple features may be active within one project, but summary surfaces should
still choose a primary feature/change for concise display.

### 4.4 Primary workflows

#### Workflow 1: Re-orient to a project

The user returns to a project and needs to know:

- what this project is
- what the current active feature/change is
- what the last meaningful work was
- which agent was working on it

#### Workflow 2: Open the active feature/change

The user sees that agent X is driving FEAT-N or OpenSpec change Y and needs to
jump straight into the relevant documents.

The UX should make it easy to click directly to:

- PRD
- architecture
- roadmap
- current feature spec
- current OpenSpec change

#### Workflow 2a: Understand what "driving" means

For AgentTower, "driving" means:

- a master agent is controlling one or more slave terminals
- the master is operating against the repository's defining docs
- the master is following the PRD, architecture, and feature definitions

The operator should be able to hand the master an explicit prompt such as:

- drive FEAT-N through FEAT-M

The product assumption is:

- the PRD and feature definitions already exist, whether created through
  AgentTower's project/specs workspace or through another AI/doc workflow
- once those feature definitions exist, driving means directing the master agent
  to read the relevant docs and execute the engineering workflow end to end

The intended end-to-end driving scope is:

- read architecture and relevant docs
- execute the Speckit workflow from specify through implementation
- continue through PR creation
- continue through multiple rounds of PR review
- continue through merge

#### Workflow 3: Refine the spec

The user needs to update the feature definition, clarify requirements, or
adjust the project intent.

The UX should make it easy to invoke the correct flow for:

- Spec Kit feature refinement
- OpenSpec change/proposal refinement

Workflow ownership model:

- OpenSpec is the master tool for core specs and docs:
  - PRDs
  - architecture
  - long-lived spec/document maintenance
- Speckit is the engineering workflow:
  - feature-by-feature implementation workflow
  - engineering execution lifecycle

Operational split:

- use OpenSpec to manage and maintain the core project-definition layer
- use Speckit to drive engineering work for concrete features
- use OpenSpec inside engineering only when a local feature reveals a required
  correction or adjustment to the higher-level specs/docs

#### Workflow 4: Understand drift

The user needs to see whether the current branch/work is drifting from the
intended spec or whether a project has gone stale/confusing.

For AgentTower, drift means:

- built code no longer matches the intended spec

Drift handling model:

1. identify that implementation and spec are out of alignment
2. use OpenSpec to re-align the spec to the current as-built reality so the
   current system is described accurately
3. create a proposal/change contract describing the move from as-built back to
   as-designed
4. use that proposal to generate one or more Speckit features that refactor the
   implementation back toward the intended design

This means drift is not just a warning surface; it is the trigger for a repair
workflow spanning OpenSpec and Speckit.

### 4.5 Recommended workspace structure

The project/specs workspace should likely have these sub-surfaces:

1. Projects
2. Current Work
3. Specs
4. Changes
5. Drift

#### Projects

Shows all tracked projects with:

- project name
- current branch/worktree context
- active feature/change
- last activity
- assigned/active agents
- validation status summary
- active master summary count

Presentation choice for the first release:

- use project cards rather than a dense project table
- this is appropriate because the expected concurrent project count is small
  (roughly 5 or fewer at a time)
- cards should optimize for quick re-orientation and clear per-project summaries

Project card model for the first release:

- project name
- repository path/name
- repo state badge
- active branch/worktree badge
- active feature/change
- current phase/status
- current driving master
- compact master strip
- sub-agent count
- last activity
- validation badge + last run age
- drift badge + source + age
- attention summary
- unread notification count
- quick actions:
  - open project
  - open current feature
  - view current master
  - run validation

Supporting rules:

- the identity block should include repository state plus branch/worktree state
- the current-work summary should include active feature/change, driving master,
  and current workflow phase
- master summary should show a compact strip of up to two active masters with
  overflow summarized
- last activity should use hybrid logic:
  - prefer meaningful agent/project workflow activity
  - fall back to repo activity when no live agent signal exists
- validation state on the card should show status plus age of last validation
  result
- drift state on the card should show:
  - drift status
  - detection source
  - age of the finding
- attention summary should distinguish operational attention from notification
  count

#### Current Work

Shows:

- which feature/change is active now
- which agent is driving it
- current workflow phase
- recent activity on that feature/change
- direct links to the relevant docs

Visibility rule:

- current work should be visible from both the Project and Specs workspace and
  the Agent Operations / development workflow context
- if a feature in the specs workspace is currently being driven by an agent,
  that feature should show the active driving state
- in the development workflow view, the operator should see masters first and
  drill into a master to inspect its sub-agents

Master summary model for the first release:

- master label
- capability
- role badge
- active/inactive badge
- current status
- assigned project
- primary assigned feature/change with overflow summary
- human-readable workflow phase
- optional underlying workflow token/detail
- sub-agent rollup:
  - count
  - state summary
- attention severity + open actionable count
- last meaningful activity
- compact validation badge
- quick actions:
  - open master
  - view assigned work
  - view sub-agents
  - open queue/issues

Supporting rules:

- identity block should include label, capability, role, and active/inactive
  state
- current status should support:
  - active
  - waiting_for_input
  - blocked
  - reviewing
  - idle
  - offline
  - degraded
- assigned work should show one primary feature/change plus overflow summary
- phase display should be hybrid:
  - human-readable phase label first
  - workflow-specific token/detail optionally visible
- sub-agent summary should show count plus state rollup, not only raw count
- last activity should use hybrid logic:
  - prefer meaningful workflow activity
  - fall back to last event if needed
- validation state on the summary should be compact and scoped to current work
- this summary should appear both:
  - inside a project context
  - in a cross-project development/operations view

#### Specs

Document-centered view for:

- PRD
- architecture
- roadmap
- feature specs

Navigation model:

- project first
- then feature
- when viewing a feature, show a document list/panel for the document set that
  contains or contextualizes that feature

#### Changes

Shows proposed or active changes, especially OpenSpec-side change work.

#### Drift

Shows signals that:

- current branch is out of sync with the intended feature/change
- docs/specs are stale relative to active work
- multiple projects have diverged and need operator review

Drift detection is expected to be difficult and should likely rely on an
ongoing agent-driven analysis loop rather than only static checks.

Recommended drift model:

- hybrid approach
- static checks for obvious drift
- agent-driven review loop for deeper semantic drift

### 4.6 UX principles

- project-first
- document-centered
- agent-linked
- phase-aware
- easy re-entry after time away
- one-click navigation to the right spec artifact
- drift should be visible and actionable

Core action model in this workspace:

- view docs
- update docs
- launch spec workflow
- re-enter prior context
- hand work to an agent

Handing work to an agent may happen either from the project/specs workspace or
from the engineering/development workflow context, depending on what the
operator is doing.

Recommended handoff flow:

1. choose agent
2. attach agent to project
3. show the features that the agent can work on
4. allow the operator to select one, a set, or all
5. generate the master-driving prompt automatically
6. run

The system should also maintain defaults/configuration for:

- which other agent systems a master is allowed to employ
- which helper agent types are preferred for which classes of tasks

Example concern:

- which agent is the best librarian/research helper

Deferred follow-up:

- move agent-capability mapping and helper-prompt policy into a separately
  updateable service so AgentTower can subscribe to the latest recommended
  routing/mapping rules

## 5. Testing and Demo UX Model

This workspace is centered on validation control, not on test authoring.

### 5.1 Primary operator questions

1. What tests and demos exist for this project or branch?
2. What should I run now?
3. What ran recently, and what happened?
4. Is this branch or project state demo-ready?
5. Where did validation fail?

### 5.2 Scope

This workspace should:

- show available tests and demos
- group them by project, branch, or logical suite
- let the operator run them
- show recent results

This workspace should not try to:

- generate all test cases
- simulate whole systems
- replace the underlying test frameworks

### 5.3 Primary workflows

#### Workflow 1: Inspect available validation

The user should be able to see what validation exists for the current project
or branch.

#### Workflow 2: Run current validation

The user should be able to trigger the available validation flow for the
current project or branch without remembering shell commands.

#### Workflow 3: Judge demo readiness

The user should be able to tell whether the current branch or project is ready
for demo or needs more work.

### 5.4 UX principles

- operator-facing, not framework-facing
- current-project aware
- branch-aware
- recent-result visibility first
- demo readiness should be explicit

## 6. Handoff Prompt Model

This section defines how AgentTower should hand work to a master agent.

The handoff flow is one of the core product actions:

- choose master
- attach/select project
- select one or more features or changes
- generate the driving prompt
- submit it to the master
- persist the assignment and its context

### 6.1 Required inputs

The handoff flow should require:

1. master agent
2. project/repository
3. work item selection
4. mode

Work item selection should support:

- one feature
- multiple features
- feature range such as `FEAT-N` through `FEAT-M`
- one OpenSpec change
- multiple OpenSpec changes

Mode should support:

- spec refinement
- engineering execution
- drift repair
- validation/demo prep

### 6.2 Optional inputs

Optional inputs should include:

- priority
- deadline or milestone target
- helper-agent policy override
- operator notes or intent

### 6.3 Auto-filled context

The system should inject the obvious context so the operator does not have to
rebuild it manually.

Auto-filled context should include:

- project/repository identity
- active branch/worktree if relevant
- PRD path
- architecture doc path
- roadmap path
- selected feature spec paths
- selected OpenSpec change paths
- current feature/change stage, status, and subphase
- known drift state
- current validation state
- allowed helper-agent defaults
- repo-specific workflow rules

### 6.4 Prompt structure

The generated prompt should use a stable sectioned structure.

Recommended sections:

1. Assignment
2. Project Context
3. Workflow Instruction
4. Helper-Agent Policy
5. Success Criteria
6. Stopping and Escalation Rules

#### Assignment

Examples:

- drive `FEAT-011` through `FEAT-013`
- refine OpenSpec change `change-xyz`
- perform drift repair for `FEAT-009`

#### Project Context

Should include:

- repository
- relevant document paths
- current project state

#### Workflow Instruction

Should tell the master which workflow system governs the assignment.

Examples:

- use OpenSpec for core spec/doc maintenance
- use Speckit for engineering workflow
- run the full Speckit flow in order when executing engineering work
- obey repo-specific workflow constraints

#### Helper-Agent Policy

Should include:

- which helper systems are allowed
- which helper roles are preferred for which task types

#### Success Criteria

Should state what "done" means for the assignment.

#### Stopping and Escalation Rules

Should state:

- when to continue autonomously
- when to ask the operator
- when to stop because of mismatch or blocker

### 6.5 Prompt modes

The generated prompt should vary by mode.

#### Spec refinement

Emphasize:

- docs first
- OpenSpec ownership
- clarifying intent
- updating spec artifacts

#### Engineering execution

Emphasize:

- read PRD, architecture, and selected feature docs
- run the Speckit flow end to end
- continue through PR, review, and merge loop

#### Drift repair

Emphasize:

- compare as-built versus as-designed
- update OpenSpec/specs to describe current reality
- create corrective proposal/change contract
- generate and drive follow-on Speckit features to restore intended design

#### Validation/demo prep

Emphasize:

- inspect available tests and demos
- run validation
- summarize readiness and blockers

### 6.6 Range handling

If the operator selects a range such as `FEAT-N` through `FEAT-M`, AgentTower
should normalize it into an explicit ordered work list.

The system should resolve:

- exact features included
- missing feature numbers
- deferred features
- already-merged features

The master should receive the explicit resolved list, not only shorthand.

### 6.7 Persistence model

Each handoff should be durable and reviewable.

The stored handoff object should include:

- handoff id
- timestamp
- operator
- target master
- project
- selected work items
- generated prompt text
- prompt mode
- helper-agent policy used
- current assignment state
- linked feature/change ids

### 6.8 Assignment states

The handoff itself should have its own lifecycle.

Recommended states:

- drafted
- submitted
- accepted
- active
- waiting
- blocked
- completed
- cancelled
- superseded

This assignment-state model is separate from the feature/change lifecycle
status model.

### 6.9 Recommended UX flow

1. user selects master
2. user selects project
3. user selects feature(s)/change(s)
4. AgentTower suggests mode
5. AgentTower shows helper-agent policy/defaults
6. AgentTower generates preview
7. user edits optional notes if needed
8. user submits
9. handoff is stored and linked to:
   - master
   - project
   - features/changes

### 6.10 Editable vs system-owned content

The operator should be able to edit:

- optional notes
- selected work items
- mode
- helper policy override
- priority
- deadline

The operator should not normally edit the entire generated base prompt
template.

Preferred model:

- the system owns the prompt skeleton
- the operator may add or adjust a thin instruction layer on top

### 6.11 Future follow-up

Agent helper-capability mapping and helper-prompt policy should eventually be
moveable into a separately updateable service so AgentTower can subscribe to
newer recommended mappings and prompt bundles without hard-coding all defaults
forever.

### 6.12 Handoff object schema

The generated handoff should be stored as a durable structured object.

Recommended first-release schema:

- `handoff_id`
- `created_at`
- `updated_at`
- `operator_id`
- `project_repo`
- `project_label`
- `target_master_agent_id`
- `target_master_label`
- `mode`
- `priority`
- `deadline_at` optional
- `assignment_state`
- `selected_work_items`
- `resolved_work_items`
- `primary_work_item`
- `linked_feature_ids`
- `linked_change_ids`
- `context_bundle`
- `helper_policy_id`
- `helper_policy_snapshot`
- `generated_prompt`
- `operator_notes`
- `submitted_at` optional
- `accepted_at` optional
- `completed_at` optional
- `cancelled_at` optional
- `superseded_by_handoff_id` optional

#### Field semantics

`selected_work_items`

- what the operator chose directly
- may include shorthand such as feature ranges

`resolved_work_items`

- explicit normalized ordered list after expansion/resolution
- this is what the master actually receives as the work list

`context_bundle`

- repo and worktree context
- doc paths
- workflow constraints
- current feature/change state summaries
- drift and validation context known at handoff time

`helper_policy_snapshot`

- materialized policy used for this handoff at generation time
- preserves historical reproducibility even if defaults later change

#### Recommended storage rules

- store the full generated prompt text
- preserve both shorthand user intent and explicit resolved work list
- preserve a snapshot of the helper policy used
- keep handoffs queryable by project, master, feature/change, and assignment
  state

## 7. Drift Signal Model

Drift should be treated as a first-class product signal, not just an incidental
 warning.

### 7.1 Definition

For AgentTower, drift means:

- implementation no longer matches intended specification strongly enough that
  operator review or corrective work is required

### 7.2 Recommended hybrid model

Use a hybrid approach:

1. static checks for obvious drift
2. agent-driven review loop for deeper semantic drift

This avoids relying only on brittle static rules while still keeping some
 deterministic signals.

### 7.3 Drift signal schema

Recommended first-release fields:

- `drift_signal_id`
- `project_repo`
- `scope_type`
- `scope_id`
- `detected_at`
- `updated_at`
- `severity`
- `confidence`
- `source`
- `status`
- `summary`
- `details`
- `recommended_action`
- `linked_feature_ids`
- `linked_change_ids`
- `linked_branch` optional
- `linked_worktree` optional
- `reviewed_at` optional
- `resolved_at` optional

#### Scope types

- `project`
- `feature`
- `change`
- `branch`
- `worktree`
- `assignment`

#### Sources

- `static_check`
- `agent_review`
- `operator_report`
- `test_result`

#### Statuses

- `new`
- `review_needed`
- `confirmed`
- `accepted_as_built`
- `repair_planned`
- `resolved`
- `dismissed`

#### Severity

- `info`
- `warning`
- `high`
- `critical`

#### Confidence

- `low`
- `medium`
- `high`

### 7.4 Static drift checks

First-release static checks should focus on obvious mismatches such as:

- active branch/worktree not matching intended feature/change
- feature/work assignment not matching current repo context
- expected spec artifact missing
- merged or deferred feature still treated as active work
- validation state inconsistent with claimed feature status
- PR/review state inconsistent with internal workflow stage

### 7.5 Agent-driven drift review

Agent-driven review should look for higher-order mismatch such as:

- code behavior appears inconsistent with the spec intent
- docs/specs are stale relative to active implementation
- active work is targeting the wrong feature or wrong project context
- as-built state no longer matches as-designed expectations

This loop should produce human-readable findings, not opaque scores only.

### 7.6 Drift handling workflow

The intended drift workflow is:

1. detect likely drift
2. review/confirm drift
3. if confirmed, align documentation to as-built reality where needed
4. create an OpenSpec proposal/change contract for returning to as-designed
5. generate one or more Speckit features to execute the corrective refactor

The Drift workspace should support that workflow directly.

### 7.7 Recommended presentation

At summary level, show:

- drift status
- source
- age
- severity

At detail level, show:

- human-readable explanation
- supporting evidence
- recommended next action
- linked features/changes/branches

## 8. Testing and Demo Workspace Data Model

This workspace should expose validation as an operator-controlled system, not
as raw test-runner output only.

### 8.1 Primary objects

Recommended first-release objects:

1. validation target
2. validation entrypoint
3. validation run
4. demo readiness summary

### 8.2 Validation target

A validation target is the thing the user is validating.

Recommended fields:

- `target_id`
- `project_repo`
- `branch`
- `worktree`
- `target_label`
- `target_type`
- `linked_feature_ids`
- `linked_change_ids`

`target_type` examples:

- `project`
- `branch`
- `feature_set`
- `change_set`

### 8.3 Validation entrypoint

A validation entrypoint is a runnable test/demo action known to AgentTower.

Recommended fields:

- `entrypoint_id`
- `project_repo`
- `label`
- `entrypoint_type`
- `scope`
- `command_or_runner_ref`
- `description`
- `recommended_when`
- `estimated_duration`
- `blocking_level`
- `tags`
- `enabled`

`entrypoint_type` examples:

- `unit_test`
- `integration_test`
- `contract_test`
- `smoke`
- `e2e`
- `demo_flow`
- `doctor`

`blocking_level` examples:

- `informational`
- `recommended`
- `required`

### 8.4 Validation run

A validation run is one execution of an entrypoint against a target.

Recommended fields:

- `run_id`
- `entrypoint_id`
- `target_id`
- `started_at`
- `completed_at` optional
- `state`
- `result`
- `summary`
- `log_ref`
- `artifact_refs`
- `triggered_by`
- `linked_feature_ids`
- `linked_change_ids`

`state` examples:

- `queued`
- `running`
- `completed`
- `cancelled`
- `failed_to_start`

`result` examples:

- `pass`
- `fail`
- `partial`
- `error`
- `cancelled`

### 8.5 Demo readiness summary

This is the operator-facing answer to "can I demo this now?"

Recommended fields:

- `readiness_id`
- `project_repo`
- `branch`
- `updated_at`
- `overall_state`
- `summary`
- `blocking_findings`
- `recommended_next_runs`
- `recent_runs`
- `linked_feature_ids`

`overall_state` examples:

- `unknown`
- `not_ready`
- `at_risk`
- `ready`

### 8.6 Recommended UX behavior

The Testing and Demo workspace should:

- show available entrypoints grouped by project/branch
- show which entrypoints are required vs recommended
- show recent run history
- show the current demo readiness summary clearly

The first release should not try to replace raw test tooling, only to organize
and control it.

## 9. UI Outline

The UI should follow the workspace model rather than flatten everything into a
single navigation list.

### 9.1 Top-level navigation

1. Agent Operations
2. Project and Specs
3. Testing and Demo
4. Settings

### 9.2 Agent Operations navigation

1. Dashboard
2. Containers
3. Panes
4. Agents
5. Events
6. Queue
7. Routes
8. Health

### 9.3 Project and Specs navigation

1. Projects
2. Current Work
3. Specs
4. Changes
5. Drift

### 9.4 Testing and Demo navigation

1. Available Validation
2. Runs
3. Demo Readiness

### 9.5 Shared surfaces

- notifications panel
- notification history
- global project switcher
- settings

## 10. Delivery Order

### FEAT-012

Flutter desktop control panel for the first three workspaces:

- Agent Operations:
  - dashboard
  - containers
  - panes
  - agents
  - events
  - queue
  - routes
  - health
  - adopt/register flow
  - log attach/detach
  - direct send
  - route management
- Project and Specs:
  - project list
  - current work
  - specs navigation
  - change navigation
  - drift surface
- Testing and Demo:
  - available validation
  - run controls
  - run history
  - demo readiness
- shared:
  - notifications panel
  - settings

### FEAT-013

Managed session creation and lifecycle:

- create panes
- launch agent CLIs
- auto-register
- auto-attach logs
- delete/recreate managed panes

### Later

- richer live event stream UX
- better swarm visualizations
- log inspector / raw mode
- future-relationship planning UX
- more advanced drift analysis
- optional V2 daemon-container deployment UI
