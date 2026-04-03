/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, Dispatch, ReactNode, RefObject, SetStateAction } from "react";
import type {
  AIAnalysisStatus,
  ApiCase,
  CaseGraphData,
  CaseMonitorStatus,
  CaseMonitoringHistory,
  EnrichmentReport,
  ExportArtifactRecord,
  ExportAuthorizationCaseInput,
  ExportAuthorizationGuidance,
  FociArtifactRecord,
  NetworkRiskResult,
  NvdOverlayRecord,
  OscalArtifactRecord,
  PersonScreeningResult,
  RiskStoryline as RiskStorylineType,
  SprsImportRecord,
  SupplierPassport,
  WorkflowControlSummary,
  CyberRiskScore,
} from "@/lib/api";
import {
  fetchCase,
  fetchSupplierPassport,
  fetchEnrichment,
  fetchCaseGraph,
  fetchCaseNetworkRisk,
  fetchCaseMonitoringHistory,
  fetchAIAnalysisStatus,
  runCaseMonitor,
  generateDossier as requestDossier,
  buildProtectedUrl,
  listFociArtifacts,
  listSprsImports,
  listOscalArtifacts,
  listNvdOverlays,
  uploadFociArtifact,
  uploadSprsImport,
  uploadOscalArtifact,
  runNvdOverlay,
  uploadExportArtifact,
  listExportArtifacts,
  fetchCaseScreenings,
  screenPerson,
  screenBatchCsv,
  runTransactionAuthorization,
  listTransactionAuthorizations,
  fetchTransactionAuthorization,
} from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import type { WorkflowLane } from "../portfolio-utils";
import type { TransactionAuthorizationResult } from "../transaction-authorization-panel";
import { emit } from "@/lib/telemetry";

type EvidenceTab = "intel" | "findings" | "events" | "model" | "graph";
type GraphDepth = 3 | 4;
type AnalystView = "decision" | "evidence" | "model";

interface CaseContextValue {
  // Case data
  c: VettingCase;
  cal: VettingCase["cal"] | null;
  isReadOnly: boolean;

  // Enrichment state
  enrichment: EnrichmentReport | null;
  setEnrichment: Dispatch<SetStateAction<EnrichmentReport | null>>;
  loadingEnrichment: boolean;
  setLoadingEnrichment: Dispatch<SetStateAction<boolean>>;
  enriching: boolean;
  setEnriching: Dispatch<SetStateAction<boolean>>;

  // UI state
  analystView: AnalystView;
  setAnalystView: Dispatch<SetStateAction<AnalystView>>;
  evidenceTab: EvidenceTab;
  setEvidenceTab: Dispatch<SetStateAction<EvidenceTab>>;
  pendingEvidenceTab: EvidenceTab | null;
  setPendingEvidenceTab: Dispatch<SetStateAction<EvidenceTab | null>>;
  showStream: boolean;
  setShowStream: Dispatch<SetStateAction<boolean>>;
  showAI: boolean;
  setShowAI: Dispatch<SetStateAction<boolean>>;
  showMoreActions: boolean;
  setShowMoreActions: Dispatch<SetStateAction<boolean>>;
  showSourceStatus: boolean;
  setShowSourceStatus: Dispatch<SetStateAction<boolean>>;
  showMonitorHistory: boolean;
  setShowMonitorHistory: Dispatch<SetStateAction<boolean>>;

  // Graph state
  graphData: CaseGraphData | null;
  setGraphData: Dispatch<SetStateAction<CaseGraphData | null>>;
  graphLoading: boolean;
  setGraphLoading: Dispatch<SetStateAction<boolean>>;
  graphDepth: GraphDepth;
  setGraphDepth: Dispatch<SetStateAction<GraphDepth>>;
  provenanceEntityId: string | null;
  setProvenanceEntityId: Dispatch<SetStateAction<string | null>>;
  provenanceRelId: number | null;
  setProvenanceRelId: Dispatch<SetStateAction<number | null>>;

  // Network & storyline
  networkRisk: NetworkRiskResult | null;
  setNetworkRisk: Dispatch<SetStateAction<NetworkRiskResult | null>>;
  storyline: RiskStorylineType | null;
  setStoryline: Dispatch<SetStateAction<RiskStorylineType | null>>;

  // Supplier passport
  supplierPassport: SupplierPassport | null;
  setSupplierPassport: Dispatch<SetStateAction<SupplierPassport | null>>;
  workflowControlSummary: WorkflowControlSummary | null;
  setWorkflowControlSummary: Dispatch<SetStateAction<WorkflowControlSummary | null>>;

  // Export authorization
  exportAuthorization: ExportAuthorizationCaseInput | null;
  setExportAuthorization: Dispatch<SetStateAction<ExportAuthorizationCaseInput | null>>;
  exportAuthorizationGuidance: ExportAuthorizationGuidance | null;
  setExportAuthorizationGuidance: Dispatch<SetStateAction<ExportAuthorizationGuidance | null>>;
  exportArtifacts: ExportArtifactRecord[];
  setExportArtifacts: Dispatch<SetStateAction<ExportArtifactRecord[]>>;
  uploadingExportArtifact: boolean;
  setUploadingExportArtifact: Dispatch<SetStateAction<boolean>>;

