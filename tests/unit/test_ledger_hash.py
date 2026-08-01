"""Unit tests for the ledger hash chain (pure function, no database)."""

from __future__ import annotations

from retrace.memory.ledger import compute_entry_hash


def test_hash_is_deterministic() -> None:
    a = compute_entry_hash(None, 1, "incident_opened", {"service": "api"}, "agent")
    b = compute_entry_hash(None, 1, "incident_opened", {"service": "api"}, "agent")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_chain_links_and_detects_tampering() -> None:
    h1 = compute_entry_hash(None, 1, "incident_opened", {"service": "api"}, "agent")
    h2 = compute_entry_hash(h1, 2, "belief_updated", {"confidence": 0.87}, "agent")

    # Changing an earlier payload changes its hash, breaking the chain link.
    tampered = compute_entry_hash(None, 1, "incident_opened", {"service": "hacked"}, "agent")
    assert tampered != h1
    h2_from_tampered = compute_entry_hash(
        tampered, 2, "belief_updated", {"confidence": 0.87}, "agent"
    )
    assert h2_from_tampered != h2
