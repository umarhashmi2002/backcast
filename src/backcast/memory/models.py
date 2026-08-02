"""Pydantic models for the memory layer.

HLC timestamps (``db_ts``) are carried as strings to preserve the full decimal
precision CockroachDB returns from ``cluster_logical_timestamp()`` — they are
fed back verbatim into ``AS OF SYSTEM TIME``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Severity(StrEnum):
    sev1 = "sev1"
    sev2 = "sev2"
    sev3 = "sev3"
    sev4 = "sev4"
    sev5 = "sev5"


class IncidentStatus(StrEnum):
    triggered = "triggered"
    acknowledged = "acknowledged"
    investigating = "investigating"
    mitigating = "mitigating"
    resolved = "resolved"
    closed = "closed"


class EvidenceKind(StrEnum):
    alert = "alert"
    metric = "metric"
    log = "log"
    trace = "trace"
    deploy = "deploy"
    topology = "topology"
    human = "human"
    external = "external"


class HypothesisStatus(StrEnum):
    open = "open"
    supported = "supported"
    refuted = "refuted"
    confirmed = "confirmed"
    dismissed = "dismissed"


class LeaseStatus(StrEnum):
    claimed = "claimed"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    released = "released"


class NodeType(StrEnum):
    evidence = "evidence"
    hypothesis = "hypothesis"
    belief = "belief"
    action = "action"
    incident = "incident"
    procedure = "procedure"
    semantic_fact = "semantic_fact"


class Relation(StrEnum):
    supports = "supports"
    contradicts = "contradicts"
    verifies = "verifies"
    refutes = "refutes"
    supersedes = "supersedes"
    derived_from = "derived_from"
    recalled_for = "recalled_for"
    remediates = "remediates"


class Evidence(BaseModel):
    id: UUID | None = None
    org_id: str
    incident_id: UUID
    kind: EvidenceKind
    source: str = "system"
    content: str
    observed_at: datetime | None = None
    s3_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    db_ts: str | None = None
    created_at: datetime | None = None


class RecalledEvidence(BaseModel):
    id: UUID
    incident_id: UUID
    kind: EvidenceKind
    content: str
    observed_at: datetime
    distance: float
    score: float


class Hypothesis(BaseModel):
    id: UUID | None = None
    org_id: str
    incident_id: UUID
    statement: str
    status: HypothesisStatus = HypothesisStatus.open
    db_ts: str | None = None
    created_at: datetime | None = None


class Belief(BaseModel):
    id: UUID | None = None
    org_id: str
    incident_id: UUID
    hypothesis_id: UUID
    confidence: float
    rationale: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    superseded_by: UUID | None = None
    incident_state_version: int | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    created_by: str = "agent"
    db_ts: str | None = None


class BeliefState(BaseModel):
    """A point-in-time reconstruction of what the agent believed and knew."""

    incident_id: UUID
    as_of_hlc: str
    beliefs: list[Belief] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class LedgerEntry(BaseModel):
    incident_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    actor: str | None = None
    prev_hash: str | None = None
    entry_hash: str


class LeaseClaim(BaseModel):
    won: bool
    action_key: str
    holder: str
    status: LeaseStatus
    lease_id: UUID | None = None
    idempotency_key: str | None = None
    lease_generation: int = 1
    existing_holder: str | None = None


class SemanticFact(BaseModel):
    id: UUID | None = None
    org_id: str
    statement: str
    source: str = "consolidation"
    service: str | None = None
    confidence: float = 0.6
    importance: float = 0.5
    retrieval_score: float = 1.0
    created_at: datetime | None = None


class RecalledFact(BaseModel):
    id: UUID
    statement: str
    service: str | None = None
    confidence: float
    retrieval_score: float
    distance: float
    score: float


class Procedure(BaseModel):
    id: UUID | None = None
    org_id: str
    name: str
    trigger_pattern: str
    steps: str
    service: str | None = None
    success_count: int = 0
    failure_count: int = 0
    source_incident_id: UUID | None = None


class RecalledProcedure(BaseModel):
    id: UUID
    name: str
    trigger_pattern: str
    steps: str
    success_count: int
    failure_count: int
    distance: float
    score: float


class ConsolidationReport(BaseModel):
    incident_id: UUID
    skipped: bool = False
    reason: str | None = None
    facts_created: int = 0
    facts_reinforced: int = 0
    procedure_created: bool = False
    procedure_reinforced: bool = False
