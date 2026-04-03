import type {
  AIAnalysisStatus,
  CaseGraphData,
  CaseMonitoringHistory,
  ConnectorStatus,
  EnrichmentReport,
  SupplierPassport,
} from "@/lib/api";
import type { Calibration, VettingCase } from "@/lib/types";

export type EvidenceTabId = "intel" | "findings" | "events" | "model" | "graph";

export interface EvidenceTabItem {
  id: EvidenceTabId;
  label: string;
  disabled?: boolean;
}

export interface ToneConfig {
  color: string;
  background: string;
  border: string;
  label?: string;
}

export interface MonitoringHistorySummary {
  runs: number;
  changed: number;
  newFindings: number;
}

export interface MonitoringLaneCopy {
  title: string;
  detail: string;
  runsLabel: string;
  changedLabel: string;
  findingsLabel: string;
  loadingLabel: string;
  emptyTitle: string;
  emptyDetail: string;
  findingsText: (count: number) => string;
  shiftedText: string;
}

export interface BatchScreeningRow extends Record<string, unknown> {
  person_name?: string;
  screening_status?: string;
  composite_score?: number;
  recommended_action?: string;
  nationalities?: string[];
}

export interface PersonScreeningRecord extends Record<string, unknown> {
  screening_status?: string;
  status?: string;
  composite_score?: number;
  matched_lists?: Array<Record<string, unknown>>;
  deemed_export?: unknown;
  deemed_export_assessment?: string;
  recommended_action?: string;
  created_at?: string;
}

export interface SprsAssessmentContainer {
  assessment_summary?: Record<string, unknown> | null;
}

export interface AiBriefViewState {
  status: AIAnalysisStatus | null;
  summary: string | null;
  detail: string | null;
  ready: boolean;
}

export interface CaseDetailViewModel {
  caseData: VettingCase;
  calibration: Calibration | null;
  enrichment: EnrichmentReport | null;
  graphData: CaseGraphData | null;
  supplierPassport: SupplierPassport | null;
  monitoringHistory: CaseMonitoringHistory | null;
}

export type SourceStatusMap = Record<string, ConnectorStatus>;
