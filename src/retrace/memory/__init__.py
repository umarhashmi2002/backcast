"""Retrace cognitive memory engine.

Four memory tiers over a single CockroachDB cluster:
  * episodic  — immutable :class:`~retrace.memory.evidence.EvidenceStore`
  * semantic/procedural — long-term stores (added incrementally)
  * working   — disposable, Row-Level TTL

Plus the mechanisms that make it *agentic* memory rather than a RAG cache:
  * :class:`~retrace.memory.beliefs.BeliefStore` — time-versioned beliefs + provenance graph
  * :class:`~retrace.memory.temporal.TemporalReconstructor` — AS OF SYSTEM TIME no-leak recall
  * :class:`~retrace.memory.leases.ActionLeaseCoordinator` — memory-governed safe autonomy
  * :class:`~retrace.memory.ledger.EventLedger` — hash-chained permanent provenance
"""

from __future__ import annotations

from .beliefs import BeliefStore
from .embeddings import BedrockEmbedder, Embedder, HashEmbedder, build_embedder
from .engine import MemoryEngine
from .evidence import EvidenceStore
from .incidents import IncidentStore
from .leases import ActionLeaseCoordinator
from .ledger import EventLedger
from .models import (
    Belief,
    BeliefState,
    Evidence,
    EvidenceKind,
    Hypothesis,
    HypothesisStatus,
    IncidentStatus,
    LeaseClaim,
    LeaseStatus,
    LedgerEntry,
    NodeType,
    Relation,
    Severity,
)
from .temporal import TemporalReconstructor

__all__ = [
    "ActionLeaseCoordinator",
    "BedrockEmbedder",
    "Belief",
    "BeliefState",
    "BeliefStore",
    "Embedder",
    "EventLedger",
    "Evidence",
    "EvidenceKind",
    "EvidenceStore",
    "HashEmbedder",
    "Hypothesis",
    "HypothesisStatus",
    "IncidentStatus",
    "IncidentStore",
    "LeaseClaim",
    "LeaseStatus",
    "LedgerEntry",
    "MemoryEngine",
    "NodeType",
    "Relation",
    "Severity",
    "TemporalReconstructor",
    "build_embedder",
]
