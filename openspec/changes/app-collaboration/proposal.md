# Add Multi-Operator App Collaboration (Watch / Co-Drive)

## Why

Omnigent's headline collaboration feature is sharing a live agent session so
teammates can watch, co-drive, or fork it. AgentTower's analogue is letting
multiple operators connect to the **same** daemon and see the same registry and
event stream, with a clear split between read-only *watch* and permitted
*co-drive*. This answers PRD Open Question #2 (how multiple humans observe the
system) using the existing FEAT-011 `app.*` backend, without inventing a new
control plane.

This is a **V2** capability: true remote/URL sharing requires an authenticated
network transport, which collides with the MVP no-network-listener stance. This
change therefore scopes collaboration to **local, same-host** app sessions and
records remote sharing as an explicit non-goal with the gate it would require.

## What Changes

- **Assign each app session a role:** `observer` (read-only) or `operator`
  (may mutate). FEAT-011 already supports up to 8 concurrent app sessions.
- **Guarantee a consistent shared live view:** all connected sessions observe
  the same registry and event stream.
- **Enforce co-drive server-side:** only `operator` sessions may perform
  mutations; `observer` sessions are read-only, reusing the `app.*` permission
  model (and `routing-policy-layers` where relevant).
- **Audit across sessions:** record which session performed which mutation.
- **Draw an explicit local-only boundary:** same-host socket only; remote / URL
  sharing and mobile access are non-goals here, gated behind a future
  authenticated-transport decision.

## Impact

- **New capability spec:** `app-collaboration` (extends the FEAT-011 `app.*`
  surface; no new listener).
- **Builds on:** FEAT-011 (app backend + session registry). Ideally composes
  with `routing-policy-layers` (policies can govern co-drive deliveries).
- **No code ships in this change** — spec/design proposal only.
- **Non-goals:** remote / mobile transport (the deferred "reachable-from-
  anywhere" item), OIDC / external identity, and session *forking* semantics
  (candidate to defer).
- **Open question:** is watch + co-drive sufficient for v1, or is session fork
  required?
