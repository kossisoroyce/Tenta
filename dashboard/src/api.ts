// Typed client for the Tenta runtime + control-plane API.

export type Decision = "allow" | "review" | "block";
export type Severity = "critical" | "warn" | "watch" | "stable";
export type Stage = "champion" | "shadow" | "candidate" | "fallback" | "archived";
export type DatabaseBackend = "sqlite" | "postgres";
export type HealingStatus =
  | "proposed"
  | "running"
  | "completed"
  | "rejected"
  | "rolled_back";

export interface ActorPayload {
  actor: string;
  role?: string;
  source?: string;
  request_id?: string;
  reason?: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...(options ?? {}) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      (payload as { message?: string }).message || response.statusText || "Request failed";
    throw new Error(message);
  }
  return payload as T;
}

function post<T>(path: string, body?: object): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

/* --------------------------- Health / decisions ---------------------------- */

export type AuthRole = "viewer" | "operator" | "analyst" | "detector" | "model-risk" | "admin";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: AuthRole;
  source?: string;
  created_at?: string | null;
  last_login_at?: string | null;
}

export interface AuthStatus {
  enabled: boolean;
  users_configured: boolean;
  needs_bootstrap: boolean;
  cookie_name: string;
  password_hasher: string;
  storage: Record<string, unknown>;
}

