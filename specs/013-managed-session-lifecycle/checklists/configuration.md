# Configuration Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that configuration requirements (templates, launch command profiles, paths, defaults, validation) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Schema Definition

- [x] CHK001 Are the standard templates' configuration shapes specified (file format, location, schema)? [Gap, Spec §FR-001]
- [x] CHK002 Are the standard templates' default contents (1 master + 2 slaves, 2 masters + 2 slaves) specified field-by-field? [Gap, Spec §FR-001]
- [x] CHK003 Are the launch command profile configuration shapes specified (file format, location, fields)? [Gap, Spec §FR-002]
- [x] CHK004 Are configuration requirements specified for label-pattern templates (FR-003) — is the pattern configurable per template? [Gap, Spec §FR-003]

## Defaults & Overrides

- [x] CHK005 Are configuration overrides specified (per-container, per-layout-instance, per-pane)? [Gap]
- [x] CHK006 Are defaults specified for omitted configuration fields (default capability, default label pattern, default working directory)? [Gap]
- [x] CHK007 Are the precedence rules between operator-supplied launch commands and template-default commands specified? [Clarity, Spec §FR-002]

## Validation

- [x] CHK008 Are validation requirements specified for configuration before layout creation (required fields, command syntax, label-pattern syntax)? [Gap]
- [x] CHK009 Are validation requirements specified for the tmux session name input (length, character set)? [Gap, Spec §FR-016]

## Lifecycle

- [x] CHK010 Are configuration reload requirements specified (does the daemon hot-reload, or restart-only)? [Gap]
- [x] CHK011 Are configuration migration requirements specified across versions of the template schema? [Gap, Cross-ref: deployment.md]
- [x] CHK012 Are configuration requirements specified for the durable storage path used by FR-020? [Gap, Spec §FR-020]
- [x] CHK013 Are configuration requirements specified for the canonical local-socket path (FR-017)? [Gap, Spec §FR-017]
- [x] CHK014 Are configuration requirements specified for the scan interval that interacts with the pending-managed marker (FR-014)? [Gap, Spec §FR-014]
- [x] CHK015 Are configuration requirements specified for the audit retention behavior in MVP (file location, format) even though retention is indefinite? [Gap, Spec §FR-021]

## Tmux Adapter

- [x] CHK016 Are configuration requirements specified for which tmux pane-control flags AgentTower must support? [Gap]
- [x] CHK017 Are configuration requirements specified for tmux server selection (default socket vs custom)? [Gap]

---

## Walk closure (2026-05-25)

17/17 items resolved by R8/R9 (template + launch profile YAML schemas) + FR-024 (operator override with name-wins precedence and no-auto-create policy from pre-implement walk topic H) + spec §Assumptions (canonical YAML paths) + FR-016 (input validation from pre-implement walk topic D) + examples/managed_templates/ and examples/launch_commands/ as discoverable references (T003).
