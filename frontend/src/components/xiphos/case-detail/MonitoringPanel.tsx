import React from "react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { CaseMonitoringHistory, MonitoringHistoryEntry } from "@/lib/api";
import type { MonitoringHistorySummary, MonitoringLaneCopy, ToneConfig } from "./case-detail-types";

interface MonitoringPanelProps {
  monitorHistoryRef: React.RefObject<HTMLDivElement | null>;
  monitoringHistory: CaseMonitoringHistory | null;
  monitoringHistorySummary: MonitoringHistorySummary | null;
  monitoringHistoryLoading: boolean;
  latestMonitoringChecks: MonitoringHistoryEntry[];
  monitoringLaneCopy: MonitoringLaneCopy;
  monitoringEntryTone: (entry: MonitoringHistoryEntry) => ToneConfig;
  formatMonitorTierLabel: (tier: string) => string;
}

export const MonitoringPanel: React.FC<MonitoringPanelProps> = ({
  monitorHistoryRef,
  monitoringHistory,
  monitoringHistorySummary,
  monitoringHistoryLoading,
  latestMonitoringChecks,
  monitoringLaneCopy,
  monitoringEntryTone,
  formatMonitorTierLabel,
}) => {
  if (!monitoringHistory) return null;

  return (
    <div
      ref={monitorHistoryRef}
      className="rounded-lg"
      style={{
        background: T.surface,
        border: `1px solid ${T.border}`,
        padding: 12,
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
            {monitoringLaneCopy.title}
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
            {monitoringLaneCopy.detail}
          </div>
        </div>
        {monitoringHistory.latest_score?.tier && (
          <div
            className="rounded-full px-2 py-1"
            style={{ background: `${T.accent}12`, color: T.accent, fontSize: FS.xs, fontWeight: 700 }}
          >
            Current {formatMonitorTierLabel(monitoringHistory.latest_score.tier)}
          </div>
        )}
      </div>

      {monitoringHistorySummary && (
        <div
          className="rounded-lg"
          style={{
            background: T.raised,
            border: `1px solid ${T.border}`,
            padding: SP.sm + 2,
            marginBottom: SP.sm + 2,
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: SP.sm }}>
            {[
              { label: monitoringLaneCopy.runsLabel, value: monitoringHistorySummary.runs, color: T.text, bg: T.surface },
              { label: monitoringLaneCopy.changedLabel, value: monitoringHistorySummary.changed, color: T.amber, bg: `${T.amber}12` },
              { label: monitoringLaneCopy.findingsLabel, value: monitoringHistorySummary.newFindings, color: T.accent, bg: `${T.accent}12` },
            ].map((card) => (
              <div key={card.label} className="rounded-lg" style={{ background: card.bg, padding: PAD.default, border: `1px solid ${T.border}` }}>
                <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  {card.label}
                </div>
                <div style={{ fontSize: FS.base, color: card.color, fontWeight: 700, marginTop: SP.xs }}>
                  {card.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ maxHeight: 360, overflow: "auto", display: "flex", flexDirection: "column", gap: SP.sm }}>
        {monitoringHistoryLoading && !monitoringHistory ? (
          <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: SP.md, color: T.muted, fontSize: FS.sm }}>
            {monitoringLaneCopy.loadingLabel}
          </div>
        ) : latestMonitoringChecks.length === 0 ? (
          <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: SP.md }}>
            <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
              {monitoringLaneCopy.emptyTitle}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.xs, lineHeight: 1.5 }}>
              {monitoringLaneCopy.emptyDetail}
            </div>
          </div>
        ) : (
          latestMonitoringChecks.map((entry, index) => {
            const tone = monitoringEntryTone(entry);
            return (
              <div
                key={`${entry.checked_at || "check"}-${index}`}
                className="rounded-lg"
                style={{ background: T.raised, border: `1px solid ${T.border}`, padding: SP.sm + 2 }}
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                      {entry.checked_at
                        ? new Date(entry.checked_at).toLocaleString([], {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "Recent check"}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted, marginTop: SP.xs - 1 }}>
                      {formatMonitorTierLabel(entry.previous_risk || "UNKNOWN")} {"->"} {formatMonitorTierLabel(entry.current_risk || "UNKNOWN")}
                    </div>
                  </div>
                  <span
                    style={{
                      padding: PAD.tight,
                      borderRadius: 999,
                      fontSize: FS.xs,
                      color: tone.color,
                      background: tone.background,
                      border: `1px solid ${tone.border}`,
                      fontWeight: 700,
                    }}
                  >
                    {tone.label}
                  </span>
                </div>

                <div className="flex items-center gap-3 flex-wrap" style={{ marginTop: SP.sm }}>
                  <span style={{ fontSize: FS.sm, color: T.dim }}>
                    {monitoringLaneCopy.findingsText(entry.new_findings_count ?? 0)}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim }}>
                    {(entry.resolved_findings_count ?? 0) === 1 ? "1 resolved" : `${entry.resolved_findings_count ?? 0} resolved`}
                  </span>
                  {entry.risk_changed ? (
                    <span style={{ fontSize: FS.sm, color: T.amber, fontWeight: 600 }}>
                      {monitoringLaneCopy.shiftedText}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
