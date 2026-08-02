"""AWS Lambda handlers for Backcast.

Each module exposes a ``handler(event, context)`` entry point:
  * :mod:`backcast.api.ingest`      — alert webhook -> incident (idempotent)
  * :mod:`backcast.api.commander`   — one Incident Commander turn (Bedrock)
  * :mod:`backcast.api.consolidate` — scheduled evidence-preserving consolidation
"""

from __future__ import annotations

from . import commander, consolidate, ingest
from .http import json_response, parse_body
from .runtime import get_engine

__all__ = ["commander", "consolidate", "get_engine", "ingest", "json_response", "parse_body"]
