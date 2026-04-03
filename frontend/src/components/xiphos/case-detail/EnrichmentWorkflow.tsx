import React, { useRef } from "react";
import { Upload } from "lucide-react";
import { useCaseDetail } from "./case-context";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { WorkflowLane } from "../portfolio-utils";

interface EnrichmentWorkflowProps {
  isReadOnly: boolean;
  authorityLaneKey: WorkflowLane;
  showFociPanel: boolean;
  showSprsPanel: boolean;
  showOscalPanel: boolean;
  uploadingFociArtifact: boolean;
  uploadingSprsArtifact: boolean;
  uploadingOscalArtifact: boolean;
  uploadingNvdOverlay: boolean;
  latestFociSummary: Record<string, unknown> | null;
  latestSprsSummaries: Array<{ assessment_summary?: Record<string, unknown> | null }>;
  latestOscalSummary: Record<string, unknown> | null;
  sprsStatusLabel: (status: string) => string;
}

export const EnrichmentWorkflow: React.FC<EnrichmentWorkflowProps> = ({
  isReadOnly,
  authorityLaneKey,
  showFociPanel,
  showSprsPanel,
  showOscalPanel,
  uploadingFociArtifact,
  uploadingSprsArtifact,
  uploadingOscalArtifact,
  uploadingNvdOverlay,
  latestFociSummary,
  latestSprsSummaries,
  latestOscalSummary,
  sprsStatusLabel,
}) => {
  const {
    handleFociArtifactSelected,
    handleSprsImportSelected,
    handleOscalArtifactSelected,
    handleRunNvdOverlay,
  } = useCaseDetail();

  const fociInputRef = useRef<HTMLInputElement>(null);
  const sprsInputRef = useRef<HTMLInputElement>(null);
  const oscalInputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      {showFociPanel && authorityLaneKey === "counterparty" && (
        <div className="rounded-lg glass-card" style={{ padding: PAD.default, marginTop: SP.md }}>
          <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: SP.sm + 2 }}>
            <div>
              <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                FOCI disclosure evidence
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.5 }}>
                Attach FCI form or FOCI assertion so Helios can ground trust decisions in current Foreign Ownership Control or Influence status.
              </div>
            </div>
            {!isReadOnly && (
              <button
                onClick={() => fociInputRef.current?.click()}
                disabled={uploadingFociArtifact}
                aria-label="Upload FOCI artifact"
                style={{
                  padding: PAD.default,
                  borderRadius: SP.md - 2,
                  border: `1px solid ${T.border}`,
                  background: uploadingFociArtifact ? T.surface : `${T.accent}10`,
                  color: uploadingFociArtifact ? T.muted : T.accent,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.sm,
                  cursor: uploadingFociArtifact ? "wait" : "pointer",
                }}
              >
                <Upload size={14} />
                {uploadingFociArtifact ? "Uploading..." : "Upload FOCI"}
              </button>
            )}
          </div>

          <input
            ref={fociInputRef}
            type="file"
            accept=".pdf,application/pdf"
            style={{ display: "none" }}
            onChange={handleFociArtifactSelected}
          />

          {latestFociSummary && (
            <div style={{ padding: PAD.default, borderRadius: SP.sm, background: T.raised, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: SP.xs }}>
                Latest submission
              </div>
              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                {String(latestFociSummary.document_label || "FOCI document")}
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.sm - 2, lineHeight: 1.5 }}>
                {String(latestFociSummary.assertion_text || "")}
              </div>
            </div>
          )}
        </div>
      )}

      {showSprsPanel && authorityLaneKey === "counterparty" && (
        <div className="rounded-lg glass-card" style={{ padding: PAD.default, marginTop: SP.md }}>
          <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: SP.sm + 2 }}>
            <div>
              <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                SPRS assessment evidence
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.5 }}>
                Attach SPRS assessment or import data so Helios can ground trust decisions in current CMMC and remediation status.
              </div>
            </div>
            {!isReadOnly && (
              <button
                onClick={() => sprsInputRef.current?.click()}
                disabled={uploadingSprsArtifact}
                aria-label="Upload SPRS artifact"
                style={{
                  padding: PAD.default,
                  borderRadius: SP.md - 2,
                  border: `1px solid ${T.border}`,
                  background: uploadingSprsArtifact ? T.surface : `${T.accent}10`,
                  color: uploadingSprsArtifact ? T.muted : T.accent,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.sm,
                  cursor: uploadingSprsArtifact ? "wait" : "pointer",
                }}
              >
                <Upload size={14} />
                {uploadingSprsArtifact ? "Uploading..." : "Upload SPRS"}
              </button>
            )}
          </div>

          <input
            ref={sprsInputRef}
            type="file"
            accept=".pdf,application/pdf"
            style={{ display: "none" }}
            onChange={handleSprsImportSelected}
          />

          {latestSprsSummaries.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: SP.sm + 2 }}>
              {latestSprsSummaries.map((artifact, idx) => {
                const summary = artifact.assessment_summary;
                return (
                  <div key={idx} style={{ padding: PAD.default, borderRadius: SP.sm, background: T.raised, border: `1px solid ${T.border}` }}>
                    <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: SP.xs }}>
                      Assessment {idx + 1}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginBottom: SP.xs }}>
                      {String(summary?.matched_supplier_name || "Unknown supplier")}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted, display: "flex", gap: SP.sm, flexWrap: "wrap", marginBottom: SP.sm - 2 }}>
                      <span>{String(summary?.assessment_date || "")}</span>
                      <span>•</span>
                      <span>CMMC {String(summary?.current_cmmc_level || "N/A")}</span>
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim }}>
                      {sprsStatusLabel(String(summary?.status || "unknown"))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {showOscalPanel && authorityLaneKey === "cyber" && (
        <div className="rounded-lg glass-card" style={{ padding: PAD.default, marginTop: SP.md }}>
          <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: SP.sm + 2 }}>
            <div>
              <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                OSCAL remediation evidence
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.5 }}>
                Attach OSCAL SSP or POA&M JSON so Helios can ground supplier cyber-trust decisions in control-family coverage and active remediation work.
              </div>
            </div>
            {!isReadOnly && (
              <button
                onClick={() => oscalInputRef.current?.click()}
                disabled={uploadingOscalArtifact}
                aria-label="Upload OSCAL artifact"
                style={{
                  padding: PAD.default,
                  borderRadius: SP.md - 2,
                  border: `1px solid ${T.border}`,
                  background: uploadingOscalArtifact ? T.surface : `${T.accent}10`,
                  color: uploadingOscalArtifact ? T.muted : T.accent,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.sm,
                  cursor: uploadingOscalArtifact ? "wait" : "pointer",
                }}
              >
                <Upload size={14} />
                {uploadingOscalArtifact ? "Uploading..." : "Upload OSCAL JSON"}
              </button>
            )}
          </div>

          <input
            ref={oscalInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: "none" }}
            onChange={handleOscalArtifactSelected}
          />

          {latestOscalSummary && (
            <div style={{ padding: "10px 12px", borderRadius: 8, background: T.raised, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Latest document
              </div>
              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginBottom: 4 }}>
                {String(latestOscalSummary.document_label || "OSCAL artifact")}
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim }}>
                System: {String(latestOscalSummary.system_name || "Unnamed system")}
              </div>
            </div>
          )}
        </div>
      )}

      {authorityLaneKey === "cyber" && !isReadOnly && (
        <button
          onClick={() => void handleRunNvdOverlay()}
          disabled={uploadingNvdOverlay}
          style={{
            marginTop: 12,
            padding: "9px 12px",
            borderRadius: 10,
            border: `1px solid ${T.border}`,
            background: uploadingNvdOverlay ? T.surface : `${T.accent}10`,
            color: uploadingNvdOverlay ? T.muted : T.accent,
            fontSize: FS.sm,
            fontWeight: 700,
            cursor: uploadingNvdOverlay ? "wait" : "pointer",
          }}
        >
          {uploadingNvdOverlay ? "Running NVD overlay..." : "Run NVD Overlay"}
        </button>
      )}
    </>
  );
};
