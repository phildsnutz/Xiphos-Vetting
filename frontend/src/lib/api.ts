/**
 * Xiphos API client.
 * Base URL defaults to window origin (same-origin deployment)
 * or can be overridden via VITE_API_URL env var.
 */

const BASE = import.meta.env.VITE_API_URL ?? "";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

/* ---- Cases ---- */

export interface ApiCase {
  id: string;
  vendor_name: string;
  status: string;
  created_at: string;
  score: Record<string, unknown> | null;
}

export async function fetchCases(limit = 100): Promise<ApiCase[]> {
  const data = await json<{ cases: ApiCase[] }>(`/api/cases?limit=${limit}`);
  return data.cases;
}

export async function fetchCase(id: string): Promise<ApiCase> {
  return json<ApiCase>(`/api/cases/${id}`);
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
  programType = "standard_industrial",
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

/* ---- OSINT Enrichment ---- */

export interface EnrichmentFinding {
  source: string;
  category: string;
  title: string;
  detail: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  confidence: number;
  url: string;
}

export interface ConnectorStatus {
  has_data: boolean;
  findings_count: number;
  elapsed_ms: number;
  error: string;
}

export interface EnrichmentReport {
  vendor_name: string;
  country: string;
  enriched_at: string;
  total_elapsed_ms: number;
  overall_risk: string;
  summary: {
    findings_total: number;
    critical: number;
    high: number;
    medium: number;
    connectors_run: number;
    connectors_with_data: number;
    errors: number;
  };
  identifiers: Record<string, string>;
  findings: EnrichmentFinding[];
  relationships: Array<Record<string, unknown>>;
  risk_signals: Array<Record<string, unknown>>;
  connector_status: Record<string, ConnectorStatus>;
  errors: string[];
  _cached?: boolean;
}

export async function enrichVendor(
  name: string,
  country = "",
  force = false,
): Promise<EnrichmentReport> {
  return json<EnrichmentReport>("/api/enrich", {
    method: "POST",
    body: JSON.stringify({ name, country, force }),
  });
}

export async function enrichCase(caseId: string): Promise<EnrichmentReport> {
  return json<EnrichmentReport>(`/api/cases/${caseId}/enrich`, {
    method: "POST",
  });
}

export async function enrichAndScore(caseId: string): Promise<{
  enrichment: EnrichmentReport;
  score: ScoreResult;
  augmentation: Record<string, unknown>;
}> {
  return json(`/api/cases/${caseId}/enrich-and-score`, {
    method: "POST",
  });
}

export async function fetchEnrichment(caseId: string): Promise<EnrichmentReport | null> {
  try {
    return await json<EnrichmentReport>(`/api/cases/${caseId}/enrichment`);
  } catch {
    return null;
  }
}

/* ---- Health ---- */

export interface HealthStatus {
  status: string;
  version: string;
  osint_enabled: boolean;
  osint_connectors: string[];
  osint_cache: { total_entries: number; fresh_entries: number; total_cache_hits: number };
}

export async function fetchHealth(): Promise<HealthStatus> {
  return json<HealthStatus>("/api/health");
}
