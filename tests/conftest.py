"""Shared pytest configuration.

Hypothesis enforces a 200ms-per-example deadline by default. Our property tests
are pure math, so their runtime is not the property under test — but they run
under `coverage` tracing, and on a loaded or throttled machine (a CI runner, a
laptop mid-build) a single example can cross the deadline and redden an otherwise
correct suite. A timing check is worth less here than a stable signal.

This does not suppress any *correctness* health check: a test that filters out too
many inputs still fails loudly, because that distorts the input distribution and
means the generator needs fixing rather than silencing.
"""

from __future__ import annotations

from hypothesis import settings

settings.register_profile("backcast", deadline=None)
settings.load_profile("backcast")
