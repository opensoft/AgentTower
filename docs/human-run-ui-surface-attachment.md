# Human-Run UI Surface Attachment

Status: concept architecture  
Repository context: AgentTower local control tower  
Purpose: define how AgentTower can discover, register, monitor, and optionally control existing human-run tmux panes, GUI windows, and browser sessions that it did not start

## 1. Core idea

AgentTower should not only manage sessions that it launches. It should be able to attach to existing human-run UI surfaces.

Examples:

```text
existing tmux pane running Claude or Codex
existing tmux pane running a shell or script
existing browser window opened by a human
existing browser tab logged into an external platform
existing GUI app window used for a human-in-the-loop workflow
```

This is important for workflows where a human must login to a website or external system, and AgentTower/Omnigent then needs to observe, coordinate, or assist without owning the original login event.

The key rule is:

> AgentTower discovers and registers work surfaces. It does not need to be the process that launched them.

## 2. Existing tmux pane model

The current AgentTower product direction already supports tmux pane discovery.

AgentTower should discover accessible tmux sessions, windows, and panes using tmux-native identifiers.

Primary tmux identity:

```text
tmux pane_id, such as %4
session name
window index/name
pane index/title
pane current command
pane current path
pane tty
pane pid
```

Recommended discovery command:

```bash
tmux list-panes -a -F '#{session_name}\t#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_tty}\t#{pane_title}'
```

AgentTower should store the pane as a registered work surface even if the pane was created by another tool.

## 3. General Work Surface abstraction

AgentTower should generalize from tmux panes to a broader Work Surface model.

```yaml
doctype: Work Surface
surface_id: string
surface_kind: tmux_pane | gui_window | browser_target | container_shell | unknown
created_by_agenttower: true | false
discovery_method: tmux | x11 | wayland | macos_quartz | windows_ui_automation | browser_cdp | browser_extension | manual
human_owned_session: true | false
control_allowed: false
notify_allowed: true
metadata: object
status: discovered | registered | active | stale | unavailable | retired
```

This keeps launch ownership separate from discovery and control permission.

## 4. Browser surface model

Browser workflows require multiple IDs.

A browser window or tab can have:

```text
OS window ID
OS process ID
browser profile/user-data-dir
browser remote debugging endpoint
browser target ID / page ID
tab URL
tab title
CDP websocket URL if available
human login status, inferred only by policy-safe signals
```

Recommended model:

```yaml
doctype: Browser Target Surface
surface_id: browser_target_000001
surface_kind: browser_target
created_by_agenttower: false
browser_family: chromium | chrome | edge | firefox | safari | unknown
os_window_id: string | null
process_id: integer | null
remote_debugging_url: string | null
cdp_target_id: string | null
websocket_debugger_url: string | null
url: string
title: string
profile_hint: string | null
human_owned_session: true
control_allowed: false
capture_allowed: false
status: discovered | registered | active | stale | unavailable
```

## 5. Browser attachment modes

### 5.1 CDP attach to browser started with remote debugging

Best automation mode for Chromium-based browsers.

Requirements:

```text
browser was started with --remote-debugging-port or equivalent
AgentTower can reach http://localhost:<port>/json/version
AgentTower can list targets at http://localhost:<port>/json/list
policy allows inspection/control
```

Discovery output:

```text
browser version
webSocketDebuggerUrl
targetId
page URL
title
attached / detached state
```

Limit:

```text
If a normal browser was not started with remote debugging, AgentTower generally cannot attach to it with CDP after the fact.
```

### 5.2 Human-visible browser harness

A browser session is launched or selected in a visible desktop session. The human can complete login, MFA, or other authentication steps. AgentTower then registers the browser surface.

Use for external medical evidence platforms, payer portals, EHR portals, and systems where human login is required.

Preferred behavior:

```text
human performs login
AgentTower registers browser target
control remains notify-only until explicitly allowed
AgentTower captures only approved outputs
```

### 5.3 Browser extension / native host

A browser extension can expose tab identity and limited DOM/capture actions to AgentTower.

