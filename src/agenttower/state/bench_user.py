"""Shared normalization for the bench user identifier.

Docker's ``Config.User`` (persisted as ``containers.config_user``) is
permissive: it can be a username (``"brett"``), a ``user:uid`` pair
(``"brett:1000"``), a numeric uid (``"1000"``), or empty (which Docker
treats as root). For ``docker exec -u <user>`` we only want the
username portion. FEAT-004 pane discovery has had this normalization
since FR-020; FEAT-007 attach-log and FR-043 orphan recovery now
share the same rule via this helper so all three subsystems agree on
"who is this container running as" without a re-implementation.

This helper intentionally takes no environment fallback: the FEAT-004
``_resolve_bench_user`` flavor (config_user → ``$USER`` → ``getpwuid``)
is appropriate at scan time when the daemon must guess. FEAT-007
callers always have ``config_user`` from the persisted container row,
so the simple "left-of-colon, fall back to root" form is enough.
"""

from __future__ import annotations


def normalize_bench_user_for_exec(config_user: str | None) -> str:
    """Return the bench username suitable for ``docker exec -u``.

    Strips a ``:uid`` suffix from Docker's ``Config.User`` form and
    falls back to ``"root"`` when the value is empty, all-whitespace,
    or all-suffix (e.g. ``":1000"``).
    """
    if config_user:
        head = config_user.split(":", 1)[0].strip()
        if head:
            return head
    return "root"
