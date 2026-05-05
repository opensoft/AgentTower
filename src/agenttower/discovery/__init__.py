"""FEAT-003 discovery surface."""

from __future__ import annotations

from .matching import MatchingRule, default_rule
from .reconcile import ContainerUpsert, ReconcileWriteSet, reconcile
from .service import DiscoveryService

__all__ = [
    "ContainerUpsert",
    "DiscoveryService",
    "MatchingRule",
    "ReconcileWriteSet",
    "default_rule",
    "reconcile",
]
