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

async function parseResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }

  if (!res.ok) {
    const contentType = res.headers.get("content-type") || "";
    let detail = "";
    if (contentType.includes("application/json")) {
      const body = await res.json().catch(() => ({})) as { error?: string; message?: string };
      detail = body.error || body.message || "";
    } else {
      detail = await res.text().catch(() => "");
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }

  return res.json() as Promise<T>;
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

  return parseResponse<T>(res);
}

async function submitForm<T>(url: string, formData: FormData): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${url}`, {
    method: "POST",
    headers,
    body: formData,
  });

  return parseResponse<T>(res);
}

export interface AccessTicketResult {
  path: string;
  permission: string;
  access_ticket: string;
  expires_in: number;
}

export async function createAccessTicket(path: string): Promise<AccessTicketResult> {
  return json<AccessTicketResult>("/api/auth/access-ticket", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function buildProtectedUrl(path: string): Promise<string> {
  const ticket = await createAccessTicket(path);
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}access_ticket=${encodeURIComponent(ticket.access_ticket)}`;
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
  country?: string;
  profile?: string;
  program?: string;
  workflow_lane?: "counterparty" | "cyber" | "export";
  storyline?: RiskStoryline | null;
  export_authorization?: ExportAuthorizationCaseInput | null;
  export_authorization_guidance?: ExportAuthorizationGuidance | null;
  latest_foci_artifact?: FociArtifactRecord | null;
  latest_sprs_import?: SprsImportRecord | null;
  latest_oscal_artifact?: OscalArtifactRecord | null;
  latest_nvd_overlay?: NvdOverlayRecord | null;
  workflow_control_summary?: WorkflowControlSummary | null;
}

export interface HealthStatus {
  status: string;
  version?: string;
  osint_connector_count?: number;
  regulatory_gate_count?: number;
  auth_enabled?: boolean;
  dev_mode?: boolean;
  login_required?: boolean;
}

export interface StorylineSourceRef {
  kind: string;
  id: string;
}

export interface StorylineCtaTarget {
  kind: "evidence_tab" | "graph_focus" | "action_panel" | "deep_analysis" | "external_dossier_section";
  tab?: "intel" | "findings" | "events" | "model" | "graph";
  depth?: 3 | 4;
  finding_id?: string | null;
  section?: string;
}

export interface RiskStorylineCard {
  id: string;
  type: "trigger" | "impact" | "reach" | "action" | "offset";
  title: string;
  body: string;
  severity: "critical" | "high" | "medium" | "low" | "positive";
  confidence: number;
  rank: number;
  cta_label: string;
  cta_target: StorylineCtaTarget;
  source_refs: StorylineSourceRef[];
}

