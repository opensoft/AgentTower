# Clarification Questions — FEAT-012 Flutter Desktop Control Panel

**Feature**: 012-flutter-control-panel
**Spec**: `specs/012-flutter-control-panel/spec.md`
**Session date**: 2026-05-23
**Question cap (this session)**: 25 (raised from default 5 per global rule)
**Mode**: Block presentation — answer in one pass.

Each question is high‑impact (affects architecture, data model, test design, UX behavior, or operational readiness). For multiple‑choice questions, a **Recommended** option is called out with reasoning; you may reply with the option letter, say **"yes"/"recommended"** to accept the recommendation, or supply a short free‑form answer. For short‑answer questions, a **Suggested** value is provided.

---
## Q1 — Accessibility level target for first release

The spec does not name an accessibility baseline. This affects which Flutter packages, focus management, semantic labelling, and contrast standards are required from day one.

**Recommended:** Option B — WCAG 2.1 AA equivalent for keyboard navigation, focus order, semantic labels, and 4.5:1 contrast minimum, without committing to full screen‑reader certification in MVP. Best balance for an internal operator tool where keyboard‑first power use matters and a future external release should not require ripping out the UI layer.


**Answer:** Q1: B
| Option | Description |
|--------|-------------|
| A | No formal a11y target in MVP; revisit post‑MVP. |
| B | WCAG 2.1 AA‑equivalent for keyboard nav, focus, labels, contrast (no certified screen‑reader pass). |
| C | Full WCAG 2.1 AA including screen reader pass on all primary surfaces. |
| D | Keyboard navigation only (focusable controls, shortcuts) — no contrast / labels commitment. |

---
## Q2 — Localization / i18n scope for first release

Spec has no mention of localization. Strings will need wrapping if i18n is in scope; retrofitting later is expensive.

**Recommended:** Option A — English‑only in MVP, but route all user‑facing strings through a single localization layer (e.g. `flutter_localizations` / ARB files) so additional locales are a translation drop‑in. Matches the internal Opensoft cohort scope (SC‑011/012) without locking out future expansion.


**Answer:** Q2: A
| Option | Description |
|--------|-------------|
| A | English‑only MVP, strings routed through i18n layer for future locales. |
| B | English‑only MVP, plain hard‑coded strings; i18n deferred entirely. |
| C | English + one additional locale in MVP (specify which in answer). |
| D | Full multi‑locale framework with at least 2 shipped locales. |

---
## Q3 — App update / distribution mechanism

Not addressed in spec. Determines packaging, code‑signing, and rollback story.

**Recommended:** Option B — manual download of signed installer per OS, with an in‑app "check for updates" indicator that links to the release page. Avoids the operational burden of self‑hosting an update service for an MVP while still surfacing version skew vs the daemon (FR‑002).


**Answer:** Q3: B
| Option | Description |
|--------|-------------|
| A | No update channel in MVP; operators reinstall. |
| B | Manual installer per OS + in‑app "update available" indicator linking to release page. |
| C | Full auto‑update (e.g. Sparkle / Squirrel / equivalent Linux mechanism) with background download + restart. |
| D | OS app‑store distribution (Mac App Store / MSIX / Snap/Flatpak) only. |

---
## Q4 — App state persistence between launches

Spec implies persistence ("the same project remains selected when the operator returns to a workspace they previously left", Assumption mentions "across compatible app launches") but does not define what survives a restart.

**Recommended:** Option C — persist UX state (window geometry, last project, last workspace, last sub‑view, settings, list sort/filter, theme/density, notifications‑grouping toggle) in a local user‑scoped config store; never persist session tokens or domain data (those re‑bootstrap from the daemon). Matches FR‑003 in‑memory token rule and avoids cache/staleness bugs.


