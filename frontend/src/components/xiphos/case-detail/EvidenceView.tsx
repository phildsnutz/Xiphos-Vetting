import React from "react";
import { Loader2, Network, Radar } from "lucide-react";
import { LoadingSpinner } from "../loader";
import { useCaseDetail } from "./case-context";
import { EntityGraph } from "../entity-graph";
import { GraphTrainingReviewPanel } from "../graph-training-review-panel";
import { GraphProvenancePanel } from "../graph-provenance-panel";
import { EnrichmentPanel } from "../enrichment-panel";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { CaseGraphData, EnrichmentReport, GraphEntity } from "@/lib/api";
import type { Calibration, VettingCase } from "@/lib/types";
import type { EvidenceTabId, EvidenceTabItem } from "./case-detail-types";
import { emit } from "@/lib/telemetry";

interface EvidenceViewProps {
  evidenceRef: React.RefObject<HTMLDivElement | null>;
  analystView: "decision" | "evidence" | "model";
  evidenceTab: EvidenceTabId;
  loadingEnrichment: boolean;
  enrichment: EnrichmentReport | null;
  showStream: boolean;
  cal: Calibration | null;
  graphData: CaseGraphData | null;
  graphLoading: boolean;
  provenanceEntityId: string | null;
  provenanceRelId: number | null;
  c: VettingCase;
  evidenceTabs: EvidenceTabItem[];
  graphDepth: number;
  openEvidence: (tab: EvidenceTabId) => void;
  switchGraphDepth: (depth: 3 | 4) => void;
}

