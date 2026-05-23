## MODIFIED Requirements

### Requirement: FEAT-012 spec quality pass targets specs/012-flutter-control-panel/spec.md
This change MUST apply only to `specs/012-flutter-control-panel/spec.md` and
the OpenSpec change artifacts for `spec-quality-pass-feat-012`. It MUST encode
the 12 Tier-1 quality findings already identified for FEAT-012 without adding
new feature scope beyond those findings.

#### Scenario: Apply only the target spec delta
- **WHEN** the change is reviewed
- **THEN** the reviewer can confirm that the only product-spec file modified by
  the change is `specs/012-flutter-control-panel/spec.md`

#### Scenario: Preserve the resolved clarification decisions
- **WHEN** the change updates helper-agent policy semantics and the `deferred`
  feature stage
- **THEN** the updated spec reflects the 2026-05-23 clarification outcomes
  directly and leaves no open questions for those two topics
