# Demo — shot-by-shot recording script (< 3 min)

A turn-key script for the hackathon video. Total runtime ≈ **2:50**. Every shot lists the
**timestamp**, what's **on screen** (what to click), the **voiceover** (read it verbatim), and the
**number to point at** (cursor/zoom). Nothing here is faked — every panel hits the live deployment.

- **Live demo URL:** https://2beyv24r657kdthgabtbvg74n40pyolu.lambda-url.us-east-1.on.aws/
- **Fallback (terminal):** `./test-endpoints.sh` exercises the same live flow end-to-end if you'd rather screen-record a terminal.

## Prep checklist (before you hit record)

**The five frames that must be legible.** These carry the whole judging case visually — more than any
amount of code on screen. If a viewer can read only five things, make it these:

| # | Frame | Answers |
|---|-------|---------|
| 1 | `decision regret: 1.24` | What does Backcast *do*? |
| 2 | `Lesson promoted` strip | Does the memory actually learn? |
| 3 | `11% → 87%` belief revision | Is the memory genuinely temporal? |
| 4 | `deploy evidence hidden ✓` | …and is the no-leak real, not filtered? |
| 5 | `revived stale worker: fenced out ✓` | Did they take autonomous-agent safety seriously? |

**Do not add** a CDK/CloudWatch/KMS/SQL-console/schema tour. Those belong in the repo and the written
description; the video's job is to make a judge want to open the repo afterwards.


- [ ] Open the live URL in a clean browser window (no extensions bar, 1440×900+, ~125% zoom for legibility).
- [ ] Warm the Lambdas: click **Run counterfactual** once and **Run Incident Commander** once, then reload (avoids cold-start pauses on camera).
- [ ] Have a second tab on the GitHub repo and one on `…/docs` (Swagger) for the closing shot.
- [ ] Mic check; screen recorder at 60fps; cursor highlighting on.
- [ ] Close Slack/mail; silence notifications.

### Pacing — measured latencies on the deployed stack

The cluster now sits in `us-east-1` alongside the Lambdas, so the waits this script was originally
written around are gone. Current warm numbers:

| Action | Warm latency |
|---|---|
| `Run counterfactual` | **~1.1s** |
| `Replay & reconstruct` (time travel) | ~1.1s |
| `Run the race` (20 workers) | ~3.4s (1.3s of it a deliberate lease-expiry wait) |
| `Run Incident Commander` | **~15–25s** — a live Bedrock turn, and the only real wait |
| Build-your-own `Simulate` | ~0.7s |

So there is **no dead air to cover on the counterfactual** — the result lands almost immediately.
Don't pad the narration for it; let the number appear, then pause 2–3 seconds on `1.24` so it
registers. The one place you *do* need narration to cover latency is the agent turn: keep talking
through it ("recall similar incidents by vector search, record evidence, revise beliefs…") because
Bedrock takes 15–25s and varies run to run.

---

## Act 1 — The hook (0:00 – 0:22)

**0:00 · ON SCREEN:** The landing hero ("Rewind an incident. Fork the decision.").
**VOICEOVER:** "An on-call engineer restarts a service, the alert clears, incident resolved. But *was*
it? Or did the real bug just go quiet — and it'll page you again at 3 AM?"
**POINT AT:** the headline, then the tab bar.

**0:10 · ON SCREEN:** Hover the four tabs — *Counterfactual Lab · Agent Console · Time Travel · Fencing*.
**VOICEOVER:** "This is Backcast — an incident-response agent that can rewind what it knew, replay
what it could have done, and learn from the better decision. Its memory lives in CockroachDB, and the
application runs serverless on AWS. Everything you're about to see runs live against one database."
**NOTE:** "temporal decision laboratory" is good written positioning but abstract when *heard* — keep
it for the Devpost description, not the voiceover.

---

## Act 2 — Counterfactual replay, the originality (0:22 – 1:15)

**0:22 · ON SCREEN:** *Counterfactual Lab* tab. Scenario dropdown = `db_pool_exhaustion`;
"Remediation actually taken" = `restart-service`. Click **Run counterfactual**.
**VOICEOVER:** "Here's our flagship incident scenario: a deploy shrank the DB connection pool. The
on-call engineer restarted
the service. Backcast rewinds to that moment, forks *every* alternative, and scores each on a
deterministic model — the language model never decides what worked."
**POINT AT:** the bar chart animating in.

**0:38 · ON SCREEN:** The ranked bars; the big **decision regret** number (~1.24).
**VOICEOVER:** "The restart only *relieved* the symptom — it recurs. A deploy rollback was the
permanent fix. The gap between them is **decision regret**: one-point-two-four."
**THEN STOP TALKING for about two seconds** while the cursor moves ACTUAL → BEST → `1.24`. This is
the frame judges are most likely to remember; do not narrate over it. Resume with: *"And the winning
lesson gets written back into the agent's memory."*
**POINT AT:** the amber ACTUAL bar, the green BEST bar, then the orange regret number, then the
"Lesson promoted to memory" strip.

**0:58 · ON SCREEN:** Click **+ Build your own**. The custom form appears (pre-filled: "a bad config
push disabled request caching" with three remediations). Change one number (e.g. bump `add-capacity`
cost to 3), then click **Run counterfactual**.
**VOICEOVER:** "And this isn't three canned demos — define *your own* incident. Your true cause, your
remediations, your risk and cost. It runs the same deterministic engine live."
**POINT AT:** the true-cause field, a remediation row's checkboxes, then the new regret number.

