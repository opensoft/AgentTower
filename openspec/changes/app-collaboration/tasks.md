# Tasks: Multi-Operator App Collaboration

> Spec/design proposal (V2 capability). Implementation is sequenced into a later
> feature; items marked **(impl)** belong to that feature, not to this change's
> merge.

## 1. Spec authoring (this change)

- [ ] 1.1 Define the `app-collaboration` capability spec: session roles, shared
      consistent view, server-side co-drive enforcement, cross-session audit,
      and the explicit local-only boundary.
- [ ] 1.2 Cross-check against FEAT-011 (`app.*`, session registry, host-only,
      8-session cap) and `architecture.md` §23 (no network listener).
- [ ] 1.3 Confirm remote/URL/mobile sharing is recorded only as a gated
      non-goal, not a requirement.

## 2. Pre-implementation decisions

- [ ] 2.1 Decide whether session fork is in v1 or deferred.
- [ ] 2.2 Decide the default session role and the promotion step to `operator`.

## 3. Implementation **(impl, future feature)**

- [ ] 3.1 Add an `observer` / `operator` role to `app.hello` + the FEAT-011
      session registry (no new listener, no new persisted credential).
- [ ] 3.2 Ensure all connected sessions share one consistent registry/event
      view.
- [ ] 3.3 Enforce co-drive server-side: only `operator` sessions may call
      mutating `app.*` methods; `observer` mutations are rejected.
- [ ] 3.4 Record the originating app session id on every mutation audit entry.
- [ ] 3.5 Compose with `routing-policy-layers` for co-drive deliveries where
      present.

## 4. Validation

- [ ] 4.1 `openspec validate app-collaboration --strict`.
- [ ] 4.2 Confirm each ADDED requirement has at least one `#### Scenario:`.
