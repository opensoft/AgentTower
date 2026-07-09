# Cross-Container Isolation (R12) Requirements Quality Checklist

**Purpose**: "Unit tests for English" for the bench-container isolation / R12 peer-scoping trust model — the cohesive concern behind deep-review findings #1 (CRITICAL peer-identity spoof), #16 (id-normalization), and #8 (cross-tenant detail leakage) that previously spanned `security.md`, `concurrency.md`, and `api.md` without a single gating checklist (coverage-alignment CHK003).
**Created**: 2026-06-01
**Feature**: [spec.md](../spec.md) §FR-016 (R12 peer scoping) · [contracts/managed-methods.md](../contracts/managed-methods.md) §peer-scoping · [contracts/error-codes.md](../contracts/error-codes.md) (`host_only`)
**Depth**: release gate. **Audience**: feature owner + security reviewer.
**Convention**: `[x]` = requirement quality adequate (evidence inline); `[ ]` = gap.

## Identity establishment (trust model)

- [x] CHK001 Does the spec specify the SOURCE of a bench peer's container identity, and require it be **unspoofable** (kernel-derived), not container-suppliable? [Completeness, Security, Spec §FR-016 R12] — FR-016 now: identity from the peer's cgroup id, "System MUST NOT trust a container-suppliable value such as `/etc/hostname`."
- [x] CHK002 Is the identity required to be **verified against the FEAT-003 registry** (not accepted as a raw string)? [Clarity, Spec §FR-016 R12] — FR-016: "canonicalized against the FEAT-003 container registry; … does not uniquely match a registered container MUST fail closed."
- [x] CHK003 Is short(12)/full(64)-char container-id **normalization** specified so legitimate same-container peers are not falsely denied? [Completeness, Spec §FR-016 R12] — FR-016: "Identity comparison MUST normalize short (12-char) and full (64-char) container-id forms."
- [x] CHK004 Is the **fail-closed** default specified for an underivable / ambiguous peer identity (deny, never host-equivalent)? [Coverage, Exception, Spec §FR-016 R12] — FR-016: "MUST fail closed (deny)."

## Authorization scope & enforcement points

- [x] CHK005 Is the own-container-only rule specified to apply to **all** managed surfaces a bench peer can reach (create/list/detail/remove/recreate), not just create? [Coverage, Consistency, contracts/managed-methods §peer-scoping] — Contract: "Every legacy `managed.*` call from a bench-container peer is checked: `request.container_id == peer.container_id`."
- [x] CHK006 Is the cross-container denial code specified as `host_only` consistently across surfaces? [Consistency, Spec §FR-016, contracts] — `host_only` listed for create/list/detail/remove/recreate.
- [ ] CHK007 Are the **app-contract `app.managed_*`** surfaces' scoping rules stated to be host-only (not bench-peer-scoped) and is that distinction from the legacy `managed.*` namespace explicit? [Clarity, Gap] — The app namespace is host-only by construction; confirm the contract states this so the two namespaces' authorization models aren't conflated by a reader.

## Information disclosure

- [x] CHK008 Is the `host_only` error `details` shape required to be `{}` (no resolved-peer id, no foreign container/layout/pane id)? [Security, Consistency, Spec §FR-016, error-codes §FR-034a] — FR-016 now cross-references FR-034a: "details MUST be `{}` … to avoid a cross-tenant enumeration oracle."
- [x] CHK009 Is it specified that diagnostic peer/target ids stay in daemon-side logs only, never on the wire? [Clarity, Security] — Implied by the `details = {}` rule; the implementation keeps them in logs.

## Coexistence & ownership (FR-009 / FR-012)

- [x] CHK010 Are requirements defined so managed and adopted agents coexist in one container without changing adopted-pane identity/ownership? [Coverage, Spec §FR-009/§FR-012] — FR-009 (coexistence), FR-012 (no destructive actions on adopted panes).
- [x] CHK011 Is the adopted-vs-managed distinction required to be visible in operator surfaces (so isolation is observable, not just enforced)? [Completeness, Spec §FR-005] — FR-005.

## Scenario coverage

- [x] CHK012 Is the **Exception** path specified (hostile/forged peer → fail closed deny)? [Coverage, Exception, Spec §FR-016 R12] — covered by CHK001/CHK004.
- [ ] CHK013 Are requirements defined for an **unresolved-but-benign** peer (e.g. a host CLI whose pid credentials can't be read) vs a bench peer — is the host-vs-bench determination's failure mode specified? [Coverage, Gap] — The implementation treats a verified host as cross-container-allowed and an unresolvable peer as fail-closed; confirm the requirement distinguishes "verified host" from "unresolvable" so the host CLI is never accidentally denied.
- [x] CHK014 Is the trust boundary anchored to the constitution's local-first, no-network-listener model (peers are local AF_UNIX, identified by pid credentials)? [Consistency, Spec §FR-017] — FR-017 + research §R12.
