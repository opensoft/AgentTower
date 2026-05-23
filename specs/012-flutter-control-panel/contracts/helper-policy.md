# Contract: Helper-Agent Policy (FR-038a)

**Purpose**: Specify the field set, sourcing rules, snapshot semantics, and override scope for the helper-agent policy referenced by FR-037, FR-038, FR-038a, and FR-042. Resolved by `/speckit-clarify` round 2 on 2026-05-23 (Q1–Q4); this document is the operational contract that the implementation honors.

**Anchor FR**: FR-038a (added by the spec-quality-pass change). All sub-contracts here defer to FR-038a's normative wording — this document expands the contract's mechanical detail without changing the spec.

## §1 Sourcing — daemon-side only (Q1 → R-19)

Per FR-038a, helper-agent policies are exposed exclusively through the FEAT-011 `app.*` namespace. The desktop app:

- **MUST NOT** read helper-policy YAML, markdown, or any other file from disk directly.
- **MUST** fetch the policy via the FEAT-011 methods documented in `app-methods-consumed.md` §5 (`app.helper_policies.list` and `app.helper_policies.resolve`, anticipated in a FEAT-011 v1.x bump).
- **MAY** cache the resolved policy for the duration of a single handoff draft (in app memory, not on disk).

The daemon is free to source the underlying policy from:
- a baked default manifest in `agenttower/config/` or equivalent (daemon-internal),
- a repo-level override at a conventional path the daemon discovers (e.g. `agenttower/helper-policy.yaml`, per Q4 → §3), or
- any other backing store the daemon decides to add.

The app does not know or care which backing store produced the policy; it only consumes the resolved policy returned by `app.helper_policies.resolve`.

## §2 Required field set (Q2 → R-19)

A helper-agent policy carries at minimum these four fields:

```json
{
  "policy_id": "string (stable identifier)",
  "allowed_helper_capabilities": ["string", "string", ...],
  "default_helper_capability": "string",
  "policy_source": "baked_default" | "operator_override" | "repo_override"
}
```

### `policy_id` (string, required)

Stable string identifier. The daemon owns the format; the app treats it as an opaque token. Two distinct backing-store policies (e.g. baked default vs a repo-override) have distinct `policy_id`s even if their other fields happen to match.

### `allowed_helper_capabilities` (array of string, required)

Set of capability tokens that handoff-launched workflows MAY invoke. Tokens come from FEAT-011's daemon-side capability vocabulary (`claude`, `codex`, `gemini`, `opencode`, `shell`, `test-runner`, plus any FEAT-011 additions). Empty array means "no helper-agent capabilities allowed".

### `default_helper_capability` (string, required)

Single token from `allowed_helper_capabilities`. The capability the handoff defaults to when the operator does not explicitly override.

**Invariant**: `default_helper_capability ∈ allowed_helper_capabilities`. The app validates this on receipt and surfaces `runtime-degraded` per FR-004 if violated.

### `policy_source` (enum, required)

One of:

| Value | Meaning |
|---|---|
| `baked_default` | Resolved from the daemon's internal baked default. No operator or repo override applied. |
| `operator_override` | Operator supplied an override in the current handoff flow (per FR-037 + Q3). |
| `repo_override` | Daemon resolved the policy from a project-level repo override file (per Q4 + §3). |

### Fields explicitly NOT in MVP

The clarifications round 2 deliberately rejected these for MVP (Q2 → Option B / C); the app and FEAT-011 contract MUST NOT include them in helper-policy payloads at v1.x:

- Per-capability quotas (max invocations per handoff, per hour, per session).
- Per-capability tool / permission whitelists (filesystem, network, daemon mutation surfaces).

If a future FEAT-011 bump adds these, the app gains support via the standard additive-evolution rule (FEAT-011 envelope ignores unknown fields).

## §3 Repo-level override (Q4)

A project repository MAY provide a repo-level override at the conventional path:

```
agenttower/helper-policy.yaml
```