**Answer:** Q4: C
| Option | Description |
|--------|-------------|
| A | Persist nothing — every launch is a cold boot. |
| B | Persist only Settings; reset workspace/project to defaults on every launch. |
| C | Persist UX state (window, last project, last workspace + sub‑view, list sort/filter, settings); never persist session token or domain data. |
| D | Persist UX state plus a short‑lived snapshot of last‑known domain lists for instant render on launch (clearly marked stale until refresh). |

---
## Q5 — Definition of "compatible app launches" (referenced for Workspace Selection)

Key Entities calls workspace selection durable "across compatible app launches" but the term is undefined.

**Suggested:** "Same app major version AND same `app_contract_version` major as the previous run; on mismatch, persisted UX selection is dropped and the operator is taken to onboarding/Dashboard." This protects against carrying stale selections into an incompatible UI/contract layout.


**Answer:** Q5: Same app major version and same app_contract_version major; on mismatch, drop persisted UX selection and land on onboarding/Dashboard.
*Format: Short answer (≤25 words).*

---
## Q6 — Document opening behavior (PRD, architecture, roadmap, feature spec, OpenSpec change paths)

US2 / FR‑027 / FR‑031 / FR‑032 require "one‑click navigation" to these documents but do not say whether the click renders them in‑app or hands off to an external app.

**Recommended:** Option B — render markdown documents inside the app with an "Open in system editor" affordance; non‑markdown or unknown formats trigger the system default. Keeps the operator in flow for the most common case (markdown PRDs/specs/changes in this repo) without re‑implementing a code editor.


**Answer:** Q6: B
| Option | Description |
|--------|-------------|
| A | Always open in the system default application / editor — no in‑app preview. |
| B | Render markdown in‑app; non‑markdown opens in system default; provide "Open externally" for all. |
| C | Render all supported text formats in‑app (markdown + plaintext + JSON/YAML viewer) with optional external open. |
| D | Plain text preview only (no markdown rendering) plus external open. |

---
## Q7 — What makes an adopted agent a "master"?

The spec extensively references "master agents", "driving master", "compact master strip", but no functional requirement defines how an agent becomes (or is recognised as) a master vs a regular adopted agent.

**Recommended:** Option B — a master is any adopted agent whose `role` is `master` (operator‑set at adoption time) AND whose capability matches a master‑class capability registered with the daemon; the UI surfaces master views only for agents satisfying both. Aligns with the role/capability fields already required by FR‑016.


**Answer:** Q7: B
| Option | Description |
|--------|-------------|
| A | Any adopted agent can act as a master; "driving master" is determined per‑handoff with no separate identity. |
| B | An agent is a master iff `role == master` AND capability is master‑class; UI surfaces master‑specific views only for these agents. |
| C | "Master" is a daemon‑side classification (FEAT‑011 surface) the app reads; the app never decides masterhood. |
| D | "Master" is a dedicated agent type with its own adoption flow distinct from regular adopt‑existing‑pane. |

---
## Q8 — Sub‑agent tree depth limit

FR‑015 / FR‑055 / Sub‑agent entity describe a tree with rollups but do not bound depth. Affects rendering, queue rollup logic, and operator history nesting.

**Recommended:** Option B — render at most two levels (master → direct sub‑agents); deeper relationships are flattened to the nearest displayed parent with a "+N descendants" affordance. Matches the operator‑history "rolled up by agent, sub‑agents nested" wording (FR‑055) without unbounded recursion.


**Answer:** Q8: B
| Option | Description |
|--------|-------------|
| A | Unbounded depth; render whatever the daemon returns. |
| B | Max 2 levels (master → sub‑agents); deeper flattened with "+N descendants" indicator. |
| C | Max 3 levels (master → sub‑agent → sub‑sub‑agent); deeper flattened. |
| D | Configurable in Settings; default 2. |

---
## Q9 — Handoff failure recovery (failure modes)

FR‑042/043/044 define the happy path. Not specified: what happens when submission to the daemon fails, when the safe prompt queue rejects delivery, or when the target master goes offline between draft and submit.

