"""AWS Lambda handlers for Retrace.

Each module exposes a ``handler(event, context)`` entry point:
  * :mod:`retrace.api.ingest`      — alert webhook -> incident (idempotent)
  * :mod:`retrace.api.commander`   — one Incident Commander turn (Bedrock)
  * :mod:`retrace.api.consolidate` — scheduled evidence-preserving consolidation
"""

from __future__ import annotations

from . import commander, consolidate, ingest
from .http import json_response, parse_body
from .runtime import get_engine

__all__ = ["commander", "consolidate", "get_engine", "ingest", "json_response", "parse_body"]
