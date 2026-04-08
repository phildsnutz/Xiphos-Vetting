import React, { useMemo, useState } from "react";
import { CaseDetailProvider, useCaseDetail } from "./case-detail/case-context";
import { CaseHeader } from "./case-detail/CaseHeader";
import { DecisionPanel } from "./case-detail/DecisionPanel";
import { SupplierPassport } from "./case-detail/SupplierPassport";
import { EnrichmentWorkflow } from "./case-detail/EnrichmentWorkflow";
import { PersonScreening } from "./case-detail/PersonScreening";
import { MonitoringPanel } from "./case-detail/MonitoringPanel";
import { SourceStatusPanel } from "./case-detail/SourceStatusPanel";
import { EvidenceView } from "./case-detail/EvidenceView";
import { T, FS, O, PAD, SP } from "@/lib/tokens";
import { getUser } from "@/lib/auth";
import type { SupplierPassport as SupplierPassportRecord } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import type { WorkflowLane } from "./portfolio-utils";
import { SectionEyebrow } from "./shell-primitives";
import type {
  AiBriefViewState,
  BatchScreeningRow,
  EvidenceTabId,
  EvidenceTabItem,
  MonitoringHistorySummary,
  MonitoringLaneCopy,
  PersonScreeningRecord,
  SprsAssessmentContainer,
  ToneConfig,
} from "./case-detail/case-detail-types";
import {
  formatMonitorTierLabel,
  monitoringEntryTone,
  officialCorroborationTone,
  passportPostureTone,
  sprsStatusLabel,
} from "./case-detail/case-detail-formatters";

interface CaseDetailPropsLegacy {
  c: VettingCase;
  onBack: () => void;
  onRescore?: (caseId: string) => Promise<void>;
  onDossier?: (caseId: string) => Promise<void>;
  onCaseRefresh?: (caseId: string) => Promise<void>;
  onOpenGraphRoom?: () => void;
  globalLane?: WorkflowLane;
  laneSummary?: unknown;
}

