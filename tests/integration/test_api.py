"""End-to-end tests for the ingest and consolidate Lambda handlers.

The commander handler is exercised separately (it needs Bedrock); here we inject
the hash-embedder engine so ingest/consolidate run with no AWS dependency.
"""

from __future__ import annotations

import json

import pytest

from retrace.api import consolidate, ingest, runtime
from retrace.memory import MemoryEngine
from retrace.memory.models import Evidence, EvidenceKind, IncidentStatus

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _wire_engine(engine: MemoryEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_engine", engine)


def test_ingest_is_idempotent(engine: MemoryEngine, org: str) -> None:
    event = {
        "body": json.dumps({"org_id": org, "fingerprint": "am-123", "service": "payments-api"})
    }

    first = ingest.handler(event)
    assert first["statusCode"] == 201
    second = ingest.handler(event)
    assert second["statusCode"] == 200

    body1, body2 = json.loads(first["body"]), json.loads(second["body"])
    assert body1["incident_id"] == body2["incident_id"]
    assert body2["created"] is False


def test_consolidate_batch_is_idempotent(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "outage", "payments-api")["id"]
    engine.evidence.record(
        Evidence(
            org_id=org, incident_id=iid, kind=EvidenceKind.deploy, content="deploy v2.4.1 leak"
        )
    )
    hypothesis = engine.beliefs.create_hypothesis(org, iid, "deploy v2.4.1 connection leak")
    assert hypothesis.id is not None
    engine.beliefs.set_belief(org, iid, hypothesis.id, 0.9)
    engine.incidents.set_status(iid, IncidentStatus.resolved, resolution="rolled back v2.4.1")

    first = consolidate.handler({"org_id": org, "limit": 10})
    assert json.loads(first["body"])["consolidated"] >= 1

    # Already marked consolidated -> the next run is a no-op.
    second = consolidate.handler({"org_id": org, "limit": 10})
    assert json.loads(second["body"])["consolidated"] == 0
