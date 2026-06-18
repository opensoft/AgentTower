# Tasks: Pluggable Discovery / Substrate Backends

> Spec/design proposal. Implementation is sequenced into a later feature; items
> marked **(impl)** belong to that feature, not to this change's merge.

## 1. Spec authoring (this change)

- [ ] 1.1 Define the `discovery-backends` capability spec: the backend
      interface, identity namespacing, per-backend degraded isolation, and the
      two reference backends.
- [ ] 1.2 Cross-check against FEAT-003 / FEAT-004 (current discovery) and
      FEAT-007 (host-visible-log invariant as a backend property).
- [ ] 1.3 Confirm the refactor is behavior-preserving for the bench backend.

## 2. Pre-implementation decisions

- [ ] 2.1 Decide the cross-backend identity-key format and migration for
      already-registered agents.
- [ ] 2.2 Decide global vs per-target backend configuration.

## 3. Implementation **(impl, future feature)**

- [ ] 3.1 Define the `DiscoveryBackend` interface (enumerate targets / panes,
      attach-log capability probe, identity_key).
- [ ] 3.2 Refactor bench-container discovery (FEAT-003/004) as backend #1 with
      no behavior change; guard with existing integration tests.
- [ ] 3.3 Add a backend registry + per-backend config + enable/disable.
- [ ] 3.4 Implement identity namespacing (`backend_id` prefix) with
      back-compat for stored `bench:` rows.
- [ ] 3.5 Per-backend degraded-state isolation (one backend's failure does not
      affect others).
- [ ] 3.6 Add the host-only tmux backend as reference #2.

## 4. Validation

- [ ] 4.1 `openspec validate discovery-backends --strict`.
- [ ] 4.2 Confirm each ADDED requirement has at least one `#### Scenario:`.