  // FOCI artifacts
  latestFociArtifact: FociArtifactRecord | null;
  setLatestFociArtifact: Dispatch<SetStateAction<FociArtifactRecord | null>>;
  fociArtifacts: FociArtifactRecord[];
  setFociArtifacts: Dispatch<SetStateAction<FociArtifactRecord[]>>;
  uploadingFociArtifact: boolean;
  setUploadingFociArtifact: Dispatch<SetStateAction<boolean>>;

  // SPRS imports
  latestSprsImport: SprsImportRecord | null;
  setLatestSprsImport: Dispatch<SetStateAction<SprsImportRecord | null>>;
  sprsImports: SprsImportRecord[];
  setSprsImports: Dispatch<SetStateAction<SprsImportRecord[]>>;
  uploadingSprsImport: boolean;
  setUploadingSprsImport: Dispatch<SetStateAction<boolean>>;

  // OSCAL artifacts
  latestOscalArtifact: OscalArtifactRecord | null;
  setLatestOscalArtifact: Dispatch<SetStateAction<OscalArtifactRecord | null>>;
  oscalArtifacts: OscalArtifactRecord[];
  setOscalArtifacts: Dispatch<SetStateAction<OscalArtifactRecord[]>>;
  uploadingOscalArtifact: boolean;
  setUploadingOscalArtifact: Dispatch<SetStateAction<boolean>>;

  // NVD overlays
  latestNvdOverlay: NvdOverlayRecord | null;
  setLatestNvdOverlay: Dispatch<SetStateAction<NvdOverlayRecord | null>>;
  nvdOverlays: NvdOverlayRecord[];
  setNvdOverlays: Dispatch<SetStateAction<NvdOverlayRecord[]>>;
  runningNvdOverlay: boolean;
  setRunningNvdOverlay: Dispatch<SetStateAction<boolean>>;
  nvdProductTermsInput: string;
  setNvdProductTermsInput: Dispatch<SetStateAction<string>>;

  // Cyber risk
  cyberRiskScore: CyberRiskScore | null;
  setCyberRiskScore: Dispatch<SetStateAction<CyberRiskScore | null>>;
  loadingCyberScore: boolean;
  setLoadingCyberScore: Dispatch<SetStateAction<boolean>>;

  // Screening
  personScreeningName: string;
  setPersonScreeningName: Dispatch<SetStateAction<string>>;
  personScreeningNationalities: string;
  setPersonScreeningNationalities: Dispatch<SetStateAction<string>>;
  personScreeningEmployer: string;
  setPersonScreeningEmployer: Dispatch<SetStateAction<string>>;
  personScreeningResult: Record<string, unknown> | null;
  setPersonScreeningResult: Dispatch<SetStateAction<Record<string, unknown> | null>>;
  personScreeningHistory: Array<Record<string, unknown>>;
  setPersonScreeningHistory: Dispatch<SetStateAction<Array<Record<string, unknown>>>>;
  screeningPerson: boolean;
  setScreeningPerson: Dispatch<SetStateAction<boolean>>;
  batchScreeningFile: File | null;
  setBatchScreeningFile: Dispatch<SetStateAction<File | null>>;
  batchScreeningResults: Array<Record<string, unknown>>;
  setBatchScreeningResults: Dispatch<SetStateAction<Array<Record<string, unknown>>>>;
  screeningBatch: boolean;
  setScreeningBatch: Dispatch<SetStateAction<boolean>>;
  batchScreeningError: string | null;
  setBatchScreeningError: Dispatch<SetStateAction<string | null>>;

  // Transaction auth
  txAuth: TransactionAuthorizationResult | null;
  setTxAuth: Dispatch<SetStateAction<TransactionAuthorizationResult | null>>;
  txAuthLoading: boolean;
  setTxAuthLoading: Dispatch<SetStateAction<boolean>>;

  // Monitoring
  monitorStatus: CaseMonitorStatus | null;
  setMonitorStatus: Dispatch<SetStateAction<CaseMonitorStatus | null>>;
  monitoringHistory: CaseMonitoringHistory | null;
  setMonitoringHistory: Dispatch<SetStateAction<CaseMonitoringHistory | null>>;
  monitoringHistoryLoading: boolean;
  setMonitoringHistoryLoading: Dispatch<SetStateAction<boolean>>;
  monitorHistoryKey: number;
  setMonitorHistoryKey: Dispatch<SetStateAction<number>>;

  // AI brief
  aiBriefStatus: AIAnalysisStatus | null;
  setAiBriefStatus: Dispatch<SetStateAction<AIAnalysisStatus | null>>;

  // Other state
  rescoring: boolean;
  setRescoring: Dispatch<SetStateAction<boolean>>;
  generating: boolean;
  setGenerating: Dispatch<SetStateAction<boolean>>;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  authorityLaneSelection: { caseId: string; lane: WorkflowLane } | null;
  setAuthorityLaneSelection: Dispatch<SetStateAction<{ caseId: string; lane: WorkflowLane } | null>>;

