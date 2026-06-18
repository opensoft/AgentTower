# Tasks: Layered Routing/Input Delivery Policies

> Spec/design proposal. Implementation is sequenced into a later feature; items
> marked **(impl)** belong to that feature, not to this change's merge.

## 1. Spec authoring (this change)

- [ ] 1.1 Define the `routing-policy` capability spec: layered resolution,
      precedence + merge rules, MVP policy types, decision auditing, and
      backward compatibility.
- [ ] 1.2 Cross-check against FEAT-009 (gate + kill switch), FEAT-010 (routes),
      and `agent-connection-tiers` tier-independent outbound safety.
- [ ] 1.3 Confirm no requirement governs agent tool calls (router-only scope).

## 2. Pre-implementation decisions

- [ ] 2.1 Decide fixed rule-types vs minimal DSL for the first implementing
      feature.
- [ ] 2.2 Decide default rate-cap keying (source / target / pair).

## 3. Implementation **(impl, future feature)**

- [ ] 3.1 Add a `policies` table (schema bump) keyed by scope (global / agent /
      route).
- [ ] 3.2 Implement deterministic resolution (deny-wins, min-wins) in the
      existing delivery path.
- [ ] 3.3 Implement MVP policy types: rate cap, require-approval, allow/deny by
      source role+capability, target-busy/quiet hold, global kill switch.
- [ ] 3.4 Emit `policy_allowed` / `policy_blocked` / `policy_held` audit events.
- [ ] 3.5 `agenttower policy {list,add,remove,show}` CLI.
- [ ] 3.6 Surface policies + decisions through the FEAT-011 app backend.
- [ ] 3.7 Map FEAT-009 `send_input_allowed` + kill switch onto the base layer;
      prove no-policy behavior is unchanged.

## 4. Validation

- [ ] 4.1 `openspec validate routing-policy-layers --strict`.
- [ ] 4.2 Confirm each ADDED requirement has at least one `#### Scenario:`.
