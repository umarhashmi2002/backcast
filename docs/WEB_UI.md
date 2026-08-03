# Web UI — design & wireframe

A single-page **React + TypeScript (Vite)** app that runs the real engine (via the FastAPI backend) and
visualizes the three headline mechanisms. Built to a small, consistent design system.

## Principles
- **Show, don't tell** — every panel runs live and renders the actual data (scores, HLCs, verdicts).
- **One system, three proofs** — counterfactual replay (the star), temporal reconstruction, safe autonomy.
- **Calm, technical, trustworthy** — dark theme, generous spacing, tabular numerics, no gimmicks.

## Design tokens
| Token | Value | Use |
|---|---|---|
| `--bg` | `#0b1020` | app background (radial glow top-right) |
| `--panel` | `#141b2e` | cards |
| `--ink` / `--muted` | `#e8edf7` / `#93a0bd` | text |
| `--purple` | `#7b5cff` | primary (CockroachDB) |
| `--orange` | `#ff9f43` | accent (AWS), decision regret |
| `--green` / `--amber` / `--red` | success / actual / failure | verdicts, best/actual/error |
| radius | `14px` · type | `ui-sans-serif` system stack, tabular numerals for data |

## Wireframe

```text
┌───────────────────────────────────────────────────────────────────┐
│ 🔁 Backcast            temporal decision laboratory · CockroachDB×AWS│
├───────────────────────────────────────────────────────────────────┤
│  Rewind an incident. Fork the decision.                             │
│  Compare what would have happened.                    [gradient h1] │
│  Every panel runs the real engine against a live CockroachDB.       │
├───────────────────────────────────────────────────────────────────┤
│  ① Counterfactual replay                            [Run ▸]         │
│  ───────────────────────────────────────────────────────────────   │
│  rollback-deploy  ████████████████████░  0.88  ★BEST                │
│  increase-pool    ██████████████████░░░  0.82                       │
│  restart (actual) ████░░░░░░░░░░░░░░░░░ -0.36  ←ACTUAL              │
│  wait             ██████░░░░░░░░░░░░░░░ -0.10                       │
│                                                                     │
│   decision regret  1.24   ▸ lesson promoted to memory               │
├───────────────────────────────────────────────────────────────────┤
│  ② Temporal reconstruction & belief revision        [Run ▸]         │
│  ┌── 03:14 (AS OF SYSTEM TIME) ──┐  ┌── now ──────────────────┐     │
│  │ • metric: pool 94%            │  │ • metric: pool 94%       │     │
│  │ surge ███████░ 58%            │  │ • deploy: v2.4.1 …       │     │
│  │ deploy █░░░░░░ 11%            │  │ surge █░ 8% deploy ███ 87│     │
│  └───────────────────────────────┘  └──────────────────────────┘   │
│   no-leak ✓   belief 11%→87%   ledger verified ✓                    │
├───────────────────────────────────────────────────────────────────┤
│  ③ Safe autonomy — one action, once                 [Run ▸]         │
│   20 workers → 1 won · takeover gen 2 · stale worker fenced ✓        │
│   external effect executed exactly 1×                               │
└───────────────────────────────────────────────────────────────────┘
```

## Components
- `App` — layout + state (which panels have run).
- `Hero` — headline + subcopy.
- `Panel` — reusable card (title, subtitle, run button with spinner, results slot).
- `BranchBars` — the counterfactual score chart + regret + lesson.
- `Timeline` — the 03:14-vs-now reconstruction with belief meters.
- `RaceResult` — the fencing verdict grid.
- `api.ts` — typed `fetch` wrappers for `/api/counterfactual`, `/api/incident`, `/api/race`.

## Build & serve
`npm --prefix web run build` outputs to `src/backcast/webapp/static/` (index.html + `assets/`), which
FastAPI serves at `/` and the Lambda ships in its image — one artifact, local and cloud.
