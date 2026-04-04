import React from "react";
import { ChevronDown, FileText } from "lucide-react";
import { useCaseDetail } from "./case-context";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { AIAnalysisStatus } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { PRODUCT_PILLAR_META, WORKFLOW_LANE_META, workflowLaneForCase } from "../portfolio-utils";
import { StatusPill } from "../shell-primitives";

interface CaseHeaderProps {
  c: VettingCase;
  isReadOnly: boolean;
  hasApi: boolean;
  aiBriefStatus: AIAnalysisStatus | null;
  aiBriefSummary: string | null;
  onRefreshAiBrief: () => void;
}

export const CaseHeader: React.FC<CaseHeaderProps> = ({
  c,
  isReadOnly,
  hasApi,
  aiBriefStatus,
  aiBriefSummary,
  onRefreshAiBrief,
}) => {
  const {
    showMoreActions,
    setShowMoreActions,
    handleDossier,
    generating,
    moreActionsRef,
  } = useCaseDetail();
  const aiBriefLoading = aiBriefStatus?.status === "running" || aiBriefStatus?.status === "pending";
  const aiBriefReady = aiBriefStatus?.status === "ready" || aiBriefStatus?.status === "completed";
  const supportingLayer = WORKFLOW_LANE_META[workflowLaneForCase(c)];
  const aiBriefTone = aiBriefReady ? "success" : aiBriefLoading ? "info" : "neutral";
  const aiBriefLabel = aiBriefSummary || (aiBriefLoading ? "AI brief warming" : "AI brief idle");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SP.sm, marginBottom: SP.sm }}>
      <div className="flex items-center gap-2 flex-wrap">
        <StatusPill tone="info">{PRODUCT_PILLAR_META.vendor_assessment.label}</StatusPill>
        <StatusPill tone="neutral">{supportingLayer.label}</StatusPill>
        <StatusPill tone={aiBriefTone}>{aiBriefLabel}</StatusPill>
        <StatusPill tone="neutral">Case {c.id}</StatusPill>
      </div>

      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: T.text, marginBottom: SP.xs }}>
            {c.name}
          </h1>
          <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, maxWidth: 760 }}>
            Keep the decision visible, work the evidence on the right, and let AXIOM or the graph close whatever stays dark.
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {!isReadOnly && hasApi && (
            <button
              onClick={() => void onRefreshAiBrief()}
              disabled={aiBriefLoading}
              aria-label="Refresh AI brief status"
              className="helios-focus-ring"
              style={{
                padding: PAD.default,
                borderRadius: SP.md - 2,
                border: `1px solid ${T.border}`,
                background: aiBriefLoading ? T.surface : `${T.accent}10`,
                color: aiBriefLoading ? T.textSecondary : T.accent,
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: aiBriefLoading ? "wait" : "pointer",
              }}
            >
              {aiBriefLoading ? "Refreshing..." : "Warm brief"}
            </button>
          )}

          <div style={{ position: "relative" }} ref={moreActionsRef}>
            <button
              onClick={() => setShowMoreActions(!showMoreActions)}
              aria-label="Open case actions"
              aria-haspopup="menu"
              aria-expanded={showMoreActions}
              className="helios-focus-ring"
              style={{
                padding: PAD.default,
                borderRadius: SP.md - 2,
                border: `1px solid ${T.border}`,
                background: T.surface,
                color: T.text,
                fontSize: FS.sm,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: SP.sm - 2,
              }}
            >
              <span>Actions</span>
              <ChevronDown size={14} />
            </button>

            {showMoreActions && (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  right: 0,
                  marginTop: SP.xs,
                  background: T.surface,
                  border: `1px solid ${T.border}`,
                  borderRadius: SP.sm,
                  zIndex: 1000,
                  minWidth: 200,
                }}
              >
                {!isReadOnly && hasApi && (
                  <button
                    aria-label="Generate HTML dossier"
                    onClick={() => {
                      void handleDossier();
                      setShowMoreActions(false);
                    }}
                    disabled={generating}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: PAD.default,
                      background: "transparent",
                      color: T.text,
                      fontSize: FS.sm,
                      border: "none",
                      cursor: generating ? "wait" : "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: SP.sm,
                    }}
                  >
                    <FileText size={14} />
                    {generating ? "Generating..." : "Generate HTML dossier"}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
