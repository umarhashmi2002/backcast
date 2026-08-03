// Typed client for the Backcast FastAPI backend.

export interface Branch {
  label: string;
  remediations: string[];
  score: number;
  recovered: boolean;
  recurred: boolean;
  time_to_recovery_s: number;
  risk: number;
  cost: number;
  unnecessary_actions: number;
  is_actual: boolean;
  is_best: boolean;
}

export interface CounterfactualResult {
  incident_id: string;
  scenario: string;
  forked_at_hlc: string;
  branches: Branch[];
  best_label: string;
  decision_regret: number;
  lesson: string | null;
  ledger_verified: boolean;
}

export interface EvidenceItem {
  kind: string;
  content: string;
}
export interface Snapshot {
  evidence: EvidenceItem[];
  surge: number;
  deploy: number;
}
export interface IncidentResult {
  incident_id: string;
  t1_hlc: string;
  surge_hypothesis: string;
  deploy_hypothesis: string;
  at_t1: Snapshot;
  now: Snapshot;
  no_leak: boolean;
  deploy_belief_history: { confidence: number; current: boolean }[];
  ledger_verified: boolean;
}

export interface RaceResult {
  workers: number;
  winners: number;
  crash_takeover_generation: number;
  taker_completed: boolean;
  revived_stale_worker_accepted: boolean;
  external_effect_executions: number;
}

async function post<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const runCounterfactual = () => post<CounterfactualResult>("/api/counterfactual");
export const runIncident = () => post<IncidentResult>("/api/incident");
export const runRace = () => post<RaceResult>("/api/race?workers=20");
