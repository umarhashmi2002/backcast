"""MemoryEngine — the single facade over Retrace's CockroachDB memory layer."""

from __future__ import annotations

from ..config import Settings, get_settings
from ..db.connection import Connection, shared_connection
from .beliefs import BeliefStore
from .consolidation import Consolidator, Distiller
from .embeddings import Embedder, build_embedder
from .evidence import EvidenceStore
from .incidents import IncidentStore
from .leases import ActionLeaseCoordinator
from .ledger import EventLedger
from .procedural import ProceduralStore
from .semantic import SemanticStore
from .temporal import TemporalReconstructor


class MemoryEngine:
    """Wires the memory stores over one connection.

    Uses autocommit so single statements commit immediately; stores open
    explicit transactions (``conn.transaction()``) where atomicity is required
    (belief revision, ledger appends).
    """

    def __init__(
        self,
        conn: Connection | None = None,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
        *,
        distiller: Distiller | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.conn = conn or shared_connection()
        self.conn.autocommit = True
        self.embedder = embedder or build_embedder(self.settings)

        self.incidents = IncidentStore(self.conn)
        self.evidence = EvidenceStore(self.conn, self.embedder, self.settings)
        self.ledger = EventLedger(self.conn)
        self.beliefs = BeliefStore(self.conn)
        self.temporal = TemporalReconstructor(self.conn)
        self.leases = ActionLeaseCoordinator(self.conn)
        self.semantic = SemanticStore(self.conn, self.embedder, self.settings)
        self.procedural = ProceduralStore(self.conn, self.embedder, self.settings)
        self.consolidator = Consolidator(self, distiller)

    def close(self) -> None:
        if not self.conn.closed:
            self.conn.close()
