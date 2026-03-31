import { useState, useEffect, useMemo } from "react";
import { tierBand, parseTier, displayName, T } from "@/lib/tokens";
import { portfolioDisposition, workflowLaneForCase, WORKFLOW_LANE_META } from "./portfolio-utils";
import type { WorkflowLane } from "./portfolio-utils";
import { fetchMonitorChanges, fetchPortfolioAnomalies } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import type { MonitorChangeEntry } from "@/lib/api";
import { AlertTriangle, TrendingUp, TrendingDown, ArrowRight, Grid3X3, LayoutDashboard, Shield } from "lucide-react";
import { emit } from "@/lib/telemetry";

interface PortfolioScreenProps {
  allCases: VettingCase[];
  cases: VettingCase[];
  query?: string;
  onSelect: (c: VettingCase) => void;
  globalLane?: WorkflowLane;
  onGlobalLaneChange?: (lane: WorkflowLane) => void;
  onNavigate?: (tab: string) => void;
  laneSummary?: {
    lane: WorkflowLane;
    label: string;
    shortLabel: string;
    description: string;
    activeCount: number;
    reviewCount: number;
    blockedCount: number;
    watchCount: number;
    summary: string;
    topCaseName: string | null;
  };
}

type SortBy = "score" | "name" | "date";
type PortfolioFocus = "all" | "watchlist";
type LaneFilter = "all" | "counterparty" | "cyber" | "export";

function caseTimestamp(c: VettingCase): number {
  const raw = c.created_at || c.date;
  if (!raw) return 0;
  const parsed = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
  return Number.isFinite(parsed) ? parsed : 0;
}