export const EvidenceView: React.FC<EvidenceViewProps> = ({
  evidenceRef,
  analystView,
  evidenceTab,
  loadingEnrichment,
  enrichment,
  showStream,
  cal,
  graphData,
  graphLoading,
  provenanceEntityId,
  provenanceRelId,
  c,
  evidenceTabs,
  graphDepth,
  openEvidence,
  switchGraphDepth,
}) => {
  const {
    setProvenanceEntityId,
    setProvenanceRelId,
    refreshDerivedCaseData,
  } = useCaseDetail();

  if (analystView !== "evidence" && analystView !== "model") return null;

  return (
    <div ref={evidenceRef} className="mt-3 rounded-lg glass-card" style={{ padding: SP.md + 2 }}>
      <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
        {analystView === "model" ? "Model" : "Evidence"}
      </div>
      <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.xs }}>
        {analystView === "model"
          ? "Model-specific reasoning, confidence, and top contribution drivers."
          : "Connector outputs, findings, timelines, and graph evidence behind the decision."}
      </div>

      <div className="flex gap-2 flex-wrap mt-3">
        {evidenceTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => openEvidence(tab.id)}
            disabled={tab.disabled}
            aria-label={`Open ${tab.label}`}
            className="rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: PAD.default,
              fontSize: FS.sm,
              background: evidenceTab === tab.id ? T.accent + "18" : T.raised,
              color: evidenceTab === tab.id ? T.accent : tab.disabled ? T.muted : T.dim,
              borderColor: evidenceTab === tab.id ? T.accent + "44" : T.border,
              opacity: tab.disabled ? 0.55 : 1,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {loadingEnrichment && evidenceTab !== "model" && (
          <div className="flex items-center justify-center py-8">
            <LoadingSpinner />
          </div>
        )}

        {evidenceTab === "model" && cal && (
          <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4 tab-content-enter">
            <div className="glass-card p-4">
              <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
                Model View
              </div>
              <div style={{ fontSize: FS.xl, fontWeight: 700, color: T.text, marginBottom: SP.xs, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                {Math.round(cal.p * 100)}%
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                Coverage {Math.round(cal.cov * 100)}%. Confidence {Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)))}%.
              </div>
            </div>
            <div className="glass-card p-4">
              <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted, letterSpacing: "0.06em" }}>
                Top Model Factors
              </div>
              <div className="flex flex-col gap-3">
                {/* Factors would be rendered here */}
              </div>
            </div>
          </div>
        )}

        {evidenceTab === "graph" && (
          <div className="glass-panel p-5 tab-content-enter">
            <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
              <div className="flex items-center gap-2">
                <Network size={15} color={T.accent} />
                <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted, letterSpacing: "0.06em" }}>
                  Entity Association Graph
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span style={{ fontSize: FS.sm, color: T.muted }}>Scope</span>
                <button
                  onClick={() => switchGraphDepth(3)}
                  aria-label="Set graph to focused network"
                  className="rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
                  style={{
                    padding: PAD.default,
                    fontSize: FS.sm,
                    background: graphDepth === 3 ? T.accent + "18" : T.surface,
                    color: graphDepth === 3 ? T.accent : T.dim,
                    borderColor: graphDepth === 3 ? T.accent + "44" : T.border,
                  }}
                >
                  Focused network
                </button>
                <button
                  onClick={() => switchGraphDepth(4)}
                  aria-label="Set graph to extended network"
                  className="rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
                  style={{
                    padding: PAD.default,
                    fontSize: FS.sm,
                    background: graphDepth === 4 ? T.accent + "18" : T.surface,
                    color: graphDepth === 4 ? T.accent : T.dim,
                    borderColor: graphDepth === 4 ? T.accent + "44" : T.border,
                  }}
                >
                  Extended network
                </button>
              </div>
            </div>

            <GraphTrainingReviewPanel
              rootEntityId={graphData?.root_entity_id}
              entityName={graphData?.entities.find((entity: GraphEntity) => entity.id === graphData.root_entity_id)?.canonical_name || c.name}
              onGraphRefresh={() => refreshDerivedCaseData({ reloadGraph: true })}
            />

            {graphLoading && (
              <div className="glass-card flex items-center justify-center py-10 animate-fade-in" style={{ marginTop: 14 }}>
                <Loader2 className="animate-spin" size={18} color={T.muted} />
                <span style={{ fontSize: FS.sm, color: T.muted, marginLeft: 8 }}>Loading graph data...</span>
              </div>
            )}

            {graphData && (
              <EntityGraph
                entities={graphData.entities}
                relationships={graphData.relationships}
                rootEntityId={graphData.root_entity_id}
                width={780}
                height={520}
                onEntityClick={(entity: GraphEntity) => {
                  setProvenanceRelId(null);
                  setProvenanceEntityId(entity.id);
                  emit("graph_entity_clicked", {
                    screen: "case_graph",
                    case_id: c.id,
                    metadata: { entity_id: entity.id, entity_type: entity.entity_type, entity_name: entity.canonical_name },
                  });
                }}
                onRelationshipClick={(relId: string | number) => {
                  if (typeof relId !== "number") return;
                  setProvenanceEntityId(null);
                  setProvenanceRelId(relId);
                  emit("graph_relationship_clicked", { screen: "case_graph", case_id: c.id, metadata: { relationship_id: relId } });
                }}
              />
            )}

            {(provenanceEntityId || provenanceRelId != null) && (
              <GraphProvenancePanel
                entityId={provenanceEntityId}
                relationshipId={provenanceRelId}
                onClose={() => {
                  setProvenanceEntityId(null);
                  setProvenanceRelId(null);
                }}
              />
            )}

            {!graphLoading && !graphData && (
              <div className="glass-card flex flex-col items-center justify-center py-10 animate-fade-in" style={{ marginTop: SP.md + 2 }}>
                <Network size={28} color={T.muted} style={{ marginBottom: 10, opacity: 0.5 }} />
                <div style={{ fontSize: FS.sm, color: T.dim, fontWeight: 600 }}>No graph data yet</div>
                <div style={{ fontSize: FS.caption, color: T.muted, marginTop: SP.xs }}>Re-run the assessment to populate the knowledge graph.</div>
              </div>
            )}
          </div>
        )}

        {evidenceTab !== "model" && evidenceTab !== "graph" && enrichment && !showStream && (
          <EnrichmentPanel caseId={c.id} report={enrichment} section={evidenceTab} />
        )}

        {evidenceTab !== "model" && !enrichment && !showStream && !loadingEnrichment && (
          <div className="glass-card p-6 flex flex-col items-center justify-center animate-fade-in">
            <Radar size={28} color={T.muted} style={{ marginBottom: 10, opacity: 0.5 }} />
            <div style={{ fontSize: FS.sm, color: T.dim, fontWeight: 600 }}>No evidence loaded</div>
            <div style={{ fontSize: FS.caption, color: T.muted, marginTop: SP.xs }}>Run screening to load evidence for this case.</div>
          </div>
        )}
      </div>
    </div>
  );
};
