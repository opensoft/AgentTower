# Work Surface Registry and Communication Feature Set

Status: concept architecture  
Repository context: AgentTower local control tower  
Purpose: define the AgentTower-owned feature set for identifying, mapping, maintaining communication with, and safely controlling terminals, tmux panes, GUI windows, and browser surfaces

## 1. Core decision

The feature set for maintaining communication with windows, terminals, browser tabs, and tmux panes belongs in **AgentTower**.

Other products, such as MedxFactory or codexFactory, should consume this feature set through an AgentTower harness rather than reimplementing window, terminal, or browser-surface discovery themselves.

The rule is:

> AgentTower owns work-surface discovery, identity, mapping, communication, permissions, and audit. Domain factories consume registered surfaces through policy-bound job envelopes.

## 2. Work Surface definition

A Work Surface is any local or remote interactive surface that a human or agent may use.

Examples:

```text
tmux pane
terminal window
container shell
GUI app window
browser window
browser tab / browser target
external platform session
human-run login session
agent-run long job
```

A Work Surface may have been created by AgentTower or discovered after a human or another tool created it.

## 3. Feature ownership boundary

### AgentTower owns

```text
surface discovery
surface identity
surface registry
surface labels and roles
surface mapping relationships
surface communication channels
surface status tracking
capture permission state
input permission state
notification routing
focus / activate requests where allowed
audit events for surface operations
```

### Domain factories own

```text
why a surface is needed
what business or clinical workflow it supports
what data may be sent or captured
what policy gates apply
what artifact schema receives captured output
who reviews the result
```

Example:

```text
AgentTower:
  finds and tracks an OpenEvidence browser tab

MedxFactory:
  decides whether OpenEvidence may be used, what deidentified question may be sent, and how the result is reviewed
```

## 4. Work Surface identity model

Every Work Surface should have a stable AgentTower identity plus provider-specific IDs.

```yaml
doctype: Work Surface
surface_id: surface_000001
surface_kind: tmux_pane | terminal_window | gui_window | browser_target | container_shell | unknown
created_by_agenttower: true | false
human_owned_session: true | false
label: string
role: orchestrator | worker | external_platform | evidence_session | test_runner | container_shell | unknown
project_hint: string | null
process_id: integer | null
owner_user: string | null
discovery_method: tmux | x11 | wayland | macos_quartz | windows_ui_automation | browser_cdp | browser_extension | manual
status: discovered | registered | active | stale | unavailable | retired
```

## 5. Tmux pane identity

Tmux panes are the first-class AgentTower surface type.

Recommended identifiers:

```text
pane_id, such as %4
session_name
window_index
window_name
pane_index
pane_pid
pane_tty
pane_current_command
pane_current_path
pane_title
```

Recommended discovery command:

```bash
tmux list-panes -a -F '#{session_name}\t#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_tty}\t#{pane_title}'
```

The registry should mark whether AgentTower launched the pane.

```yaml
surface_kind: tmux_pane
created_by_agenttower: false
pane_id: "%4"
notify_allowed: true
input_allowed: false
```

## 6. GUI window identity

GUI windows require platform-specific IDs.

Recommended identifiers:

```text
os_window_id
process_id
application_name
window_title
workspace / desktop if available
bounds if available
focused / visible state
```

Discovery options:

```text
Linux X11:
  wmctrl, xdotool, xprop, AT-SPI

Linux Wayland:
  compositor-specific APIs, portals, or accessibility APIs where available

macOS:
  Quartz CGWindowList, Accessibility API, AppleScript when appropriate

Windows:
  EnumWindows, UI Automation, PowerShell / Win32 APIs
```

GUI window discovery should be best-effort and platform-labeled because reliability varies by OS and display server.

## 7. Browser target identity

Browser workflows need both OS-level and browser-level identity.

Recommended identifiers:

```text
browser_family
os_window_id
process_id
profile_hint
remote_debugging_url
browser_context_id
cdp_target_id
websocket_debugger_url
tab_url
tab_title
attached_state
```

Browser CDP discovery is only available when the browser exposes a remote debugging endpoint.

```text
If a normal browser was not started with remote debugging enabled, AgentTower generally cannot attach to it through CDP after the fact.
```

For existing human-run browser sessions without CDP, use one of:

```text
manual registration
browser extension / native host
OS-level window registration
human-visible harness mode
```

## 8. Communication channels

Each Work Surface may expose zero or more communication channels.

