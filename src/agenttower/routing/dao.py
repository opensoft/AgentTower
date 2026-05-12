"""FEAT-009 `message_queue` and `daemon_state` DAO.

Implements all CRUD + state-transition methods for the FEAT-009 queue
schema declared in data-model.md §2. Every transition runs under
`BEGIN IMMEDIATE` and is wrapped in the bounded SQLite-lock retry
policy (Group-A walk Q5: 3 attempts at 10/50/250 ms; persistent
failure → SqliteLockConflict → `failure_reason='sqlite_lock_conflict'`).

This module is the sole production-side writer for `message_queue` and
`daemon_state` rows; only the delivery worker, queue service, and
kill-switch service call into it.
"""

from __future__ import annotations
