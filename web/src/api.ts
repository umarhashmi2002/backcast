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
  forked_state?: ForkedState | null;
}

/** What the agent knew at the fork HLC, reconstructed via AS OF SYSTEM TIME. */
export interface ForkedState {
  as_of_hlc: string;
  evidence: string[];
  beliefs: { confidence: number; rationale: string | null }[];
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
  canonical_action_owners: number;
  /** Idempotency-guarded write standing in for the remediation; not an external effect. */
  simulated_effect_applications: number;
}

/** Turn a failed response into the backend's own message, not just its status code. */
async function failure(res: Response): Promise<Error> {
  let detail = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
    else if (body.detail != null) detail = JSON.stringify(body.detail);
  } catch {
    // Non-JSON body (a proxy error page, a truncated response) — status only.
  }
  return new Error(detail || `request failed (HTTP ${res.status})`);
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await failure(res);
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
