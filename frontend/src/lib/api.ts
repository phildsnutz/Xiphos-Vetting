/**
 * Xiphos API client.
 * Base URL defaults to window origin (same-origin deployment)
 * or can be overridden via VITE_API_URL env var.
 *
 * Automatically injects bearer token from session storage when available.
 */

import { getToken, clearSession } from "./auth";

const BASE = import.meta.env.VITE_API_URL ?? "";

/** Callback set by AuthProvider to handle 401s (auto-logout) */
let onAuthError: (() => void) | null = null;
export function setAuthErrorHandler(handler: () => void): void {
  onAuthError = handler;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers,
  });

  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

/* ---- Profiles ---- */

export async function fetchProfiles(): Promise<ComplianceProfile[]> {
  const data = await json<{ profiles: ComplianceProfile[] }>("/api/profiles");
  return data.profiles;
}

export async function fetchProfile(id: string): Promise<ComplianceProfile> {
  return json<ComplianceProfile>(`/api/profiles/${id}`);
}

/* ---- Cases ---- */

export interface ApiCase {
  id: string;
  vendor_name: string;
  status: string;
  created_at: string;
  score: Record<string, unknown> | null;
}

/** Compliance profile types */
export interface ComplianceProfile {
  id: string;
  name: string;
  description: string;
  entity_label: string;
  program_types: Array<{ id: string; label: string }>;
  required_fields: string[];
  optional_fields: Array<{ id: string; label: string; type: string; options?: Array<{ value: string; label: string }> }>;
  ui_config: Record<string, unknown>;
  regulatory_references: Array<{ name: string; url: string; description: string }>;
}

/** Payload shape for POST /api/cases (snake_case for backend) */
export interface CreateCasePayload {
  name: string;
  country: string;
  ownership: {
    publicly_traded: boolean;
    state_owned: boolean;
    beneficial_owner_known: boolean;
    ownership_pct_resolved: number;
    shell_layers: number;
    pep_connection: boolean;
    foreign_ownership_pct?: number;
    foreign_ownership_is_allied?: boolean;
  };
  data_quality: {
    has_lei: boolean;
    has_cage: boolean;
    has_duns: boolean;
    has_tax_id: boolean;
    has_audited_financials: boolean;
    years_of_records: number;
  };
  exec: {
    known_execs: number;
    adverse_media: number;
    pep_execs: number;
    litigation_history: number;
  };
  program: string;
  profile?: string;
}

/** Response from POST /api/cases */
export interface CreateCaseResponse {
  case_id: string;
  composite_score: number;
  is_hard_stop: boolean;
  calibrated: Record<string, unknown>;
}

export async function fetchCases(limit = 100): Promise<ApiCase[]> {
  const data = await json<{ cases: ApiCase[] }>(`/api/cases?limit=${limit}`);
  return data.cases;
}

export async function fetchCase(id: string): Promise<ApiCase> {
  return json<ApiCase>(`/api/cases/${id}`);
}