Pros:

```text
can attach to existing normal browser tabs
can avoid remote debugging requirement
can provide user-visible permission prompts
```

Cons:

```text
requires extension install
requires browser-specific packaging
requires strict permission design
```

### 5.4 OS-level GUI automation

Use platform window APIs to identify windows.

Linux X11:

```text
wmctrl
xdotool
xprop
at-spi
```

Linux Wayland:

```text
compositor-dependent
portals or accessibility APIs where available
less reliable than X11
```

macOS:

```text
Quartz CGWindowList
Accessibility API
AppleScript where appropriate
```

Windows:

```text
EnumWindows
UI Automation
PowerShell / Win32 APIs
```

OS-level automation can find window IDs and perform limited UI operations, but it does not provide the same page-level semantic access as a browser protocol.

### 5.5 Manual registration

When automated discovery is weak, allow the user to register a surface manually.

Example:

```bash
agenttower register-surface \
  --kind browser_target \
  --label openevidence-session \
  --url https://www.openevidence.com/ \
  --control notify-only
```

## 6. CLI additions

Recommended CLI commands:

```bash
agenttower scan-surfaces
agenttower list-surfaces
agenttower list-windows
agenttower list-browser-targets
agenttower register-surface --surface <id> --label <label> --role external-platform
agenttower attach-browser-cdp --port 9222
agenttower register-window --window-id <id> --label <label>
agenttower set-control --surface <id> --mode notify-only|capture|input-allowed
agenttower focus-surface --surface <id>
agenttower capture-surface --surface <id> --policy <policy-id>
```

For tmux backward compatibility:

```bash
agenttower list-panes
agenttower register-pane --pane %4 --label claude-010 --role worker
```

## 7. Safety and permission model

Human-run UI surfaces should be notify-only by default.

Default:

```text
notify_allowed: true
capture_allowed: false
input_allowed: false
credential_capture_allowed: false
phi_capture_allowed: false
```

Escalations require explicit policy and user/organization approval:

```text
capture_allowed
input_allowed
file_download_allowed
clipboard_access_allowed
phi_capture_allowed
```

Never allow by default:

```text
password capture
MFA bypass
credential export
stealth automation
unapproved scraping
unapproved PHI transmission
```

## 8. External platform workflow pattern

A common pattern:

```text
1. Human opens external platform in browser.
2. Human logs in normally.
3. AgentTower discovers/registers the browser target or window.
4. AgentTower marks the surface human_owned_session=true.
5. Medx Omnigent sends a bounded job envelope.
6. AgentTower performs only allowed observation/control actions.
7. Captured output becomes a structured artifact.
8. Workflow gates route the artifact for review.
```

## 9. Relationship to MedxFactory

MedxFactory can use AgentTower to support external medical platforms such as evidence search websites, payer portals, EHR portals, or lab portals.

AgentTower should provide the local human-run UI attachment capability.

MedxFactory should provide:

```text
policy checks
minimum-necessary question construction
PHI controls
artifact schema
clinical review gates
local organization approval
Medx Domain Hermes safety policy
```

## 10. Implementation recommendation

Phase 1:

```text
general Work Surface registry
tmux pane discovery as existing core path
manual browser/window registration
visible browser harness workflow
notify-only default
structured surface audit events
```

Phase 2:

```text
Chromium CDP target discovery
browser target registration
controlled capture under policy
relationship between OS window and browser target when possible
```

Phase 3:

```text
browser extension / native host for existing normal browser tabs
cross-platform GUI window discovery
controlled UI automation under explicit permission
```

## 11. Summary

AgentTower should support a general work-surface attachment model.

```text
tmux pane
  -> already core AgentTower surface

GUI window
  -> OS-level discovered work surface

browser target
  -> CDP, extension, or manually registered web surface

human-run external platform
  -> registered work surface with explicit control/capture policy
```

The key rule is:

> AgentTower may attach to work surfaces it did not start, but control and capture must be explicit, auditable, and policy-bound.
