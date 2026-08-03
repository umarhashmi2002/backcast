import { useState } from "react";
import * as api from "./api";
import type { CounterfactualResult, IncidentResult, RaceResult, Snapshot } from "./api";

function useRun<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fn());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  return { data, loading, error, run };
}

const pct = (s: number) => Math.max(2, Math.min(100, ((s + 0.5) / 1.5) * 100));

function Hero() {
  return (
    <section className="hero">
      <span className="pill">temporal decision laboratory for on-call</span>
      <h1>
        Rewind an incident. <span className="g">Fork the decision.</span>
        <br />
        Compare what would have happened.
      </h1>
      <p>
        Every panel runs the <b>real</b> engine against a live CockroachDB — reconstructing the past
        with <code>AS OF SYSTEM TIME</code>, forking counterfactuals, and governing autonomous actions
        with fencing tokens. Nothing is faked.
      </p>
    </section>
  );
}

function Panel(props: {
  n: string;
  title: string;
  tag?: string;
  sub: string;
  loading: boolean;
  cta: string;
  onRun: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="head">
        <span className="n">{props.n}</span>
        <h2>{props.title}</h2>
        {props.tag && <span className="pill">{props.tag}</span>}
      </div>
      <div className="sub">{props.sub}</div>
      <div className="runrow">
        <button onClick={props.onRun} disabled={props.loading}>
          {props.loading ? <><span className="spinner" /> running…</> : `${props.cta} ▸`}
        </button>
      </div>
      {props.children}
    </section>
  );
}

function BranchBars({ r }: { r: CounterfactualResult }) {
  return (
    <div className="out">
      <div className="pill" style={{ marginBottom: 12 }}>
        scenario: {r.scenario} · forked at HLC {r.forked_at_hlc.slice(0, 14)}…
      </div>
      {r.branches.map((b) => {
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
                <div className="bar-fill" style={{ width: `${pct(b.score)}%`, background: color }} />
              </div>
              <div className="bar-score">{b.score.toFixed(2)}</div>
            </div>
            <div className="bar-note">
              {result} · t={b.time_to_recovery_s}s · risk {b.risk}
            </div>
          </div>
        );
      })}
      <div className="regret">
        <span className="n">{r.decision_regret.toFixed(2)}</span>
        <span>decision regret (best − actual) — how much better the optimal call was</span>
      </div>
      {r.lesson && (
        <div className="lesson">
          <b>Lesson promoted to memory →</b> {r.lesson}
        </div>
      )}
      <div className="kv" style={{ marginTop: 10 }}>
        <b>ledger chain</b>
        <span className={r.ledger_verified ? "ok" : "no"}>
          {r.ledger_verified ? "verified ✓" : "broken"}
        </span>
      </div>
    </div>
  );
}

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

function Timeline({ r }: { r: IncidentResult }) {
  return (
    <div className="out">
      <div className="tl">
        <Column title="03:14 — reconstructed (AS OF SYSTEM TIME)" snap={r.at_t1} />
        <Column title="now — everything known" snap={r.now} />
      </div>
      <div className="kv" style={{ marginTop: 12 }}>
        <b>no-leak guarantee</b>
        <span className={r.no_leak ? "ok" : "no"}>
          {r.no_leak ? "deploy evidence hidden from the 03:14 view ✓" : "LEAK"}
        </span>
        <b>belief revision</b>
        <span>
          {r.deploy_belief_history.map((h) => `${Math.round(h.confidence * 100)}%`).join(" → ")} on
          “deploy connection leak”
        </span>
        <b>ledger chain</b>
        <span className={r.ledger_verified ? "ok" : "no"}>
          {r.ledger_verified ? "verified ✓" : "broken"}
        </span>
      </div>
    </div>
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

export default function App() {
  const cf = useRun(api.runCounterfactual);
  const inc = useRun(api.runIncident);
  const race = useRun(api.runRace);
  return (
    <div className="wrap">
      <header>
        <span className="logo">🔁</span>
        <span className="brand">Backcast</span>
        <span className="badges">CockroachDB × AWS · agentic memory</span>
      </header>

      <Hero />

      <Panel
        n="①"
        title="Counterfactual replay"
        tag="the pivot"
        sub="An engineer restarts a service and the alert clears. Was it the right call? Backcast forks the incident and simulates every alternative on a deterministic model."
        cta="Run counterfactual"
        loading={cf.loading}
        onRun={cf.run}
      >
        {cf.error ? <div className="out err">error: {cf.error}</div> : cf.data && <BranchBars r={cf.data} />}
      </Panel>

      <Panel
        n="②"
        title="Temporal reconstruction & belief revision"
        sub="At 03:14 the agent blamed a traffic surge; at 03:17 a deploy correlation flipped it. Reconstruct the 03:14 view — and prove it can't see evidence learned later."
        cta="Reconstruct the past"
        loading={inc.loading}
        onRun={inc.run}
      >
        {inc.error ? <div className="out err">error: {inc.error}</div> : inc.data && <Timeline r={inc.data} />}
      </Panel>

      <Panel
        n="③"
        title="Safe autonomy — one action, once"
        sub="Duplicate workers race to remediate; exactly one wins the lease. The winner crashes; a standby takes over; the revived stale worker is fenced out."
        cta="Race 20 workers"
        loading={race.loading}
        onRun={race.run}
      >
        {race.error ? <div className="out err">error: {race.error}</div> : race.data && <Race r={race.data} />}
      </Panel>

      <footer>
        Backcast — built for the CockroachDB × AWS Agentic Memory Hackathon ·{" "}
        <a href="https://github.com/umarhashmi2002/backcast">source</a>
      </footer>
    </div>
  );
}
