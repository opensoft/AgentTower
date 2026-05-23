## Context

FEAT-012 already has its primary user stories, FR set, and clarified answers,
but the clarified decisions were not fully encoded back into the normative
spec. This change is a spec-only reconciliation pass: it does not introduce
new product scope, but it does make the existing decisions testable and
unambiguous.

## Goals / Non-Goals

**Goals:**
- Reconcile the FEAT-012 spec with the 2026-05-23 clarification answers.
- Preserve FR numbering and existing scope while tightening the wording where
  the current spec still leaves room for incompatible implementations.
- Leave a reviewable OpenSpec change trail before archive.

**Non-Goals:**
- No implementation changes.
- No new FEAT-012 scope beyond the 12 named findings.
- No edits to clarify files, checklists, or unrelated product docs.

## Decisions

- Use one OpenSpec change to capture all 12 findings so reviewers can inspect a
  single coherent delta instead of a sequence of piecemeal spec tweaks.
- Treat the work as a spec-only quality pass against the existing Spec Kit spec
  file `specs/012-flutter-control-panel/spec.md`.
- Encode the resolved helper-policy and `deferred` decisions directly in the
  spec rather than leaving design-phase flags, because those questions were
  already settled in the round-2 clarification pass.

## Risks / Trade-offs

- [Risk] A large spec-only patch can accidentally drift into unrelated wording
  changes. -> Mitigation: limit edits to the named sections and preserve
  surrounding text wherever possible.
- [Risk] OpenSpec capability naming here does not map to an existing
  `openspec/specs/` capability because the repository stores the source spec in
  Spec Kit form. -> Mitigation: keep the delta spec explicit that the target is
  `specs/012-flutter-control-panel/spec.md` and avoid implying any broader
  capability split.