function relativeCaseTime(c: VettingCase): string {
  const ts = caseTimestamp(c);
  if (!ts) return c.date || "";
  const diffMs = Date.now() - ts;
  const diffMinutes = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);
  if (diffMinutes < 1) return "Now";
  if (diffMinutes < 60) return `${diffMinutes}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function operatorPriorityScore(c: VettingCase): number {
  const disposition = portfolioDisposition(c);
  const base =
    disposition === "blocked"
      ? 400
      : disposition === "review"
        ? 260
        : disposition === "qualified"
          ? 140
          : 80;
  const stopWeight = (c.cal?.stops?.length ?? 0) * 20;
  const flagWeight = (c.cal?.flags?.length ?? 0) * 10;
  const recencyBoost = Math.max(0, 72 - Math.floor((Date.now() - caseTimestamp(c)) / 3_600_000));
  return base + stopWeight + flagWeight + recencyBoost;
}

function operatorSummary(c: VettingCase): string {
  const stop = c.cal?.stops?.[0]?.x?.trim();
  if (stop) return stop;
  const flag = c.cal?.flags?.[0]?.x?.trim();
  if (flag) return flag;
  const recommendation = c.cal?.recommendation?.trim();
  if (recommendation) return recommendation;
  const regulatory = c.cal?.regulatoryStatus?.trim();
  if (regulatory) return regulatory;
  const context = c.cal?.sensitivityContext?.trim();
  if (context) return context;
  const finding = c.cal?.finds?.[0]?.trim();
  if (finding) return finding;
  return c.program || c.profile || "Ready for analyst review.";
}

function dispositionTone(disposition: ReturnType<typeof portfolioDisposition>) {
  if (disposition === "blocked") return { color: "#f87171", bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.26)" };
  if (disposition === "review") return { color: "#fbbf24", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.24)" };
  if (disposition === "qualified") return { color: T.accent, bg: `${T.accent}12`, border: `${T.accent}28` };
  return { color: "#34d399", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.24)" };
}

export function PortfolioScreen({
  allCases,
  cases,
  onSelect,
  globalLane,
  onNavigate,
  laneSummary,
}: PortfolioScreenProps) {
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const portfolioFocus: PortfolioFocus = "all";
  const laneFilter: LaneFilter = globalLane ?? "all";
  const [anomalies, setAnomalies] = useState<Record<string, unknown>[]>([]);
  const [monitorChanges, setMonitorChanges] = useState<MonitorChangeEntry[]>([]);

  useEffect(() => {
    fetchPortfolioAnomalies(20).then((r) => setAnomalies(r.anomalies ?? [])).catch(() => {});
    fetchMonitorChanges(20).then((r) => setMonitorChanges(r.changes ?? [])).catch(() => {});
  }, []);
  const activeLaneMeta = laneFilter === "all" ? null : WORKFLOW_LANE_META[laneFilter];
  const blockedCases = useMemo(
    () => cases.filter((c) => portfolioDisposition(c) === "blocked"),
    [cases],
  );
  const reviewCases = useMemo(
    () => cases.filter((c) => portfolioDisposition(c) === "review"),
    [cases],
  );
  const qualifiedCases = useMemo(
    () => cases.filter((c) => portfolioDisposition(c) === "qualified"),
    [cases],
  );
  const priorityCases = useMemo(
    () => [...cases].sort((a, b) => operatorPriorityScore(b) - operatorPriorityScore(a)).slice(0, 4),
    [cases],
  );
  const recentCaseName = priorityCases[0] ? displayName(priorityCases[0].name) : laneSummary?.topCaseName ?? null;

  // Sorted case list
  const sortedCases = useMemo(() => {
    const focusCases = portfolioFocus === "watchlist"
      ? cases.filter((c) => portfolioDisposition(c) === "qualified")
      : cases;
    const scopedCases = laneFilter === "all"
      ? focusCases
      : focusCases.filter((c) => workflowLaneForCase(c) === laneFilter);
    const sorted = [...scopedCases];
    if (sortBy === "score") {
      sorted.sort((a, b) => operatorPriorityScore(b) - operatorPriorityScore(a));
    } else if (sortBy === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "date") {
      sorted.sort((a, b) => caseTimestamp(b) - caseTimestamp(a));
    }
    return sorted;
  }, [cases, sortBy, portfolioFocus, laneFilter]);

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col p-6">
      {activeLaneMeta && (
        <div className="mb-4 py-2 text-xs text-slate-500">
          {activeLaneMeta.label} · {cases?.length || 0} active · {blockedCases.length} blocked
        </div>
      )}

      <div className="mb-5 glass-panel animate-slide-up" style={{ padding: 24 }}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div style={{ fontSize: 11, color: activeLaneMeta?.accent || T.accent, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: 8 }}>
              Operator workbench
            </div>
            <h1 className="text-3xl font-bold text-slate-50" style={{ letterSpacing: "-0.04em", marginBottom: 10 }}>
              Work the queue, not the chrome.
            </h1>
            <p className="text-sm leading-7 text-slate-300" style={{ maxWidth: 760 }}>
              {laneSummary?.summary || activeLaneMeta?.description || "Review the cases that need a decision next, clear blockers, and move the lane forward."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:min-w-[320px]">
            <div className="glass-card" style={{ padding: 14 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Blocked</div>
              <div className="text-2xl font-bold text-red-400">{blockedCases.length}</div>
            </div>
            <div className="glass-card" style={{ padding: 14 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Review</div>
              <div className="text-2xl font-bold text-amber-300">{reviewCases.length}</div>
            </div>
            <div className="glass-card" style={{ padding: 14 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Watch</div>
              <div className="text-2xl font-bold text-sky-300">{qualifiedCases.length}</div>
            </div>
            <div className="glass-card" style={{ padding: 14 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Top case</div>
              <div className="text-sm font-semibold text-slate-100 truncate">{recentCaseName || "None"}</div>
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={() => priorityCases[0] && onSelect(priorityCases[0])}
            disabled={!priorityCases[0]}
            className="btn-interactive"
            style={{
              padding: "11px 14px",
              borderRadius: 14,
              border: "none",
              background: priorityCases[0] ? T.accent : T.border,
              color: priorityCases[0] ? "#04101f" : T.muted,
              cursor: priorityCases[0] ? "pointer" : "default",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontWeight: 700,
            }}
          >
            Open top priority
            <ArrowRight size={14} />
          </button>
          <button
            onClick={() => onNavigate?.("helios")}
            className="btn-interactive"
            style={{
              padding: "11px 14px",
              borderRadius: 14,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.text,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontWeight: 700,
            }}
          >
            <Shield size={14} />
            New intake
          </button>
          <button
            onClick={() => onNavigate?.("graph")}
            className="btn-interactive"
            style={{
              padding: "11px 14px",
              borderRadius: 14,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.text,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontWeight: 700,
            }}
          >
            <Grid3X3 size={14} />
            Graph intel
          </button>
          <button
            onClick={() => onNavigate?.("dashboard")}
            className="btn-interactive"
            style={{
              padding: "11px 14px",
              borderRadius: 14,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.text,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontWeight: 700,
            }}
          >
            <LayoutDashboard size={14} />
            Overview
          </button>
        </div>
      </div>

      {/* What Changed Strip */}
      {monitorChanges.length > 0 && (
        <div className="mb-4 glass-card animate-slide-up" style={{ padding: "10px 14px" }}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 overflow-x-auto" style={{ minWidth: 0 }}>
              <span className="shrink-0 font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted, letterSpacing: "0.06em" }}>
                Recent changes
              </span>
              <div className="flex items-center gap-2 stagger-children">
                {monitorChanges.slice(0, 5).map((change, idx) => {
                  const caseMatch = allCases.find((c) => c.id === change.vendor_id);
                  const name = change.vendor_name || (caseMatch ? displayName(caseMatch.name) : change.vendor_id.slice(0, 8));
                  const isIncrease = change.change_type === "risk_increase" || (!change.change_type && (change.current_risk ?? "") > (change.previous_risk ?? ""));
                  const ChangeIcon = isIncrease ? TrendingUp : TrendingDown;
                  const changeColor = isIncrease ? T.red : T.green;
                  return (
                    <button
                      key={`${change.vendor_id}-${idx}`}
                      onClick={() => {
                        if (caseMatch) {
                          onSelect(caseMatch);
                          emit("what_changed_clicked", { screen: "portfolio", case_id: change.vendor_id, metadata: { vendor_name: change.vendor_name || caseMatch.name, change_type: change.change_type } });
                        }
                      }}
                      title={change.delta_summary || undefined}
                      className="inline-flex items-center gap-1.5 rounded-full shrink-0 cursor-pointer btn-interactive"
                      style={{
                        padding: "5px 10px",
                        fontSize: 11,
                        fontWeight: 600,
                        color: changeColor,
                        background: `${changeColor}12`,
                        border: `1px solid ${changeColor}28`,
                      }}
                    >
                      <ChangeIcon size={10} />
                      <span style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
                    </button>
                  );
                })}
                {monitorChanges.length > 5 && (
                  <span className="shrink-0 rounded-full" style={{ padding: "5px 10px", fontSize: 11, fontWeight: 600, color: T.muted, background: T.raised, border: `1px solid ${T.border}` }}>
                    +{monitorChanges.length - 5} more
                  </span>
                )}
              </div>
            </div>
            {anomalies.length > 0 && (
              <div className="shrink-0 inline-flex items-center gap-1.5 rounded-full" style={{ padding: "5px 10px", fontSize: 11, fontWeight: 700, color: T.amber, background: `${T.amber}12`, border: `1px solid ${T.amber}28` }}>
                <AlertTriangle size={10} />
                {anomalies.length} anomal{anomalies.length === 1 ? "y" : "ies"}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mb-5 grid grid-cols-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-4">
        <div className="glass-card" style={{ padding: 18 }}>
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Priority queue</div>
          {priorityCases.length > 0 ? (
            <div className="space-y-3">
              {priorityCases.map((c) => {
                const disposition = portfolioDisposition(c);
                const tone = dispositionTone(disposition);
                return (
                  <button
                    key={c.id}
                    onClick={() => onSelect(c)}
                    className="w-full text-left rounded-2xl card-interactive"
                    style={{
                      padding: 14,
                      border: `1px solid ${tone.border}`,
                      background: tone.bg,
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold text-slate-100 truncate">{displayName(c.name)}</div>
                        <div className="mt-1 text-sm leading-6 text-slate-300">{operatorSummary(c)}</div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs text-slate-500">{relativeCaseTime(c)}</div>
                        <div
                          className="mt-2 inline-flex rounded-full px-2 py-1 text-xs font-bold"
                          style={{ color: tone.color, background: "rgba(15,23,42,0.45)", border: `1px solid ${tone.border}` }}
                        >
                          {disposition === "blocked" ? "Blocked" : disposition === "review" ? "Review" : disposition === "qualified" ? "Watch" : "Clear"}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-700 bg-slate-950/50 p-4 text-sm text-slate-400">
              No active cases in this lane yet.
            </div>
          )}
        </div>

        {/* KPI Cards Row */}
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-4 stagger-children">
        {/* Cases in Scope */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Cases in Scope</p>
          <p className="text-2xl font-bold text-slate-100" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.length || 0}
          </p>
        </div>

        {/* Blocked */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Blocked</p>
          <p className="text-2xl font-bold text-red-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {blockedCases.length}
          </p>
        </div>

        {/* Review Queue */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Review Queue</p>
          <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {reviewCases.length}
          </p>
        </div>

        {/* Watchlist */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Watchlist</p>
          <p className="text-2xl font-bold text-sky-300" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {qualifiedCases.length}
          </p>
        </div>

        {/* Avg Risk */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Avg Risk</p>
          <p className="text-2xl font-bold text-slate-100" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases && cases.length > 0
              ? Math.round(
                  cases.reduce((sum, c) => {
                    const band = tierBand(parseTier(c.cal?.tier || "green"));
                    const riskMap: Record<string, number> = {
                      critical: 95,
                      elevated: 75,
                      conditional: 50,
                      acceptable: 25,
                    };
                    return sum + (riskMap[band] || 0);
                  }, 0) / cases.length
                )
              : 0}
            %
          </p>
        </div>
      </div>
      </div>

      {/* Clean Case Table */}
      <div className="flex-1 overflow-auto">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">Cases</h2>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400">Sort by</label>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortBy)}
              className="rounded bg-slate-800 border border-slate-700 px-3 py-1 text-xs text-slate-300 cursor-pointer hover:border-slate-600"
            >
              <option value="score">Risk Score</option>
              <option value="date">Date</option>
              <option value="name">Vendor Name</option>
            </select>
          </div>
        </div>

        {cases && cases.length > 0 ? (
          <div className="overflow-x-auto border border-slate-700 rounded-lg">
            <table className="w-full text-sm">
              <thead style={{ position: 'sticky', top: 0, zIndex: 10 }}>
                <tr className="border-b border-slate-700 bg-slate-800">
                  <th className="px-4 py-3 text-left font-semibold text-slate-200">
                    Vendor Name
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-200">
                    Country
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-200">
                    Tier
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-200">
                    Risk Score
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-200">
                    Disposition
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-200">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedCases.map((c, idx) => {
                  const band = tierBand(parseTier(c.cal?.tier || "green"));
                  const bandColor =
                    band === "critical"
                      ? "#ef4444"
                      : band === "elevated"
                        ? "#f59e0b"
                        : "#10b981";
                  const disposition = portfolioDisposition(c);
                  const riskScore = c.cal?.p ?? c.sc;

                  return (
                    <tr
                      key={c.id}
                      onClick={() => onSelect(c)}
                      style={{
                        minHeight: '48px',
                        backgroundColor: idx % 2 === 0 ? '#111118' : 'transparent',
                        borderLeftWidth: "3px",
                        borderLeftColor: bandColor,
                        cursor: 'pointer',
                        transition: 'all 200ms ease-out',
                        boxShadow: 'none',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.boxShadow = 'none';
                      }}
                      className="border-b border-slate-700"
                    >
                      <td className="px-4 py-3 font-semibold text-slate-100">
                        {displayName(c.name)}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {c.cc || "N/A"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-1 rounded text-xs font-semibold ${
                            band === "critical"
                              ? "bg-red-900 text-red-200"
                              : band === "elevated"
                                ? "bg-yellow-900 text-yellow-200"
                                : "bg-green-900 text-green-200"
                          }`}
                        >
                          {band.charAt(0).toUpperCase() + band.slice(1)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-300" style={{ textAlign: 'right', fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                        {(riskScore * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3">
                        {disposition === "blocked" && (
                          <span className="px-2 py-1 rounded text-xs font-semibold bg-red-900 text-red-200">
                            Blocked
                          </span>
                        )}
                        {disposition === "review" && (
                          <span className="px-2 py-1 rounded text-xs font-semibold bg-yellow-900 text-yellow-200">
                            Review
                          </span>
                        )}
                        {disposition === "qualified" && (
                          <span className="px-2 py-1 rounded text-xs font-semibold bg-slate-700 text-slate-300">
                            Qualified
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs" style={{ textAlign: 'right' }}>
                        {c.date
                          ? new Date(c.date).toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                              year: "numeric",
                            })
                          : "N/A"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-700 bg-slate-950/60 p-6 text-sm text-slate-400">
            <div className="text-base font-semibold text-slate-100 mb-2">No active cases in this lane.</div>
            <div className="leading-6 mb-4">Open a new intake to start the queue, or switch lanes if the work is sitting somewhere else.</div>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => onNavigate?.("helios")}
                className="btn-interactive"
                style={{
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: "none",
                  background: T.accent,
                  color: "#04101f",
                  cursor: "pointer",
                  fontWeight: 700,
                }}
              >
                Open intake
              </button>
              <button
                onClick={() => onNavigate?.("dashboard")}
                className="btn-interactive"
                style={{
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: `1px solid ${T.border}`,
                  background: T.surface,
                  color: T.text,
                  cursor: "pointer",
                  fontWeight: 700,
                }}
              >
                Open overview
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
