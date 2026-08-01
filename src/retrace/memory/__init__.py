"""Retrace cognitive memory engine.

Four memory tiers over a single CockroachDB cluster:
  * episodic  — immutable :class:`~retrace.memory.evidence.EvidenceStore`
  * semantic  — :class:`~retrace.memory.semantic.SemanticStore` (revisable, decayed)
  * procedural — :class:`~retrace.memory.procedural.ProceduralStore` (outcome-weighted)
  * working   — disposable, Row-Level TTL

Plus the mechanisms that make it *agentic* memory rather than a RAG cache:
  * :class:`~retrace.memory.beliefs.BeliefStore` — time-versioned beliefs + provenance graph
  * :class:`~retrace.memory.temporal.TemporalReconstructor` — AS OF SYSTEM TIME no-leak recall
  * :class:`~retrace.memory.leases.ActionLeaseCoordinator` — memory-governed safe autonomy
  * :class:`~retrace.memory.ledger.EventLedger` — hash-chained permanent provenance
  * :class:`~retrace.memory.consolidation.Consolidator` — evidence-preserving reflection
"""

from __future__ import annotations

from .beliefs import BeliefStore
from .consolidation import (
    Consolidator,
    DistillationResult,
    Distiller,
    LLMDistiller,
    RuleBasedDistiller,
)
from .embeddings import BedrockEmbedder, Embedder, HashEmbedder, build_embedder
from .engine import MemoryEngine
from .evidence import EvidenceStore
from .incidents import IncidentStore
from .leases import ActionLeaseCoordinator
from .ledger import EventLedger
from .models import (
    Belief,
    BeliefState,
    ConsolidationReport,
    Evidence,
    EvidenceKind,
    Hypothesis,
    HypothesisStatus,
    IncidentStatus,
    LeaseClaim,
    LeaseStatus,
    LedgerEntry,
    NodeType,
    Procedure,
    RecalledFact,
    RecalledProcedure,
    Relation,
    SemanticFact,
    Severity,
)
from .procedural import ProceduralStore
from .semantic import SemanticStore
from .temporal import TemporalReconstructor

__all__ = [
    "ActionLeaseCoordinator",
    "BedrockEmbedder",
    "Belief",
    "BeliefState",
    "BeliefStore",
    "ConsolidationReport",
    "Consolidator",
    "DistillationResult",
    "Distiller",
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
    "LLMDistiller",
    "LeaseClaim",
    "LeaseStatus",
    "LedgerEntry",
    "MemoryEngine",
    "NodeType",
    "ProceduralStore",
    "Procedure",
    "RecalledFact",
    "RecalledProcedure",
    "Relation",
    "RuleBasedDistiller",
    "SemanticFact",
    "SemanticStore",
    "Severity",
    "TemporalReconstructor",
    "build_embedder",
]