The **daemon** discovers and parses this file; the **app** never reads it. When the daemon resolves a policy that originated from a repo override, the resolved policy MUST set `policy_source = "repo_override"`.

Example repo-level override file (informative; the daemon owns the parser):

```yaml
# agenttower/helper-policy.yaml
policy_id: agenttower-repo-default
allowed_helper_capabilities:
  - claude
  - codex
  - shell
  - test-runner
default_helper_capability: claude
```

## §4 Operator override scope — per-handoff only (Q3)

Per Q3 round 2, operator overrides (FR-037) apply **only to the current handoff submission**. There are no per-master, per-project, or global operator-level helper-policy persistence at MVP.

Implications:

- Each handoff carries its own resolved policy in `Handoff.helperPolicySnapshot` (per §5).
- An override on Handoff H1 has no effect on the next handoff drafted to the same master.
- The Settings surface does not expose a "default helper-policy override" field.

## §5 Snapshot semantics (FR-042 + Q2)

Per FR-042, every submitted handoff persists `helper_policy_snapshot`. The snapshot's shape:

```json
{
  "resolved_policy": {
    "policy_id": "string",
    "allowed_helper_capabilities": ["string", ...],
    "default_helper_capability": "string",
    "policy_source": "baked_default" | "operator_override" | "repo_override"
  },
  "snapshotted_at": "2026-05-23T18:45:00Z",
  "operator_override_of_policy_id": "string | null",
  "repo_override_path": "string | null"
}
```

- `resolved_policy` is the policy in effect at submission time (after override resolution).
- `snapshotted_at` is the daemon's submission timestamp.
- `operator_override_of_policy_id` is non-null iff `policy_source == "operator_override"`; it holds the `policy_id` the operator was overriding (the "base" policy before override).
- `repo_override_path` is non-null iff `policy_source == "repo_override"`; it holds the path the daemon discovered (informational, for audit).

**Reproducibility invariant**: a submitted handoff's prompt-context section MUST be reconstructible from the snapshot without any further daemon lookup, even if baked defaults or repo overrides change later. This is the load-bearing reason the spec persists the snapshot, not just the policy id.

## §6 Failure modes & degradation

### Helper-policy methods absent on FEAT-011 v1.0 (R-19 caveat)

If FEAT-011's running contract version does not yet expose `app.helper_policies.list` / `.resolve`, the handoff flow's policy section is `runtime-degraded` per FR-004:

- Policy selector is disabled with an inline explanation referencing the missing contract version.
- Operator may still draft a handoff in `default` mode; submission proceeds with the daemon's implicit default (the daemon decides what that means).
- The contract-version banner from FR-002 informs the operator that policy override is unavailable until upgrade.

### Resolved policy violates the `default ∈ allowed` invariant

App surfaces `runtime-degraded` and disables submission until the daemon returns a valid policy. The app does NOT auto-correct (per FR-005 / Conservative Automation principle).

### Repo override file is malformed (daemon-side error)

The daemon returns the baked default and includes a doctor warning in `app.readiness`. The app surfaces the warning on the Handoff helper-policy section but does not block submission.

## §7 Doctor / preflight coverage (FR-009 + §1)

The FR-009 doctor check #6 ("OS-native notification permission is granted IF the FR-058 toggle is enabled") is unchanged. A new doctor check is **NOT** added for helper-policy specifically — `app.readiness` already surfaces helper-policy-resolution health as part of its subsystem probes (per FR-022).

## §8 What this contract does NOT cover

- **Daemon-side policy resolution algorithm**: out of scope for FEAT-012; lives in the FEAT-011 follow-up that adds the helper-policy methods.
- **Capability vocabulary evolution**: capability tokens (`claude`, `codex`, etc.) are FEAT-011's responsibility; the app accepts whatever set the daemon returns.
- **Helper-agent execution**: this contract is about **policy** (allowed/default capabilities), not about how a helper agent is invoked. Execution lives in the daemon and the master agent's workflow.