```yaml
communication_channels:
  - channel_type: notify
    allowed: true
    description: AgentTower may route notifications about this surface.
  - channel_type: capture
    allowed: false
    description: AgentTower may capture text, screenshot, DOM, or transcript only if explicitly permitted.
  - channel_type: input
    allowed: false
    description: AgentTower may type or send commands only if explicitly permitted.
  - channel_type: focus
    allowed: false
    description: AgentTower may bring the surface to the foreground only if permitted.
  - channel_type: tool_protocol
    allowed: false
    description: AgentTower may use CDP, extension, or structured protocol if permitted.
```

Default policy:

```text
notify_allowed: true
capture_allowed: false
input_allowed: false
credential_capture_allowed: false
phi_capture_allowed: false
```

## 9. Communication map

AgentTower should maintain a map of relationships between surfaces.

Examples:

```text
orchestrator pane -> worker pane
Medx Omnigent job -> OpenEvidence browser target
human browser window -> captured evidence artifact
tmux pane -> container shell
browser target -> OS window
external platform session -> domain workflow job
```

Example:

```yaml
doctype: Work Surface Link
link_id: surface_link_000001
source_surface_id: surface_tmux_001
target_surface_id: surface_browser_001
relationship: controls | observes | notifies | captures_from | associated_with | spawned | attached_to
created_by: agenttower | user | domain_factory
policy_id: string
status: active | suspended | retired
```

## 10. Surface lifecycle

```text
DISCOVERED
  -> REGISTERED
  -> LABELED
  -> PERMISSIONED
  -> ACTIVE
  -> STALE
  -> UNAVAILABLE
  -> RETIRED
```

A surface can become stale when:

```text
window no longer exists
process exited
tmux pane disappeared
browser target closed
URL or title no longer matches expected workflow
permission state changed
human revoked control
```

## 11. External platform session pattern

For external platforms such as OpenEvidence, payer portals, EHR portals, or lab portals:

```text
1. Human opens or identifies the external platform window/browser tab.
2. Human performs login/MFA if required.
3. AgentTower registers the surface as human_owned_session=true.
4. Surface is notify-only by default.
5. Domain factory submits a bounded job envelope.
6. AgentTower performs only approved communication/capture/input operations.
7. Captured output is returned as a structured artifact to the domain factory.
8. Domain factory performs its own policy review.
```

## 12. Job envelope

Domain factories should call AgentTower with bounded job envelopes.

```yaml
agenttower_surface_job:
  job_id: medx.external_evidence_000001
  requested_by: medx_omnigent
  surface_id: surface_browser_001
  purpose: external_evidence_consultation
  allowed_actions:
    - notify
    - capture_visible_answer
    - capture_visible_citations
  blocked_actions:
    - capture_credentials
    - bypass_mfa
    - download_restricted_content
    - send_unapproved_phi
  audit_required: true
  expires_at: datetime
```

## 13. Safety rules

Mandatory rules:

```text
1. AgentTower may discover surfaces it did not start.
2. Human-owned surfaces are notify-only by default.
3. Input, capture, focus, and protocol control require explicit permission.
4. Credential capture is never allowed by default.
5. MFA bypass is never allowed.
6. Browser attachment through CDP requires an exposed debug endpoint or explicitly supported browser extension/native host.
7. AgentTower should not assume a browser target is available just because a GUI window exists.
8. Every surface communication action must be auditable.
9. Domain factories define why the surface is used and what data may be captured.
10. AgentTower defines how surfaces are identified, mapped, permissioned, and communicated with.
```

## 14. Implementation sequence

Recommended build order:

```text
1. Extend registry from Pane to Work Surface.
2. Keep tmux pane discovery as first-class Work Surface discovery.
3. Add Work Surface Link / communication map table.
4. Add manual register-surface command.
5. Add GUI window discovery adapters by platform.
6. Add browser CDP target discovery for explicitly debug-enabled Chromium sessions.
7. Add surface permission model.
8. Add surface job envelope execution.
9. Add capture/input/focus actions under explicit permission.
10. Add browser extension/native host option for existing normal browser tabs.
```

## 15. Summary

AgentTower should be the system of record for local interactive work surfaces.

```text
terminals
tmux panes
container shells
GUI windows
browser targets
human-run external platform sessions
```

The key rule is:

> Keep window, terminal, browser, and communication-surface discovery in AgentTower. Domain factories should consume those surfaces through bounded, audited, policy-bound jobs.