export interface AuthApiKey {
  id: string;
  key_prefix: string;
  label: string;
  role: AuthRole;
  created_at?: string | null;
  expires_at?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export interface HealthResponse {
  status: string;
  runtime?: { status?: string; cached_decisions?: number };
  workload?: WorkloadSummary;
  model?: {
    status?: string;
    model_id?: string;
    model_version?: string;
    backend?: string;
    stage?: string;
    artifact_hash?: string | null;
    signature?: string;
  };
  policy?: { status?: string; version?: string; review_threshold?: number; block_threshold?: number };
  audit?: { status?: string; sinks?: Array<{ sink?: string; events_written?: number }> };
  storage?: { status?: string; backend?: string; path?: string };
}

export interface DecisionRecord {
  id?: string;
  transaction_id: string;
  decision_request_id?: string;
  workload_id?: string;
  decision: Decision | string;
  score: number;
  model_id?: string;
  model_version?: string;
  policy_version?: string;
  reason_codes?: string[];
  latency_ms?: number;
  event_time?: string;
  created_at?: string;
  degraded_mode?: boolean;
}

export interface ScoreRequest {
  decision_request_id: string;
  workload_id?: string;
  subject_id: string;
  context_id: string;
  value: number;
  currency: string;
  channel: string;
  event_time: string;
  features: {
    entity_risk: number;
    velocity_10m: number;
    subject_age_days: number;
    prior_adverse_events: number;
    high_risk_segment: boolean;
  };
}

export interface ScoreResponse extends DecisionRecord {}

export interface OverviewResponse {
  health: HealthResponse;
  summary: {
    open_drift_alerts: number;
    healing_pending: number;
    champion: string;
    champion_version: string;
    shadow: string | null;
    pending_labels: number;
  };
  distribution: {
    allow: number;
    review: number;
    block: number;
    total: number;
    block_rate: number;
    review_rate: number;
  };
  latency: { p50: number; p95: number; p99: number; samples: number };
  recent: DecisionRecord[];
}

/* --------------------------------- Models ---------------------------------- */

export interface ModelMetrics {
  auc: number;
  pr_auc: number;
  fpr: number;
  recall: number;
  precision: number;
  p99_latency_ms: number;
}

export interface ServingEndpoint {
  model_id: string;
  model_version: string;
  stage: Stage;
  status: "serving" | "registered_not_serving";
  url: string | null;
  endpoint_url: string | null;
  method: "POST";
  content_type: string;
  contract: string;
  serving_mode: string;
  workload_id: string;
  health_url: string;
  workload_url: string;
  decision_lookup_url: string;
  promotion_url: string;
  notes: string;
}

export interface ModelRecord {
  model_id: string;
  version: string;
  backend: string;
  stage: Stage;
  artifact_hash: string | null;
  signature: string;
  traffic_pct: number;
  metrics: ModelMetrics | null;
  trained_on: string;
  promoted_at: string | null;
  created_at: string;
  notes: string;
  serving_endpoint?: ServingEndpoint;
}

export interface Artifact {
  artifact_id: string;
  model_id: string;
  version: string;
  backend: string;
  artifact_hash: string;
  signature: string;
  size_mb: number;
  trained_on: string;
  metrics: ModelMetrics;
}

export interface ModelsResponse {
  champion: string;
  champion_version: string;
  shadow: string | null;
  shadow_divergence: ShadowDivergence | null;
  counts: { total: number; candidate: number; shadow: number; archived: number };
  models: ModelRecord[];
  available_artifacts: Artifact[];
  serving_endpoint: ServingEndpoint;
}

export interface ShadowDivergence {
  champion: string;
  shadow: string;
  agreement: number;
  sample_size: number;
  segments: Array<{
    segment: string;
    sample_size: number;
    agreement: number;
    disagreements: number;
    champion_decision: string;
    shadow_decision: string;
    outcome: string;
  }>;
}

/* --------------------------------- Healing --------------------------------- */

export interface HealingAction {
  id: string;
  title: string;
  type: string;
  risk: "low" | "medium" | "high";
  status: HealingStatus;
  proposed_by: string;
  trigger: string;
  rationale: string;
  policy_gate: string;
  estimated_impact: Record<string, string>;
  linked_drift: string | null;
  proposed_at: string;
  approver: string | null;
  decided_at: string | null;
  outcome: { status: string; note?: string; [k: string]: unknown } | null;
}

export interface HealingResponse {
  actions: HealingAction[];
  counts: Record<string, number>;
  pending_approval: number;
}

/* ---------------------------------- Drift ---------------------------------- */

export interface DriftMonitor {
  id: string;
  segment: string;
  feature: string;
  detector: string;
  statistic: number;
  threshold: number;
  severity: Severity;
  confidence: number;
  baseline_window: string;
  current_window: string;
  population: number;
  recommended_action: string;
  status: "active" | "acknowledged" | "escalated";
  detected_at: string;
  linked_action: string | null;
  decided_by?: string;
}

export interface DriftResponse {
  monitors: DriftMonitor[];
  counts: Record<string, number>;
  open_alerts: number;
}

/* ---------------------------- Policy / feedback ---------------------------- */

export interface PolicyEntry {
  id: string;
  timestamp: string;
  change: string;
  kind: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  approved_by: string;
  approval_type: "auto" | "human";
  linked_action: string | null;
  status: string;
  reason?: string | null;
}

export interface WorkloadFeature {
  name: string;
  label: string;
  type: string;
  aliases: string[];
  default: unknown;
  required: boolean;
  description: string;
}

export interface WorkloadSummary {
  workload_id: string;
  name: string;
  version: string;
  description: string;
  domain: string;
  status: string;
  feature_count: number;
  policy: { version: string; review_threshold: number; block_threshold: number };
}

export interface WorkloadSpec extends WorkloadSummary {
  request_aliases: Record<string, string[]>;
  features: WorkloadFeature[];
  reason_rules: Array<Record<string, unknown>>;
  reason_labels: Record<string, string>;
  outcome_labels: Record<string, string>;
  sample_payload: ScoreRequest & Record<string, unknown>;
}

export interface WorkloadsResponse {
  active_workload_id: string;
  active: WorkloadSpec;
  workloads: WorkloadSummary[];
}

export interface FeedbackResponse {
  confirmed_fraud_7d: number;
  confirmed_legit_7d: number;
  analyst_overturn_rate: number;
  pending_labels: number;
  median_label_delay_hours: number;
  p90_label_delay_hours: number;
  feedback_queue_depth: number;
  label_delay_buckets: Array<{ bucket: string; count: number }>;
  recent: Array<{
    transaction_id: string;
    decision_request_id?: string;
    model_decision: string;
    analyst_label: string;
    outcome_label?: string;
    agreement: boolean;
    segment: string;
    delay_hours: number;
    analyst: string;
  }>;
}

export interface BenchmarksResponse {
  latency_ms: { p50: number; p95: number; p99: number; max: number };
  slo_p99_ms: number;
  throughput_tps: number;
  peak_tps_24h: number;
  fallback_rate_24h: number;
  error_rate_24h: number;
  latency_trend: number[];
  throughput_trend: number[];
  model_comparison: Array<
    { model_id: string; version: string; stage: Stage; backend: string } & ModelMetrics
  >;
  live_latency_ms?: { p50: number; p95: number; p99: number; samples: number };
}

/* ------------------------- Storage / audit ledger ------------------------- */

export interface StorageHealth {
  status?: string;
  backend?: string | null;
  path?: string;
  schema_version?: number | string;
  cached_decisions?: number;
  decision_events?: number;
  operation_events?: number;
  namespace?: string;
  has_snapshot?: boolean;
  updated_at?: string;
}

export interface DatabaseBackendOption {
  backend: DatabaseBackend | string;
  label: string;
  default_storage_url: string;
  provisionable: boolean;
  requires: string[];
  provisioner?: string;
  compose_file?: string;
  compose_file_exists?: boolean;
  service?: string;
  driver_available?: boolean;
}

export interface DatabaseStatusResponse {
  configured_storage_url: string;
  connected: StorageHealth;
  control_plane: StorageHealth;
  available_backends: DatabaseBackendOption[];
}

export interface OperationEvent {
  id: string;
  operation_type: string;
  actor: string;
  target: string | null;
  status: string;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  message: string | null;
  role: string | null;
  source: string | null;
  request_id: string | null;
  reason: string | null;
  created_at: string;
  previous_hash: string | null;
  event_hash: string | null;
}

export interface ProvisionDatabaseResponse {
  status: string;
  provisioned: boolean;
  storage_url: string;
  storage: StorageHealth;
  control_plane: StorageHealth | null;
  operation: OperationEvent | null;
  provisioning: {
    backend?: string;
    mode?: string;
    compose_file?: string;
    service?: string;
    started?: boolean;
    wait?: boolean;
    command?: { command: string[]; returncode: number; stdout?: string; stderr?: string };
    [key: string]: unknown;
  } | null;
  config_path: string | null;
}

export interface AuditChainReport {
  chain: string;
  status: "valid" | "partial" | "invalid" | string;
  backend?: string;
  events_checked: number;
  events_verified: number;
  legacy_events: number;
  total_events: number;
  complete: boolean;
  head_hash: string | null;
  tail_hash: string | null;
  issues: Array<string | { message?: string; [key: string]: unknown }>;
  warnings: Array<string | { message?: string; [key: string]: unknown }>;
}

export interface AuditIntegrityResponse {
  status: "valid" | "partial" | "invalid" | string;
  decisions: AuditChainReport;
  operations: AuditChainReport;
}

/* --------------------------------- Calls ----------------------------------- */

export const getAuthStatus = () => request<AuthStatus>("/v1/auth/status");
export const getMe = () => request<{ user: AuthUser }>("/v1/auth/me");
export const bootstrapAuth = (body: { email: string; password: string; display_name?: string }) =>
  post<{ user: AuthUser }>("/v1/auth/bootstrap", body);
export const loginAuth = (body: { email: string; password: string }) =>
  post<{ user: AuthUser }>("/v1/auth/login", body);
export const logoutAuth = () => post<{ status: string }>("/v1/auth/logout");
export const listApiKeys = () => request<{ api_keys: AuthApiKey[] }>("/v1/auth/api-keys");
export const createApiKey = (body: { label: string; role?: AuthRole; expires_at?: string | null }) =>
  post<{ api_key: AuthApiKey; token: string }>("/v1/auth/api-keys", body);
export const revokeApiKey = (id: string) =>
  post<{ api_key: AuthApiKey }>(`/v1/auth/api-keys/${encodeURIComponent(id)}/revoke`);

export const getOverview = () => request<OverviewResponse>("/v1/overview");
export const getDecisions = (limit = 40) =>
  request<{ decisions: DecisionRecord[] }>(`/v1/decisions?limit=${limit}`);
export const getTransaction = (id: string) =>
  request<DecisionRecord>(`/v1/decision-requests/${encodeURIComponent(id)}`);
export const postScore = (body: ScoreRequest) => post<ScoreResponse>("/v1/decision-requests", body);

export const getModels = () => request<ModelsResponse>("/v1/models");
export const getServingEndpoint = () => request<ServingEndpoint>("/v1/serving-endpoint");
export const loadModel = (artifact_id: string, actor?: ActorPayload) =>
  post<ModelRecord>("/v1/models/load", { artifact_id, ...(actor ?? {}) });
export interface UploadSpec {
  model_id: string;
  version: string;
  backend?: string;
  filename?: string;
  size_mb?: number;
}
export const uploadModel = (spec: UploadSpec, actor?: ActorPayload) =>
  post<ModelRecord>("/v1/models/upload", { ...spec, ...(actor ?? {}) });
export const promoteModel = (id: string, stage: "shadow" | "champion", actor?: ActorPayload) =>
  post<ModelRecord>(`/v1/models/${encodeURIComponent(id)}/promote`, { stage, ...(actor ?? {}) });
export const rollbackModel = (actor?: ActorPayload) => post<ModelRecord>("/v1/models/rollback", actor);

export const getHealing = () => request<HealingResponse>("/v1/healing/actions");
export const decideHealing = (id: string, decision: "approve" | "reject", actor?: ActorPayload) =>
  post<HealingAction>(`/v1/healing/actions/${encodeURIComponent(id)}/${decision}`, actor);
export const rollbackHealing = (id: string, actor?: ActorPayload) =>
  post<HealingAction>(`/v1/healing/actions/${encodeURIComponent(id)}/rollback`, actor);

export const getDrift = () => request<DriftResponse>("/v1/drift");
export const updateDrift = (id: string, action: "acknowledge" | "escalate", actor?: ActorPayload) =>
  post<DriftMonitor>(`/v1/drift/${encodeURIComponent(id)}/${action}`, actor);

export const getPolicyHistory = () => request<{ entries: PolicyEntry[] }>("/v1/policy/history");
export const getWorkloads = () => request<WorkloadsResponse>("/v1/workloads");
export const getActiveWorkload = () => request<WorkloadSpec>("/v1/workloads/active");
export const activateWorkload = (workload_id: string, actor?: ActorPayload) =>
  post<{ active: WorkloadSpec; operation: OperationEvent }>("/v1/workloads/activate", {
    workload_id,
    reason: "Dashboard workload activation",
    ...(actor ?? {}),
  });
export const getOperations = (limit = 30) =>
  request<{ operations: OperationEvent[]; limit: number }>(`/v1/operations?limit=${limit}`);
export const getAuditIntegrity = () => request<AuditIntegrityResponse>("/v1/audit/integrity");
export const getDatabaseStatus = () => request<DatabaseStatusResponse>("/v1/database/status");
export const provisionSQLite = (actor?: ActorPayload) =>
  post<ProvisionDatabaseResponse>("/v1/database/provision", {
    backend: "sqlite",
    path: "data/tenta.sqlite3",
    persist: true,
    reason: "Dashboard SQLite provision",
    ...(actor ?? {}),
  });
export const provisionPostgres = (actor?: ActorPayload) =>
  post<ProvisionDatabaseResponse>("/v1/database/provision", {
    backend: "postgres",
    persist: true,
    reason: "Dashboard Postgres provision",
    ...(actor ?? {}),
  });
export const getFeedback = () => request<FeedbackResponse>("/v1/feedback");
export const getBenchmarks = () => request<BenchmarksResponse>("/v1/benchmarks");
