# The memory model

Backcast models memory the way a careful operator's mind works: a durable record of what happened, a
revisable set of beliefs about *why*, learned procedures for *what to do*, and a scratchpad that is
safe to forget. All of it lives in CockroachDB.

## Tiers

### Episodic — `evidence` (immutable) + `event_ledger` (hash-chained)
Raw signals the agent observed: metrics, logs, traces, deploys, human notes. **Never updated or
deleted.** Each row carries `observed_at` (valid time) and `db_ts` (the commit HLC), and an optional
`VECTOR(1024)` embedding indexed by C-SPANN for cross-incident recall. The ledger records every
significant event as an append-only, hash-linked entry — tamper-evident within the database, with
KMS-signed checkpoints exported to S3 Object Lock for durable integrity beyond the GC window.

### Belief — `hypotheses`, `beliefs`, `provenance_edges`
Candidate explanations, and a **time-versioned** confidence over them. A confidence change appends a
new `beliefs` row and closes the previous one (`valid_until`, `superseded_by`) — the full revision
history is preserved. `provenance_edges` is a typed graph: `evidence —supports/contradicts→ hypothesis`,
`action —verifies→ hypothesis`, `belief —supersedes→ belief`. This is what lets Backcast answer
*"which evidence changed the agent's mind, and when?"*

### Semantic / Procedural — `semantic_memory`, `procedural_memory`
Distilled, reusable knowledge and remediations that *worked* (confidence from success/failure counts).
Vector-indexed. Revisable and **retrieval-decayed**: a `retrieval_score` lowers recall priority over
time without destroying the fact; supersession (`superseded_by`) revises beliefs explicitly.

### Working — `working_memory`
The live session scratchpad. The **only** tier with Row-Level TTL — it is disposable by design.

## Consolidation is evidence-preserving (on purpose)

Naïvely asking an LLM to re-summarize memory after every interaction is dangerous: repeated rewriting
of consolidated memory can drift and corrupt genuinely useful knowledge. Backcast therefore:

- keeps **raw evidence immutable** — it is never rewritten;
- runs consolidation **only on incident closure** (gated), not after every turn;
- writes semantic facts as **versioned** rows that can be *superseded*, not overwritten;
- weights procedures by **observed success/failure**, not by an LLM's say-so;
- lets low-value memory **decay in retrieval score** rather than being deleted;
- physically deletes **only** disposable working memory (Row-Level TTL).

The result: the system gets smarter without losing the ground truth its audit trail depends on.

## Recall ranking

Vector indexes rank by raw distance; recall additionally blends **recency** and (for long-term
memory) a decaying **retrieval score** and **importance**, so *what mattered* beats *what is merely
nearest*. Because Titan v2 embeddings are L2-normalized, we use the default L2 op class with the
`<->` operator — **ranking-equivalent** to cosine (the numeric distances differ; the ordering does
not), verified on the CockroachDB Cloud version in use (v26.2). Historical (`AS OF SYSTEM TIME`)
recall scores by exact distance over a bounded set rather than assuming the ANN index is used.
See [`src/backcast/memory/scoring.py`](../src/backcast/memory/scoring.py).