**Recommended:** Option C — on submission failure the handoff remains in `drafted` with the error attached; on delivery failure (queue accepted but prompt rejected downstream) the handoff moves to `submitted` then surfaces a delivery‑failure indicator with a "Retry delivery" action; if the target master goes offline between draft and submit, submission is allowed but the handoff is held in `submitted` (no `accepted` transition) until reconnection. Keeps the durable record intact in every case and surfaces failures explicitly.


**Answer:** Q9: C
| Option | Description |
|--------|-------------|
| A | Submission failure discards the draft; operator must redo. |
| B | Submission failure preserves draft; delivery failure cancels the handoff automatically. |
| C | Submission failure → stays `drafted` + error attached; delivery failure → stays `submitted` + delivery‑failure indicator + retry; offline master → submission allowed, held `submitted` until reconnection. |
| D | All failure modes raise a modal; nothing is persisted until daemon acknowledges. |

---
## Q10 — Behavior when multiple OS users share the workstation

Trust model is same‑host UID match. Not specified: whether each OS user gets isolated app state, or whether the app even supports running for multiple OS users on the same machine.

**Recommended:** Option A — each OS user runs their own app instance against their own daemon socket; app state (settings, persisted UX state) is stored in the OS user's config directory; the app makes no attempt to share state across OS users. Matches the same‑host UID trust model and avoids cross‑user data leakage.


**Answer:** Q10: A
| Option | Description |
|--------|-------------|
| A | Per‑OS‑user isolation: each user has their own app state and connects to their own daemon socket. |
| B | Single‑user assumption: only one OS user per workstation is supported; undefined behavior otherwise. |
| C | Shared workstation state (system‑wide config) with per‑user session token; explicitly multi‑user aware. |

---
## Q11 — App‑internal diagnostics & logging

The spec covers daemon‑side observability but not what the app itself records (UI errors, render failures, contract version mismatches, action latencies).

**Recommended:** Option B — local rotating log file in the OS user's app data directory (e.g. `~/.local/share/agenttower-app/logs/`) capturing app errors, contract version events, and action latencies; exposed from Settings → "Open log folder" and "Copy diagnostics bundle". No telemetry uploaded anywhere by default. Matches local‑only posture and gives operators a copy‑pasteable bug report.


**Answer:** Q11: B
| Option | Description |
|--------|-------------|
| A | No app‑side logging in MVP. |
| B | Local rotating log file + "Open log folder" / "Copy diagnostics bundle" actions in Settings; no upload. |
| C | Local log + opt‑in upload to an Opensoft‑internal endpoint on crash. |
| D | Local log + always‑on telemetry to an Opensoft‑internal endpoint. |

---
## Q12 — Theme & density options

FR‑009 mentions "theme/density" without enumerating. Affects design tokens / theming system choice.

**Recommended:** Option B — Light + Dark + System (follows OS); density Comfortable + Compact. Mirrors common Flutter desktop conventions, covers operator preference (compact = more rows per screen) without sprawling into per‑surface theming complexity.


**Answer:** Q12: B
| Option | Description |
|--------|-------------|
| A | Light + Dark only; single density. |
| B | Light + Dark + System (follows OS); density Comfortable + Compact. |
| C | Light + Dark + System; density Comfortable + Compact + Cozy. |
| D | High‑contrast variant in addition to Light/Dark/System; single density. |

---
## Q13 — Keyboard navigation / shortcut commitment

Operator‑facing tool; spec does not say whether keyboard‑first navigation is a hard requirement.

**Recommended:** Option B — every primary action reachable from a keyboard shortcut + Tab/Shift+Tab/Arrow navigation through all interactive elements + a global command palette (e.g. Ctrl/Cmd+K) covering project switching, workspace switching, and most‑used actions. Power users on this kind of operational tool will live in the keyboard, and a palette covers the long tail without bespoke shortcuts per action.


