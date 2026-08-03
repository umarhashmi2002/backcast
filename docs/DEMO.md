# Demo guide

A tight, repeatable script for the < 3-minute video and live judging. Everything runs the **real**
engine against CockroachDB — nothing is faked or pre-recorded.

## Setup (pick one)

- **Live URL** (best for judges): open the deployed `WebappUrl` — the interactive UI.
- **Local web UI:** `make bootstrap && make db-up && make web` → http://localhost:8000
- **Terminal:** `make db-up` then the CLI commands below.

## The 3-act story

### Act 1 — Counterfactual replay (the differentiator) · ~70s

> "An on-call engineer restarts a service, the alert clears, incident closed. But *was that the right
> call?* Backcast rewinds and finds out."

- **Web:** click **① Run counterfactual**. **CLI:** `uv run backcast counterfactual`.
- **Point at:**
  - the branch **score bars** — `rollback-deploy` (★ BEST, permanent fix) far outranks the actual
    `restart` (which only *relieves* and recurs);
  - the big **decision regret = 1.24** — how much better the optimal decision was;
  - the **lesson promoted to memory** — the agent now *knows* the better remediation, verified by
    simulation, not guessed;
  - "**outcomes are computed by a deterministic model — the LLM never decides success.**"
- **Why it wins:** this is only possible because incidents, branches, outcomes, and the memory they
  feed live in one transactional store. A vector-store chatbot cannot do this.

### Act 2 — Temporal reconstruction & belief revision · ~60s

> "At 03:14 the agent blamed a traffic surge. At 03:17 a deploy correlation flipped it. Backcast can
> show *exactly* what it believed at 03:14 — without seeing anything it learned later."

- **Web:** click **② Reconstruct the past**. **CLI:** `uv run backcast demo`.
- **Point at:**
  - the two side-by-side panels (03:14 vs. now) and the belief meters (**surge 58% → 8%**,
    **deploy 11% → 87%**);
  - **No-leak guarantee = true** — the deploy evidence is *hidden* from the 03:14 view (enforced by
    CockroachDB MVCC via `AS OF SYSTEM TIME`);
  - **ledger chain verified** — a tamper-evident audit trail.

### Act 3 — Safe autonomy (fencing) · ~40s

> "When 20 duplicate workers race to run the same rollback, exactly one may act — and a crashed worker
> can never double-execute."

- **Web:** click **③ Race 20 workers**. **CLI:** `make race-demo`.
- **Point at:**
  - **1** winner out of 20 (transactional `UNIQUE` claim);
  - the winner **crashes**, a standby **takes over** (generation → 2), and the **revived stale worker is
    fenced out**;
  - the external effect executed **exactly once** across the crash + revival (idempotency + fencing).

## Close · ~10s

> "One transactionally-consistent temporal database — CockroachDB — gives the agent memory it can
> reconstruct, reason over, learn from, and act on safely. Deployed serverless on AWS."

## Map to the judging criteria

| Criterion | Shown in |
|---|---|
| Agentic Memory Design | Acts 1–3 (evidence, beliefs, actions, counterfactual branches — all in CockroachDB) |
| Technological Implementation | `AS OF SYSTEM TIME`, C-SPANN, fencing, hash chain — used correctly; typed + tested + CI |
| Real-World Impact | Act 1 (compounding *verified* knowledge on a universal on-call problem) |
| Product Readiness | Act 3 + fenced/idempotent actions, least-privilege IAM, tamper-evident audit |
| Creativity & Originality | Act 1 (transactionally-consistent counterfactual replay + decision regret) |
