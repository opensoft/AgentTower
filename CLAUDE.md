<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`specs/001-package-state-foundation/plan.md`.
<!-- SPECKIT END -->

# AgentTower Agent Context

AgentTower is a local-first Python CLI and daemon for coordinating tmux-based
AI agents inside Opensoft bench containers.

Read these project docs before creating or implementing specs:

- `docs/product-requirements.md`
- `docs/architecture.md`
- `docs/mvp-feature-sequence.md`

Spec Kit lives under `.specify/`. OpenSpec lives under `openspec/`.

MVP deployment is host-daemon first: `agenttowerd` runs on the host, bench
containers run thin `agenttower` clients over a mounted Unix socket, and there
is no network listener in MVP.
