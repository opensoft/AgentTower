"""FEAT-009 `--target` resolver.

Per Clarifications session 2 Q2 + research §R-001: the `--target`
argument accepts either an `agent_id` (shape `agt_<12-hex>` per the
FEAT-006 AGENT_ID_RE) or a label. If the input matches the agent_id
shape it is resolved as agent_id; otherwise it is resolved as label.
Multiple active label matches return `target_label_ambiguous`; no
match in either form returns `agent_not_found` (FEAT-008 inheritance,
not the earlier-draft `target_not_found`).
"""

from __future__ import annotations
