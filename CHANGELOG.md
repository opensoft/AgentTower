# Changelog

All notable changes to AgentTower are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added — FEAT-011: Local App Backend Contract (`app_contract_version = "1.0"`)

A versioned, host-only `app.*` socket method namespace over the existing
newline-delimited JSON Unix socket, so a packaged desktop control panel
can operate AgentTower without scraping human CLI output. Backend
contract only — no Flutter UI, no managed session creation, no network
listener.

**32 `app.*` methods at v1.0:**

- Bootstrap — `app.preflight`, `app.hello`
- Health — `app.readiness`, `app.dashboard`
- Discovery scans — `app.scan.containers`, `app.scan.panes`,
  `app.scan.status`
- Entity reads (`list` + `detail` for each) — `app.container.*`,
  `app.pane.*`, `app.agent.*`, `app.log_attachment.*`, `app.event.*`,
  `app.queue.*`, `app.route.*`
- Adopt mutation — `app.agent.register_from_pane`
- Operator mutations — `app.agent.update`, `app.log.attach`,
  `app.log.detach`, `app.send_input`, `app.queue.approve`,
  `app.queue.delay`, `app.queue.cancel`, `app.route.add`,
  `app.route.remove`, `app.route.update`

**Contract:**

- Uniform envelopes — `{ok, app_contract_version, result}` /
  `{ok:false, app_contract_version, error:{code, message, details}}`.
- 27-entry closed `error.code` set with a per-code `details` registry;
  `error.details` is always an object.
- `app_contract_version` is `MAJOR.MINOR` (`1.0`); a major mismatch is
  refused at `app.hello` (`app_contract_major_unsupported`, no session
  issued). Within a major, only additive change.
- Host-only — every `app.*` call from a bench-container peer is rejected
  with `host_only`; the legacy FEAT-002..FEAT-010 namespace is unchanged
  and remains available to in-container thin clients.
- Opaque per-session `app_session_token` (in-memory, 8-session cap, no
  user identity); the underlying trust model stays same-host-UID +
  socket file permissions.
- Wire framing — strict UTF-8, `\n`-terminated, one JSON object per
  line; violations rejected with `malformed_request`. Request line cap
  enforced; oversized `app.*` lines get `payload_too_large`.
- Pagination — `limit` default 50 / cap 200; opaque `cursor_next`
  (≤ 512 chars); exact-match filters; `field[:asc|:desc]` ordering.

**Invariants:** no non-Unix-socket listener introduced; no new persisted
secret, token, or credential — the session table, scan registry, and
idempotency map are in-memory only and lost on daemon restart. All
`app.*` methods dispatch into the same daemon-internal service layer as
the legacy CLI methods.

Implementation: `src/agenttower/app_contract/`. Spec, contracts, and the
client developer guide: `specs/011-app-backend-contract/` and
`docs/app-contract-client-guide.md`.