---

## Act 3 — The live agent (1:15 – 1:55)

**1:15 · ON SCREEN:** *Agent Console* tab. The alert textarea is pre-filled ("payments-api 5xx… after
deploy d-8842"). Click **Run Incident Commander**.
**VOICEOVER:** "Now the agent itself. Type any alert. This is a real Amazon Nova Pro tool-use loop
against CockroachDB — not a script."
**POINT AT:** the textarea, then the spinner ("agent running…").

> **This is the one real wait in the video — 15–25s of live Bedrock, and it varies run to run.**
> Do **not** click twice and do **not** stop talking. Fill it deliberately:
>
> *"While Nova reasons, the agent can recall similar incidents from vector memory, add new
> observations, revise its hypotheses, and coordinate the proposed action through CockroachDB."*
>
> Then, as the trace lands: *"And here is the actual tool trace."* A 20-second call narrated this way
> reads as computation; the same 20 seconds in silence reads as a hang. Record several takes and keep
> the best genuine run — that is still an authentic live demonstration, not a fabricated one.

**1:28 · ON SCREEN:** The tool trace fills in (recall → observe → assess → **propose_remediation** →
resolve); the beliefs meters; the claimed action.
**VOICEOVER:** "Watch it work: recall similar incidents by vector search, record evidence, revise its
beliefs, and — critically — claim a **fenced action lease** before any remediation can become the
canonical action. Every step is written to a hash-chained ledger."
**POINT AT:** the orange `propose_remediation` step, then the "claimed action" row, then
"ledger chain — verified ✓".

---

## Act 4 — The technical proofs (1:55 – 2:32)

**1:55 · ON SCREEN:** *Time Travel* tab. Click **Reconstruct 03:14**. Two columns appear.
**VOICEOVER:** "Two guarantees that need one temporal database. First: what did the agent believe at
3:14? We reconstruct it with CockroachDB's `AS OF SYSTEM TIME` —"
**POINT AT:** the left "03:14" column.

**2:08 · ON SCREEN:** The "no-leak" row (green ✓) and the belief flip (11% → 87%).
**VOICEOVER:** "— and the deploy evidence we learned *later* is invisible in that past view. No
hindsight leak, enforced by the database, not by our code. The belief flips from eleven to
eighty-seven percent as evidence arrives."
**POINT AT:** "deploy evidence hidden ✓", then the "11% → 87%" belief revision.

**2:20 · ON SCREEN:** *Fencing* tab. Slider at 20. Click **Run the race**.
**VOICEOVER:** "Second: safe autonomy. Twenty workers race for one action lease — exactly one wins.
The winner crashes, a standby takes over, and when the original worker returns, its stale fencing
token prevents it from finalizing. Backcast guarantees one current logical owner without pretending an
external side effect can be part of the same database transaction."
**POINT AT:** "won the lease: 1", "revived stale worker: fenced out ✓", "canonical action owner: 1".
**DO NOT SAY** "the external effect runs exactly once" — this build never executes a real
remediation, and the counter on screen is an idempotency-guarded write inside the same cluster.
Claiming exactly-once external execution is the one line a systems-minded judge would catch, and it
would undercut the claims that *are* true.

---

## Close (2:32 – 2:50)

**2:32 · ON SCREEN:** Scroll to the hero / or cut to the README architecture diagram.
**VOICEOVER:** "Counterfactual replay, temporal no-leak recall, fencing-safe actions, and a
hash-chained audit ledger with KMS-signed checkpoints — CockroachDB lets us keep all of that in one
transactional, time-travelling system of record. And it's deployed on AWS with Bedrock, Lambda,
API Gateway, and KMS."
**POINT AT:** the "one temporal system of record" box in the architecture diagram.

**2:44 · ON SCREEN:** GitHub repo tab (or the `…/docs` Swagger page).
**VOICEOVER:** "It's open source, deployed, and tested end to end. Backcast — so on-call finally
learns from the past instead of repeating it."
**POINT AT:** the repo URL / the live demo URL.

---

## If you narrate live instead of scripting voiceover

Same order, but let the numbers speak: linger ~2 s on the **regret number**, the **fenced-out ✓**, and
the **no-leak ✓**. Those three moments are the whole pitch.

## Timing budget

| Act | Window | Beat |
|-----|--------|------|
| 1 | 0:00–0:22 | Hook + what it is |
| 2 | 0:22–1:15 | Counterfactual regret + **build your own** |
| 3 | 1:15–1:55 | Live Nova Pro agent + fenced lease |
| 4 | 1:55–2:32 | No-leak time travel + fencing race |
| Close | 2:32–2:50 | One temporal DB thesis + CTA |

Keep it under 3:00. If you run long, trim Act 4's fencing to a 6-second glance — the regret number and
the live agent are the two moments that win.

## Map to the judging criteria

| Criterion | Shown in |
|---|---|
| Agentic Memory Design | Acts 2–4 (evidence, beliefs, actions, counterfactual branches — all in CockroachDB) |
| Technical Implementation | `AS OF SYSTEM TIME`, C-SPANN, fencing, hash chain — used correctly; typed + tested + CI |
| Real-World Impact | Act 2 (compounding *verified* knowledge on a universal on-call problem) |
| Production Readiness | Act 3–4 + fenced/idempotent actions, least-privilege IAM, tamper-evident audit |
| Creativity & Originality | Act 2 (transactionally-consistent counterfactual replay + decision regret + build-your-own) |