**Answer:** Q13: B
| Option | Description |
|--------|-------------|
| A | Mouse‑first; tab navigation works but no documented shortcuts in MVP. |
| B | Full keyboard navigation + documented shortcuts for primary actions + global command palette (Ctrl/Cmd+K). |
| C | Full keyboard navigation + documented shortcuts, no command palette in MVP. |
| D | Documented shortcuts only for the live agent‑ops surfaces; other workspaces mouse‑first. |

---
## Q14 — Interaction‑stability window concrete value (FR‑053 / SC‑008a)

Spec defers the concrete value to plan phase but the cohort tests reference it (SC‑008a "documented interaction‑stability window … across 100 simulated live‑update bursts").

**Suggested:** 2 seconds from the operator's last hover/click/keypress on the attention queue. Long enough to prevent click‑target swaps during normal pointer dwell; short enough that the queue does not feel frozen during active operator work.


**Answer:** Q14: 2 seconds since last interaction
*Format: Short answer (≤10 words, e.g. "2 seconds since last interaction").*

---
## Q15 — First‑launch project selection (with multiple already‑registered projects)

When persistence carries multiple projects (Assumption notes both explicit Add and inference from `project_path`), it is undefined which project (if any) is active on a launch after the persisted last‑project becomes invalid (project removed / repo path moved).

**Recommended:** Option B — restore the last‑active project if it still resolves; otherwise land on the Projects view with no project selected and a banner explaining the previous project is no longer available. Avoids silent context substitution that could mislead an operator into acting on the wrong project.


**Answer:** Q15: B
| Option | Description |
|--------|-------------|
| A | Always land on Projects view with no selection. |
| B | Restore last‑active project if it resolves; else Projects view + banner explaining the change. |
| C | Restore last‑active project if it resolves; else auto‑select the most recently active project. |
| D | Restore last‑active project if it resolves; else block app entry behind a "choose project" dialog. |

---
## Q16 — Project removal flow

Projects can be added (explicit Add / inferred from adopted agents) but the spec does not say how a project is removed, or what happens to its persisted state.

**Recommended:** Option B — operator can "Remove project" from the Projects view; removal asks for confirmation and clears project‑scoped UI persistence (last sub‑view, sort/filter) but does not delete any daemon‑side data (agents, handoffs, drift findings remain owned by the daemon). The project will reappear if it is later re‑inferred from an adopted agent's `project_path`, with persisted UI state reset.


**Answer:** Q16: B
| Option | Description |
|--------|-------------|
| A | No removal in MVP; projects only added, never removed from the app. |
| B | Operator can remove project; clears UI persistence; daemon‑side data untouched; reappears if re‑inferred. |
| C | Removal is a daemon‑side delete via `app.*`; cascades to all daemon data linked to that project. |
| D | Removal hides from UI only; persisted UI state retained for "undo" until next session. |

---
## Q17 — Handoff querying scope (FR‑045)

FR‑045 says queryable by project, master, feature/change, and assignment state, but does not say whether free‑text search or date range filtering are required.

**Recommended:** Option B — structured filters only (the four listed in FR‑045) plus an additional date‑range filter on `created_at`; no free‑text search in MVP. Covers the realistic operator query patterns (recent handoffs to master X, all blocked handoffs, handoffs on FEAT‑N) without committing to a search index in the first release.


**Answer:** Q17: B
| Option | Description |
|--------|-------------|
| A | Exactly the four filters in FR‑045; no extras. |
| B | Four filters + date‑range filter on `created_at`. |
| C | Four filters + date‑range + free‑text search across prompt text and notes. |
| D | Free‑text search only (across all fields); no structured filters surfaced. |

---
## Q18 — List view sort / filter persistence (per FR‑063 list surfaces)

Not specified: do operators' sort and filter choices in Containers/Panes/Agents/Events/Queue/Routes/Projects/Available Validation/Runs/Drift persist across navigation and between sessions?

**Recommended:** Option C — persist per‑view sort/filter for the current session AND across sessions, scoped per project where the view is project‑scoped (Drift, Available Validation, Runs) and globally for non‑project views. Operators returning to a view should not have to re‑apply filters they were using; per‑project scoping prevents one project's filter leaking into another.