/** Create a new vendor case on the backend. Returns score + calibration. */
export async function createCase(payload: CreateCasePayload): Promise<CreateCaseResponse> {
  return json<CreateCaseResponse>("/api/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/* ---- Alerts ---- */

export interface ApiAlert {
  id: number;
  entity_name: string;
  severity: string;
  title: string;
  description: string;
  resolved: boolean;
}

export async function fetchAlerts(limit = 50): Promise<ApiAlert[]> {
  const data = await json<{ alerts: ApiAlert[] }>(`/api/alerts?limit=${limit}&unresolved=true`);
  return data.alerts;
}

/* ---- Score (re-score) ---- */

export interface ScoreResult {
  case_id: string;
  composite_score: number;
  is_hard_stop: boolean;
  calibrated: {
    calibrated_probability: number;
    calibrated_score: number;
    calibrated_tier: string;
    interval: { lower: number; upper: number; coverage: number };
    hard_stop_decisions: Array<{ trigger: string; explanation: string; confidence: number }>;
    soft_flags: Array<{ trigger: string; explanation: string; confidence: number }>;
    contributions: Array<{
      factor: string;
      raw_score: number;
      confidence: number;
      signed_contribution: number;
      description: string;
    }>;
    narratives: { findings: string[] };
    marginal_information_values: Array<{
      recommendation: string;
      expected_info_gain_pp: number;
      tier_change_probability: number;
    }>;
  };
}

export async function rescore(
  caseId: string,
  programType = "dod_unclassified",
  criticalityTier = 3,
): Promise<ScoreResult> {
  return json<ScoreResult>(`/api/cases/${caseId}/score`, {
    method: "POST",
    body: JSON.stringify({ program_type: programType, criticality_tier: criticalityTier }),
  });
}

/* ---- Dossier ---- */

export interface DossierResult {
  case_id: string;
  dossier_path: string;
  download_url: string;
  updated_at: string;
}

export async function generateDossier(caseId: string): Promise<DossierResult> {
  return json<DossierResult>(`/api/cases/${caseId}/dossier`, {
    method: "POST",
  });
}

export async function downloadDossierPDF(caseId: string): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}/api/cases/${caseId}/dossier-pdf`, {
    method: "POST",
    headers,
  });

  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    throw new Error(`Failed to download PDF: ${res.status}`);
  }

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `dossier-${caseId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/* ---- OSINT Enrichment ---- */

export interface EnrichmentFinding {
  finding_id?: string;
  source: string;
  category?: string;
  title: string;
  detail: string;
  severity: string;
  confidence: number;
  url?: string;
}

export interface NormalizedEvent {
  id?: number;
  case_id?: string;
  report_hash?: string;
  finding_id: string;
  event_type: string;
  subject: string;
  date_range: { start?: string | null; end?: string | null };
  jurisdiction?: string;
  status: string;
  confidence: number;
  source_refs: string[];
  source_finding_ids: string[];
  connector?: string;
  normalization_method?: string;
  severity?: string;
  title?: string;
  assessment?: string;
}

export interface IntelSummaryItem {
  title: string;
  assessment: string;
  status: string;
  severity: string;
  confidence: number;
  source_finding_ids: string[];
  connectors: string[];
  recommended_action: string;
}

export interface IntelSummaryPayload {
  items: IntelSummaryItem[];
  stats?: {
    citation_coverage?: number;
    finding_count_considered?: number;
  };
  normalized_event_count?: number;
}

export interface IntelSummaryRecord {
  id?: number;
  case_id?: string;
  created_by?: string;
  report_hash?: string;
  prompt_version?: string;
  provider?: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  elapsed_ms?: number;
  summary: IntelSummaryPayload;
  created_at?: string;
}

export interface IntelSummaryJob {
  id: string;
  case_id?: string;
  created_by?: string;
  report_hash?: string;
  status: string;
  summary_id?: number | null;
  error?: string | null;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface IntelSummaryAsyncResponse {
  status: string;
  case_id: string;
  vendor_name: string;
  summary?: IntelSummaryRecord;
  job?: IntelSummaryJob;
  job_id?: string | null;
}

export interface IntelSummaryResult {
  case_id: string;
  vendor_name: string;
  summary: IntelSummaryPayload;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  elapsed_ms: number;
  created_at?: string;
  prompt_version?: string;
  report_hash?: string;
}

export interface ConnectorStatus {
  has_data: boolean;
  findings_count: number;
  elapsed_ms: number;
  error?: string;
}

export interface EnrichmentSummary {
  findings_total: number;
  connectors_run: number;
  connectors_with_data: number;
  errors: number;
}

export interface EnrichmentReport {
  overall_risk: string;
  summary: EnrichmentSummary;
  identifiers: Record<string, string>;
  findings: EnrichmentFinding[];
  connector_results: Record<string, unknown>;
  connector_status: Record<string, ConnectorStatus>;
  total_elapsed_ms: number;
  report_hash?: string;
  events?: NormalizedEvent[];
  intel_summary?: IntelSummaryRecord | null;
  enriched_at?: string;
  _cached?: boolean;
}

export async function enrichAndScore(caseId: string): Promise<{
  enrichment: { overall_risk: string; summary: string; identifiers: Record<string, string>; total_elapsed_ms: number };
  augmentation: { changes: string[]; extra_risk_signals: string[]; verified_identifiers: string[] };
  scoring: ScoreResult;
}> {
  return json(`/api/cases/${caseId}/enrich-and-score`, { method: "POST" });
}

export async function fetchEnrichment(caseId: string): Promise<EnrichmentReport> {
  return json<EnrichmentReport>(`/api/cases/${caseId}/enrichment`);
}

export async function queueIntelSummary(caseId: string): Promise<IntelSummaryAsyncResponse> {
  return json<IntelSummaryAsyncResponse>(`/api/cases/${caseId}/intel-summary-async`, { method: "POST" });
}

export async function fetchIntelSummaryStatus(caseId: string): Promise<IntelSummaryAsyncResponse> {
  return json<IntelSummaryAsyncResponse>(`/api/cases/${caseId}/intel-summary-status`);
}

export async function fetchIntelSummary(caseId: string): Promise<IntelSummaryResult> {
  return json<IntelSummaryResult>(`/api/cases/${caseId}/intel-summary`);
}

/* ---- Backend Sanctions Screening ---- */

export interface ScreeningMatch {
  name: string;
  list: string;
  score: number;
  matched_on: string;
  source: string;
}

export interface ScreeningResult {
  matched: boolean;
  best_score: number;
  matched_name: string;
  matched_entry: { name: string; list: string; program: string; country: string; source: string } | null;
  all_matches: ScreeningMatch[];
  screening_db: string;
  screening_ms: number;
}

/** Screen a vendor name against the backend sanctions DB (31K+ entities) */
export async function screenVendor(name: string): Promise<ScreeningResult> {
  return json<ScreeningResult>("/api/screen", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

/* ---- Entity Resolution ---- */

export interface MatchFeatures {
  name_score: number;
  country_match: boolean;
  identifier_count: number;
  ownership_signal: boolean;
  source_rank: number;
}

export interface EntityCandidate {
  legal_name: string;
  source: string;
  confidence: number;
  candidate_id?: string;
  match_features?: MatchFeatures;
  deterministic_score?: number;
  cik?: string;
  lei?: string;
  ticker?: string;
  country?: string;
  jurisdiction?: string;
  wikidata_id?: string;
  description?: string;
  uei?: string;
  cage?: string;
  duns?: string;
  naics?: string;
  state?: string;
  city?: string;
  sba_certifications?: string[];
  business_types?: string[];
  highest_owner?: string;
  highest_owner_country?: string;
  immediate_owner?: string;
  immediate_owner_country?: string;
  has_proceedings?: boolean;
  registration_status?: string;
}

export interface EntityResolution {
  mode: "deterministic_only" | "deterministic_plus_ai";
  status: "recommended" | "ambiguous" | "abstained" | "disabled" | "unavailable";
  abstained: boolean;
  recommended_candidate_id?: string | null;
  confidence: number;
  reason_summary?: string | null;
  reason_detail?: string[];
  evidence?: {
    used_country: boolean;
    used_profile: boolean;
    used_program: boolean;
    used_context: boolean;
    candidate_count_evaluated: number;
  };
  request_id?: string;
  input_hash?: string;
  prompt_version?: string;
  latency_ms?: number;
}

export interface ResolveResponse {
  query: string;
  candidates: EntityCandidate[];
  count: number;
  resolution?: EntityResolution;
}

export async function resolveEntity(
  name: string,
  options?: {
    country?: string;
    profile?: string;
    program?: string;
    context?: string;
    use_ai?: boolean;
    max_candidates?: number;
  },
): Promise<ResolveResponse> {
  return json("/api/resolve", {
    method: "POST",
    body: JSON.stringify({ name, ...options }),
  });
}

export async function submitResolveFeedback(
  requestId: string,
  selectedCandidateId: string,
  acceptedRecommendation?: boolean,
): Promise<{ status: string; accepted_recommendation?: boolean }> {
  const body: Record<string, unknown> = {
    request_id: requestId,
    selected_candidate_id: selectedCandidateId,
  };
  if (acceptedRecommendation !== undefined) {
    body.accepted_recommendation = acceptedRecommendation;
  }

  return json("/api/resolve/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* ---- Contract Vehicle Search ---- */

export interface VehicleVendor {
  vendor_name: string;
  role: string; // "prime" | "subcontractor" | "prime+sub"
  award_id?: string;
  award_amount?: number;
  awarding_agency?: string;
  description?: string;
  start_date?: string;
  end_date?: string;
  prime_award_id?: string;
  prime_recipient?: string;
  uei?: string;
}

export interface VehicleSearchResult {
  vehicle_name: string;
  search_terms: string[];
  timestamp: string;
  primes: VehicleVendor[];
  subs: VehicleVendor[];
  unique_vendors: VehicleVendor[];
  total_primes: number;
  total_subs: number;
  total_unique: number;
  idv_awards_checked?: number;
  errors?: Array<{ source: string; message: string }>;
}

export async function searchContractVehicle(
  vehicle: string,
  includeSubs = true,
  limit = 30,
): Promise<VehicleSearchResult> {
  return json("/api/vehicle-search", {
    method: "POST",
    body: JSON.stringify({ vehicle, include_subs: includeSubs, limit }),
  });
}

export interface BatchAssessResult {
  total: number;
  created: number;
  errors: number;
  results: Array<{
    case_id?: string;
    vendor_name: string;
    status: string;
    tier?: string;
    error?: string;
  }>;
}

export async function batchAssessVehicle(
  vendors: VehicleVendor[],
  program = "dod_unclassified",
  profile = "defense_acquisition",
): Promise<BatchAssessResult> {
  return json("/api/vehicle-batch-assess", {
    method: "POST",
    body: JSON.stringify({
      vendors: vendors.map(v => ({ vendor_name: v.vendor_name, country: "US" })),
      program,
      profile,
    }),
  });
}

/* ---- User Management (admin only) ---- */

export interface ApiUser {
  id: string;
  email: string;
  name: string;
  role: string;
  created_at: string;
}

export async function fetchUsers(): Promise<ApiUser[]> {
  return json<ApiUser[]>("/api/auth/users");
}

export async function createUser(
  email: string,
  password: string,
  name: string,
  role: string,
): Promise<ApiUser> {
  return json<ApiUser>("/api/auth/users", {
    method: "POST",
    body: JSON.stringify({ email, password, name, role }),
  });
}

/* ---- AI Analysis ---- */

export interface AIProvider {
  name: string;
  display_name: string;
  models: string[];
  default_model: string;
}

export interface AIConfig {
  configured: boolean;
  provider?: string;
  model?: string;
  api_key_hint?: string;
}

export interface AIAnalysis {
  case_id: string;
  vendor_name: string;
  analysis: {
    executive_summary: string;
    risk_narrative: string;
    critical_concerns: string[];
    mitigating_factors: string[];
    recommended_actions: string[];
    regulatory_exposure: string;
    confidence_assessment: string;
    verdict: string;
  };
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  elapsed_ms: number;
  created_at?: string;
}

export async function fetchAIProviders(): Promise<AIProvider[]> {
  const data = await json<{ providers: AIProvider[] }>("/api/ai/providers");
  return data.providers;
}

export async function fetchAIConfig(): Promise<AIConfig> {
  return json<AIConfig>("/api/ai/config");
}

export async function saveAIConfig(provider: string, model: string, apiKey: string): Promise<{ status: string }> {
  return json("/api/ai/config", {
    method: "POST",
    body: JSON.stringify({ provider, model, api_key: apiKey }),
  });
}

export async function deleteAIConfig(): Promise<{ status: string }> {
  return json("/api/ai/config", { method: "DELETE" });
}

export async function saveOrgAIConfig(provider: string, model: string, apiKey: string): Promise<{ status: string }> {
  return json("/api/ai/config/org-default", {
    method: "POST",
    body: JSON.stringify({ provider, model, api_key: apiKey }),
  });
}

export async function runAIAnalysis(caseId: string): Promise<AIAnalysis> {
  return json<AIAnalysis>(`/api/cases/${caseId}/analyze`, { method: "POST" });
}

export async function fetchAIAnalysis(caseId: string): Promise<AIAnalysis> {
  return json<AIAnalysis>(`/api/cases/${caseId}/analysis`);
}

/* ---- Audit Log (auditor+) ---- */

export interface AuditEntry {
  id: number;
  timestamp: string;
  user_id: string;
  email?: string;
  action: string;
  resource?: string;
  resource_id?: string;
  detail: string;
  ip_address: string;
  status_code?: number;
}

export async function fetchAuditLog(limit = 100): Promise<AuditEntry[]> {
  return json<AuditEntry[]>(`/api/audit?limit=${limit}`);
}

/* ---- Decision Workflow ---- */

export interface Decision {
  id: number;
  vendor_id: string;
  decision: "approve" | "reject" | "escalate";
  decided_by: string;
  decided_by_email: string;
  reason: string | null;
  posterior_at_decision: number | null;
  tier_at_decision: string | null;
  created_at: string;
}

export interface SubmitDecisionPayload {
  decision: "approve" | "reject" | "escalate";
  reason?: string;
}

export interface SubmitDecisionResponse {
  decision_id: number;
  vendor_id: string;
  decision: string;
  decided_by: string;
  decided_by_email: string;
  reason: string | null;
  posterior_at_decision: number | null;
  tier_at_decision: string | null;
  created_at: string;
}

export async function submitDecision(
  vendorId: string,
  decision: "approve" | "reject" | "escalate",
  reason?: string,
): Promise<SubmitDecisionResponse> {
  return json<SubmitDecisionResponse>(`/api/cases/${vendorId}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, reason }),
  });
}

export async function getDecisions(
  vendorId: string,
  limit = 50,
): Promise<{ vendor_id: string; decisions: Decision[]; latest_decision: Decision | null }> {
  return json(`/api/cases/${vendorId}/decisions?limit=${limit}`);
}

/* ---- Profile Comparison ---- */

export interface ComparisonContribution {
  factor: string;
  raw_score: number;
  confidence: number;
  signed_contribution: number;
  description: string;
}

export interface ComparisonDecision {
  trigger: string;
  explanation: string;
  confidence: number;
}

export interface ProfileComparison {
  profile_id: string;
  profile_name: string;
  tier: string;
  posterior: number;
  hard_stops: ComparisonDecision[];
  soft_flags: ComparisonDecision[];
  contributions: ComparisonContribution[];
  error?: string;
}

export interface CompareResult {
  entity: {
    name: string;
    country: string;
  };
  comparisons: ProfileComparison[];
}

export async function compareProfiles(
  name: string,
  country: string,
  profileIds: string[],
  programs: Record<string, string> = {},
): Promise<CompareResult> {
  return json<CompareResult>("/api/compare", {
    method: "POST",
    body: JSON.stringify({
      name,
      country,
      profiles: profileIds,
      programs,
    }),
  });
}

/* ---- Batch Import ---- */

export interface BatchUploadResponse {
  batch_id: string;
  filename: string;
  total_vendors: number;
  status: string;
  created_at: string;
}

export interface BatchItem {
  id: number;
  batch_id: string;
  vendor_name: string;
  country: string;
  case_id: string | null;
  tier: string | null;
  posterior: number | null;
  findings_count: number | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface BatchSummary {
  completed: number;
  tier_distribution: Record<string, number>;
  total_findings: number;
  avg_posterior: number;
}

export interface BatchDetail {
  id?: string;
  batch_id: string;
  filename: string;
  uploaded_by: string;
  uploaded_by_email: string;
  status: string;
  total_vendors: number;
  processed: number;
  completion_pct: number;
  created_at: string;
  completed_at: string | null;
  items: BatchItem[];
  summary: BatchSummary;
}

export interface BatchMetadata {
  id: string;
  batch_id?: string;
  filename: string;
  uploaded_by: string;
  uploaded_by_email: string;
  status: string;
  total_vendors: number;
  processed: number;
  completion_pct: number;
  created_at: string;
  completed_at: string | null;
}

export async function uploadBatchCSV(file: File): Promise<BatchUploadResponse> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${BASE}/api/batch/upload`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export async function listBatches(): Promise<BatchMetadata[]> {
  const data = await json<{ batches: BatchMetadata[] }>("/api/batch");
  return data.batches;
}

export async function getBatchDetail(batchId: string): Promise<BatchDetail> {
  return json<BatchDetail>(`/api/batch/${batchId}`);
}

export async function downloadBatchReport(batchId: string): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}/api/batch/${batchId}/report`, { headers });
  if (!res.ok) throw new Error(`Failed to download report: ${res.status}`);

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `batch-${batchId}-report.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