  // Refs
  evidenceRef: RefObject<HTMLDivElement | null>;
  actionPanelRef: RefObject<HTMLDivElement | null>;
  authorityInputsRef: RefObject<HTMLDivElement | null>;
  sourceStatusRef: RefObject<HTMLDivElement | null>;
  monitorHistoryRef: RefObject<HTMLDivElement | null>;
  moreActionsRef: RefObject<HTMLDivElement | null>;
  fociInputRef: RefObject<HTMLInputElement | null>;
  sprsInputRef: RefObject<HTMLInputElement | null>;
  oscalInputRef: RefObject<HTMLInputElement | null>;
  exportArtifactInputRef: RefObject<HTMLInputElement | null>;

  // Callbacks
  loadGraphData: (depth?: GraphDepth) => Promise<void>;
  refreshDerivedCaseData: (opts?: { enrichmentReport?: EnrichmentReport | null; reloadGraph?: boolean }) => Promise<void>;
  refreshCaseContext: () => Promise<void>;
  refreshAiBriefStatus: () => Promise<void>;
  refreshMonitoringHistory: () => Promise<void>;
  handleEnrich: () => Promise<void>;
  handleStreamComplete: () => Promise<void>;
  handleRescore: () => Promise<void>;
  handleDossier: () => Promise<void>;
  handleMonitor: () => Promise<void>;
  handleFociArtifactSelected: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleExportArtifactSelected: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleSprsImportSelected: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleOscalArtifactSelected: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleRunNvdOverlay: () => Promise<void>;
  handleScreenPerson: () => Promise<void>;
  handleBatchScreenCsv: () => Promise<void>;
  handleDownloadCsvTemplate: () => void;
  handleRunTxAuth: () => Promise<void>;
  loadPersonScreeningHistory: () => Promise<void>;
  loadTxAuth: () => Promise<void>;
}

const CaseContext = createContext<CaseContextValue | null>(null);

export function useCaseDetail(): CaseContextValue {
  const ctx = useContext(CaseContext);
  if (!ctx) {
    throw new Error("useCaseDetail must be used within CaseDetailProvider");
  }
  return ctx;
}

