"""Retrace — an AI SRE Incident Commander with production-grade agentic memory.

CockroachDB is the single system of record for the agent's memory: working,
episodic, semantic, and procedural memory live in one distributed database,
combining transactional state, C-SPANN vector recall, and time-travel
provenance (``AS OF SYSTEM TIME``).
"""

__version__ = "0.1.0"
