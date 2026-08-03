"""MemoryEngine — the single facade over Backcast's CockroachDB memory layer."""

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
from .models import RecalledEvidence
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

        # Counterfactual replay (rewind → fork → simulate → compare). Imported here
        # to keep the module-load order memory → simulation (simulation only needs
        # MemoryEngine as a type).
        from ..simulation.branches import CounterfactualService

        self.counterfactual = CounterfactualService(self)

    def historical_recall(
        self,
        org_id: str,
        query: str,
        as_of_hlc: str,
        *,
        top_k: int = 8,
        exclude_incident: object = None,
    ) -> list[RecalledEvidence]:
        """Embed ``query`` and recall evidence as it existed at ``as_of_hlc`` (exact, no-leak)."""
        return self.temporal.historical_recall(
            org_id,
            self.embedder.embed_one(query),
            as_of_hlc,
            top_k=top_k,
            exclude_incident=exclude_incident,  # type: ignore[arg-type]
        )

    def close(self) -> None:
        if not self.conn.closed:
            self.conn.close()
