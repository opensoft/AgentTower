## Why

The FEAT-012 spec already captures the right product shape, but several
clarified decisions were still missing from the normative text. This change
brings the spec back into sync with the clarification rounds so downstream
planning, review, and implementation do not have to guess at lifecycle,
identity, onboarding, helper-policy, and doctor-check behavior.

## What Changes

- Add missing acceptance scenarios for clarified bootstrap, restore, handoff,
  supersede, and notification-grouping behaviors.
- Add identity rules to the affected key entities and tighten the persisted UX
  state model.
- Add explicit lifecycle transition rules for panes, drift signals, handoffs,
  and validation runs.
- Define the helper-agent policy contract, `deferred` feature stage semantics,
  canonical feature-range syntax, onboarding completion criteria, and Settings
  doctor checks.
- Normalize terminology and add required FR-079 document-rendering references.

## Capabilities

### New Capabilities
- `flutter-control-panel-spec-quality-pass`: OpenSpec-managed quality pass over
  the FEAT-012 Flutter control panel specification.

### Modified Capabilities
- None.

## Impact

- Updates only `specs/012-flutter-control-panel/spec.md`.
- Creates OpenSpec proposal, design, delta-spec, task, and handoff artifacts
  for human review before archive.
- Changes no implementation code, runtime behavior, or FEAT-011 contract text.
