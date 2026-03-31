import { useState, useEffect, useMemo } from "react";
import { tierBand, parseTier, displayName, T } from "@/lib/tokens";
import { portfolioDisposition, workflowLaneForCase, WORKFLOW_LANE_META } from "./portfolio-utils";
import type { WorkflowLane } from "./portfolio-utils";
import { fetchMonitorChanges, fetchPortfolioAnomalies } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import type { MonitorChangeEntry } from "@/lib/api";
import { AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
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

export function PortfolioScreen({
  allCases,
  cases,
  onSelect,
  globalLane,
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
      sorted.sort((a, b) => (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc));
    } else if (sortBy === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "date") {
      sorted.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    }
    return sorted;
  }, [cases, sortBy, portfolioFocus, laneFilter]);

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col p-6">
      {/* Single-line Status Bar */}
      {activeLaneMeta && (
        <div className="mb-6 py-2 text-xs text-slate-500">
          {activeLaneMeta.label} · {cases?.length || 0} active · {cases?.filter((c) => portfolioDisposition(c) === "blocked").length || 0} blocked
        </div>
      )}

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

      {/* KPI Cards Row */}
      <div className="mb-8 grid grid-cols-5 gap-4 stagger-children">
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
            {cases?.filter((c) => portfolioDisposition(c) === "blocked").length || 0}
          </p>
        </div>

        {/* Review Queue */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Review Queue</p>
          <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.filter((c) => portfolioDisposition(c) === "review").length || 0}
          </p>
        </div>

        {/* Watchlist */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4 card-interactive">
          <p className="text-xs font-medium text-slate-500 mb-2">Watchlist</p>
          <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.filter((c) => {
              const lane = workflowLaneForCase(c);
              return lane !== "export" && lane !== "cyber";
            }).length || 0}
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
          <p className="text-slate-400 text-sm py-4">No active cases</p>
        )}
      </div>
    </div>
  );
}