const CaseDetailContent: React.FC<{ isReadOnly: boolean; hasApi: boolean; onOpenGraphRoom?: () => void }> = ({ isReadOnly, hasApi, onOpenGraphRoom }) => {
  const {
    c,
    cal,
    supplierPassport,
    enrichment,
    showMonitorHistory,
    showSourceStatus,
    analystView,
    evidenceTab,
    setAnalystView,
    setEvidenceTab,
    setPendingEvidenceTab,
    graphData,
    graphDepth,
    setGraphDepth,
    graphLoading,
    loadGraphData,
    provenanceEntityId,
    provenanceRelId,
    loadingEnrichment,
    showStream,
    handleEnrich,
    monitoringHistory,
    monitoringHistoryLoading,
    aiBriefStatus,
    refreshAiBriefStatus,
    latestFociArtifact,
    latestSprsImport,
    latestOscalArtifact,
    sprsImports,
    uploadingFociArtifact,
    uploadingSprsImport,
    uploadingOscalArtifact,
    runningNvdOverlay,
    personScreeningName,
    setPersonScreeningName,
    personScreeningResult,
    screeningPerson,
    batchScreeningFile,
    setBatchScreeningFile,
    batchScreeningResults,
    batchScreeningError,
    screeningBatch,
    evidenceRef,
    sourceStatusRef,
    monitorHistoryRef,
  } = useCaseDetail();

  const [showPersonScreening, setShowPersonScreening] = useState(false);

  const authorityLaneKey: WorkflowLane = c.workflowLane ?? "counterparty";
  const showFociPanel = c.profile === "defense_acquisition" || !!latestFociArtifact;
  const showSprsPanel = c.profile === "defense_acquisition" || sprsImports.length > 0 || !!latestSprsImport;
  const showOscalPanel = c.profile === "defense_acquisition" || !!latestOscalArtifact;
  const latestFociSummary = (latestFociArtifact?.structured_fields ?? null) as Record<string, unknown> | null;
  const latestSprsSummaries = useMemo<SprsAssessmentContainer[]>(
    () => sprsImports.map((artifact) => ({ assessment_summary: artifact.structured_fields?.summary as Record<string, unknown> | null })),
    [sprsImports],
  );
  const latestOscalSummary = (latestOscalArtifact?.structured_fields?.summary ?? null) as Record<string, unknown> | null;
  const latestMonitoringChecks = useMemo(
    () => monitoringHistory?.monitoring_history ?? [],
    [monitoringHistory],
  );
  const monitoringHistorySummary = useMemo<MonitoringHistorySummary | null>(() => {
    if (!monitoringHistory) return null;
    return {
      runs: latestMonitoringChecks.length,
      changed: latestMonitoringChecks.filter((entry) => entry.risk_changed).length,
      newFindings: latestMonitoringChecks.reduce((sum, entry) => sum + (entry.new_findings_count ?? 0), 0),
    };
  }, [latestMonitoringChecks, monitoringHistory]);
  const supplierPassportTone = useMemo<ToneConfig>(
    () => passportPostureTone(supplierPassport?.posture),
    [supplierPassport?.posture],
  );
  const supplierPassportOfficialCorroboration = useMemo(
    () => supplierPassport?.identity?.official_corroboration ?? null,
    [supplierPassport],
  );
  const supplierPassportOfficialTone = useMemo<ToneConfig>(
    () => officialCorroborationTone(supplierPassportOfficialCorroboration),
    [supplierPassportOfficialCorroboration],
  );
  const aiBriefView = useMemo<AiBriefViewState>(() => {
    if (!aiBriefStatus) {
      return { status: null, summary: null, detail: null, ready: false };
    }
    const ready = aiBriefStatus.status === "ready" || aiBriefStatus.status === "completed";
    const summary =
      aiBriefStatus.status === "ready" || aiBriefStatus.status === "completed"
        ? "AI brief ready"
        : aiBriefStatus.status === "running"
          ? "AI brief warming"
          : aiBriefStatus.status === "pending"
            ? "AI brief queued"
            : aiBriefStatus.status === "failed"
              ? "AI brief unavailable"
              : "AI brief not warmed";
    const detail =
      ready && aiBriefStatus.analysis?.created_at
        ? `Ready for dossier and AI panel • ${new Date(aiBriefStatus.analysis.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : ready
          ? "Ready for dossier and AI panel"
          : aiBriefStatus.status === "running"
            ? "Preparing the narrative from the latest screening"
            : aiBriefStatus.status === "pending"
              ? "Queued behind the latest enrich or re-enrich run"
              : aiBriefStatus.status === "failed"
                ? "Will regenerate on dossier open if needed"
                : enrichment
                  ? "Older case; the brief will warm on next dossier or screening run"
                  : "Will warm after screening completes";
    return { status: aiBriefStatus, summary, detail, ready };
  }, [aiBriefStatus, enrichment]);

  const downloadSupplierPassportJson = (passport: SupplierPassportRecord) => {
    const json = JSON.stringify(passport, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `supplier-passport-${c.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatPassportPosture = (posture: string) => posture?.replaceAll("_", " ") || "unknown";

  const monitoringLaneCopy: MonitoringLaneCopy = {
    title: "Monitoring History",
    detail: "Continuous oversight of risk tier changes and new findings.",
    runsLabel: "Runs",
    changedLabel: "Risk shifts",
    findingsLabel: "New findings",
    loadingLabel: "Loading monitoring data...",
    emptyTitle: "No monitoring data",
    emptyDetail: "Monitor this case to track risk changes over time.",
    findingsText: (count: number) => (count === 1 ? "1 new finding" : `${count} new findings`),
    shiftedText: "Risk tier shifted",
  };

  const evidenceTabs: EvidenceTabItem[] = [
    { id: "model", label: "Model", disabled: !cal },
    { id: "graph", label: "Graph Intel", disabled: false },
    { id: "findings", label: "Findings", disabled: !enrichment },
    { id: "events", label: "Timeline", disabled: !enrichment },
  ];

  const openEvidence = (tab: EvidenceTabId) => {
    if (tab === "graph") {
      setAnalystView("evidence");
      setEvidenceTab("graph");
      setPendingEvidenceTab(null);
      if (!graphData && !graphLoading) {
        void loadGraphData(graphDepth as 3 | 4);
      }
      return;
    }
    if (tab !== "model" && !enrichment) {
      if (isReadOnly) {
        return;
      }
      setPendingEvidenceTab(tab);
      setAnalystView("evidence");
      void handleEnrich();
      return;
    }
    setAnalystView(tab === "model" ? "model" : "evidence");
    setEvidenceTab(tab);
    setPendingEvidenceTab(null);
  };

  const switchGraphDepth = (depth: 3 | 4) => {
    if (depth === graphDepth) return;
    setGraphDepth(depth);
    if (evidenceTab === "graph") {
      void loadGraphData(depth);
    }
  };

  const workspaceTabs = [
    {
      id: "decision",
      label: "Decision",
      description: "Disposition, supplier posture, and person screening.",
      active: analystView === "decision",
      action: () => {
        setAnalystView("decision");
        setPendingEvidenceTab(null);
      },
    },
    {
      id: "evidence",
      label: "Evidence",
      description: "Connector output, findings, and timeline.",
      active: analystView === "evidence" && evidenceTab !== "graph",
      action: () => openEvidence(enrichment ? evidenceTab === "graph" ? "findings" : evidenceTab : "findings"),
    },
    {
      id: "model",
      label: "Model",
      description: "Score reasoning, confidence, and factor view.",
      active: analystView === "model",
      action: () => openEvidence("model"),
    },
    {
      id: "graph",
      label: "Graph Intel",
      description: "Open the canonical graph room for relationship fabric and provenance.",
      active: analystView === "evidence" && evidenceTab === "graph",
      action: () => openEvidence("graph"),
    },
  ] as const;
  const activeWorkspace = workspaceTabs.find((tab) => tab.active) ?? workspaceTabs[0];

  return (
    <div
      style={{
        padding: PAD.default,
        background: T.bg,
        minHeight: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: SP.md,
      }}
    >
      <CaseHeader
        c={c}
        isReadOnly={isReadOnly}
        hasApi={hasApi}
        aiBriefStatus={aiBriefView.status}
        aiBriefSummary={aiBriefView.summary}
        onRefreshAiBrief={() => void refreshAiBriefStatus()}
      />

      <div
        style={{
          padding: `${SP.xs}px 0 ${SP.sm}px`,
          display: "flex",
          flexDirection: "column",
          gap: SP.sm,
          borderBottom: `1px solid ${T.border}`,
        }}
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <SectionEyebrow>Workspace</SectionEyebrow>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
              {activeWorkspace.label} active. Decision stays anchored while evidence, graph, and model pressure move on the right.
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {workspaceTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                data-case-view={tab.id}
                onClick={tab.action}
                className="helios-focus-ring"
                aria-label={`Open ${tab.label.toLowerCase()} workspace`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                  borderRadius: 999,
                  border: `1px solid ${tab.active ? `${T.accent}${O["30"]}` : T.border}`,
                  background: tab.active ? T.accentSoft : T.surface,
                  color: tab.active ? T.accent : T.textSecondary,
                  padding: PAD.default,
                  cursor: "pointer",
                  fontSize: FS.sm,
                  fontWeight: 700,
                }}
                title={tab.description}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div
        className="grid grid-cols-1 xl:grid-cols-[minmax(340px,0.88fr)_minmax(0,1.12fr)] gap-4 flex-1 min-h-0"
        style={{ flex: 1, minHeight: 0 }}
      >
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            gap: SP.md,
            minHeight: 0,
            overflowY: "auto",
            paddingRight: SP.xs,
          }}
        >
          <div
            style={{
              position: "sticky",
              top: 0,
              zIndex: 1,
              paddingBottom: SP.sm,
              background: T.bg,
            }}
          >
            <SectionEyebrow>Decision rail</SectionEyebrow>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
              Disposition, passport, and screening stay in view while you work the evidence.
            </div>
          </div>

          <DecisionPanel c={c} cal={cal} />

          <SupplierPassport
            supplierPassport={supplierPassport}
            supplierPassportTone={supplierPassportTone}
            supplierPassportOfficialCorroboration={supplierPassportOfficialCorroboration}
            supplierPassportOfficialTone={supplierPassportOfficialTone}
            downloadSupplierPassportJson={downloadSupplierPassportJson}
            formatPassportPosture={formatPassportPosture}
          />

          <PersonScreening
            isReadOnly={isReadOnly}
            screeningPerson={personScreeningName}
            setScreeningPerson={setPersonScreeningName}
            screeningResult={personScreeningResult as PersonScreeningRecord | null}
            batchScreeningResults={batchScreeningResults as BatchScreeningRow[]}
            batchScreeningFile={batchScreeningFile}
            setBatchScreeningFile={setBatchScreeningFile}
            batchScreeningError={batchScreeningError}
            screeningLoading={screeningPerson}
            screeningBatch={screeningBatch}
            showPersonScreening={showPersonScreening}
            setShowPersonScreening={setShowPersonScreening}
          />
        </section>

        <section
          style={{
            display: "flex",
            flexDirection: "column",
            gap: SP.md,
            minHeight: 0,
            overflowY: "auto",
            paddingRight: SP.xs,
          }}
        >
          <div
            style={{
              position: "sticky",
              top: 0,
              zIndex: 1,
              paddingBottom: SP.sm,
              background: T.bg,
            }}
          >
            <SectionEyebrow>Evidence rail</SectionEyebrow>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
              Evidence stays primary. Open Graph Intel, monitoring, and enrichment only when the case needs deeper pressure testing.
            </div>
          </div>

          <EvidenceView
            evidenceRef={evidenceRef}
            analystView={analystView}
            evidenceTab={evidenceTab}
            loadingEnrichment={loadingEnrichment}
            enrichment={enrichment}
            showStream={showStream}
            cal={cal}
            graphData={graphData}
            graphLoading={graphLoading}
            provenanceEntityId={provenanceEntityId}
            provenanceRelId={provenanceRelId}
            c={c}
            evidenceTabs={evidenceTabs}
            graphDepth={graphDepth}
            onOpenGraphRoom={onOpenGraphRoom}
            openEvidence={openEvidence}
            switchGraphDepth={switchGraphDepth}
          />

          <EnrichmentWorkflow
            isReadOnly={isReadOnly}
            authorityLaneKey={authorityLaneKey}
            showFociPanel={showFociPanel}
            showSprsPanel={showSprsPanel}
            showOscalPanel={showOscalPanel}
            uploadingFociArtifact={uploadingFociArtifact}
            uploadingSprsArtifact={uploadingSprsImport}
            uploadingOscalArtifact={uploadingOscalArtifact}
            uploadingNvdOverlay={runningNvdOverlay}
            latestFociSummary={latestFociSummary}
            latestSprsSummaries={latestSprsSummaries}
            latestOscalSummary={latestOscalSummary}
            sprsStatusLabel={sprsStatusLabel}
          />

          {(showMonitorHistory || (showSourceStatus && enrichment)) && (
            <div className="grid grid-cols-1 2xl:grid-cols-2 gap-3">
              {showMonitorHistory && (
                <MonitoringPanel
                  monitorHistoryRef={monitorHistoryRef}
                  monitoringHistory={monitoringHistory}
                  monitoringHistorySummary={monitoringHistorySummary}
                  monitoringHistoryLoading={monitoringHistoryLoading}
                  latestMonitoringChecks={latestMonitoringChecks}
                  monitoringLaneCopy={monitoringLaneCopy}
                  monitoringEntryTone={monitoringEntryTone}
                  formatMonitorTierLabel={formatMonitorTierLabel}
                />
              )}
              {showSourceStatus && enrichment && (
                <SourceStatusPanel sourceStatusRef={sourceStatusRef} enrichment={enrichment} showStream={showStream} />
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export const CaseDetail: React.FC<CaseDetailPropsLegacy> = (props) => {
  const user = getUser();
  const isReadOnly = user?.role === "reviewer" || user?.role === "auditor";
  return (
    <CaseDetailProvider
      c={props.c}
      onRescore={props.onRescore}
      onDossier={props.onDossier}
      onCaseRefresh={props.onCaseRefresh}
      isReadOnly={!!isReadOnly}
    >
      <CaseDetailContent isReadOnly={!!isReadOnly} hasApi={true} onOpenGraphRoom={props.onOpenGraphRoom} />
    </CaseDetailProvider>
  );
};
