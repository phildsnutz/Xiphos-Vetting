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

export interface EnrichmentReport {
  overall_risk: string;
  summary: string;
  identifiers: Record<string, string>;
  findings: Array<{
    source: string;
    title: string;
    detail: string;
    severity: string;
  }>;
  connector_results: Record<string, unknown>;
  total_elapsed_ms: number;
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
  user_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  detail: string;
  ip_address: string;
  outcome: string;
}

export async function fetchAuditLog(limit = 100): Promise<AuditEntry[]> {
  return json<AuditEntry[]>(`/api/audit?limit=${limit}`);
}