export function CaseDetailProvider({
  c,
  onRescore,
  onDossier,
  onCaseRefresh,
  isReadOnly,
  children,
}: {
  c: VettingCase;
  onRescore?: (caseId: string) => Promise<void>;
  onDossier?: (caseId: string) => Promise<void>;
  onCaseRefresh?: (caseId: string) => Promise<void>;
  isReadOnly: boolean;
  children: ReactNode;
}) {
  const cal = c.cal ?? null;

  // Enrichment
  const [enrichment, setEnrichment] = useState<EnrichmentReport | null>(null);
  const [loadingEnrichment, setLoadingEnrichment] = useState(true);
  const [enriching, setEnriching] = useState(false);

  // UI
  const [analystView, setAnalystView] = useState<AnalystView>("decision");
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>("model");
  const [pendingEvidenceTab, setPendingEvidenceTab] = useState<EvidenceTab | null>(null);
  const [showStream, setShowStream] = useState(false);
  const [showAI, setShowAI] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [showSourceStatus, setShowSourceStatus] = useState(false);
  const [showMonitorHistory, setShowMonitorHistory] = useState(false);

  // Graph
  const [graphData, setGraphData] = useState<CaseGraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphDepth, setGraphDepth] = useState<GraphDepth>(3);
  const [provenanceEntityId, setProvenanceEntityId] = useState<string | null>(null);
  const [provenanceRelId, setProvenanceRelId] = useState<number | null>(null);

  // Network & storyline
  const [networkRisk, setNetworkRisk] = useState<NetworkRiskResult | null>(null);
  const [storyline, setStoryline] = useState<RiskStorylineType | null>(null);

  // Supplier passport
  const [supplierPassport, setSupplierPassport] = useState<SupplierPassport | null>(null);
  const [workflowControlSummary, setWorkflowControlSummary] = useState<WorkflowControlSummary | null>(null);

  // Export
  const [exportAuthorization, setExportAuthorization] = useState<ExportAuthorizationCaseInput | null>(null);
  const [exportAuthorizationGuidance, setExportAuthorizationGuidance] = useState<ExportAuthorizationGuidance | null>(null);
  const [exportArtifacts, setExportArtifacts] = useState<ExportArtifactRecord[]>([]);
  const [uploadingExportArtifact, setUploadingExportArtifact] = useState(false);

  // FOCI
  const [latestFociArtifact, setLatestFociArtifact] = useState<FociArtifactRecord | null>(null);
  const [fociArtifacts, setFociArtifacts] = useState<FociArtifactRecord[]>([]);
  const [uploadingFociArtifact, setUploadingFociArtifact] = useState(false);

  // SPRS
  const [latestSprsImport, setLatestSprsImport] = useState<SprsImportRecord | null>(null);
  const [sprsImports, setSprsImports] = useState<SprsImportRecord[]>([]);
  const [uploadingSprsImport, setUploadingSprsImport] = useState(false);

  // OSCAL
  const [latestOscalArtifact, setLatestOscalArtifact] = useState<OscalArtifactRecord | null>(null);
  const [oscalArtifacts, setOscalArtifacts] = useState<OscalArtifactRecord[]>([]);
  const [uploadingOscalArtifact, setUploadingOscalArtifact] = useState(false);

  // NVD
  const [latestNvdOverlay, setLatestNvdOverlay] = useState<NvdOverlayRecord | null>(null);
  const [nvdOverlays, setNvdOverlays] = useState<NvdOverlayRecord[]>([]);
  const [runningNvdOverlay, setRunningNvdOverlay] = useState(false);
  const [nvdProductTermsInput, setNvdProductTermsInput] = useState("");

  // Cyber
  const [cyberRiskScore, setCyberRiskScore] = useState<CyberRiskScore | null>(null);
  const [loadingCyberScore, setLoadingCyberScore] = useState(false);

  // Screening
  const [personScreeningName, setPersonScreeningName] = useState("");
  const [personScreeningNationalities, setPersonScreeningNationalities] = useState("");
  const [personScreeningEmployer, setPersonScreeningEmployer] = useState("");
  const [personScreeningResult, setPersonScreeningResult] = useState<Record<string, unknown> | null>(null);
  const [personScreeningHistory, setPersonScreeningHistory] = useState<Array<Record<string, unknown>>>([]);
  const [screeningPerson, setScreeningPerson] = useState(false);
  const [batchScreeningFile, setBatchScreeningFile] = useState<File | null>(null);
  const [batchScreeningResults, setBatchScreeningResults] = useState<Array<Record<string, unknown>>>([]);
  const [screeningBatch, setScreeningBatch] = useState(false);
  const [batchScreeningError, setBatchScreeningError] = useState<string | null>(null);

  // Transaction auth
  const [txAuth, setTxAuth] = useState<TransactionAuthorizationResult | null>(null);
  const [txAuthLoading, setTxAuthLoading] = useState(false);

  // Monitoring
  const [monitorStatus, setMonitorStatus] = useState<CaseMonitorStatus | null>(null);
  const [monitoringHistory, setMonitoringHistory] = useState<CaseMonitoringHistory | null>(null);
  const [monitoringHistoryLoading, setMonitoringHistoryLoading] = useState(false);
  const [monitorHistoryKey, setMonitorHistoryKey] = useState(0);

  // AI brief
  const [aiBriefStatus, setAiBriefStatus] = useState<AIAnalysisStatus | null>(null);

  // Other
  const [rescoring, setRescoring] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authorityLaneSelection, setAuthorityLaneSelection] = useState<{ caseId: string; lane: WorkflowLane } | null>(null);

  // Refs
  const evidenceRef = useRef<HTMLDivElement | null>(null);
  const actionPanelRef = useRef<HTMLDivElement | null>(null);
  const authorityInputsRef = useRef<HTMLDivElement | null>(null);
  const sourceStatusRef = useRef<HTMLDivElement | null>(null);
  const monitorHistoryRef = useRef<HTMLDivElement | null>(null);
  const moreActionsRef = useRef<HTMLDivElement | null>(null);
  const fociInputRef = useRef<HTMLInputElement | null>(null);
  const sprsInputRef = useRef<HTMLInputElement | null>(null);
  const oscalInputRef = useRef<HTMLInputElement | null>(null);
  const exportArtifactInputRef = useRef<HTMLInputElement | null>(null);
  const showFociPanel = c.profile === "defense_acquisition" || fociArtifacts.length > 0 || !!latestFociArtifact;
  const showSprsPanel = c.profile === "defense_acquisition" || sprsImports.length > 0 || !!latestSprsImport;
  const showOscalPanel = c.profile === "defense_acquisition" || oscalArtifacts.length > 0 || !!latestOscalArtifact;
  const showNvdPanel = c.profile === "defense_acquisition" || nvdOverlays.length > 0 || !!latestNvdOverlay;

  const refreshCaseContext = useCallback(async () => {
    const [detail, passport] = await Promise.all([
      fetchCase(c.id) as Promise<ApiCase>,
      fetchSupplierPassport(c.id).catch(() => null),
    ]);
    setStoryline(detail.storyline ?? null);
    setExportAuthorization(detail.export_authorization ?? null);
    setExportAuthorizationGuidance(detail.export_authorization_guidance ?? null);
    setLatestFociArtifact(detail.latest_foci_artifact ?? null);
    setLatestSprsImport(detail.latest_sprs_import ?? null);
    setLatestOscalArtifact(detail.latest_oscal_artifact ?? null);
    setLatestNvdOverlay(detail.latest_nvd_overlay ?? null);
    setWorkflowControlSummary(detail.workflow_control_summary ?? null);
    setSupplierPassport(passport);
  }, [c.id]);

  const refreshAiBriefStatus = useCallback(async () => {
    try {
      const status = await fetchAIAnalysisStatus(c.id);
      setAiBriefStatus(status);
    } catch {
      setAiBriefStatus(null);
    }
  }, [c.id]);

  const refreshMonitoringHistory = useCallback(async () => {
    setMonitoringHistoryLoading(true);
    try {
      const history = await fetchCaseMonitoringHistory(c.id, 10);
      setMonitoringHistory(history);
    } catch {
      setMonitoringHistory(null);
    } finally {
      setMonitoringHistoryLoading(false);
    }
  }, [c.id]);

  useEffect(() => {
    let cancelled = false;

    setStoryline(null);
    setExportAuthorization(null);
    setExportAuthorizationGuidance(null);
    setLatestFociArtifact(null);
    setFociArtifacts([]);
    setLatestSprsImport(null);
    setSprsImports([]);
    setLatestOscalArtifact(null);
    setOscalArtifacts([]);
    setLatestNvdOverlay(null);
    setNvdOverlays([]);
    setNvdProductTermsInput("");
    setExportArtifacts([]);
    setWorkflowControlSummary(null);
    setSupplierPassport(null);
    setMonitorStatus(null);
    setMonitoringHistory(null);
    setShowMonitorHistory(false);
    setAiBriefStatus(null);

    Promise.all([
      fetchCase(c.id).catch(() => null),
      fetchSupplierPassport(c.id).catch(() => null),
    ])
      .then(([detail, passport]) => {
        if (cancelled) return;
        if (detail) {
          const typed = detail as ApiCase;
          setStoryline(typed.storyline ?? null);
          setExportAuthorization(typed.export_authorization ?? null);
          setExportAuthorizationGuidance(typed.export_authorization_guidance ?? null);
          setLatestFociArtifact(typed.latest_foci_artifact ?? null);
          setLatestSprsImport(typed.latest_sprs_import ?? null);
          setLatestOscalArtifact(typed.latest_oscal_artifact ?? null);
          setLatestNvdOverlay(typed.latest_nvd_overlay ?? null);
          setWorkflowControlSummary(typed.workflow_control_summary ?? null);
        }
        setSupplierPassport(passport);
      })
      .catch(() => {});

    void refreshAiBriefStatus();
    void refreshMonitoringHistory();

    return () => {
      cancelled = true;
    };
  }, [c.id, refreshAiBriefStatus, refreshMonitoringHistory]);

  useEffect(() => {
    let cancelled = false;
    if (!showFociPanel) {
      setFociArtifacts([]);
      return () => {
        cancelled = true;
      };
    }

    listFociArtifacts(c.id)
      .then((artifacts) => {
        if (cancelled) return;
        setFociArtifacts(artifacts);
        setLatestFociArtifact((current) => current ?? artifacts[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setFociArtifacts([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, showFociPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showSprsPanel) {
      setSprsImports([]);
      return () => {
        cancelled = true;
      };
    }

    listSprsImports(c.id)
      .then((imports) => {
        if (cancelled) return;
        setSprsImports(imports);
        setLatestSprsImport((current) => current ?? imports[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setSprsImports([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, showSprsPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showOscalPanel) {
      setOscalArtifacts([]);
      return () => {
        cancelled = true;
      };
    }

    listOscalArtifacts(c.id)
      .then((artifacts) => {
        if (cancelled) return;
        setOscalArtifacts(artifacts);
        setLatestOscalArtifact((current) => current ?? artifacts[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setOscalArtifacts([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, showOscalPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showNvdPanel) {
      setNvdOverlays([]);
      return () => {
        cancelled = true;
      };
    }

    listNvdOverlays(c.id)
      .then((overlays) => {
        if (cancelled) return;
        setNvdOverlays(overlays);
        setLatestNvdOverlay((current) => current ?? overlays[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setNvdOverlays([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, showNvdPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!exportAuthorization) {
      setExportArtifacts([]);
      return () => {
        cancelled = true;
      };
    }

    listExportArtifacts(c.id)
      .then((artifacts) => {
        if (!cancelled) {
          setExportArtifacts(artifacts);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExportArtifacts([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, exportAuthorization]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (sourceStatusRef.current && !sourceStatusRef.current.contains(event.target as Node)) {
        setShowSourceStatus(false);
      }
      if (monitorHistoryRef.current && !monitorHistoryRef.current.contains(event.target as Node)) {
        setShowMonitorHistory(false);
      }
      if (moreActionsRef.current && !moreActionsRef.current.contains(event.target as Node)) {
        setShowMoreActions(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const enrichmentAvailable = Boolean(supplierPassport?.identity?.enriched_at);

    if (!enrichmentAvailable) {
      setEnrichment(null);
      setLoadingEnrichment(false);
      return () => {
        cancelled = true;
      };
    }

    setLoadingEnrichment(true);

    fetchEnrichment(c.id)
      .then((report) => {
        if (cancelled) return;
        setEnrichment(report);
        if (!pendingEvidenceTab) {
          const tab = report.intel_summary ? "intel" : "findings";
          setEvidenceTab(tab);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEnrichment(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingEnrichment(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [c.id, pendingEvidenceTab, supplierPassport?.identity?.enriched_at]);

  useEffect(() => {
    let cancelled = false;
    fetchCaseNetworkRisk(c.id)
      .then((data) => {
        if (!cancelled && data && data.network_risk_score !== undefined) {
          setNetworkRisk(data);
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [c.id]);

  const loadGraphData = useCallback(async (depth: GraphDepth = graphDepth) => {
    if (graphLoading) return;
    setGraphLoading(true);
    try {
      const data = await fetchCaseGraph(c.id, depth);
      if (data.entities && data.relationships) {
        setGraphData(data);
      }
    } finally {
      setGraphLoading(false);
    }
  }, [c.id, graphDepth, graphLoading]);

  const refreshDerivedCaseData = useCallback(async ({
    enrichmentReport,
    reloadGraph = false,
  }: {
    enrichmentReport?: EnrichmentReport | null;
    reloadGraph?: boolean;
  } = {}) => {
    const [detail, passport, latestEnrichment, latestNetworkRisk] = await Promise.all([
      fetchCase(c.id).catch(() => null),
      fetchSupplierPassport(c.id).catch(() => null),
      enrichmentReport === undefined ? fetchEnrichment(c.id).catch(() => null) : Promise.resolve(enrichmentReport),
      fetchCaseNetworkRisk(c.id).catch(() => null),
    ]);

    if (detail) {
      const typed = detail as ApiCase;
      setStoryline(typed.storyline ?? null);
      setExportAuthorization(typed.export_authorization ?? null);
      setExportAuthorizationGuidance(typed.export_authorization_guidance ?? null);
      setLatestFociArtifact(typed.latest_foci_artifact ?? null);
      setLatestSprsImport(typed.latest_sprs_import ?? null);
      setLatestOscalArtifact(typed.latest_oscal_artifact ?? null);
      setLatestNvdOverlay(typed.latest_nvd_overlay ?? null);
      setWorkflowControlSummary(typed.workflow_control_summary ?? null);
    }
    setSupplierPassport(passport);
    setEnrichment(latestEnrichment ?? null);
    if (latestNetworkRisk && latestNetworkRisk.network_risk_score !== undefined) {
      setNetworkRisk(latestNetworkRisk);
    }
    if (reloadGraph && latestEnrichment) {
      await loadGraphData(graphDepth);
    }
  }, [c.id, graphDepth, loadGraphData]);

  const handleEnrich = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot run enrichment on a case.");
      return;
    }
    setEnriching(true);
    setShowStream(true);
    setShowAI(false);
    setShowSourceStatus(false);
    setError(null);
  };

  const handleStreamComplete = async () => {
    try {
      const fullReport = await fetchEnrichment(c.id);
      setEnrichment(fullReport);
      setPendingEvidenceTab(null);
      await Promise.all([
        refreshDerivedCaseData({ enrichmentReport: fullReport, reloadGraph: evidenceTab === "graph" || !!graphData }),
        refreshAiBriefStatus(),
        onCaseRefresh ? onCaseRefresh(c.id) : Promise.resolve(),
      ]);
      setShowStream(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load enrichment report");
    } finally {
      setEnriching(false);
    }
  };

  const handleRescore = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot re-score a case.");
      return;
    }
    if (!onRescore) return;
    setRescoring(true);
    setError(null);
    try {
      await onRescore(c.id);
      await Promise.all([refreshCaseContext(), refreshAiBriefStatus()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-score failed");
    } finally {
      setRescoring(false);
    }
  };

  const handleDossier = async () => {
    setGenerating(true);
    setError(null);
    try {
      const data = await requestDossier(c.id);
      const url = data.download_url || `/api/dossiers/dossier-${c.id}.html`;
      const protectedUrl = await buildProtectedUrl(url);
      window.open(protectedUrl, "_blank");
      void refreshAiBriefStatus();
    } catch (e) {
      if (onDossier) {
        try {
          await onDossier(c.id);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Dossier generation failed");
        }
      } else {
        setError(e instanceof Error ? e.message : "Dossier generation failed");
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleMonitor = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot run monitoring checks.");
      return;
    }
    setError(null);
    try {
      const queued = await runCaseMonitor(c.id);
      setMonitorStatus(queued);
      emit("monitor_triggered", { screen: "case_detail", case_id: c.id, metadata: { vendor_name: c.name } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Monitoring check failed");
    }
  };

  const handleFociArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingFociArtifact(true);
    setError(null);
    try {
      const { inferFociArtifactType } = await import("./case-detail-formatters");
      const artifact = await uploadFociArtifact(c.id, {
        file,
        artifactType: inferFociArtifactType(file.name),
      });
      setFociArtifacts((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestFociArtifact(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload FOCI artifact");
    } finally {
      setUploadingFociArtifact(false);
      if (event.target) event.target.value = "";
    }
  }, [c.id]);

  const handleExportArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !exportAuthorization) return;
    const nextArtifactType = exportAuthorizationGuidance?.classification_analysis.known
      ? "export_license_history"
      : "export_classification_memo";
    setUploadingExportArtifact(true);
    setError(null);
    try {
      const artifact = await uploadExportArtifact(c.id, {
        file,
        artifactType: nextArtifactType,
        declaredClassification: exportAuthorization.classification_guess || "",
        declaredJurisdiction: exportAuthorization.jurisdiction_guess || "",
      });
      setExportArtifacts((current) => [artifact, ...current]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload export artifact");
    } finally {
      setUploadingExportArtifact(false);
      if (event.target) event.target.value = "";
    }
  }, [c.id, exportAuthorization, exportAuthorizationGuidance]);

  const handleSprsImportSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingSprsImport(true);
    setError(null);
    try {
      const artifact = await uploadSprsImport(c.id, { file });
      setSprsImports((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestSprsImport(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload SPRS export");
    } finally {
      setUploadingSprsImport(false);
      if (event.target) event.target.value = "";
    }
  }, [c.id]);

  const handleOscalArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingOscalArtifact(true);
    setError(null);
    try {
      const artifact = await uploadOscalArtifact(c.id, { file });
      setOscalArtifacts((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestOscalArtifact(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload OSCAL artifact");
    } finally {
      setUploadingOscalArtifact(false);
      if (event.target) event.target.value = "";
    }
  }, [c.id]);

  const handleRunNvdOverlay = useCallback(async () => {
    const { splitProductTermsInput } = await import("./case-detail-formatters");
    const productTerms = splitProductTermsInput(nvdProductTermsInput);
    if (productTerms.length === 0) {
      setError("Add at least one supplier product or software reference for the NVD overlay.");
      return;
    }
    setRunningNvdOverlay(true);
    setError(null);
    try {
      const artifact = await runNvdOverlay(c.id, { productTerms });
      setNvdOverlays((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestNvdOverlay(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run NVD overlay");
    } finally {
      setRunningNvdOverlay(false);
    }
  }, [c.id, nvdProductTermsInput]);

  const handleScreenPerson = useCallback(async () => {
    if (!personScreeningName.trim()) {
      setError("Enter a person name for screening.");
      return;
    }
    setScreeningPerson(true);
    setError(null);
    try {
      const result = await screenPerson({
        name: personScreeningName,
        nationalities: personScreeningNationalities.split(",").map((n) => n.trim()).filter((n) => n.length > 0),
        employer: personScreeningEmployer || undefined,
        case_id: c.id,
      });
      setPersonScreeningResult(result);
      emit("person_screened", { workflow_lane: "export", screen: "case_detail", case_id: c.id, metadata: { has_matches: (result.ofac_matches?.length ?? 0) > 0, deemed_export: result.deemed_export_triggered ?? false } });
      setPersonScreeningHistory((current) => [{ ...result, screened_at: String(result.created_at || new Date().toISOString()) }, ...current]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to screen person");
      setPersonScreeningResult(null);
    } finally {
      setScreeningPerson(false);
    }
  }, [c.id, personScreeningEmployer, personScreeningName, personScreeningNationalities]);

  const handleBatchScreenCsv = useCallback(async () => {
    if (!batchScreeningFile) {
      setError("Select a CSV file for batch screening.");
      return;
    }
    setScreeningBatch(true);
    setBatchScreeningError(null);
    setBatchScreeningResults([]);
    setError(null);
    try {
      const data = await screenBatchCsv(c.id, batchScreeningFile);
      const screenings = Array.isArray(data.screenings) ? data.screenings : [];
      setBatchScreeningResults(screenings);
      setPersonScreeningHistory((current) => [
        ...screenings.map((s: PersonScreeningResult) => ({
          ...s,
          screened_at: String(s.created_at || new Date().toISOString()),
        })),
        ...current,
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Batch screening failed";
      setBatchScreeningError(msg);
      setError(msg);
    } finally {
      setScreeningBatch(false);
    }
  }, [batchScreeningFile, c.id]);

  const handleDownloadCsvTemplate = useCallback(() => {
    const csvContent = "name,nationalities,employer\nJohn Doe,\"CN,HK\",Huawei Technologies\nJane Smith,RU,Rosatom\nAli Hassan,IR,\nMaria Garcia,MX,Pemex\n";
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "person_screening_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const loadTxAuth = useCallback(async () => {
    try {
      const data = await listTransactionAuthorizations(c.id, undefined, 1);
      const latest = data.authorizations?.[0] as { id?: string } | undefined;
      if (!latest?.id) {
        setTxAuth(null);
        return;
      }
      const detail = await fetchTransactionAuthorization(latest.id);
      setTxAuth(detail as unknown as TransactionAuthorizationResult);
    } catch (err) {
      console.error("Failed to load transaction authorization:", err);
    }
  }, [c.id]);

  const handleRunTxAuth = useCallback(async () => {
    if (!exportAuthorization) return;
    setTxAuthLoading(true);
    try {
      const nats = exportAuthorization.foreign_person_nationalities;
      const persons = nats && nats.length > 0
        ? [{
            name: exportAuthorization.recipient_name || "Unspecified person",
            nationalities: nats,
            employer: exportAuthorization.recipient_name || "",
          }]
        : [];
      const { getUser } = await import("@/lib/auth");
      const result = await runTransactionAuthorization({
        jurisdiction_guess: exportAuthorization.jurisdiction_guess || "unknown",
        request_type: exportAuthorization.request_type,
        classification_guess: exportAuthorization.classification_guess || "unknown",
        destination_country: exportAuthorization.destination_country || "",
        destination_company: exportAuthorization.recipient_name || "",
        item_or_data_summary: exportAuthorization.item_or_data_summary || "",
        end_use_summary: exportAuthorization.end_use_summary || "",
        access_context: exportAuthorization.access_context || "",
        persons,
        case_id: c.id,
        requested_by: getUser()?.email || "ui",
      });
      setTxAuth(result as unknown as TransactionAuthorizationResult);
      emit("transaction_authorized", { workflow_lane: "export", screen: "case_detail", case_id: c.id, metadata: { destination: exportAuthorization?.destination_country, request_type: exportAuthorization?.request_type } });
    } catch (err) {
      console.error("Transaction authorization failed:", err);
    } finally {
      setTxAuthLoading(false);
    }
  }, [c.id, exportAuthorization]);

  const loadPersonScreeningHistory = useCallback(async () => {
    try {
      const data = await fetchCaseScreenings(c.id);
      const screenings = Array.isArray(data.screenings) ? data.screenings : [];
      setPersonScreeningHistory(
        screenings.map((item) => ({
          ...item,
          screened_at: String(item.screened_at || item.created_at || ""),
        })),
      );
    } catch (err) {
      console.error("Failed to load screening history:", err);
    }
  }, [c.id]);

  const value: CaseContextValue = {
    c,
    cal,
    isReadOnly,
    enrichment,
    setEnrichment,
    loadingEnrichment,
    setLoadingEnrichment,
    enriching,
    setEnriching,
    analystView,
    setAnalystView,
    evidenceTab,
    setEvidenceTab,
    pendingEvidenceTab,
    setPendingEvidenceTab,
    showStream,
    setShowStream,
    showAI,
    setShowAI,
    showMoreActions,
    setShowMoreActions,
    showSourceStatus,
    setShowSourceStatus,
    showMonitorHistory,
    setShowMonitorHistory,
    graphData,
    setGraphData,
    graphLoading,
    setGraphLoading,
    graphDepth,
    setGraphDepth,
    provenanceEntityId,
    setProvenanceEntityId,
    provenanceRelId,
    setProvenanceRelId,
    networkRisk,
    setNetworkRisk,
    storyline,
    setStoryline,
    supplierPassport,
    setSupplierPassport,
    workflowControlSummary,
    setWorkflowControlSummary,
    exportAuthorization,
    setExportAuthorization,
    exportAuthorizationGuidance,
    setExportAuthorizationGuidance,
    exportArtifacts,
    setExportArtifacts,
    uploadingExportArtifact,
    setUploadingExportArtifact,
    latestFociArtifact,
    setLatestFociArtifact,
    fociArtifacts,
    setFociArtifacts,
    uploadingFociArtifact,
    setUploadingFociArtifact,
    latestSprsImport,
    setLatestSprsImport,
    sprsImports,
    setSprsImports,
    uploadingSprsImport,
    setUploadingSprsImport,
    latestOscalArtifact,
    setLatestOscalArtifact,
    oscalArtifacts,
    setOscalArtifacts,
    uploadingOscalArtifact,
    setUploadingOscalArtifact,
    latestNvdOverlay,
    setLatestNvdOverlay,
    nvdOverlays,
    setNvdOverlays,
    runningNvdOverlay,
    setRunningNvdOverlay,
    nvdProductTermsInput,
    setNvdProductTermsInput,
    cyberRiskScore,
    setCyberRiskScore,
    loadingCyberScore,
    setLoadingCyberScore,
    personScreeningName,
    setPersonScreeningName,
    personScreeningNationalities,
    setPersonScreeningNationalities,
    personScreeningEmployer,
    setPersonScreeningEmployer,
    personScreeningResult,
    setPersonScreeningResult,
    personScreeningHistory,
    setPersonScreeningHistory,
    screeningPerson,
    setScreeningPerson,
    batchScreeningFile,
    setBatchScreeningFile,
    batchScreeningResults,
    setBatchScreeningResults,
    screeningBatch,
    setScreeningBatch,
    batchScreeningError,
    setBatchScreeningError,
    txAuth,
    setTxAuth,
    txAuthLoading,
    setTxAuthLoading,
    monitorStatus,
    setMonitorStatus,
    monitoringHistory,
    setMonitoringHistory,
    monitoringHistoryLoading,
    setMonitoringHistoryLoading,
    monitorHistoryKey,
    setMonitorHistoryKey,
    aiBriefStatus,
    setAiBriefStatus,
    rescoring,
    setRescoring,
    generating,
    setGenerating,
    error,
    setError,
    authorityLaneSelection,
    setAuthorityLaneSelection,
    evidenceRef,
    actionPanelRef,
    authorityInputsRef,
    sourceStatusRef,
    monitorHistoryRef,
    moreActionsRef,
    fociInputRef,
    sprsInputRef,
    oscalInputRef,
    exportArtifactInputRef,
    loadGraphData,
    refreshDerivedCaseData,
    refreshCaseContext,
    refreshAiBriefStatus,
    refreshMonitoringHistory,
    handleEnrich,
    handleStreamComplete,
    handleRescore,
    handleDossier,
    handleMonitor,
    handleFociArtifactSelected,
    handleExportArtifactSelected,
    handleSprsImportSelected,
    handleOscalArtifactSelected,
    handleRunNvdOverlay,
    handleScreenPerson,
    handleBatchScreenCsv,
    handleDownloadCsvTemplate,
    handleRunTxAuth,
    loadPersonScreeningHistory,
    loadTxAuth,
  };

  return (
    <CaseContext.Provider value={value}>
      {children}
    </CaseContext.Provider>
  );
}
