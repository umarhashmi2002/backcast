import { useEffect, useState } from "react";
import * as api from "./api";
import type {
  AgentResult,
  CounterfactualResult,
  RaceResult,
  RemediationSpec,
  ScenarioInfo,
  Snapshot,
} from "./api";

function useRun<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (...args: A) => {
    setLoading(true);
    setError(null);
    try {
      setData(await fn(...args));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  return { data, loading, error, run };
}

// Scores are signed and unbounded (a user-defined incident can produce any range),
// so the domain is derived from the data — always including zero so the axis is
// meaningful — rather than assumed. Bars diverge from the zero line.
type Scale = { zero: number; left: (s: number) => number; width: (s: number) => number; lo: number; hi: number };

function makeScale(scores: number[]): Scale {
  const lo = Math.min(0, ...scores);
  const hi = Math.max(0, ...scores);
  const span = hi - lo || 1;
  const at = (s: number) => ((s - lo) / span) * 100;
  return {
    lo,
    hi,
    zero: at(0),
    left: (s) => (s >= 0 ? at(0) : at(s)),
    width: (s) => Math.max(0.6, (Math.abs(s) / span) * 100),
  };
}

// --------------------------------------------------------------------------- //
// Shared: the branch bar chart (used by both library + custom counterfactuals)
// --------------------------------------------------------------------------- //
// The engine forks *every* remediation, including the one actually taken, so the
// actual branch and its identical fork both come back. Merge them into one row
// (keeping the descriptive fork label and both tags) rather than showing a duplicate.
function dedupeBranches(branches: CounterfactualResult["branches"]) {
  const byKey = new Map<string, CounterfactualResult["branches"][number]>();
  for (const b of branches) {
    const key = [...b.remediations].sort().join("|");
    const seen = byKey.get(key);
    if (!seen) {
      byKey.set(key, { ...b });
      continue;
    }
    seen.is_best = seen.is_best || b.is_best;
    seen.is_actual = seen.is_actual || b.is_actual;
    // Prefer the label that names the remediation over the generic "actual".
    if (seen.label === "actual" && b.label !== "actual") seen.label = b.label;
  }
  return [...byKey.values()].sort((a, b) => b.score - a.score);
}

function BranchBars({ r }: { r: CounterfactualResult }) {
  const branches = dedupeBranches(r.branches);
  const scale = makeScale(branches.map((b) => b.score));
  return (
    <div className="out">
      <div className="pill" style={{ marginBottom: 12 }}>
        scenario: {r.scenario}
        {r.actual_remediation ? ` · actually taken: ${r.actual_remediation}` : ""}
        {r.forked_at_hlc ? ` · forked at HLC ${r.forked_at_hlc.slice(0, 14)}…` : ""}
      </div>
      {branches.map((b) => {
        const color = b.is_best ? "var(--green)" : b.is_actual ? "var(--amber)" : "#4a5578";
        const result = b.recovered ? "fixed" : b.recurred ? "recurs" : "no fix";
        return (
          <div key={b.label}>
            <div className="bar-row">
              <div className="bar-label">
                {b.label.replace("fork:", "")}
                {b.is_best && <span className="tag best">BEST</span>}
                {b.is_actual && <span className="tag actual">ACTUAL</span>}
              </div>
              <div className="bar-track">
                <div className="bar-zero" style={{ left: `${scale.zero}%` }} />
                <div
                  className="bar-fill"
                  style={{ left: `${scale.left(b.score)}%`, width: `${scale.width(b.score)}%`, background: color }}
                />
              </div>
              <div className="bar-score">{b.score.toFixed(2)}</div>
            </div>
            <div className="bar-note">
              {result} · t={b.time_to_recovery_s}s · risk {b.risk} · cost {b.cost}
            </div>
          </div>
        );
      })}
      <div className="bar-axis">
        score axis: {scale.lo.toFixed(2)} — {scale.hi.toFixed(2)} · the vertical rule marks zero; bars left of it
        scored negative
      </div>
      <div className="regret">
        <span className="n">{r.decision_regret.toFixed(2)}</span>
        <span>simulated decision regret (best − actual) — model-estimated, under the deterministic scenario</span>
      </div>
      {r.lesson && (
        <div className="lesson">
          <b>Lesson promoted (simulation-verified) →</b> {r.lesson}
        </div>
      )}
      {r.ledger_verified !== undefined && (
        <div className="kv" style={{ marginTop: 10 }}>
          <b>ledger chain</b>
          <span className={r.ledger_verified ? "ok" : "no"}>
            {r.ledger_verified ? "verified ✓" : "broken"}
          </span>
        </div>
      )}
    </div>
  );
}

// Default the "actually taken" remediation to one that does NOT permanently fix the
// incident — preferring a symptom-reliever like a restart. Defaulting to the optimal
// action makes decision regret 0.00, which hides the entire point of the tool.
function defaultActual(scen: ScenarioInfo | undefined): string {
  if (!scen) return "";
  const entries = Object.entries(scen.remediations);
  const reliever = entries.find(([, r]) => r.relieves && !r.fixes);
  const nonFixer = entries.find(([, r]) => !r.fixes);
  return (reliever ?? nonFixer ?? entries[0])?.[0] ?? "";
}

// Nova Pro sometimes emits its scratchpad as literal <thinking> markup and wraps the
// deliverable in tags of its own. Neither is meant for the reader — strip both, and
// fall back to the raw text if stripping leaves nothing.
function cleanSummary(summary: string): string {
  const cleaned = summary
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, " ")
    .replace(/<\/?[a-z_]+>/gi, " ")
    .replace(/\*\*\*?/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || summary.trim();
}

// --------------------------------------------------------------------------- //
// Tab 1 — Counterfactual Lab (library scenario OR build-your-own)
// --------------------------------------------------------------------------- //
interface CustomRow {
  name: string;
  fixes: boolean;
  relieves: boolean;
  risk: number;
  cost: number;
  time: number;
}
const DEFAULT_ROWS: CustomRow[] = [
  { name: "revert-config", fixes: true, relieves: false, risk: 0.15, cost: 0.8, time: 90 },
  { name: "add-capacity", fixes: false, relieves: true, risk: 0.3, cost: 2.0, time: 120 },
  { name: "page-oncall", fixes: false, relieves: false, risk: 0.05, cost: 0.2, time: 30 },
];

function CounterfactualLab({ scenarios }: { scenarios: ScenarioInfo[] }) {
  const [mode, setMode] = useState<"library" | "custom">("library");
  const [result, setResult] = useState<CounterfactualResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [scenKey, setScenKey] = useState(scenarios[0]?.key ?? "db_pool_exhaustion");
  const scen = scenarios.find((s) => s.key === scenKey);
  const remNames = scen ? Object.keys(scen.remediations) : [];
  const [actual, setActual] = useState(defaultActual(scen));
  useEffect(() => {
    setActual(defaultActual(scenarios.find((s) => s.key === scenKey)));
  }, [scenKey, scenarios]);

  const [trueCause, setTrueCause] = useState("a bad config push disabled request caching");
  const [rows, setRows] = useState<CustomRow[]>(DEFAULT_ROWS);
  const [customActual, setCustomActual] = useState("add-capacity");

  const setRow = (i: number, patch: Partial<CustomRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function run() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      if (mode === "library") {
        setResult(await api.runCounterfactual({ scenario_key: scenKey, actual_remediation: actual }));
      } else {
        const remediations: Record<string, RemediationSpec> = {};
        for (const r of rows) {
          const n = r.name.trim();
          if (n)
            remediations[n] = {
              fixes: r.fixes,
              relieves: r.relieves,
              recovery_seconds: r.time,
              risk: r.risk,
              cost: r.cost,
            };
        }
        const names = Object.keys(remediations);
        if (!trueCause.trim() || names.length === 0) {
          setError("Enter a true cause and at least one remediation.");
          return;
        }
        const chosen = remediations[customActual] ? customActual : names[0];
        setResult(await api.runSimulate({ true_cause: trueCause, remediations, actual: [chosen] }));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel">
      <div className="head">
        <h2>Counterfactual replay</h2>
        <span className="pill">the originality pivot</span>
      </div>
      <div className="sub">
        Pick a real incident (or <b>build your own</b>), choose which remediation was actually taken,
        and Backcast forks every alternative on a <b>deterministic</b> model — then quantifies how much
        better the best call would have been. The LLM never decides which action worked.
      </div>

      <div className="seg">
        <button className={mode === "library" ? "on" : ""} onClick={() => setMode("library")}>
          Library scenario
        </button>
        <button className={mode === "custom" ? "on" : ""} onClick={() => setMode("custom")}>
          + Build your own
        </button>
      </div>

      {mode === "library" ? (
        <div className="form">
          <label className="field">
            <span>Incident scenario</span>
            <select value={scenKey} onChange={(e) => setScenKey(e.target.value)}>
              {scenarios.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.key} — {s.description}
                </option>
              ))}
            </select>
          </label>
          {scen && (
            <div className="chips">
              {Object.entries(scen.remediations).map(([n, e]) => (
                <span key={n} className="chip">
                  {n}
                  {e.fixes && <i className="fx"> fixes</i>}
                  {e.relieves && <i className="rl"> relieves</i>}
                </span>
              ))}
            </div>
          )}
          <label className="field">
            <span>Remediation actually taken</span>
            <select value={actual} onChange={(e) => setActual(e.target.value)}>
              {remNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : (
        <div className="form">
          <label className="field">
            <span>Hidden true cause</span>
            <input value={trueCause} onChange={(e) => setTrueCause(e.target.value)} placeholder="what actually broke" />
          </label>
          <div className="remhead">
            <span>remediation</span>
            <span>fixes</span>
            <span>relieves</span>
            <span>risk</span>
            <span>cost</span>
            <span>time s</span>
            <span />
          </div>
          {rows.map((r, i) => (
            <div className="remrow" key={i}>
              <input value={r.name} onChange={(e) => setRow(i, { name: e.target.value })} placeholder="name" />
              <input type="checkbox" checked={r.fixes} onChange={(e) => setRow(i, { fixes: e.target.checked, relieves: e.target.checked ? false : r.relieves })} />
              <input type="checkbox" checked={r.relieves} onChange={(e) => setRow(i, { relieves: e.target.checked, fixes: e.target.checked ? false : r.fixes })} />
              <input type="number" step="0.05" value={r.risk} onChange={(e) => setRow(i, { risk: parseFloat(e.target.value) || 0 })} />
              <input type="number" step="0.1" value={r.cost} onChange={(e) => setRow(i, { cost: parseFloat(e.target.value) || 0 })} />
              <input type="number" step="10" value={r.time} onChange={(e) => setRow(i, { time: parseFloat(e.target.value) || 0 })} />
              <button className="x" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} title="remove">
                ×
              </button>
            </div>
          ))}
          <div className="form2">
            <button className="ghost" onClick={() => setRows((rs) => [...rs, { name: "", fixes: false, relieves: false, risk: 0.1, cost: 1, time: 60 }])}>
              + add remediation
            </button>
            <label className="field inline">
              <span>actually taken</span>
              <select value={customActual} onChange={(e) => setCustomActual(e.target.value)}>
                {rows.filter((r) => r.name.trim()).map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      )}

      <div className="runrow" style={{ marginTop: 14 }}>
        <button onClick={run} disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" /> simulating…
            </>
          ) : (
            "Run counterfactual ▸"
          )}
        </button>
      </div>

      {error ? <div className="out err">error: {error}</div> : result && <BranchBars r={result} />}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Tab 2 — Agent Console (live Amazon Nova Pro turn)
// --------------------------------------------------------------------------- //
const EXAMPLE_SIGNAL =
  "payments-api returning 5xx; DB connection pool saturated right after deploy d-8842. Error rate 12%, latency up.";

function AgentConsole({ scenarios }: { scenarios: ScenarioInfo[] }) {
  const [signal, setSignal] = useState(EXAMPLE_SIGNAL);
  const [scenKey, setScenKey] = useState(scenarios[0]?.key ?? "");
  const { data, loading, error, run } = useRun(api.runAgent);

  return (
    <section className="panel">
      <div className="head">
        <h2>Incident Commander — live agent</h2>
        <span className="pill">Amazon Nova Pro · ~20s</span>
      </div>
      <div className="sub">
        Type any alert and watch the real agent reason in a Bedrock tool-use loop against CockroachDB:
        recall similar incidents → record evidence → revise beliefs → claim a <b>fenced action lease</b>{" "}
        → resolve. This is a live model call, not a script.
      </div>

      <div className="form">
        <label className="field">
          <span>Alert signal</span>
          <textarea rows={3} value={signal} onChange={(e) => setSignal(e.target.value)} />
        </label>
        <label className="field">
          <span>Seed scenario (optional — makes it replay-eligible)</span>
          <select value={scenKey} onChange={(e) => setScenKey(e.target.value)}>
            <option value="">— none (free-form) —</option>
            {scenarios.map((s) => (
              <option key={s.key} value={s.key}>
                {s.key}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="runrow" style={{ marginTop: 14 }}>
        <button onClick={() => run({ signal, scenario_key: scenKey || undefined })} disabled={loading || !signal.trim()}>
          {loading ? (
            <>
              <span className="spinner" /> agent running…
            </>
          ) : (
            "Run Incident Commander ▸"
          )}
        </button>
      </div>

      {error ? <div className="out err">error: {error}</div> : data && <AgentTrace r={data} />}
    </section>
  );
}

function AgentTrace({ r }: { r: AgentResult }) {
  return (
    <div className="out">
      <div className="trace">
        {r.tool_calls.map((t, i) => (
          <div className={`step${t === "propose_remediation" ? " act" : ""}`} key={i}>
            <span className="dot" />
            {t}
          </div>
        ))}
      </div>
      <div className="kv" style={{ marginTop: 12 }}>
        <b>steps</b>
        <span>{r.steps}</span>
        <b>claimed action</b>
        <span className={r.claimed_action ? "ok" : ""}>{r.claimed_action ?? "— (proposed none)"}</span>
        <b>ledger chain</b>
        <span className={r.ledger_verified ? "ok" : "no"}>{r.ledger_verified ? "verified ✓" : "broken"}</span>
      </div>
      {r.beliefs.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="pill" style={{ marginBottom: 8 }}>beliefs after the turn</div>
          {r.beliefs.map((b, i) => (
            <div className="belief" key={i}>
              <span className="lab" style={{ width: 230, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {b.statement}
              </span>
              <span className="meter">
                <i style={{ width: `${Math.round(b.confidence * 100)}%` }} />
              </span>
              <b className="v">{Math.round(b.confidence * 100)}%</b>
            </div>
          ))}
        </div>
      )}
      <div className="lesson" style={{ borderColor: "var(--purple)", marginTop: 12 }}>
        <b>agent summary →</b> {cleanSummary(r.summary)}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Tab 3 — Time Travel (temporal no-leak + belief revision)
// --------------------------------------------------------------------------- //
function Meter({ label, v }: { label: string; v: number }) {
  return (
    <div className="belief">
      <span className="lab">{label}</span>
      <span className="meter">
        <i style={{ width: `${Math.round(v * 100)}%` }} />
      </span>
      <b className="v">{Math.round(v * 100)}%</b>
    </div>
  );
}
function Column({ title, snap }: { title: string; snap: Snapshot }) {
  return (
    <div className="t">
      <h3>{title}</h3>
      {snap.evidence.map((e, i) => (
        <div className="ev" key={i}>
          • <b>{e.kind}</b> {e.content}
        </div>
      ))}
      <div style={{ marginTop: 8 }}>
        <Meter label="surge" v={snap.surge} />
        <Meter label="deploy" v={snap.deploy} />
      </div>
    </div>
  );
}
function TimeTravel() {
  const { data, loading, error, run } = useRun(api.runIncident);
  return (
    <section className="panel">
      <div className="head">
        <h2>Time travel — reconstruct the past</h2>
      </div>
      <div className="sub">
        Replays a scripted incident against the live engine: first the agent blames a traffic surge,
        then a deploy correlation flips it. Reconstruct the <b>earlier</b> belief state with{" "}
        <code>AS OF SYSTEM TIME</code> at the captured HLC — and prove it <b>cannot</b> see evidence
        recorded later. The no-leak guarantee is enforced by MVCC, not app code.
      </div>
      <div className="runrow" style={{ marginTop: 12 }}>
        <button onClick={() => run()} disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" /> reconstructing…
            </>
          ) : (
            "Replay & reconstruct ▸"
          )}
        </button>
      </div>
      {error ? (
        <div className="out err">error: {error}</div>
      ) : (
        data && (
          <div className="out">
            <div className="tl">
              <Column title="earlier HLC — reconstructed (AS OF SYSTEM TIME)" snap={data.at_t1} />
              <Column title="now — everything known" snap={data.now} />
            </div>
            <div className="kv" style={{ marginTop: 12 }}>
              <b>no-leak guarantee</b>
              <span className={data.no_leak ? "ok" : "no"}>
                {data.no_leak ? "deploy evidence hidden from the earlier view ✓" : "LEAK"}
              </span>
              <b>belief revision</b>
              <span>
                {data.deploy_belief_history.map((h) => `${Math.round(h.confidence * 100)}%`).join(" → ")} on
                “deploy connection leak”
              </span>
              <b>ledger chain</b>
              <span className={data.ledger_verified ? "ok" : "no"}>
                {data.ledger_verified ? "verified ✓" : "broken"}
              </span>
            </div>
          </div>
        )
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Tab 4 — Fencing (concurrency + crash-safety)
// --------------------------------------------------------------------------- //
function Fencing() {
  const [workers, setWorkers] = useState(20);
  const { data, loading, error, run } = useRun(api.runRace);
  return (
    <section className="panel">
      <div className="head">
        <h2>Safe autonomy — one action, once</h2>
      </div>
      <div className="sub">
        {workers} workers race to remediate; exactly one wins the lease. The winner crashes; a standby
        takes over (fencing generation bumps); the revived stale worker is <b>fenced out</b>, and the
        external effect runs exactly once.
      </div>
      <div className="form2" style={{ marginTop: 12 }}>
        <label className="field inline">
          <span>workers</span>
          <input type="range" min={2} max={50} value={workers} onChange={(e) => setWorkers(parseInt(e.target.value))} />
          <b style={{ width: 28, textAlign: "right" }}>{workers}</b>
        </label>
        <button onClick={() => run(workers)} disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" /> racing…
            </>
          ) : (
            "Run the race ▸"
          )}
        </button>
      </div>
      {error ? (
        <div className="out err">error: {error}</div>
      ) : (
        data && <Race r={data} />
      )}
    </section>
  );
}
function Race({ r }: { r: RaceResult }) {
  return (
    <div className="out">
      <div className="kv">
        <b>workers racing</b>
        <span>{r.workers}</span>
        <b>won the lease</b>
        <span className={r.winners === 1 ? "ok" : "no"}>{r.winners} (must be exactly 1)</span>
        <b>crash → takeover</b>
        <span>generation {r.crash_takeover_generation} (bumped on takeover)</span>
        <b>revived stale worker</b>
        <span className={r.revived_stale_worker_accepted ? "no" : "ok"}>
          {r.revived_stale_worker_accepted ? "accepted — BAD" : "fenced out ✓"}
        </span>
        <b>external effect</b>
        <span className={r.external_effect_executions === 1 ? "ok" : "no"}>
          executed exactly {r.external_effect_executions}× across crash + revival
        </span>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Shell
// --------------------------------------------------------------------------- //
type TabId = "cf" | "agent" | "time" | "fence";
const TABS: { id: TabId; label: string }[] = [
  { id: "cf", label: "Counterfactual Lab" },
  { id: "agent", label: "Agent Console" },
  { id: "time", label: "Time Travel" },
  { id: "fence", label: "Fencing" },
];

export default function App() {
  const [tab, setTab] = useState<TabId>("cf");
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  useEffect(() => {
    api.getScenarios().then((d) => setScenarios(d.scenarios)).catch(() => setScenarios([]));
  }, []);

  return (
    <div className="wrap">
      <header>
        <span className="logo">🔁</span>
        <span className="brand">Backcast</span>
        <span className="badges">CockroachDB × AWS · agentic memory</span>
      </header>

      <section className="hero">
        <span className="pill">temporal decision laboratory for on-call</span>
        <h1>
          Rewind an incident. <span className="g">Fork the decision.</span>
          <br />
          Compare what would have happened.
        </h1>
        <p>
          Every tab drives the <b>real</b> engine against a live CockroachDB — define your own incident,
          run a live agent, reconstruct the past with <code>AS OF SYSTEM TIME</code>, and govern
          autonomous actions with fencing tokens. The counterfactual lab and agent console take your
          input; time travel and the lease race replay a fixed scripted incident against the live
          engine. Outcomes are always computed, never canned.
        </p>
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "cf" && <CounterfactualLab scenarios={scenarios} />}
      {tab === "agent" && <AgentConsole scenarios={scenarios} />}
      {tab === "time" && <TimeTravel />}
      {tab === "fence" && <Fencing />}

      <footer>
        Backcast — built for the CockroachDB × AWS Agentic Memory Hackathon ·{" "}
        <a href="https://github.com/umarhashmi2002/backcast">source</a> ·{" "}
        <a href="/docs">API</a>
      </footer>
    </div>
  );
}
