"""Interactive web demo for Backcast (FastAPI + a single-page UI).

Runs the real memory engine against CockroachDB. The counterfactual, temporal,
and fencing demos are deterministic / DB-only, so the app needs no Bedrock and
stays fast and reliable for a live judge-facing demo.
"""
