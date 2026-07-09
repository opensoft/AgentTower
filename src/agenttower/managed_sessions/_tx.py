"""Shared transaction-lock helper for FEAT-013 (concurrency fix C1).

Background
==========

The FEAT-009 delivery worker owns a single SQLite connection
(``worker_conn``) with ``isolation_level=None`` and serializes ALL of
its transactions through a single ``worker_tx_lock``. FEAT-010 (routing
worker) and FEAT-011 (app contract) reuse the same connection + lock so
multiple background workers can mutate state without surfacing
``sqlite3.OperationalError: cannot start a transaction within a
transaction``.

FEAT-013's daemon-boot wiring passes the SAME ``worker_conn`` to the
managed-sessions handlers via ``ctx.state_conn``. Without ``tx_lock``
discipline, a FEAT-013 ``create_layout`` issuing ``BEGIN IMMEDIATE``
while the FEAT-009 worker is mid-transaction would either crash or
silently land its writes inside the wrong transaction boundary.

Solution
========

Every FEAT-013 entry point that mutates the DB takes an optional
``tx_lock: threading.Lock | None`` parameter. The body acquires the
lock around its statement block(s) via :func:`tx_guard`. Production
daemon wiring passes ``ctx.state_tx_lock`` (== ``worker_tx_lock``);
tests that own their own sqlite connection pass ``None`` and the
context manager is a no-op.

Lock ordering
=============

The per-container ``serializer.for_container(cid)`` lock is held for
the LONG duration of a service operation (including tmux RPCs and
backend calls). The ``tx_lock`` is acquired only around the SHORT DB
statement blocks, INSIDE the per-container lock. This ordering is
strict and safe — the per-container lock is feature-local; the tx_lock
is cross-feature.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Optional


def tx_guard(lock: Optional[threading.Lock]) -> "contextlib.AbstractContextManager[object]":
    """Return a context manager that acquires ``lock`` if it is not None.

    A ``None`` lock yields a no-op ``contextlib.nullcontext()``. Callers
    can therefore wrap every DB-statement block in
    ``with tx_guard(tx_lock):`` regardless of whether the lock was
    actually wired — keeping production and test paths identical at the
    call site.
    """
    if lock is None:
        return contextlib.nullcontext()
    return lock


__all__ = ["tx_guard"]
