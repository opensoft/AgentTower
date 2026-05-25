"""FEAT-013 tmux command recorder fixture (T015).

Records the exact tmux argv sequences issued by `tmux_create.py` so
contract tests can assert the argv-first invocation pattern (no shell
metachar interpolation, per research §R6 / Principle III).
"""

from __future__ import annotations
