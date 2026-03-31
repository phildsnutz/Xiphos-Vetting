import { useState, useEffect } from "react";
import { T, FS } from "@/lib/tokens";
import { Activity, TrendingUp, TrendingDown, CheckCircle, Clock, Minus } from "lucide-react";
import { fetchMonitorRunHistory } from "@/lib/api";
import type { MonitorRunEntry } from "@/lib/api";
import { SkeletonCard } from "./loader";
import { emit } from "@/lib/telemetry";

interface MonitorHistoryPanelProps {
  caseId: string;
  vendorName: string;
  /** Bump to force re-fetch (e.g. after monitoring completes) */
  refreshKey?: number;
}

function changeIcon(changeType?: string) {
  switch (changeType) {
    case "risk_increase":
      return { Icon: TrendingUp, color: T.red };
    case "risk_decrease":
      return { Icon: TrendingDown, color: T.green };
    case "new_findings":
      return { Icon: Activity, color: T.amber };
    case "resolved_findings":
      return { Icon: CheckCircle, color: T.green };
    case "no_change":
    default:
      return { Icon: Minus, color: T.muted };
  }
}

function statusBadge(status: string) {
  switch (status) {
    case "completed":
      return { color: T.green, bg: `${T.green}14`, label: "Completed" };
    case "pending":
      return { color: T.amber, bg: `${T.amber}14`, label: "Pending" };
    case "failed":
      return { color: T.red, bg: `${T.red}14`, label: "Failed" };
    default:
      return { color: T.muted, bg: T.raised, label: status };
  }
}

function relativeTime(iso?: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function scoreDelta(before?: number | null, after?: number | null): string | null {
  if (before == null || after == null) return null;
  const delta = Math.round((after - before) * 1000) / 10;
  if (delta === 0) return null;
  return delta > 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`;
}

export function MonitorHistoryPanel({ caseId, vendorName, refreshKey }: MonitorHistoryPanelProps) {
  const [runs, setRuns] = useState<MonitorRunEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchMonitorRunHistory(caseId, 10)
      .then((data) => {
        if (!cancelled) {
          setRuns(data.runs ?? []);
          emit("monitor_history_viewed", {
            screen: "case_detail",
            case_id: caseId,
            metadata: { run_count: data.runs?.length ?? 0, vendor_name: vendorName },
          });
        }
      })
      .catch(() => {
        if (!cancelled) setRuns([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [caseId, refreshKey, vendorName]);

  return (
    <div className="glass-card p-4 animate-fade-in" style={{ marginTop: 14 }}>
      <div className="flex items-center gap-2 mb-3">
        <Activity size={14} color={T.accent} />
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted, letterSpacing: "0.06em" }}>
          Monitor Run History
        </span>
      </div>

      {loading && (
        <div className="flex flex-col gap-2">
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
        </div>
      )}

      {!loading && runs.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8">
          <Clock size={24} color={T.muted} style={{ marginBottom: 8, opacity: 0.5 }} />
          <div style={{ fontSize: FS.sm, color: T.dim, fontWeight: 600 }}>No monitor runs yet</div>
          <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>Run monitoring to see history here.</div>
        </div>
      )}

      {!loading && runs.length > 0 && (
        <div className="flex flex-col gap-2 stagger-children">
          {runs.map((run) => {
            const { Icon: ChangeIcon, color: changeColor } = changeIcon(run.change_type);
            const badge = statusBadge(run.status);
            const delta = scoreDelta(run.score_before, run.score_after);
            return (
              <div
                key={run.run_id}
                className="rounded-lg p-3 card-interactive"
                style={{ background: T.bg, border: `1px solid ${T.border}` }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2" style={{ minWidth: 0 }}>
                    <div
                      className="rounded-md flex items-center justify-center shrink-0"
                      style={{
                        width: 28,
                        height: 28,
                        background: `${changeColor}14`,
                        border: `1px solid ${changeColor}28`,
                        marginTop: 2,
                      }}
                    >
                      <ChangeIcon size={13} color={changeColor} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                        {run.delta_summary || (run.change_type === "no_change" ? "No material change" : run.change_type?.replace(/_/g, " ") || "Monitor run")}
                      </div>
                      <div className="flex items-center gap-2 flex-wrap" style={{ marginTop: 4 }}>
                        {delta && (
                          <span
                            className="rounded-full font-mono"
                            style={{
                              padding: "2px 7px",
                              fontSize: 11,
                              fontWeight: 700,
                              color: delta.startsWith("+") ? T.red : T.green,
                              background: delta.startsWith("+") ? `${T.red}14` : `${T.green}14`,
                            }}
                          >
                            {delta}
                          </span>
                        )}
                        {(run.new_findings_count ?? 0) > 0 && (
                          <span style={{ fontSize: 11, color: T.amber }}>
                            {run.new_findings_count} new finding{run.new_findings_count === 1 ? "" : "s"}
                          </span>
                        )}
                        {(run.sources_triggered ?? []).length > 0 && (
                          <span style={{ fontSize: 11, color: T.muted }}>
                            {run.sources_triggered!.length} source{run.sources_triggered!.length === 1 ? "" : "s"} triggered
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span
                      className="rounded-full"
                      style={{
                        padding: "2px 7px",
                        fontSize: 11,
                        fontWeight: 600,
                        color: badge.color,
                        background: badge.bg,
                      }}
                    >
                      {badge.label}
                    </span>
                    <span style={{ fontSize: 11, color: T.muted }}>
                      {relativeTime(run.completed_at || run.started_at)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
