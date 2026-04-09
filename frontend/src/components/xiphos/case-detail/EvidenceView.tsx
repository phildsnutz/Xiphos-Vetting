import React from "react";
import { Network, Radar, ArrowRight } from "lucide-react";
import { LoadingSpinner } from "../loader";
import { useCaseDetail } from "./case-context";
import { EnrichmentPanel } from "../enrichment-panel";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { CaseGraphData, EnrichmentReport } from "@/lib/api";
import type { Calibration, VettingCase } from "@/lib/types";
import type { EvidenceTabId, EvidenceTabItem } from "./case-detail-types";

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
  c: VettingCase;
  evidenceTabs: EvidenceTabItem[];
  graphDepth: number;
  onOpenGraphRoom?: () => void;
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
  c,
  evidenceTabs,
  graphDepth,
  onOpenGraphRoom,
  openEvidence,
  switchGraphDepth,
}) => {
  const {
    refreshDerivedCaseData,
  } = useCaseDetail();

  if (analystView !== "evidence" && analystView !== "model") return null;

  const evidenceTitle =
    analystView === "model"
      ? "Model reasoning"
      : evidenceTab === "graph"
        ? "Graph Intel"
        : evidenceTab === "events"
          ? "Evidence timeline"
          : evidenceTab === "findings"
            ? "Connector findings"
            : "Evidence";
  const evidenceDescription =
    analystView === "model"
      ? "Read the calibrated view, confidence, and factor pressure without leaving the case."
      : evidenceTab === "graph"
        ? "Use the graph room to interrogate the relationship fabric instead of relying on an old local snapshot."
        : "Stay inside the evidence stream, then pivot deeper only when the case needs it.";

  return (
    <div
      ref={evidenceRef}
      style={{
        marginTop: SP.xs,
        padding: PAD.comfortable,
        borderRadius: 18,
        background: T.surface,
        border: `1px solid ${T.border}`,
      }}
    >
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            {evidenceTitle}
          </div>
          <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs, lineHeight: 1.55 }}>
            {evidenceDescription}
          </div>
        </div>

        <div className="flex gap-2 flex-wrap">
        {evidenceTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => openEvidence(tab.id)}
            disabled={tab.disabled}
            aria-label={`Open ${tab.label}`}
            className="rounded-full font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: "8px 12px",
              fontSize: FS.sm,
              background: evidenceTab === tab.id ? T.accentSoft : T.surface,
              color: evidenceTab === tab.id ? T.accent : tab.disabled ? T.muted : T.dim,
              borderColor: evidenceTab === tab.id ? `${T.accent}44` : T.border,
              opacity: tab.disabled ? 0.55 : 1,
              fontWeight: 700,
            }}
            title={tab.label}
          >
            {tab.label}
          </button>
        ))}
        </div>
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
                  Graph Intel Room
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

            <div
              className="glass-card animate-fade-in"
              style={{
                marginTop: 14,
                padding: PAD.comfortable,
                display: "flex",
                flexDirection: "column",
                gap: SP.md,
                border: `1px solid ${T.border}`,
                background: T.bg,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700 }}>
                  The graph room is the canonical graph surface now
                </div>
                <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6, maxWidth: 760 }}>
                  This case workspace no longer renders the stale embedded graph. Open Graph Intel to interrogate the full relationship fabric without falling back to the old local graph UI.
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <div
                  style={{
                    borderRadius: 999,
                    padding: "8px 12px",
                    border: `1px solid ${T.border}`,
                    background: T.surface,
                    fontSize: FS.sm,
                    color: T.textSecondary,
                    fontWeight: 700,
                  }}
                >
                  {graphLoading ? "Refreshing network…" : `${graphData?.entity_count ?? graphData?.entities.length ?? 0} nodes`}
                </div>
                <div
                  style={{
                    borderRadius: 999,
                    padding: "8px 12px",
                    border: `1px solid ${T.border}`,
                    background: T.surface,
                    fontSize: FS.sm,
                    color: T.textSecondary,
                    fontWeight: 700,
                  }}
                >
                  {graphLoading ? "Collecting edges…" : `${graphData?.relationship_count ?? graphData?.relationships.length ?? 0} edges`}
                </div>
                <div
                  style={{
                    borderRadius: 999,
                    padding: "8px 12px",
                    border: `1px solid ${T.border}`,
                    background: T.surface,
                    fontSize: FS.sm,
                    color: T.textSecondary,
                    fontWeight: 700,
                  }}
                >
                  Depth {graphDepth}
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={onOpenGraphRoom}
                  className="helios-focus-ring"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: SP.xs,
                    border: "none",
                    background: T.accent,
                    color: T.textInverse,
                    borderRadius: 999,
                    padding: `${PAD.default}`,
                    fontSize: FS.sm,
                    fontWeight: 800,
                    cursor: onOpenGraphRoom ? "pointer" : "default",
                    opacity: onOpenGraphRoom ? 1 : 0.65,
                  }}
                  disabled={!onOpenGraphRoom}
                >
                  Open Graph Intel room
                  <ArrowRight size={14} />
                </button>

                <button
                  type="button"
                  onClick={() => void refreshDerivedCaseData({ reloadGraph: true })}
                  className="helios-focus-ring"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: SP.xs,
                    borderRadius: 999,
                    border: `1px solid ${T.border}`,
                    background: T.surface,
                    color: T.textSecondary,
                    padding: PAD.default,
                    fontSize: FS.sm,
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Refresh case graph
                </button>
              </div>

              {graphLoading ? (
                <div className="flex items-center gap-2" style={{ fontSize: FS.sm, color: T.muted }}>
                  <LoadingSpinner />
                  Rebuilding the case network snapshot…
                </div>
              ) : null}

              {!graphLoading && !graphData ? (
                <div style={{ fontSize: FS.sm, color: T.muted }}>
                  No case graph has been built yet. Re-run the assessment or refresh the case graph before opening the room.
                </div>
              ) : null}
            </div>
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
