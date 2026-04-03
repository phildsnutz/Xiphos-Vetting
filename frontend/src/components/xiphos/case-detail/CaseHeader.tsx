import React from "react";
import { ChevronDown, FileText } from "lucide-react";
import { useCaseDetail } from "./case-context";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { AIAnalysisStatus } from "@/lib/api";
import type { VettingCase } from "@/lib/types";

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

  return (
    <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: T.text, marginBottom: SP.sm - 2 }}>
          {c.name}
        </h1>
        <div className="flex items-center gap-2 flex-wrap">
          <span style={{ fontSize: FS.sm, color: T.muted, fontWeight: 600, textTransform: "uppercase" }}>
            Case ID
          </span>
          <span className="font-mono" style={{ fontSize: FS.sm, color: T.dim }}>
            {c.id}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {!isReadOnly && hasApi && (
          <button
            onClick={() => void onRefreshAiBrief()}
            disabled={aiBriefLoading}
            aria-label="Refresh AI brief status"
            style={{
              padding: PAD.default,
              borderRadius: SP.md - 2,
              border: `1px solid ${T.border}`,
              background: aiBriefLoading ? T.surface : `${T.accent}10`,
              color: aiBriefLoading ? T.muted : T.accent,
              fontSize: FS.sm,
              fontWeight: 700,
              cursor: aiBriefLoading ? "wait" : "pointer",
            }}
          >
            {aiBriefLoading ? "Refreshing..." : "Refresh AI Brief"}
          </button>
        )}

        {aiBriefSummary && (
          <div
            style={{
              padding: PAD.tight,
              borderRadius: SP.sm,
              background: aiBriefReady ? `${T.accent}12` : T.surface,
              border: `1px solid ${aiBriefReady ? `${T.accent}33` : T.border}`,
              fontSize: FS.sm,
              color: aiBriefReady ? T.accent : T.muted,
              fontWeight: 600,
            }}
          >
            {aiBriefSummary}
          </div>
        )}

        <div style={{ position: "relative" }} ref={moreActionsRef}>
          <button
            onClick={() => setShowMoreActions(!showMoreActions)}
            aria-label="Open case actions"
            aria-haspopup="menu"
            aria-expanded={showMoreActions}
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
                  {generating ? "Generating..." : "Generate HTML Dossier"}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
