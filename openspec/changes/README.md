# Omnigent-Derived Change Family — Roadmap

This directory holds a coordinated family of OpenSpec changes derived from the
AgentTower ↔ Omnigent analysis in `docs/related-work-omnigent.md` (research
only) and `docs/integration-tiers.md` (research only). The changes are
independent OpenSpec proposals; this note records how they fit together.

## Dependency / build order

```text
agent-connection-tiers   (A) ── foundation: how AT connects to an agent
        │                        (Tier 0 tmux / Tier 1 native / Tier 2 Omnigent)
        ├── routing-policy-layers (B) ── layered delivery policies; composes with
        │                                 the tier-independent outbound gate
        ├── discovery-backends    (D) ── pluggable substrates feeding the registry
        │                                 (independent of B)
        └── app-collaboration     (C, V2) ── multi-operator watch/co-drive over
                                              the FEAT-011 app backend; ideally
                                              composes with B
```

Recommended order: **A → B → D → C**. B and D are largely independent and can
proceed in parallel; C builds on the app backend and ideally on B.

## Shared guardrails (every change)

- **No network listener** — C/E gated behind a separately decided authenticated
  transport.
- **Router, not puppeteer** — AgentTower routes; Omnigent (Tier 2) drives.
- **No host-absolute paths** in any artifact.
- Every requirement carries at least one scenario (`openspec validate --strict`
  clean).

## Dispositions of the remaining candidates

- **E — reachable-from-anywhere / mobile:** deferred non-goal. Recorded inside
  `app-collaboration` with the gate it needs (authenticated transport + a
  deliberate reversal of the no-network-listener stance). Becomes its own change
  only if that gate is opened.
- **F — agent network-egress policy:** advisory only. AgentTower cannot
  intercept an unmodified agent's syscalls, so this is a documented capability
  gap (and at most an opt-in container-network recommendation), not a change.

## Changes

| ID | Change | Capability | Status |
| --- | --- | --- | --- |
| A | `agent-connection-tiers` | `agent-integration` | proposed (validated) |
| B | `routing-policy-layers` | `routing-policy` | proposed |
| D | `discovery-backends` | `discovery-backends` | proposed |
| C | `app-collaboration` | `app-collaboration` | proposed (V2) |