**Answer:** Q18: C
| Option | Description |
|--------|-------------|
| A | Reset on every navigation away. |
| B | Persist per‑view sort/filter for the current session only; reset on app restart. |
| C | Persist per‑view sort/filter session AND across sessions; per‑project scope for project‑scoped views. |
| D | Persist across sessions but globally (not per‑project), even for project‑scoped views. |

---
## Q19 — Notification grouping rule definition (FR‑057)

FR‑057 says "rule‑based grouping of equivalent low‑severity notifications". Not defined: what makes two notifications "equivalent", and the collapsing threshold.

**Recommended:** Option B — collapse N≥3 consecutive notifications that share `event_class` AND `agent_id` AND severity ≤ `warning` within a rolling 60‑second window into a single grouped row showing the count and most recent timestamp; `high` and `critical` are never grouped (already implied by FR‑057 "high‑severity items MUST NOT be grouped"). Operator can expand any grouped row; toggle in Settings disables grouping globally. Deterministic, easy to test (no model dependency), and matches the "rule‑based first" Assumption.


**Answer:** Q19: B
| Option | Description |
|--------|-------------|
| A | Collapse only when ≥5 consecutive notifications share `event_class`, regardless of agent / window. |
| B | Collapse ≥3 consecutive notifications sharing `event_class` AND `agent_id` AND severity ≤ warning within 60 s; expand on click; never group high/critical. |
| C | Collapse ≥2 notifications sharing `event_class` only, any agent, no time window. |
| D | Defer specific rule to plan phase; spec only requires the property, not the rule. |

---
## Q20 — Default global keyboard shortcut for the project switcher

Only relevant if Q13 selects B or C. The project switcher is reachable from any workspace (FR‑007). Operators will use it constantly.

**Suggested:** `Ctrl+P` on Linux/Windows and `Cmd+P` on macOS for the project switcher, distinct from the command palette `Ctrl/Cmd+K` to avoid mode confusion. Conventional ("P" for project, mirrors common IDE quick‑open feel) and does not collide with browser/system reserved shortcuts.


**Answer:** Q20: Ctrl+P on Linux/Windows; Cmd+P on macOS
*Format: Short answer (≤15 words).*

---
## Q21 — Behavior on contract‑version‑incompatible bootstrap

FR‑002 says degrade to read‑only when minimum required contract version is unmet. Not specified: which surfaces are gated and how the user is informed.

**Recommended:** Option C — global banner on every workspace naming the mismatch and the upgrade path; views whose minimum contract version is unmet render the documented "contract‑version‑incompatible" state from FR‑004 with the specific missing version called out; mutations on those views are disabled with an inline explanation; read views still render. Matches FR‑004's enumerated runtime state and gives the operator concrete guidance.


**Answer:** Q21: C
| Option | Description |
|--------|-------------|
| A | Hard‑block the app with an upgrade screen until contract is satisfied. |
| B | Global banner only; all views attempt to render and individual mutations fail with daemon errors as they occur. |
| C | Global banner + per‑surface "contract‑version‑incompatible" state where required + disabled mutations with inline explanation. |
| D | Read‑only mode globally for the entire app whenever any minor‑version requirement is unmet. |

---
## Q22 — Handling of large `Events` / `Queue` / `Runs` lists (pagination vs virtualized scroll)

FR‑063 references "daemon‑supported pagination page size" but does not say whether the app paginates explicitly or renders an infinite‑scroll / virtualized list.

**Recommended:** Option B — virtualized list with on‑demand fetching of the next page as the operator scrolls; daemon pagination cursors drive the fetch; an explicit "Jump to most recent" affordance is always visible on event‑style streams. Best UX for streaming/live data; explicit "page N of M" UI is awkward for these surfaces.


