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
  incident_id?: string;
  scenario: string;
  actual_remediation?: string;
  forked_at_hlc?: string | null;
  branches: Branch[];
  best_label: string;
  decision_regret: number;
  lesson: string | null;
  ledger_verified?: boolean;
}

export interface RemediationSpec {
  fixes: boolean;
  relieves: boolean;
  recovery_seconds: number;
  risk: number;
  cost: number;
}

export interface ScenarioInfo {
  key: string;
  true_cause: string;
  description: string;
  remediations: Record<string, RemediationSpec>;
}

export interface AgentResult {
  incident_id: string;
  steps: number;
  tool_calls: string[];
  claimed_action: string | null;
  summary: string;
  beliefs: { statement: string; confidence: number }[];
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

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const getScenarios = () => get<{ scenarios: ScenarioInfo[] }>("/api/scenarios");

export const runCounterfactual = (body: { scenario_key: string; actual_remediation: string }) =>
  post<CounterfactualResult>("/api/counterfactual", body);

export interface SimulateBody {
  true_cause: string;
  description?: string;
  remediations: Record<string, RemediationSpec>;
  actual: string[];
}
export const runSimulate = (body: SimulateBody) => post<CounterfactualResult>("/api/simulate", body);

export const runAgent = (body: { signal: string; scenario_key?: string }) =>
  post<AgentResult>("/api/agent", body);

export const runIncident = () => post<IncidentResult>("/api/incident");
export const runRace = (workers: number) => post<RaceResult>(`/api/race?workers=${workers}`);
