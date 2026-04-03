import React from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useCaseDetail } from "./case-context";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { BatchScreeningRow, PersonScreeningRecord } from "./case-detail-types";

interface PersonScreeningProps {
  isReadOnly: boolean;
  screeningPerson: string;
  setScreeningPerson: (person: string) => void;
  screeningResult: PersonScreeningRecord | null;
  batchScreeningResults: BatchScreeningRow[];
  batchScreeningFile: File | null;
  setBatchScreeningFile: (file: File | null) => void;
  batchScreeningError: string | null;
  screeningLoading: boolean;
  screeningBatch: boolean;
  showPersonScreening: boolean;
  setShowPersonScreening: (show: boolean) => void;
}

export const PersonScreening: React.FC<PersonScreeningProps> = ({
  isReadOnly,
  screeningPerson,
  setScreeningPerson,
  screeningResult,
  batchScreeningResults,
  batchScreeningFile,
  setBatchScreeningFile,
  batchScreeningError,
  screeningLoading,
  screeningBatch,
  showPersonScreening,
  setShowPersonScreening,
}) => {
  const {
    handleScreenPerson,
    handleBatchScreenCsv,
    handleDownloadCsvTemplate,
  } = useCaseDetail();

  if (!showPersonScreening) {
    return (
      <div className="rounded-lg glass-card" style={{ padding: PAD.default, marginTop: SP.md }}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Person screening
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.5 }}>
              Screen individuals against sanctions, denied parties, adverse media, and related watchlists.
            </div>
          </div>
          <button
            onClick={() => setShowPersonScreening(true)}
            aria-label="Show person screening tools"
            style={{
              padding: PAD.default,
              borderRadius: SP.md - 2,
              border: `1px solid ${T.border}`,
              background: `${T.accent}10`,
              color: T.accent,
              fontSize: FS.sm,
              fontWeight: 700,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: SP.sm,
            }}
          >
            Open screening
            <ChevronDown size={14} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg glass-card" style={{ padding: PAD.default, marginTop: SP.md }}>
      <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: SP.sm + 2 }}>
        <div>
          <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Person screening
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.5 }}>
            Screen individuals against sanctions, denied parties, adverse media, and related watchlists.
          </div>
        </div>
        <button
          onClick={() => setShowPersonScreening(false)}
          aria-label="Hide person screening tools"
          style={{
            padding: PAD.tight,
            borderRadius: SP.sm,
            border: `1px solid ${T.border}`,
            background: T.surface,
            color: T.muted,
            fontSize: FS.sm,
            fontWeight: 600,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: SP.sm - 2,
          }}
        >
          Hide
          <ChevronUp size={14} />
        </button>
      </div>

      {/* Individual Screening */}
      {!isReadOnly && (
        <div style={{ display: "flex", gap: SP.sm, alignItems: "center", marginBottom: SP.md }}>
          <input
            type="text"
            value={screeningPerson}
            onChange={(e) => setScreeningPerson(e.target.value)}
            placeholder="Enter person name..."
            aria-label="Person name for screening"
            style={{
              flex: 1,
              padding: PAD.default,
              borderRadius: SP.md - 2,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.text,
              fontSize: FS.sm,
            }}
          />
          <button
            onClick={() => void handleScreenPerson()}
            disabled={screeningLoading || !screeningPerson}
            aria-label="Run person screening"
            style={{
              padding: PAD.default,
              borderRadius: SP.md - 2,
              border: `1px solid ${T.border}`,
              background: screeningLoading || !screeningPerson ? T.surface : `${T.accent}10`,
              color: screeningLoading || !screeningPerson ? T.muted : T.accent,
              fontSize: FS.sm,
              fontWeight: 700,
              cursor: screeningLoading || !screeningPerson ? "default" : "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {screeningLoading ? "Screening..." : "Screen"}
          </button>
        </div>
      )}

      {/* Batch Screening */}
      {!isReadOnly && (
        <div style={{ display: "flex", flexDirection: "column", gap: SP.sm, marginBottom: SP.md }}>
          <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Batch screening
          </div>
          <div style={{ display: "flex", gap: SP.sm, alignItems: "center" }}>
            <button
              onClick={() => void handleDownloadCsvTemplate()}
              aria-label="Download CSV template for batch screening"
              style={{
                padding: PAD.tight,
                borderRadius: SP.sm,
                border: `1px solid ${T.border}`,
                background: "transparent",
                color: T.accent,
                fontSize: FS.xs,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Download template
            </button>
          </div>
          <div style={{ display: "flex", gap: SP.sm, alignItems: "center" }}>
            <label
              style={{
                flex: 1,
                padding: PAD.default,
                borderRadius: SP.md - 2,
                border: `1px dashed ${T.border}`,
                background: T.surface,
                color: batchScreeningFile ? T.text : T.muted,
                fontSize: FS.sm,
                cursor: "pointer",
                textAlign: "center",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {batchScreeningFile ? batchScreeningFile.name : "Choose CSV file..."}
              <input
                type="file"
                accept=".csv,text/csv"
                aria-label="Choose CSV file for batch screening"
                style={{ display: "none" }}
                onChange={(e) => {
                  setBatchScreeningFile(e.target.files?.[0] || null);
                }}
              />
            </label>
            <button
              onClick={() => void handleBatchScreenCsv()}
              disabled={screeningBatch || !batchScreeningFile}
              aria-label="Run batch screening from CSV"
              style={{
                padding: PAD.default,
                borderRadius: SP.md - 2,
                border: `1px solid ${T.border}`,
                background: screeningBatch || !batchScreeningFile ? T.surface : `${T.accent}10`,
                color: screeningBatch || !batchScreeningFile ? T.muted : T.accent,
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: screeningBatch || !batchScreeningFile ? "default" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {screeningBatch ? "Screening..." : "Screen batch"}
            </button>
          </div>
          {batchScreeningError && (
            <div style={{ marginTop: SP.sm, padding: PAD.default, borderRadius: SP.sm, background: `${T.red}12`, border: `1px solid ${T.red}33`, color: T.red, fontSize: FS.sm }}>
              {batchScreeningError}
            </div>
          )}
        </div>
      )}

      {/* Batch Results Table */}
      {batchScreeningResults.length > 0 && (
        <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: PAD.default, marginBottom: SP.sm + 2 }}>
          <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: SP.sm }}>
            Batch results ({batchScreeningResults.length} screened)
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: FS.sm }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                  <th style={{ padding: PAD.tight, textAlign: "left", color: T.muted, fontSize: FS.xs, fontWeight: 600 }}>Name</th>
                  <th style={{ padding: PAD.tight, textAlign: "left", color: T.muted, fontSize: FS.xs, fontWeight: 600 }}>Status</th>
                  <th style={{ padding: PAD.tight, textAlign: "right", color: T.muted, fontSize: FS.xs, fontWeight: 600 }}>Score</th>
                  <th style={{ padding: PAD.tight, textAlign: "left", color: T.muted, fontSize: FS.xs, fontWeight: 600 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {batchScreeningResults.map((r, idx) => {
                  const status = String(r.screening_status || "UNKNOWN");
                  const statusColor = status === "CLEAR" ? T.green : status === "MATCH" ? T.red : status === "PARTIAL_MATCH" ? T.amber : status === "ESCALATE" ? T.red : T.dim;
                  return (
                    <tr key={idx} style={{ borderBottom: `1px solid ${T.border}` }}>
                      <td style={{ padding: PAD.tight, color: T.text, fontWeight: 600 }}>
                        {String(r.person_name || "Unknown")}
                      </td>
                      <td style={{ padding: PAD.tight }}>
                        <span style={{ display: "inline-block", padding: `2px ${SP.sm}px`, borderRadius: 999, background: `${statusColor}18`, border: `1px solid ${statusColor}44`, color: statusColor, fontSize: FS.xs, fontWeight: 700 }}>
                          {status.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td style={{ padding: PAD.tight, textAlign: "right", color: T.text, fontWeight: 600 }}>
                        {typeof r.composite_score === "number" ? ((r.composite_score as number) * 100).toFixed(1) + "%" : "N/A"}
                      </td>
                      <td style={{ padding: PAD.tight, color: T.dim, fontSize: FS.xs }}>
                        {String(r.recommended_action || "").substring(0, 60)}
                        {String(r.recommended_action || "").length > 60 ? "..." : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {screeningResult && (
        <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: PAD.default }}>
          <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: SP.sm }}>
            Latest result
          </div>
          <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
            {String(screeningResult.screening_status || screeningResult.status || "UNKNOWN").replaceAll("_", " ")}
          </div>
          {typeof screeningResult.recommended_action === "string" && (
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.sm - 2, lineHeight: 1.5 }}>
              {screeningResult.recommended_action}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