export interface RiskStoryline {
  version: string;
  case_id: string;
  generated_at: string;
  cards: RiskStorylineCard[];
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

export type ExportAuthorizationRequestType =
  | "item_transfer"
  | "technical_data_release"
  | "foreign_person_access";

export interface ExportAuthorizationCaseInput {
  request_type: ExportAuthorizationRequestType;
  recipient_name?: string;
  recipient_type?: string;
  destination_country?: string;
  jurisdiction_guess?: "itar" | "ear" | "ofac_overlay" | "unknown";
  classification_guess?: string;
  item_or_data_summary?: string;
  end_use_summary?: string;
  access_context?: string;
  foreign_person_nationalities?: string[];
}

export interface ExportAuthorizationCountryAnalysis {
  destination_country: string;
  country_bucket: string;
  rationale: string;
}

export interface ExportAuthorizationClassificationAnalysis {
  input: string;
  classification_family: string;
  label: string;
  rationale: string;
  known: boolean;
}

export interface ExportAuthorizationEndUseFlag {
  key: string;
  label: string;
  severity: "critical" | "high" | "medium" | "low";
  reference: string;
  rationale: string;
}

export interface ExportAuthorizationReference {
  title: string;
  url: string;
  note: string;
}

export interface ExportAuthorizationGuidance {
  source: string;
  version: string;
  source_class: string;
  authority_level: string;
  access_model: string;
  posture: "likely_prohibited" | "likely_license_required" | "likely_exception_or_exemption" | "likely_nlr" | "insufficient_confidence" | "escalate";
  posture_label: string;
  confidence: number;
  reason_summary: string;
  recommended_next_step: string;
  country_analysis: ExportAuthorizationCountryAnalysis;
  classification_analysis: ExportAuthorizationClassificationAnalysis;
  end_use_flags: ExportAuthorizationEndUseFlag[];
  official_references: ExportAuthorizationReference[];
  factors: string[];
}

export interface ExportArtifactRecord {
  id: string;
  case_id: string;
  artifact_type: string;
  source_system: string;
  source_class: string;
  authority_level: string;
  access_model: string;
  uploaded_by: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  retention_class: string;
  sensitivity: string;
  effective_date?: string | null;
  parse_status: string;
  created_at?: string;
  structured_fields: Record<string, unknown>;
}

export interface ExportArtifactListResponse {
  case_id: string;
  artifacts: ExportArtifactRecord[];
}

export interface WorkflowControlSummary {
  lane: "counterparty" | "cyber" | "export";
  support_level: "artifact_backed" | "partial" | "triage_only" | "awaiting_input";
  label: string;
  review_basis: string;
  action_owner: string;
  decision_boundary: string;
  missing_inputs: string[];
}

export interface SupplierPassportControlPath {
  rel_type: string;
  source_entity_id?: string;
  source_name?: string;
  target_entity_id?: string;
  target_name?: string;
  confidence: number;
  corroboration_count: number;
  data_sources: string[];
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  evidence_refs: Array<{
    title: string;
    url?: string;
    artifact_ref?: string;
    source?: string;
  }>;
}

export interface SupplierPassportClaimHealth {
  control_relationships: number;
  corroborated_paths: number;
  contradicted_claims: number;
  stale_paths: number;
  freshest_observation_at?: string | null;
  stale_threshold_days: number;
}

export interface SupplierPassportTribunalView {
  stance: "deny" | "watch" | "approve" | string;
  label: string;
  owner: string;
  score: number;
  summary: string;
  reasons: string[];
  signal_keys: string[];
}

export interface SupplierPassportTribunal {
  version: string;
  generated_at: string;
  recommended_view: "deny" | "watch" | "approve" | string;
  recommended_label: string;
  consensus_level: "strong" | "moderate" | "contested" | string;
  decision_gap: number;
  signal_snapshot: Record<string, unknown>;
  views: SupplierPassportTribunalView[];
}

export interface SupplierPassportIdentifierStatus {
  state: "verified_present" | "verified_absent" | "unverified" | "missing" | string;
  source?: string | null;
  sources?: string[];
  value?: unknown;
  reason?: string | null;
  next_access_time?: string | null;
  authority_level?: string | null;
  access_model?: string | null;
  verification_tier?: "verified" | "publicly_disclosed" | "publicly_captured" | "verified_absent" | "unverified" | "missing" | string;
  verification_label?: string | null;
}

export interface SupplierPassportOfficialConnector {
  source?: string;
  label?: string;
  authority_level?: string;
  access_model?: string;
  has_data?: boolean;
  throttled?: boolean;
  error?: string | null;
}

export interface SupplierPassportOfficialCorroboration {
  coverage_level?: "strong" | "partial" | "public_only" | "missing" | string;
  coverage_label?: string;
  official_connector_count?: number;
  relevant_official_connector_count?: number;
  official_connectors_with_data?: number;
  relevant_official_connectors_with_data?: number;
  official_identifier_count?: number;
  official_identifiers_verified?: string[];
  core_official_identifier_count?: number;
  core_official_identifiers_verified?: string[];
  public_capture_fields?: string[];
  unverified_official_fields?: string[];
  blocked_connector_count?: number;
  blocked_connectors?: SupplierPassportOfficialConnector[];
  relevant_connectors?: SupplierPassportOfficialConnector[];
  connectors?: SupplierPassportOfficialConnector[];
  country_hints?: string[];
  core_official_fields?: string[];
}

export interface OwnershipControlIntelligenceSummary {
  schema_version: string;
  adjudicator_version: string;
  adjudicator_mode: string;
  named_beneficial_owner_known: boolean;
  named_beneficial_owner?: string | null;
  controlling_parent_known: boolean;
  controlling_parent?: string | null;
  owner_class_known: boolean;
  owner_class?: string | null;
  ownership_resolution_pct: number;
  control_resolution_pct: number;
  ownership_gap: string;
  descriptor_only: boolean;
  named_owner_candidates: Array<Record<string, unknown>>;
  controller_candidates: Array<Record<string, unknown>>;
  controlling_parent_candidates: Array<Record<string, unknown>>;
  owner_class_evidence: Array<Record<string, unknown>>;
  rejected_descriptor_relationships: Array<Record<string, unknown>>;
}

export interface ThreatIntelSummary {
  shared_threat_intel_present?: boolean;
  attack_actor_families?: string[];
  attack_campaigns?: string[];
  attack_technique_ids?: string[];
  attack_techniques?: Array<{ id?: string; name?: string; tactic?: string }>;
  attack_tactics?: string[];
  cisa_advisory_ids?: string[];
  cisa_advisory_titles?: string[];
  threat_sectors?: string[];
  mitigation_focus?: string[];
  ioc_types?: string[];
  threat_intel_sources?: string[];
  threat_pressure?: string;
}

export interface CyberEvidenceSummary extends ThreatIntelSummary {
  sprs_artifact_id?: string | null;
  oscal_artifact_id?: string | null;
  nvd_artifact_id?: string | null;
  current_cmmc_level?: number | null;
  assessment_date?: string;
  assessment_status?: string;
  poam_active?: boolean;
  open_poam_items?: number;
  system_name?: string;
  total_control_references?: number;
  high_or_critical_cve_count?: number;
  critical_cve_count?: number;
  kev_flagged_cve_count?: number;
  product_terms?: string[];
  artifact_sources?: string[];
  public_evidence_present?: boolean;
  secure_by_design_evidence?: string;
  sbom_present?: boolean;
  sbom_format?: string;
  sbom_fresh_days?: number;
  vex_status?: string;
  security_txt_present?: boolean;
  psirt_contact_present?: boolean;
  support_lifecycle_published?: boolean;
  provenance_attested?: boolean;
  package_inventory_present?: boolean;
  package_inventory_count?: number;
  open_source_advisory_count?: number;
  open_source_advisory_ids?: string[];
  open_source_vulnerable_packages?: string[];
  deps_dev_related_repositories?: string[];
  deps_dev_verified_attestations?: number;
  deps_dev_verified_slsa_provenances?: number;
  scorecard_average?: number;
  scorecard_low_repo_count?: number;
  scorecard_repo_scores?: Array<{ repository?: string; score?: number }>;
  open_source_risk_level?: string;
  open_source_sources?: string[];
}

export interface SupplierPassportGraphIntelligence {
  version?: string;
  workflow_lane?: string | null;
  thin_graph?: boolean;
  thin_control_paths?: boolean;
  dominant_edge_family?: string | null;
  edge_family_counts?: Record<string, number>;
  required_edge_families?: string[];
  present_required_edge_families?: string[];
  missing_required_edge_families?: string[];
  claim_coverage_pct?: number;
  evidence_coverage_pct?: number;
  corroborated_edge_pct?: number;
  official_or_modeled_edge_count?: number;
  first_party_edge_count?: number;
  third_party_public_only_edge_count?: number;
  contradicted_edge_count?: number;
  legacy_unscoped_edge_count?: number;
  low_confidence_edge_count?: number;
  control_path_count?: number;
  intermediary_edge_count?: number;
  recent_edge_count?: number;
  stale_edge_count?: number;
  observed_edge_count?: number;
  avg_edge_age_days?: number | null;
  freshest_observation_at?: string | null;
  stalest_observation_at?: string | null;
}

export interface SupplierPassport {
  passport_version: string;
  generated_at: string;
  case_id: string;
  workflow_lane: string;
  posture: "approved" | "review" | "blocked" | "pending" | string;
  vendor: {
    id: string;
    name: string;
    country?: string;
    profile?: string;
    program?: string;
    program_label?: string;
  };
  score: {
    composite_score?: number | null;
    calibrated_probability?: number | null;
    calibrated_tier?: string | null;
    program_recommendation?: string | null;
    is_hard_stop?: boolean;
    scored_at?: string | null;
  };
  decision?: Record<string, unknown> | null;
  identity: {
    identifiers: Record<string, unknown>;
    identifier_status: Record<string, SupplierPassportIdentifierStatus>;
    official_corroboration?: SupplierPassportOfficialCorroboration | null;
    connectors_run: number;
    connectors_with_data: number;
    findings_total: number;
    overall_risk?: string | null;
    enriched_at?: string | null;
  };
  ownership: {
    profile: Record<string, unknown> & {
      beneficial_owner_known?: boolean;
      named_beneficial_owner_known?: boolean;
      controlling_parent_known?: boolean;
      owner_class_known?: boolean;
      owner_class?: string;
      ownership_pct_resolved?: number;
      control_resolution_pct?: number;
    };
    oci?: OwnershipControlIntelligenceSummary | null;
    foci_summary?: Record<string, unknown> | null;
    workflow_control?: WorkflowControlSummary | Record<string, unknown> | null;
  };
  export?: Record<string, unknown> | null;
  cyber?: CyberEvidenceSummary | null;
  threat_intel?: ThreatIntelSummary | null;
  graph: {
    entity_count: number;
    relationship_count: number;
    entity_type_distribution: Record<string, number>;
    relationship_type_distribution: Record<string, number>;
    control_paths: SupplierPassportControlPath[];
    claim_health: SupplierPassportClaimHealth;
    intelligence?: SupplierPassportGraphIntelligence;
  };
  network_risk?: Record<string, unknown> | null;
  monitoring: {
    check_count: number;
    latest_check?: Record<string, unknown> | null;
  };
  artifacts: {
    count: number;
    by_source: Record<string, number>;
  };
  tribunal: SupplierPassportTribunal;
}

export interface AssistantPlanAnomaly {
  code: string;
  severity: "high" | "medium" | "low" | string;
  message: string;
}

export interface AssistantPlanStep {
  tool_id: string;
  label: string;
  surface: string;
  mode: "read" | "review" | "generate" | string;
  description: string;
  required: boolean;
  reason: string;
}

export interface CaseAssistantPlan {
  version: string;
  generated_at: string;
  case_id: string;
  vendor_name: string;
  analyst_prompt: string;
  objective: string;
  current_posture: string;
  recommended_view?: string | null;
  consensus_level?: string | null;
  anomalies: AssistantPlanAnomaly[];
  plan: AssistantPlanStep[];
  context_snapshot: {
    tier: string;
    findings_total: number;
    control_path_count: number;
    contradicted_claims: number;
  };
  guardrails: string[];
  suggested_followups: string[];
  storyline_available: boolean;
}

export interface AssistantExportHybridReview {
  version: string;
  deterministic_posture: string;
  deterministic_posture_label: string;
  deterministic_reason_summary: string;
  deterministic_next_step: string;
  ai_proposed_posture: string;
  final_posture: string;
  disagrees_with_deterministic: boolean;
  ambiguity_flags: string[];
  missing_facts: string[];
  recommended_questions: string[];
  ai_explanation: string;
  license_exception?: Record<string, unknown> | null;
  safe_boundary: {
    ai_can_elevate: boolean;
    ai_can_downgrade_hard_stop: boolean;
    ai_can_downgrade_insufficient_confidence: boolean;
  };
}

export interface AssistantAssuranceHybridReview {
  version: string;
  deterministic_posture: string;
  deterministic_tier?: string | null;
  deterministic_reason_summary: string;
  deterministic_next_step: string;
  ai_proposed_posture: string;
  final_posture: string;
  disagrees_with_deterministic: boolean;
  ambiguity_flags: string[];
  missing_facts: string[];
  recommended_questions: string[];
  ai_explanation: string;
  artifact_sources: string[];
  threat_pressure: string;
  attack_technique_ids: string[];
  attack_actor_families: string[];
  cisa_advisory_ids: string[];
  threat_sectors: string[];
  open_source_risk_level: string;
  open_source_advisory_count: number;
  scorecard_low_repo_count: number;
  safe_boundary: {
    ai_can_elevate: boolean;
    ai_can_downgrade_blocked: boolean;
    ai_can_downgrade_review_with_artifact_backed_evidence: boolean;
  };
}

export interface CaseAssistantExecutionStep {
  tool_id: string;
  status: "ok" | "unavailable" | "error" | "blocked" | string;
  result: Record<string, unknown>;
}

export interface CaseAssistantExecutionBlockedTool {
  tool_id: string;
  reason: string;
  message: string;
}

export interface CaseAssistantExecutionResult {
  version: string;
  executed_at: string;
  case_id: string;
  objective: string;
  analyst_prompt: string;
  approved_tool_ids: string[];
  executed_steps: CaseAssistantExecutionStep[];
  blocked_tools: CaseAssistantExecutionBlockedTool[];
  approval_boundary: string;
}

export type AssistantFeedbackVerdict = "accepted" | "partial" | "rejected";
export type AssistantFeedbackType =
  | "helpful"
  | "objective_wrong"
  | "tool_missing"
  | "tool_noise"
  | "missing_evidence"
  | "wrong_explanation";

export interface CaseAssistantFeedbackPayload {
  prompt: string;
  objective: string;
  verdict: AssistantFeedbackVerdict;
  feedback_type: AssistantFeedbackType;
  comment?: string;
  approved_tool_ids?: string[];
  executed_tool_ids?: string[];
  suggested_tool_ids?: string[];
  anomaly_codes?: string[];
}

export interface CaseAssistantFeedbackResult {
  status: string;
  feedback_id: number;
  training_signal: {
    version: string;
    captured_at: string;
    objective: string;
    verdict: AssistantFeedbackVerdict;
    feedback_type: AssistantFeedbackType;
    approved_tool_ids: string[];
    executed_tool_ids: string[];
    suggested_tool_ids: string[];
    anomaly_codes: string[];
    comment: string;
  };
}

export type FociArtifactRecord = ExportArtifactRecord;

export interface FociArtifactListResponse {
  case_id: string;
  artifacts: FociArtifactRecord[];
}

export type SprsImportRecord = ExportArtifactRecord;

export interface PersonScreeningResult {
  id?: string;
  case_id?: string | null;
  person_name?: string;
  nationalities?: string[];
  employer?: string | null;
  screening_status?: string;
  composite_score?: number;
  ofac_matches?: Array<Record<string, unknown>>;
  deemed_export_triggered?: boolean;
  matched_lists?: Array<Record<string, unknown>>;
  deemed_export?: Record<string, unknown> | null;
  recommended_action?: string;
  created_at?: string;
  screened_at?: string;
  [key: string]: unknown;
}

export interface CaseScreeningsResponse {
  case_id: string;
  screenings: PersonScreeningResult[];
  count: number;
}

export interface BatchScreeningCsvResponse {
  screenings: PersonScreeningResult[];
  count: number;
  filename?: string;
  graph_ingest?: Record<string, unknown>;
}

export interface SprsImportListResponse {
  case_id: string;
  imports: SprsImportRecord[];
}

export type OscalArtifactRecord = ExportArtifactRecord;

export interface OscalArtifactListResponse {
  case_id: string;
  artifacts: OscalArtifactRecord[];
}

export type NvdOverlayRecord = ExportArtifactRecord;

export interface NvdOverlayListResponse {
  case_id: string;
  overlays: NvdOverlayRecord[];
}

export type ExportArtifactType =
  | "export_classification_memo"
  | "export_ccats_or_cj"
  | "export_license_history"
  | "export_access_control_record"
  | "export_technology_control_plan"
  | "export_deccs_or_snapr_export";

export type FociArtifactType =
  | "foci_form_328"
  | "foci_ownership_chart"
  | "foci_cap_table_or_stock_ledger"
  | "foci_kmp_or_board_list"
  | "foci_mitigation_instrument"
  | "foci_supporting_memo";

/** Payload shape for POST /api/cases (snake_case for backend) */
export interface CreateCasePayload {
  name: string;
  country: string;
  ownership: {
    publicly_traded: boolean;
    state_owned: boolean;
    beneficial_owner_known: boolean;
    named_beneficial_owner_known?: boolean;
    controlling_parent_known?: boolean;
    owner_class_known?: boolean;
    owner_class?: string;
    ownership_pct_resolved: number;
    control_resolution_pct?: number;
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
  export_authorization?: ExportAuthorizationCaseInput;
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

export async function fetchSupplierPassport(caseId: string): Promise<SupplierPassport> {
  return json<SupplierPassport>(`/api/cases/${caseId}/supplier-passport`);
}

export async function fetchCaseAssistantPlan(caseId: string, prompt: string): Promise<CaseAssistantPlan> {
  return json<CaseAssistantPlan>(`/api/cases/${caseId}/assistant-plan`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export async function executeCaseAssistantPlan(
  caseId: string,
  prompt: string,
  approvedToolIds: string[],
): Promise<CaseAssistantExecutionResult> {
  return json<CaseAssistantExecutionResult>(`/api/cases/${caseId}/assistant-execute`, {
    method: "POST",
    body: JSON.stringify({ prompt, approved_tool_ids: approvedToolIds }),
  });
}

export async function submitCaseAssistantFeedback(
  caseId: string,
  payload: CaseAssistantFeedbackPayload,
): Promise<CaseAssistantFeedbackResult> {
  return json<CaseAssistantFeedbackResult>(`/api/cases/${caseId}/assistant-feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchHealth(): Promise<HealthStatus> {
  return json<HealthStatus>("/api/health");
}

/** Create a new vendor case on the backend. Returns score + calibration. */
export async function createCase(payload: CreateCasePayload): Promise<CreateCaseResponse> {
  return json<CreateCaseResponse>("/api/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listExportArtifacts(caseId: string): Promise<ExportArtifactRecord[]> {
  const data = await json<ExportArtifactListResponse>(`/api/cases/${caseId}/export-artifacts`);
  return data.artifacts;
}

export async function listFociArtifacts(caseId: string): Promise<FociArtifactRecord[]> {
  const data = await json<FociArtifactListResponse>(`/api/cases/${caseId}/foci-artifacts`);
  return data.artifacts;
}

export async function uploadFociArtifact(
  caseId: string,
  params: {
    file: File;
    artifactType: FociArtifactType;
    notes?: string;
    declaredForeignOwner?: string;
    declaredForeignCountry?: string;
    declaredForeignOwnershipPct?: string;
    declaredMitigationStatus?: string;
    declaredMitigationType?: string;
    effectiveDate?: string;
  },
): Promise<FociArtifactRecord> {
  const formData = new FormData();
  formData.append("file", params.file);
  formData.append("artifact_type", params.artifactType);
  if (params.notes) formData.append("notes", params.notes);
  if (params.declaredForeignOwner) formData.append("declared_foreign_owner", params.declaredForeignOwner);
  if (params.declaredForeignCountry) formData.append("declared_foreign_country", params.declaredForeignCountry);
  if (params.declaredForeignOwnershipPct) formData.append("declared_foreign_ownership_pct", params.declaredForeignOwnershipPct);
  if (params.declaredMitigationStatus) formData.append("declared_mitigation_status", params.declaredMitigationStatus);
  if (params.declaredMitigationType) formData.append("declared_mitigation_type", params.declaredMitigationType);
  if (params.effectiveDate) formData.append("effective_date", params.effectiveDate);

  const data = await submitForm<{ artifact: FociArtifactRecord }>(`/api/cases/${caseId}/foci-artifacts`, formData);
  return data.artifact;
}

export async function uploadExportArtifact(
  caseId: string,
  params: {
    file: File;
    artifactType: ExportArtifactType;
    notes?: string;
    declaredClassification?: string;
    declaredJurisdiction?: string;
    effectiveDate?: string;
  },
): Promise<ExportArtifactRecord> {
  const formData = new FormData();
  formData.append("file", params.file);
  formData.append("artifact_type", params.artifactType);
  if (params.notes) formData.append("notes", params.notes);
  if (params.declaredClassification) formData.append("declared_classification", params.declaredClassification);
  if (params.declaredJurisdiction) formData.append("declared_jurisdiction", params.declaredJurisdiction);
  if (params.effectiveDate) formData.append("effective_date", params.effectiveDate);

  const data = await submitForm<{ artifact: ExportArtifactRecord }>(`/api/cases/${caseId}/export-artifacts`, formData);
  return data.artifact;
}

export async function listSprsImports(caseId: string): Promise<SprsImportRecord[]> {
  const data = await json<SprsImportListResponse>(`/api/cases/${caseId}/sprs-imports`);
  return data.imports;
}

export async function uploadSprsImport(
  caseId: string,
  params: {
    file: File;
    notes?: string;
    effectiveDate?: string;
  },
): Promise<SprsImportRecord> {
  const formData = new FormData();
  formData.append("file", params.file);
  if (params.notes) formData.append("notes", params.notes);
  if (params.effectiveDate) formData.append("effective_date", params.effectiveDate);

  const data = await submitForm<{ import: SprsImportRecord }>(`/api/cases/${caseId}/sprs-imports`, formData);
  return data.import;
}

export async function listOscalArtifacts(caseId: string): Promise<OscalArtifactRecord[]> {
  const data = await json<OscalArtifactListResponse>(`/api/cases/${caseId}/oscal-artifacts`);
  return data.artifacts;
}

export async function uploadOscalArtifact(
  caseId: string,
  params: {
    file: File;
    notes?: string;
    effectiveDate?: string;
  },
): Promise<OscalArtifactRecord> {
  const formData = new FormData();
  formData.append("file", params.file);
  if (params.notes) formData.append("notes", params.notes);
  if (params.effectiveDate) formData.append("effective_date", params.effectiveDate);

  const data = await submitForm<{ artifact: OscalArtifactRecord }>(`/api/cases/${caseId}/oscal-artifacts`, formData);
  return data.artifact;
}

export async function listNvdOverlays(caseId: string): Promise<NvdOverlayRecord[]> {
  const data = await json<NvdOverlayListResponse>(`/api/cases/${caseId}/nvd-overlays`);
  return data.overlays;
}

export async function runNvdOverlay(
  caseId: string,
  params: {
    productTerms: string[];
    notes?: string;
  },
): Promise<NvdOverlayRecord> {
  const data = await json<{ overlay: NvdOverlayRecord }>(`/api/cases/${caseId}/nvd-overlays`, {
    method: "POST",
    body: JSON.stringify({
      product_terms: params.productTerms,
      notes: params.notes || "",
    }),
  });
  return data.overlay;
}

/* ---- Cyber Risk Scoring ---- */

export interface CyberRiskDimension {
  score: number;
  weight: number;
  factors: string[];
}

export interface CyberRiskScore {
  case_id: string;
  vendor_name: string;
  cyber_risk_score: number;
  cyber_risk_tier: "LOW" | "MODERATE" | "ELEVATED" | "HIGH" | "CRITICAL";
  dimensions: {
    cmmc_readiness: CyberRiskDimension;
    vulnerability_exposure: CyberRiskDimension;
    remediation_posture: CyberRiskDimension;
    supply_chain_propagation: CyberRiskDimension;
    compliance_maturity: CyberRiskDimension;
  };
  top_findings: string[];
  recommended_actions: string[];
  confidence: number;
}

export async function computeCyberRiskScore(caseId: string, profile?: string): Promise<CyberRiskScore> {
  return json<CyberRiskScore>(`/api/cases/${caseId}/cyber-risk-score`, {
    method: "POST",
    body: JSON.stringify({ profile: profile || "" }),
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
    policy?: {
      mode?: "layered" | "standalone";
      sensitivity?: string;
      profile?: string;
      baseline_logodds?: number;
      profile_baseline_shift?: number;
      tier_weight_multiplier?: number;
      screening?: {
        composite_threshold?: number;
        prefilter?: Record<string, number>;
        signal_weights?: Record<string, number>;
        post_match_gates?: Record<string, number>;
      };
      sanctions_policy?: {
        hard_stop_threshold_default?: number;
        hard_stop_threshold_allied_cross_country?: number;
        soft_flag_floor?: number;
      };
      uncertainty?: {
        effective_n_base?: number;
        source_reliability_avg?: number;
        source_reliability_multiplier?: number;
        identifier_boost?: number;
        effective_n_final?: number;
      };
    };
    screening?: {
      matched: boolean;
      best_score: number;
      best_raw_jw: number;
      matched_name: string;
      db_label: string;
      screening_ms: number;
      match_details?: Record<string, unknown>;
      policy_basis?: {
        composite_threshold?: number;
        prefilter?: Record<string, number>;
        signal_weights?: Record<string, number>;
        post_match_gates?: Record<string, number>;
      };
    };
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

export interface AxiomSearchResult {
  status?: string;
  iteration?: number;
  entities?: Array<{
    name: string;
    entity_type?: string;
    type?: string;
    confidence?: number;
  }>;
  relationships?: Array<{
    source_entity?: string;
    source?: string;
    target_entity?: string;
    target?: string;
    rel_type?: string;
    relationship_type?: string;
    confidence?: number;
  }>;
  intelligence_gaps?: Array<{
    gap_type?: string;
    description?: string;
    confidence?: number;
  }>;
  advisory_opportunities?: Array<{
    opportunity_type?: string;
    description?: string;
    priority?: string;
  }>;
  advisory?: Array<{
    opportunity_type?: string;
    description?: string;
    priority?: string;
  }>;
  total_queries?: number;
  total_connector_calls?: number;
  elapsed_ms?: number;
  kg_ingestion?: {
    entities_created?: number;
    relationships_created?: number;
    claims_created?: number;
    evidence_created?: number;
  };
  neo4j_sync?: {
    status?: string;
    job_id?: string;
    status_url?: string | null;
    reused_existing_job?: boolean;
    error?: string;
  };
}

export async function generateDossier(caseId: string): Promise<DossierResult> {
  return json<DossierResult>(`/api/cases/${caseId}/dossier`, {
    method: "POST",
  });
}

export async function runAxiomSearchIngest(payload: {
  prime_contractor: string;
  vehicle_name?: string;
  installation?: string;
  context?: string;
  vendor_id?: string;
  provider?: "anthropic" | "openai";
  model?: string;
}): Promise<AxiomSearchResult> {
  return json<AxiomSearchResult>("/api/axiom/search/ingest", {
    method: "POST",
    body: JSON.stringify(payload),
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

  const contentType = res.headers.get("content-type") || "";
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);

  if (contentType.includes("text/html")) {
    // HTML dossier: open in new tab for rich rendering (Thales-style format)
    window.open(url, "_blank");
    setTimeout(() => window.URL.revokeObjectURL(url), 30000);
  } else {
    // PDF: download as file
    const a = document.createElement("a");
    a.href = url;
    a.download = `dossier-${caseId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }
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
  last_checked_at?: string;
  next_scheduled_at?: string;
}

export interface EnrichmentSummary {
  findings_total: number;
  connectors_run: number;
  connectors_with_data: number;
  errors: number;
}

export interface CacheFreshness {
  connectors_cached?: number;
  connectors_fresh?: number;
}

export interface GraphEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  country?: string;
}

export interface GraphEvidenceRecord {
  evidence_id: string;
  source?: string;
  title?: string;
  url?: string;
  artifact_ref?: string;
  snippet?: string;
  source_class?: string;
  authority_level?: string;
  access_model?: string;
  observed_at?: string;
  structured_fields?: Record<string, unknown>;
}

export interface GraphClaimRecord {
  claim_id: string;
  claim_value?: string;
  confidence?: number;
  contradiction_state?: string;
  observed_at?: string;
  first_observed_at?: string;
  last_observed_at?: string;
  data_source?: string;
  structured_fields?: Record<string, unknown>;
  updated_at?: string;
  asserting_agent?: {
    label?: string;
    agent_type?: string;
  };
  source_activity?: {
    source?: string;
    activity_type?: string;
    occurred_at?: string;
  };
  evidence_records?: GraphEvidenceRecord[];
}

export interface GraphRelationship {
  id?: string | number;
  source_entity_id: string;
  target_entity_id: string;
  rel_type: string;
  confidence: number;
  data_source?: string;
  evidence?: string;
  evidence_summary?: string;
  created_at?: string;
  corroboration_count?: number;
  data_sources?: string[];
  evidence_snippets?: string[];
  first_seen_at?: string;
  last_seen_at?: string;
  relationship_ids?: Array<string | number>;
  claim_records?: GraphClaimRecord[];
}

export interface NetworkRiskContributor {
  vendor_id?: string;
  vendor_name?: string;
  entity_id?: string;
  entity_name?: string;
  relationship?: string;
  rel_type?: string;
  confidence?: number;
  distance?: number;
  path?: Array<{ entity_name: string; rel_type: string; confidence: number }>;
  risk_score_pct?: number;
  contribution?: number;
}

export interface NetworkRiskPath {
  description: string;
  total_risk_contribution: number;
  source_vendor?: string;
  source_risk?: number;
}

export interface NetworkRiskResult {
  network_risk_score: number;
  network_risk_level: string;
  high_risk_neighbors: number;
  neighbor_count: number;
  risk_contributors?: NetworkRiskContributor[];
  propagation_paths?: NetworkRiskPath[];
}

export interface CaseGraphData {
  vendor_id?: string;
  root_entity_id?: string;
  graph_depth?: number;
  entity_count?: number;
  relationship_count?: number;
  entities: GraphEntity[];
  relationships: GraphRelationship[];
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
  cache_freshness?: CacheFreshness;
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

export async function fetchCaseGraph(caseId: string, depth = 3): Promise<CaseGraphData> {
  return json<CaseGraphData>(`/api/cases/${caseId}/graph?depth=${depth}`);
}

export async function fetchCaseNetworkRisk(caseId: string): Promise<NetworkRiskResult> {
  return json<NetworkRiskResult>(`/api/cases/${caseId}/network-risk`);
}

export interface MonitorLatestScore {
  composite_score?: number | null;
  tier?: string | null;
}

export interface MonitorLatestCheck {
  vendor_id?: string;
  previous_risk?: string | null;
  current_risk?: string | null;
  risk_changed?: boolean;
  new_findings_count?: number;
  resolved_findings_count?: number;
  checked_at?: string;
  created_at?: string;
}

export interface CaseMonitorStatus {
  mode?: "async" | "sync";
  sweep_id: string;
  status: "queued" | "running" | "completed" | "failed" | "not_found" | string;
  vendor_id?: string;
  triggered_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  total_vendors?: number | null;
  processed?: number | null;
  risk_changes?: number | null;
  new_alerts?: number | null;
  latest_check?: MonitorLatestCheck | null;
  latest_score?: MonitorLatestScore | null;
  status_url?: string;
  message?: string;
  error?: string;
}

export interface MonitoringHistoryEntry {
  vendor_id: string;
  previous_risk?: string | null;
  current_risk?: string | null;
  risk_changed?: boolean;
  new_findings_count?: number;
  resolved_findings_count?: number;
  checked_at?: string;
}

export interface CaseMonitoringHistory {
  vendor_id: string;
  vendor_name: string;
  monitoring_history: MonitoringHistoryEntry[];
  latest_score?: MonitorLatestScore | null;
}

export interface MonitorChangeEntry {
  run_id?: string;
  vendor_id: string;
  vendor_name?: string;
  previous_risk?: string | null;
  current_risk?: string | null;
  change_type?: "no_change" | "risk_increase" | "risk_decrease" | "new_findings" | "resolved_findings" | string;
  delta_summary?: string;
  score_before?: number | null;
  score_after?: number | null;
  new_findings_count?: number;
  resolved_findings_count?: number;
  sources_triggered?: string[];
  started_at?: string;
  completed_at?: string;
  checked_at?: string;
}

export interface MonitorRunEntry {
  run_id: string;
  vendor_id: string;
  vendor_name?: string;
  started_at: string;
  completed_at?: string;
  status: "completed" | "pending" | "failed" | string;
  change_type?: string;
  delta_summary?: string;
  score_before?: number | null;
  score_after?: number | null;
  new_findings_count?: number;
  resolved_findings_count?: number;
  sources_triggered?: string[];
  checked_at?: string;
}

export interface MonitorRunHistory {
  vendor_id: string;
  vendor_name: string;
  runs: MonitorRunEntry[];
}

export interface ProvenanceSource {
  connector: string;
  fetched_at?: string;
  confidence: number;
  raw_snippet?: string;
  title?: string;
  url?: string;
  artifact_ref?: string;
  source_class?: string;
  authority_level?: string;
  access_model?: string;
  claim_id?: string;
}

export interface EntityProvenance {
  entity: {
    id: string;
    canonical_name: string;
    entity_type: string;
    country?: string;
  };
  sources: ProvenanceSource[];
  corroboration_count: number;
  first_seen?: string | null;
  last_seen?: string | null;
}

export interface RelationshipProvenance {
  relationship: {
    source_entity_id: string;
    target_entity_id: string;
    rel_type: string;
    claim_records?: Array<{
      claim_id: string;
      data_source: string;
      confidence: number;
      claim_value?: string;
      first_observed_at?: string;
      last_observed_at?: string;
      evidence_records?: Array<{
        evidence_id: string;
        source: string;
        snippet?: string;
        title?: string;
        url?: string;
        observed_at?: string;
      }>;
    }>;
  };
  sources: ProvenanceSource[];
  corroboration_count: number;
  first_seen?: string | null;
  last_seen?: string | null;
}

export async function runCaseMonitor(caseId: string): Promise<CaseMonitorStatus> {
  return json<CaseMonitorStatus>(`/api/cases/${caseId}/monitor`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchCaseMonitorStatus(caseId: string, sweepId: string): Promise<CaseMonitorStatus> {
  return json<CaseMonitorStatus>(`/api/cases/${caseId}/monitor/${sweepId}`);
}

export async function fetchCaseMonitoringHistory(caseId: string, limit = 10): Promise<CaseMonitoringHistory> {
  return json<CaseMonitoringHistory>(`/api/cases/${caseId}/monitoring?limit=${limit}`);
}

export async function fetchMonitorChanges(limit = 20, since?: string): Promise<{ changes: MonitorChangeEntry[] }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (since) params.set("since", since);
  return json<{ changes: MonitorChangeEntry[] }>(`/api/monitor/changes?${params}`);
}

export async function fetchMonitorRunHistory(caseId: string, limit = 10): Promise<MonitorRunHistory> {
  return json<MonitorRunHistory>(`/api/cases/${caseId}/monitor/history?limit=${limit}`);
}

export async function fetchEntityProvenance(entityId: string): Promise<EntityProvenance> {
  return json<EntityProvenance>(`/api/graph/entity/${entityId}/provenance`);
}

export async function fetchRelationshipProvenance(relationshipId: number): Promise<RelationshipProvenance> {
  return json<RelationshipProvenance>(`/api/graph/relationship/${relationshipId}/provenance`);
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
  policy_basis?: {
    composite_threshold?: number;
    prefilter?: Record<string, number>;
    signal_weights?: Record<string, number>;
    post_match_gates?: Record<string, number>;
  };
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

export interface AIAnalysisJob {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  case_id?: string;
  input_hash?: string;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  analysis_id?: number | null;
}

export interface AIAnalysisStatus {
  status: "missing" | "pending" | "running" | "ready" | "completed" | "failed";
  case_id: string;
  vendor_name: string;
  analysis?: AIAnalysis;
  job?: AIAnalysisJob;
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

export async function fetchAIAnalysisStatus(caseId: string): Promise<AIAnalysisStatus> {
  return json<AIAnalysisStatus>(`/api/cases/${caseId}/analysis-status`);
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

/* ---- Beta Ops ---- */

export interface BetaFeedbackPayload {
  summary: string;
  details?: string;
  category?: "bug" | "confusion" | "request" | "general";
  severity?: "low" | "medium" | "high";
  workflow_lane?: "counterparty" | "cyber" | "export";
  screen?: string;
  case_id?: string;
  metadata?: Record<string, unknown>;
}

export interface BetaFeedbackEntry extends BetaFeedbackPayload {
  id: number;
  user_id?: string | null;
  user_email?: string | null;
  user_role?: string | null;
  status: string;
  created_at: string;
}

export interface BetaEventPayload {
  event_name: string;
  workflow_lane?: "counterparty" | "cyber" | "export";
  screen?: string;
  case_id?: string;
  metadata?: Record<string, unknown>;
}

export interface BetaOpsCount {
  count: number;
  severity?: string;
  workflow_lane?: string;
  event_name?: string;
}

export interface BetaOpsSummary {
  hours: number;
  open_feedback_count: number;
  feedback_last_24h: number;
  recent_event_count: number;
  feedback_by_severity: BetaOpsCount[];
  feedback_by_lane: BetaOpsCount[];
  event_counts: BetaOpsCount[];
  event_counts_by_lane: BetaOpsCount[];
}

export async function submitBetaFeedback(payload: BetaFeedbackPayload): Promise<{ status: string; feedback_id: number }> {
  return json("/api/beta/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function trackBetaEvent(payload: BetaEventPayload): Promise<{ status: string; event_id: number }> {
  return json("/api/beta/events", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBetaFeedback(limit = 100): Promise<BetaFeedbackEntry[]> {
  const result = await json<{ feedback: BetaFeedbackEntry[] }>(`/api/beta/feedback?limit=${limit}`);
  return result.feedback;
}

export async function fetchBetaOpsSummary(hours = 168): Promise<BetaOpsSummary> {
  return json<BetaOpsSummary>(`/api/beta/ops/summary?hours=${hours}`);
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
  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }
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

// ---- Phase 4: Portfolio Intelligence ----

export async function fetchPortfolioSnapshot(): Promise<Record<string, unknown>> {
  return json("/api/portfolio/snapshot");
}

export async function fetchPortfolioTrend(days = 30): Promise<{ trend: Record<string, unknown>[] }> {
  return json(`/api/portfolio/trend?days=${days}`);
}

export async function fetchPortfolioAnomalies(limit = 50): Promise<{ anomalies: Record<string, unknown>[]; total: number }> {
  return json(`/api/portfolio/anomalies?limit=${limit}`);
}

export async function fetchScoreHistory(caseId: string, limit = 30): Promise<{ history: Record<string, unknown>[] }> {
  return json(`/api/cases/${caseId}/score-history?limit=${limit}`);
}

export async function runDriftCheck(caseId: string): Promise<Record<string, unknown>> {
  return json(`/api/cases/${caseId}/drift`, { method: "POST" });
}

// ---- Mission Threads ----

export interface MissionThreadHeader {
  id: string;
  name: string;
  description: string;
  lane: string;
  program: string;
  theater: string;
  mission_type: string;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  member_count: number;
}

export interface MissionThreadMemberScore {
  member_id: string;
  vendor_id: string;
  entity_id: string;
  label: string;
  role: string;
  criticality: string;
  criticality_score: number;
  decision_importance: number;
  structural_importance: number;
  mission_impact_score: number;
  brittle_node_score: number;
  resilience_score: number;
  substitute_coverage_score: number;
  dependency_concentration: number;
  control_path_quality: number;
  single_point_of_failure_signal: number;
  recommended_action: string;
}

export interface MissionThreadSummary {
  mission_thread: MissionThreadHeader;
  member_count: number;
  vendor_member_count: number;
  entity_member_count: number;
  alternate_member_count: number;
  role_distribution: Record<string, number>;
  criticality_distribution: Record<string, number>;
  tier_distribution: Record<string, number>;
  members: Array<Record<string, unknown>>;
  graph: {
    entity_count: number;
    relationship_count: number;
    root_entity_ids: string[];
    entity_type_distribution: Record<string, number>;
    relationship_type_distribution: Record<string, number>;
    intelligence: Record<string, unknown>;
    resilience_summary: {
      model_version?: string;
      average_resilience_score?: number;
      average_brittle_node_score?: number;
      critical_brittle_member_count?: number;
      top_brittle_members?: MissionThreadMemberScore[];
      top_resilient_members?: MissionThreadMemberScore[];
      top_nodes_by_mission_importance?: Array<Record<string, unknown>>;
    };
    top_nodes_by_mission_importance: Array<Record<string, unknown>>;
  };
  resilience: {
    summary: {
      model_version?: string;
      average_resilience_score?: number;
      average_brittle_node_score?: number;
      critical_brittle_member_count?: number;
      top_brittle_members?: MissionThreadMemberScore[];
      top_resilient_members?: MissionThreadMemberScore[];
      top_nodes_by_mission_importance?: Array<Record<string, unknown>>;
    };
    member_scores: MissionThreadMemberScore[];
  };
}

export interface MissionThreadGraph {
  mission_thread_id: string;
  thread: MissionThreadHeader;
  member_count: number;
  vendor_member_count: number;
  entity_member_count: number;
  entity_count: number;
  relationship_count: number;
  entity_type_distribution: Record<string, number>;
  relationship_type_distribution: Record<string, number>;
  entities: Array<Record<string, unknown>>;
  relationships: GraphEdge[];
  intelligence: Record<string, unknown>;
  resilience_summary: Record<string, unknown>;
  analytics: {
    node_metrics?: Record<string, Record<string, unknown>>;
    top_nodes_by_mission_importance?: Array<Record<string, unknown>>;
  };
  member_resilience: MissionThreadMemberScore[];
}

export interface MissionThreadMemberPassport {
  passport_version: string;
  mission_thread: MissionThreadHeader;
  member: Record<string, unknown>;
  mission_context: {
    role: string;
    criticality: string;
    subsystem: string;
    site: string;
    is_alternate: boolean;
    alternate_members: Array<Record<string, unknown>>;
    focus_node_ids: string[];
    single_point_of_failure: boolean;
  };
  resilience: {
    member: MissionThreadMemberScore;
    thread: Record<string, unknown>;
  };
  focus_entities: Array<Record<string, unknown>>;
  graph: {
    entity_count: number;
    relationship_count: number;
    relationship_type_distribution: Record<string, number>;
    top_nodes_by_mission_importance: Array<Record<string, unknown>>;
  };
  supplier_passport: Record<string, unknown> | null;
}

export interface MissionThreadBriefingExposure {
  rel_type: string;
  source_entity_id: string;
  target_entity_id: string;
  source_label: string;
  target_label: string;
  intelligence_score: number;
  mission_importance: number;
  evidence: string;
  vendor_id: string;
}

export interface MissionThreadBriefingGap {
  category: string;
  severity: string;
  detail: string;
  member_id?: string | number;
}

export interface MissionThreadBriefing {
  briefing_version: string;
  generated_at: string;
  mission_thread: MissionThreadHeader;
  operator_readout: string;
  overview: {
    member_count: number;
    vendor_member_count: number;
    entity_member_count: number;
    alternate_member_count: number;
    entity_count: number;
    relationship_count: number;
    resilience_summary: Record<string, unknown>;
  };
  top_brittle_members: MissionThreadMemberScore[];
  top_control_path_exposures: MissionThreadBriefingExposure[];
  mission_important_nodes: Array<Record<string, unknown>>;
  unresolved_evidence_gaps: MissionThreadBriefingGap[];
  recommended_mitigations: string[];
  member_briefs: MissionThreadMemberPassport[];
}

export async function fetchMissionThreads(limit = 100): Promise<{ mission_threads: MissionThreadHeader[]; total: number }> {
  return json(`/api/mission-threads?limit=${limit}`);
}

export async function createMissionThread(payload: Record<string, unknown>): Promise<MissionThreadHeader> {
  return json("/api/mission-threads", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchMissionThread(id: string): Promise<MissionThreadHeader & { members?: Array<Record<string, unknown>> }> {
  return json(`/api/mission-threads/${id}`);
}

export async function fetchMissionThreadSummary(id: string, depth = 2): Promise<MissionThreadSummary> {
  return json(`/api/mission-threads/${id}/summary?depth=${depth}`);
}

export async function fetchMissionThreadGraph(id: string, depth = 2): Promise<MissionThreadGraph> {
  return json(`/api/mission-threads/${id}/graph?depth=${depth}`);
}

export async function fetchMissionThreadMemberPassport(id: string, memberId: number, depth = 2, mode = "full"): Promise<MissionThreadMemberPassport> {
  return json(`/api/mission-threads/${id}/members/${memberId}/passport?depth=${depth}&mode=${encodeURIComponent(mode)}`);
}

export async function fetchMissionThreadBriefing(id: string, depth = 2, mode = "control"): Promise<MissionThreadBriefing> {
  return json(`/api/mission-threads/${id}/briefing?depth=${depth}&mode=${encodeURIComponent(mode)}`);
}

// ---- Graph Analytics ----

export interface GraphIntelligenceResult {
  graph_size: { nodes: number; edges: number };
  top_entities_by_importance: Array<Record<string, unknown>>;
  top_entities_by_decision_importance?: Array<Record<string, unknown>>;
  top_entities_by_structural_importance?: Array<Record<string, unknown>>;
  top_entities_by_risk: Array<Record<string, unknown>>;
  risk_distribution: Record<string, number>;
  communities: { count: number; modularity: number; largest_community_size: number };
  temporal: Record<string, unknown>;
}

export interface EnrichedGraphNode {
  id: string;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  country: string;
  centrality_composite: number;
  centrality_structural?: number;
  centrality_decision?: number;
  centrality_degree: number;
  centrality_betweenness: number;
  centrality_pagerank: number;
  sanctions_exposure: number;
  risk_level: "CLEAR" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  community_id: number | null;
}

export interface GraphEdge {
  source_entity_id: string;
  target_entity_id: string;
  rel_type: string;
  confidence: number;
  data_source: string;
  evidence: string;
}

export interface FullGraphIntelligence {
  nodes: EnrichedGraphNode[];
  edges: GraphEdge[];
  summary: {
    total_nodes: number;
    total_edges: number;
    risk_distribution: Record<string, number>;
    type_distribution: Record<string, number>;
    community_count: number;
    modularity: number;
  };
  top_by_importance: EnrichedGraphNode[];
  top_by_structural_importance?: EnrichedGraphNode[];
  top_by_risk: EnrichedGraphNode[];
  communities: Array<{
    community_id: number;
    size: number;
    members: string[];
    dominant_type: string;
  }>;
  temporal: Record<string, unknown>;
}

export async function fetchGraphIntelligence(): Promise<GraphIntelligenceResult> {
  return json("/api/graph/analytics/intelligence");
}

export async function fetchFullGraphIntelligence(): Promise<FullGraphIntelligence> {
  return json("/api/graph/full-intelligence");
}

export async function fetchGraphCentrality(): Promise<{ entities: Array<Record<string, unknown>>; count: number }> {
  return json("/api/graph/analytics/centrality");
}

export async function fetchGraphCommunities(): Promise<Record<string, unknown>> {
  return json("/api/graph/analytics/communities");
}

export async function fetchGraphPath(source: string, target: string, mode: "shortest" | "critical" | "all" = "shortest"): Promise<Record<string, unknown>> {
  return json("/api/graph/analytics/path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, target, mode }),
  });
}

export async function fetchGraphSanctionsExposure(): Promise<{ entities: Array<Record<string, unknown>>; count: number }> {
  return json("/api/graph/analytics/sanctions-exposure");
}

export async function fetchGraphTemporal(): Promise<Record<string, unknown>> {
  return json("/api/graph/analytics/temporal");
}

export async function fetchPersonNetworkRisk(name: string, nationalities: string[] = []): Promise<Record<string, unknown>> {
  return json("/api/export/person-network-risk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, nationalities }),
  });
}

export async function screenPerson(payload: Record<string, unknown>): Promise<PersonScreeningResult> {
  return json<PersonScreeningResult>("/api/export/screen-person", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function screenBatchCsv(caseId: string, file: File): Promise<BatchScreeningCsvResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("case_id", caseId);
  return submitForm<BatchScreeningCsvResponse>("/api/export/screen-batch-csv", formData);
}

export async function fetchCaseScreenings(caseId: string): Promise<CaseScreeningsResponse> {
  return json<CaseScreeningsResponse>(`/api/export/screenings/${caseId}`);
}

/* ---- Transaction Authorization (S12) ---- */

export async function runTransactionAuthorization(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return json("/api/export/authorize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listTransactionAuthorizations(
  caseId?: string,
  posture?: string,
  limit?: number,
): Promise<{ authorizations: Record<string, unknown>[]; count: number }> {
  const params = new URLSearchParams();
  if (caseId) params.set("case_id", caseId);
  if (posture) params.set("posture", posture);
  if (limit) params.set("limit", String(limit));
  const qs = params.toString();
  return json(`/api/export/authorizations${qs ? `?${qs}` : ""}`);
}

export async function fetchTransactionAuthorization(authId: string): Promise<Record<string, unknown>> {
  return json(`/api/export/authorizations/${authId}`);
}

/* ---- Graph Workspaces ---- */

export interface GraphWorkspace {
  id: string;
  name: string;
  description: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  pinned_nodes: string[];
  annotations: Record<string, string>;
  filter_state: Record<string, unknown>;
  layout_mode: string;
  viewport: { x?: number; y?: number; zoom?: number };
  node_positions: Record<string, { x: number; y: number }>;
}

export async function listWorkspaces(): Promise<{ workspaces: GraphWorkspace[]; total: number }> {
  return json("/api/graph/workspaces");
}

export async function createWorkspace(data: Partial<GraphWorkspace> & { name: string }): Promise<GraphWorkspace> {
  return json("/api/graph/workspaces", { method: "POST", body: JSON.stringify(data) });
}

export async function fetchWorkspace(id: string): Promise<GraphWorkspace> {
  return json(`/api/graph/workspaces/${id}`);
}

export async function updateWorkspace(id: string, data: Partial<GraphWorkspace>): Promise<GraphWorkspace> {
  return json(`/api/graph/workspaces/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export async function deleteWorkspace(id: string): Promise<{ deleted: boolean }> {
  return json(`/api/graph/workspaces/${id}`, { method: "DELETE" });
}

export async function findShortestPath(sourceId: string, targetId: string, maxDepth?: number): Promise<{
  path: Array<{
    from_id: string; from_name: string; from_type: string;
    to_id: string; to_name: string; to_type: string;
    rel_type: string; confidence: number; direction: string;
  }> | null;
  found: boolean;
  hops: number;
  source_id: string;
  target_id: string;
}> {
  return json("/api/graph/shortest-path", {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId, target_id: targetId, max_depth: maxDepth }),
  });
}

export async function simulateRiskPropagation(sourceId: string, maxHops?: number, decayFactor?: number): Promise<{
  source: { id: string; name: string; type: string; risk_level: string; base_risk: number };
  waves: Array<{
    hop: number;
    entities: Array<{
      id: string; name: string; type: string; existing_risk_level: string;
      received_risk: number; rel_type: string; from_id: string;
    }>;
  }>;
  total_affected: number;
  max_risk_propagated: number;
}> {
  return json("/api/graph/propagation", {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId, max_hops: maxHops, decay_factor: decayFactor }),
  });
}

/* ---- Graph Briefing PDF Export ---- */

export async function generateGraphBriefing(payload: Record<string, unknown>): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${BASE}/api/graph/briefing`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    clearSession();
    onAuthError?.();
    throw new Error("Session expired. Please log in again.");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Briefing generation failed: ${res.status} ${text}`);
  }
  return res.blob();
}


export async function reAuthorizeTransaction(
  authId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return json(`/api/export/re-authorize/${authId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAuthorizationHistory(
  caseId: string,
  limit?: number,
  offset?: number,
): Promise<{
  case_id: string;
  total: number;
  offset: number;
  limit: number;
  count: number;
  authorizations: Record<string, unknown>[];
}> {
  const params = new URLSearchParams();
  if (limit) params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  const qs = params.toString();
  return json(`/api/cases/${caseId}/authorization-history${qs ? `?${qs}` : ""}`);
}


/* ---- Compliance Dashboard ---- */

export interface ComplianceSummary {
  total_cases: number;
  total_alerts: number;
  risk_distribution: Record<string, number>;
  compliance_score: number;
  timestamp?: string;
  error?: string;
}

export interface ScreeningRecord {
  case_id: string;
  vendor_name: string;
  status: string;
  created_at: string;
  score?: Record<string, unknown> | null;
}

export interface CounterpartyLaneData {
  cases_screened: number;
  high_risk_vendors: number;
  pending_reviews: number;
  recent_screenings: ScreeningRecord[];
  risk_trend: Array<{ date: string; counts: Record<string, number> }>;
  error?: string;
}

export interface AuthorizationRecord {
  case_id: string;
  vendor_name: string;
  recommendation?: string;
  created_at: string;
}

export interface ExportLaneData {
  total_authorizations: number;
  posture_distribution: Record<string, number>;
  recent_authorizations: AuthorizationRecord[];
  pending_license_applications: number;
  error?: string;
}

export interface CentralityEntity {
  entity_id: string;
  name: string;
  type: string;
  relationship_count: number;
}

export interface RiskPropagation {
  entity_id: string;
  risk_score: number;
  propagated_at: string;
}

export interface CyberLaneData {
  entities_in_graph: number;
  relationships: number;
  communities: number;
  high_centrality_entities: CentralityEntity[];
  recent_risk_propagations: RiskPropagation[];
  error?: string;
}

export interface CrossLaneInsights {
  vendors_with_export_issues: Array<{ case_id: string; vendor_name: string; status: string }>;
  graph_connected_high_risk: Array<{ entity_id: string; name: string; type: string }>;
  compliance_gaps: Array<{ type: string; count: number; severity: string; description: string }>;
  error?: string;
}

export interface ActivityItem {
  type: string;
  case_id: string;
  vendor_name: string;
  action: string;
  timestamp: string;
}

export interface ComplianceDashboardData {
  summary: ComplianceSummary;
  counterparty_lane: CounterpartyLaneData;
  export_lane: ExportLaneData;
  cyber_lane: CyberLaneData;
  cross_lane_insights: CrossLaneInsights;
  activity_feed: ActivityItem[];
}

export async function fetchComplianceDashboard(caseId?: string): Promise<ComplianceDashboardData> {
  const params = new URLSearchParams();
  if (caseId) params.set("case_id", caseId);
  const qs = params.toString();
  return json(`/api/compliance-dashboard${qs ? `?${qs}` : ""}`);
}

// ---------------------------------------------------------------------------
// Graph Training Review API
// ---------------------------------------------------------------------------

export interface PredictedLinkQueueItem {
  id: number;
  source_entity_id: string;
  source_entity_name: string;
  target_entity_id: string;
  target_entity_name: string;
  predicted_relation: string;
  predicted_edge_family: string;
  edge_already_exists?: boolean;
  score: number;
  model_version: string;
  candidate_rank?: number | null;
  reviewed: boolean;
  analyst_confirmed?: boolean | null;
  rejection_reason?: string | null;
  review_notes?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  relationship_created?: boolean;
  promoted_relationship_id?: number | null;
  created_at?: string | null;
}

export interface PredictedLinkQueueSummary {
  entity_id: string;
  entity_name: string;
  model_version: string;
  top_k: number;
  queued_count: number;
  existing_count: number;
  count: number;
  items: PredictedLinkQueueItem[];
}

export interface PredictedLinkReviewQueueResponse {
  count: number;
  predictions: PredictedLinkQueueItem[];
}

export interface PredictedLinkEdgeFamilyStats {
  edge_family: string;
  total_links: number;
  reviewed_links: number;
  pending_links: number;
  novel_pending_links?: number;
  confirmed_links: number;
  promoted_relationships: number;
}

export interface PredictedLinkSourceEntityStats {
  source_entity_id: string;
  source_entity_name: string;
  total_links: number;
  pending_links: number;
  reviewed_links: number;
  promoted_relationships: number;
}

export interface MissingEdgeRecoveryMetrics {
  queue_depth: number;
  novel_pending_links?: number;
  existing_pending_links?: number;
  analyst_confirmation_rate: number;
  review_coverage_pct: number;
  novel_edge_yield: number;
  unsupported_promoted_edge_rate: number;
  mean_review_latency_hours: number;
  median_pending_age_hours: number;
  p95_pending_age_hours: number;
  stale_pending_24h: number;
  stale_pending_7d: number;
}

export interface PredictedLinkReviewStats {
  total_links: number;
  reviewed_links: number;
  pending_links: number;
  novel_pending_links?: number;
  existing_pending_links?: number;
  confirmed_links: number;
  rejected_links: number;
  promoted_relationships: number;
  unsupported_promoted_edges: number;
  unsupported_promoted_edge_rate: number;
  confirmation_rate: number;
  review_coverage_pct: number;
  latest_activity_at?: string | null;
  by_edge_family: PredictedLinkEdgeFamilyStats[];
  by_source_entity: PredictedLinkSourceEntityStats[];
  rejection_reason_counts?: Array<{
    rejection_reason: string;
    count: number;
  }>;
  scope?: {
    source_entity_id?: string | null;
  };
  missing_edge_recovery: MissingEdgeRecoveryMetrics;
}

export interface PredictedLinkReviewInput {
  id: number;
  confirmed: boolean;
  notes?: string;
  rejection_reason?: string;
}

export interface PredictedLinkReviewBatchResponse {
  reviewed_count: number;
  confirmed_count: number;
  rejected_count: number;
  reviewed_by: string;
  reviewed_at: string;
  items: Array<{
    id: number;
    status: string;
    relationship_created: boolean;
    promoted_relationship_id?: number | null;
  }>;
}

export interface GraphTrainingDashboardStage {
  stage_id: string;
  verdict: string;
  objective: string;
}

export interface GraphTrainingDashboardSnapshot {
  verdict?: string | null;
  generated_at?: string | null;
  path?: string | null;
}

export interface GraphTrainingDashboardBenchmark extends GraphTrainingDashboardSnapshot {
  data_foundation_verdict?: string | null;
  passing_stage_count: number;
  total_stage_count: number;
  stage_results: GraphTrainingDashboardStage[];
}

export interface GraphTrainingDashboardNeo4j extends GraphTrainingDashboardSnapshot {
  node_count?: number | null;
  relationship_count?: number | null;
}

export interface GraphTrainingDashboardLiveTranche {
  generated_at?: string | null;
  path?: string | null;
  reviewed_links: number;
  pending_links: number;
  novel_pending_links: number;
  confirmed_links: number;
  rejected_links: number;
  review_coverage_pct: number;
  confirmation_rate: number;
  ownership_control_hits_at_10: number;
  ownership_control_mrr: number;
  intermediary_route_queries_evaluated: number;
  cyber_dependency_queries_evaluated: number;
}

export interface GraphTrainingDashboard {
  generated_at: string;
  readiness: GraphTrainingDashboardSnapshot;
  neo4j: GraphTrainingDashboardNeo4j;
  benchmark: GraphTrainingDashboardBenchmark;
  live_tranche: GraphTrainingDashboardLiveTranche;
}

export async function queuePredictedLinks(entityId: string, topK = 25): Promise<PredictedLinkQueueSummary> {
  return json(`/api/graph/predicted-links/${encodeURIComponent(entityId)}/queue`, {
    method: "POST",
    body: JSON.stringify({ top_k: topK }),
  });
}

export async function fetchPredictedLinkReviewQueue(params: {
  reviewed?: boolean;
  confirmed?: boolean;
  novelOnly?: boolean;
  edgeFamily?: string;
  sourceEntityId?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<PredictedLinkReviewQueueResponse> {
  const search = new URLSearchParams();
  if (params.reviewed !== undefined) search.set("reviewed", String(params.reviewed));
  if (params.confirmed !== undefined) search.set("confirmed", String(params.confirmed));
  if (params.novelOnly !== undefined) search.set("novel_only", String(params.novelOnly));
  if (params.edgeFamily) search.set("edge_family", params.edgeFamily);
  if (params.sourceEntityId) search.set("source_entity_id", params.sourceEntityId);
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  return json(`/api/graph/predicted-links/review-queue${qs ? `?${qs}` : ""}`);
}

export async function fetchPredictedLinkReviewStats(sourceEntityId?: string): Promise<PredictedLinkReviewStats> {
  const search = new URLSearchParams();
  if (sourceEntityId) search.set("source_entity_id", sourceEntityId);
  const qs = search.toString();
  return json(`/api/graph/predicted-links/review-stats${qs ? `?${qs}` : ""}`);
}

export async function fetchGraphTrainingDashboard(): Promise<GraphTrainingDashboard> {
  return json("/api/graph/training-dashboard");
}

export async function reviewPredictedLinksBatch(
  reviews: PredictedLinkReviewInput[],
): Promise<PredictedLinkReviewBatchResponse> {
  return json("/api/graph/predicted-links/review-batch", {
    method: "POST",
    body: JSON.stringify({ reviews }),
  });
}

// ---------------------------------------------------------------------------
// Neo4j Graph Intelligence API
// ---------------------------------------------------------------------------

export interface Neo4jHealthResponse {
  neo4j_available: boolean;
  timestamp: string;
}

export interface Neo4jSyncResponse {
  status: string;
  entities_synced: number;
  relationships_synced: number;
  duration_ms: number;
  timestamp: string;
}

export interface Neo4jNeighbor {
  neighbor_id: string;
  neighbor_name: string;
  entity_type: string;
  rel_type: string;
  rel_confidence: number;
}

export interface Neo4jNeighborsResponse {
  status: string;
  entity_id: string;
  neighbors: Neo4jNeighbor[];
  neighbor_count: number;
}

export interface Neo4jPathNode {
  id: string;
  name: string;
  type: string;
}

export interface Neo4jPathResponse {
  status: string;
  source_id: string;
  target_id: string;
  path_found: boolean;
  path_length: number;
  nodes: Neo4jPathNode[];
  relationships: Array<{ type: string; confidence: number }>;
}

export interface Neo4jNetworkResponse {
  entity_id: string;
  nodes: Array<{
    id: string;
    canonical_name: string;
    entity_type: string;
    country: string;
    confidence: number;
    risk_level: string;
    depth: number;
  }>;
  edges: Array<{
    source: string;
    target: string;
    rel_type: string;
    confidence: number;
  }>;
  total_nodes: number;
  total_edges: number;
}

export interface Neo4jRiskResponse {
  status: string;
  entity_id: string;
  base_risk: string;
  network_risk: number;
  risk_score: number;
  connected_risks: Array<{
    entity_id: string;
    entity_name: string;
    risk_level: string;
    relationship_types: string[];
    propagation_weight: number;
  }>;
  duration_ms: number;
}

export interface Neo4jCentralityResponse {
  status: string;
  entity_id: string;
  canonical_name: string;
  entity_type: string;
  degree_centrality: number;
  total_relationships: number;
  bridged_entities: number;
  neighbor_types: string[];
  relationship_types_used: string[];
  influence_score: number;
  risk_level: string;
}

export interface Neo4jTopEntitiesResponse {
  status: string;
  entities: Array<{
    id: string;
    name: string;
    entity_type: string;
    risk_level: string;
    degree: number;
    total_relationships: number;
  }>;
  count: number;
}

export interface Neo4jStatsResponse {
  node_count: number;
  node_types: Record<string, number>;
  relationship_count: number;
  relationship_types: Record<string, number>;
}

export async function fetchNeo4jHealth(): Promise<Neo4jHealthResponse> {
  return json("/api/neo4j/health");
}

export async function triggerNeo4jSync(): Promise<Neo4jSyncResponse> {
  return json("/api/neo4j/sync", { method: "POST" });
}

export async function triggerNeo4jIncrementalSync(since: string): Promise<Neo4jSyncResponse> {
  return json("/api/neo4j/sync/incremental", {
    method: "POST",
    body: JSON.stringify({ since }),
  });
}

export async function fetchNeo4jNeighbors(entityId: string): Promise<Neo4jNeighborsResponse> {
  return json(`/api/neo4j/neighbors/${entityId}`);
}

export async function fetchNeo4jNetwork(entityId: string, depth?: number): Promise<Neo4jNetworkResponse> {
  const params = depth ? `?depth=${depth}` : "";
  return json(`/api/neo4j/network/${entityId}${params}`);
}

export async function fetchNeo4jPath(sourceId: string, targetId: string): Promise<Neo4jPathResponse> {
  return json(`/api/neo4j/path/${sourceId}/${targetId}`);
}

export async function fetchNeo4jSharedConnections(entityA: string, entityB: string): Promise<Record<string, unknown>> {
  return json(`/api/neo4j/shared/${entityA}/${entityB}`);
}

export async function fetchNeo4jRisk(entityId: string): Promise<Neo4jRiskResponse> {
  return json(`/api/neo4j/risk/${entityId}`);
}

export async function fetchNeo4jCentrality(entityId: string): Promise<Neo4jCentralityResponse> {
  return json(`/api/neo4j/centrality/${entityId}`);
}

export async function fetchNeo4jTopEntities(limit?: number): Promise<Neo4jTopEntitiesResponse> {
  const params = limit ? `?limit=${limit}` : "";
  return json(`/api/neo4j/top-entities${params}`);
}

export async function fetchNeo4jStats(): Promise<Neo4jStatsResponse> {
  return json("/api/neo4j/stats");
}