**Answer:** Q22: B
| Option | Description |
|--------|-------------|
| A | Explicit page controls (Prev / Next / page N of M) on every list. |
| B | Virtualized infinite scroll backed by daemon pagination cursors + "Jump to most recent" on event streams. |
| C | Virtualized infinite scroll for event/queue/runs; explicit pagination for entity lists (Agents, Routes, Projects, Containers). |
| D | Load‑more button (no auto‑fetch on scroll) backed by daemon pagination. |

---
## Q23 — Conflict indicator behavior on double‑driving (Edge Case in spec)

The spec edge case says "the second handoff submission is allowed but the affected feature surfaces a conflict indicator". Not specified: whether existing in‑flight queue rows from the prior master are cancelled when the operator chooses "supersede".

**Recommended:** Option B — on supersede, the prior handoff transitions to `superseded` and `superseded_by_handoff_id` is recorded (already in FR‑042), but daemon‑side queue rows already created from the prior handoff are left to terminate naturally — the app does not auto‑cancel them. The supersede action is a record/intent change at the handoff layer; the app must not silently mutate in‑flight queue state on the operator's behalf.


**Answer:** Q23: B
| Option | Description |
|--------|-------------|
| A | Supersede also auto‑cancels all queued (non‑terminal) queue rows linked to the superseded handoff. |
| B | Supersede only updates the handoff record; existing queue rows are left to terminate naturally; operator can cancel them manually. |
| C | Supersede prompts the operator: "Cancel the prior master's in‑flight queue rows? [Yes / No]". |
| D | Supersede is blocked while the prior master has non‑terminal queue rows; operator must cancel those first. |

---
## Q24 — Onboarding skip / resume

FR‑010 enumerates eight onboarding steps. Not specified: can the operator skip individual steps, abandon onboarding partway and resume later, and what is the on‑subsequent‑launch behavior.

**Recommended:** Option B — onboarding is fully skippable from any step (single "Skip onboarding" affordance); operator‑observed progress is persisted, so re‑entering onboarding from Settings resumes at the first incomplete step; SC‑011 (≥90% step completion rate) is measured only for operators who explicitly start the flow at least once and is unaffected by skips. Best for power users who already know the product while still giving SC‑011 a clean denominator.


**Answer:** Q24: C — skippable, with skipped steps continuing to appear as dashboard nudges until completed.
| Option | Description |
|--------|-------------|
| A | Onboarding is mandatory on first launch; cannot be skipped. |
| B | Skippable from any step; progress persisted; resumable from Settings; SC‑011 measured only over users who started the flow. |
| C | Skippable, but skipped steps reappear as nudges in the Dashboard until completed. |
| D | No multi‑step onboarding — Dashboard shows a static checklist of the eight milestones; operator self‑drives. |

---
## Q25 — Quit / close behavior with active handoffs or running validation

Not specified: when the operator closes the app while it has been the trigger for a running validation, an in‑flight handoff submission, or unprocessed attention items, does it warn or silently close.

**Recommended:** Option B — close immediately without warning. The app is a thin client over the daemon: closing it does not stop daemon work (validations keep running, handoffs already submitted keep moving, queue stays). A warning would suggest closing has side effects on daemon state, which would be misleading. The operator can simply reopen to resume the view.


**Answer:** Q25: B
| Option | Description |
|--------|-------------|
| A | Always warn on close if any daemon work is in flight (running validation, recently‑submitted handoff, blocked attention items). |
| B | Close immediately without warning — daemon state is unaffected; reopen resumes the view. |
| C | Warn on close only if there is unsubmitted in‑memory state (e.g. a drafted handoff with operator notes not yet saved). |
| D | Minimize‑to‑tray instead of close by default; configurable in Settings. |

---

## How to answer

Reply with a single message containing one line per question, in any of these forms:

```
Q1: B
Q2: recommended
Q3: B; in‑app indicator should also show the daemon's latest released version
Q4: C
Q5: 2 seconds since last interaction with the attention queue
…
Q25: B
```

Per‑question free‑form notes are welcome and will be folded into the spec under `## Clarifications → ### Session 2026-05-23`.
