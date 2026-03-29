import { useState, useEffect, useMemo } from "react";
import { tierBand, TIER_BANDS, parseTier, displayName } from "@/lib/tokens";
import { portfolioDisposition, workflowLaneForCase, WORKFLOW_LANE_META } from "./portfolio-utils";
import type { WorkflowLane } from "./portfolio-utils";
import { fetchMonitorChanges, fetchPortfolioAnomalies, fetchPortfolioSnapshot } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import type { MonitorChangeEntry } from "@/lib/api";

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
const WORKFLOW_LANES = ["counterparty", "cyber", "export"] as const;

function _priorityDescription(c: VettingCase): string {
  if (c.cal?.stops && c.cal.stops.length > 0) {
    return c.cal.stops[0].t;
  }
  if (c.cal?.flags && c.cal.flags.length > 0 && c.cal.tier) {
    const band = tierBand(parseTier(c.cal.tier));
    if (band === "critical" || band === "elevated" || band === "conditional") {
      return c.cal.flags[0].t;
    }
  }
  if (c.cal?.flags && c.cal.flags.length > 1) {
    return c.cal.flags[0].t;
  }
  if (c.cal?.recommendation) {
    return c.cal.recommendation.replace(/_/g, " ");
  }
  return "Analyst review required before approval.";
}

function _priorityNextStep(c: VettingCase): string {
  const lane = workflowLaneForCase(c);
  if (portfolioDisposition(c) === "blocked") {
    if (lane === "export") {
      return "Next step: do not release the item, data, or foreign-person access request. Escalate to trade compliance now.";
    }
    if (lane === "cyber") {
      return "Next step: hold the supplier at the current boundary and escalate cyber readiness review.";
    }
    return "Next step: halt procurement and escalate to compliance.";
  }
  if (lane === "cyber") {
    return "Next step: validate SPRS posture, open POA&M items, and vulnerability pressure before expanding scope.";
  }
  if (lane === "export") {
    return "Next step: stop the request and obtain formal export-control review before any transfer or access.";
  }
  return "Next step: complete enhanced due diligence before approval.";
}

function _watchlistReason(c: VettingCase): string {
  if (c.cal?.flags && c.cal.flags.length > 0) {
    return c.cal.flags[0].t;
  }
  if (c.cal?.recommendation) {
    return c.cal.recommendation.replace(/_/g, " ");
  }
  return "Qualified approval is active.";
}

function _watchlistNextStep(c: VettingCase): string {
  const lane = workflowLaneForCase(c);
  if (c.cal?.flags && c.cal.flags.length > 0 && c.cal.flags[0].x) {
    return c.cal.flags[0].x;
  }
  if (lane === "cyber") {
    return "Next step: keep the supplier on a qualified-watch cadence and verify remediation milestones on schedule.";
  }
  if (lane === "export") {
    return "Next step: keep the authorization on controlled watch and recheck classification and country posture before any scope change.";
  }
  return "Next step: keep this vendor in the qualified-watch lane and recheck live sources on the normal cadence.";
}

function matchingCase(record: Record<string, unknown>, cases: VettingCase[]): VettingCase | null {
  const vendorId = String(record.vendor_id || "");
  if (vendorId) {
    const byId = cases.find((c) => c.id === vendorId);
    if (byId) return byId;
  }
  const entityName = String(record.entity_name || record.vendor_name || "").trim().toLowerCase();
  if (!entityName) return null;
  return cases.find((c) => c.name.trim().toLowerCase() === entityName) ?? null;
}

function monitoringCase(change: MonitorChangeEntry, cases: VettingCase[]): VettingCase | null {
  return cases.find((c) => c.id === change.vendor_id) ?? null;
}

function summarizePortfolioCases(allCases: VettingCase[], renderNow: number) {
  const total = allCases.length;
  const bandCounts = Object.fromEntries(
    TIER_BANDS.map((band) => [
      band,
      allCases.filter((x) => x.cal?.tier && tierBand(parseTier(x.cal.tier)) === band).length,
    ]),
  );
  const priorityReviews = allCases.filter((c) => portfolioDisposition(c) === "review").length;
  const watchlist = allCases.filter((c) => portfolioDisposition(c) === "qualified").length;
  const blocked = allCases.filter((c) => portfolioDisposition(c) === "blocked").length;
  const thirtyDays = 30 * 24 * 60 * 60 * 1000;
  const stale = allCases.filter((c) => renderNow - new Date(c.date).getTime() > thirtyDays).length;
  const laneCounts = Object.fromEntries(
    WORKFLOW_LANES.map((lane) => [lane, allCases.filter((c) => workflowLaneForCase(c) === lane).length]),
  );
  return { total, bandCounts, priorityReviews, watchlist, blocked, stale, laneCounts };
}

export function PortfolioScreen({
  allCases,
  cases,
  query: _query = "",
  onSelect,
  globalLane,
  onGlobalLaneChange,
  onNavigate,
  laneSummary,
}: PortfolioScreenProps) {
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [_portfolioFocus, _setPortfolioFocus] = useState<PortfolioFocus>("all");
  const laneFilter: LaneFilter = globalLane ?? "all";
  const [_showWorkflowMixDetails, _setShowWorkflowMixDetails] = useState(false);
  const [renderNow] = useState(() => Date.now());
  const [anomalies, setAnomalies] = useState<Record<string, unknown>[]>([]);
  const [monitorChanges, setMonitorChanges] = useState<MonitorChangeEntry[]>([]);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetchPortfolioAnomalies(20).then((r) => setAnomalies(r.anomalies ?? [])).catch(() => {});
    fetchMonitorChanges(20).then((r) => setMonitorChanges(r.changes ?? [])).catch(() => {});
    fetchPortfolioSnapshot().then((r) => setSnapshot(r)).catch(() => {});
  }, []);

  // Compute portfolio metrics
  const metrics = useMemo(() => summarizePortfolioCases(allCases, renderNow), [allCases, renderNow]);
  const laneScopedCases = useMemo(
    () => (laneFilter === "all" ? allCases : allCases.filter((c) => workflowLaneForCase(c) === laneFilter)),
    [allCases, laneFilter],
  );
  const scopedMetrics = useMemo(() => summarizePortfolioCases(laneScopedCases, renderNow), [laneScopedCases, renderNow]);

  const priorityCases = useMemo(() => {
    const scopedCases = laneFilter === "all"
      ? allCases
      : allCases.filter((c) => workflowLaneForCase(c) === laneFilter);
    return [...scopedCases]
      .filter((c) => {
        const disposition = portfolioDisposition(c);
        return disposition === "blocked" || disposition === "review";
      })
      .sort((a, b) => {
        const aBlocked = (a.cal?.stops?.length ?? 0) > 0 ? 1 : 0;
        const bBlocked = (b.cal?.stops?.length ?? 0) > 0 ? 1 : 0;
        if (aBlocked !== bBlocked) return bBlocked - aBlocked;
        return (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc);
      });
  }, [allCases, laneFilter]);

  const _priorityCasesByLane = useMemo(() => {
    return WORKFLOW_LANES
      .map((lane) => ({
        lane,
        cases: priorityCases.filter((c) => workflowLaneForCase(c) === lane),
      }))
      .filter((group) => group.cases.length > 0);
  }, [priorityCases]);

  const watchlistCases = useMemo(() => {
    const scopedCases = laneFilter === "all"
      ? allCases
      : allCases.filter((c) => workflowLaneForCase(c) === laneFilter);
    return [...scopedCases]
      .filter((c) => portfolioDisposition(c) === "qualified")
      .sort((a, b) => (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc));
  }, [allCases, laneFilter]);

  const laneTopCases = useMemo(() => {
    return Object.fromEntries(
      WORKFLOW_LANES.map((lane) => {
        const ranked = [...allCases]
          .filter((c) => workflowLaneForCase(c) === lane)
          .sort((a, b) => {
            const aDisposition = portfolioDisposition(a);
            const bDisposition = portfolioDisposition(b);
            const aRank = aDisposition === "blocked" ? 3 : aDisposition === "review" ? 2 : aDisposition === "qualified" ? 1 : 0;
            const bRank = bDisposition === "blocked" ? 3 : bDisposition === "review" ? 2 : bDisposition === "qualified" ? 1 : 0;
            if (aRank !== bRank) return bRank - aRank;
            return (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc);
          });
        return [lane, ranked[0] ?? null];
      }),
    ) as Record<(typeof WORKFLOW_LANES)[number], VettingCase | null>;
  }, [allCases]);

  const _watchlistCasesByLane = useMemo(() => {
    return WORKFLOW_LANES
      .map((lane) => ({
        lane,
        cases: watchlistCases.filter((c) => workflowLaneForCase(c) === lane),
      }))
      .filter((group) => group.cases.length > 0);
  }, [watchlistCases]);

  const activeLaneMeta = laneFilter === "all" ? null : WORKFLOW_LANE_META[laneFilter];
  const shellLaneMeta = laneSummary ? WORKFLOW_LANE_META[laneSummary.lane] : null;
  const displayMetrics = laneFilter === "all" ? metrics : scopedMetrics;
  const _displayAvgRisk = useMemo(() => {
    if (laneScopedCases.length === 0) return null;
    const total = laneScopedCases.reduce((sum, c) => sum + ((c.cal?.p ?? (c.sc / 100)) * 100), 0);
    return total / laneScopedCases.length;
  }, [laneScopedCases]);
  const _displayPeakRisk = useMemo(() => {
    if (laneScopedCases.length === 0) return null;
    return Math.max(...laneScopedCases.map((c) => (c.cal?.p ?? (c.sc / 100)) * 100));
  }, [laneScopedCases]);
  const _displayHardStopCount = laneFilter === "all"
    ? Number(snapshot?.hard_stop_count ?? 0)
    : displayMetrics.blocked;
  const _workflowMixExpanded = laneFilter === "all" || _showWorkflowMixDetails;
  const _portfolioExecutiveSummary = useMemo(() => {
    const subject = activeLaneMeta ? `${activeLaneMeta.label.toLowerCase()} case` : "vendor";
    if (displayMetrics.total === 0 && activeLaneMeta) {
      return `No ${activeLaneMeta.label.toLowerCase()} cases are active in this environment yet.`;
    }
    if (displayMetrics.blocked > 0) {
      const watchlistTail = displayMetrics.watchlist > 0
        ? ` ${displayMetrics.watchlist} qualified ${subject}${displayMetrics.watchlist === 1 ? " remains" : "s remain"} on the watchlist.`
        : "";
      const reviewSentence = displayMetrics.priorityReviews > 0
        ? ` ${displayMetrics.priorityReviews} additional ${subject}${displayMetrics.priorityReviews === 1 ? "" : "s"} need focused review now.`
        : "";
      return `${displayMetrics.blocked} blocked ${subject}${displayMetrics.blocked === 1 ? "" : "s"} need immediate compliance attention.${reviewSentence}${watchlistTail}`;
    }
    if (displayMetrics.priorityReviews > 0) {
      const watchlistTail = displayMetrics.watchlist > 0
        ? ` ${displayMetrics.watchlist} qualified ${subject}${displayMetrics.watchlist === 1 ? " remains" : "s remain"} on the watchlist.`
        : "";
      return `${displayMetrics.priorityReviews} ${subject}${displayMetrics.priorityReviews === 1 ? "" : "s"} need focused review now, while the rest of this queue appears stable.${watchlistTail}`;
    }
    if (displayMetrics.watchlist > 0) {
      return `${displayMetrics.watchlist} qualified ${subject}${displayMetrics.watchlist === 1 ? " remains" : "s remain"} on the watchlist, while the rest of this queue appears stable.`;
    }
    return activeLaneMeta
      ? `The ${activeLaneMeta.label.toLowerCase()} queue is currently stable with no blocked cases and no active review queue.`
      : "The portfolio is currently stable, with no blocked vendors and no active review queue.";
  }, [activeLaneMeta, displayMetrics]);
  const _shellModeViewNote = useMemo(() => {
    if (!laneSummary || !shellLaneMeta) return null;
    if (laneFilter === "all") {
      return `Shell mode remains ${shellLaneMeta.label.toLowerCase()} while this portfolio view shows all lanes.`;
    }
    if (laneFilter !== laneSummary.lane) {
      return `Shell mode remains ${shellLaneMeta.label.toLowerCase()} while this view is focused on ${WORKFLOW_LANE_META[laneFilter].label.toLowerCase()}.`;
    }
    return `This portfolio view is aligned to the current ${shellLaneMeta.label.toLowerCase()} shell mode.`;
  }, [laneFilter, laneSummary, shellLaneMeta]);

  // Sorted case list
  const sortedCases = useMemo(() => {
    const focusCases = _portfolioFocus === "watchlist"
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
  }, [cases, sortBy, _portfolioFocus, laneFilter]);

  const _activeLaneCaseCount = laneFilter === "all" ? allCases.length : allCases.filter((c) => workflowLaneForCase(c) === laneFilter).length;
  const _activeLaneWatchCount = laneFilter === "all" ? watchlistCases.length : watchlistCases.filter((c) => workflowLaneForCase(c) === laneFilter).length;
  const _activeLaneTopCase = laneFilter === "all" ? null : laneTopCases[laneFilter];
  const anomalyGroups = useMemo(() => {
    return WORKFLOW_LANES
      .map((lane) => ({
        lane,
        items: anomalies.filter((item) => {
          const linkedCase = matchingCase(item, allCases);
          return linkedCase ? workflowLaneForCase(linkedCase) === lane : lane === "counterparty";
        }),
      }))
      .filter((group) => (laneFilter === "all" || laneFilter === group.lane) && group.items.length > 0);
  }, [anomalies, allCases, laneFilter]);
  const _displayAnomalyCount = anomalyGroups.reduce((sum, group) => sum + group.items.length, 0);
  const _changeGroups = useMemo(() => {
    return WORKFLOW_LANES
      .map((lane) => ({
        lane,
        items: monitorChanges.filter((item) => {
          const linkedCase = monitoringCase(item, allCases);
          return linkedCase ? workflowLaneForCase(linkedCase) === lane : lane === "counterparty";
        }),
      }))
      .filter((group) => (laneFilter === "all" || laneFilter === group.lane) && group.items.length > 0);
  }, [monitorChanges, allCases, laneFilter]);

  const _openLaneInHelios = (lane: WorkflowLane) => {
    onGlobalLaneChange?.(lane);
    onNavigate?.("helios");
  };

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col p-6">
      {/* Single-line Status Bar */}
      {activeLaneMeta && (
        <div className="mb-6 py-2 text-xs text-slate-500">
          {activeLaneMeta.label} · {cases?.length || 0} active · {cases?.filter((c) => portfolioDisposition(c) === "blocked").length || 0} blocked
        </div>
      )}

      {/* KPI Cards Row */}
      <div className="mb-8 grid grid-cols-5 gap-4">
        {/* Cases in Scope */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <p className="text-xs font-medium text-slate-500 mb-2">Cases in Scope</p>
          <p className="text-2xl font-bold text-slate-100" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.length || 0}
          </p>
        </div>

        {/* Blocked */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <p className="text-xs font-medium text-slate-500 mb-2">Blocked</p>
          <p className="text-2xl font-bold text-red-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.filter((c) => portfolioDisposition(c) === "blocked").length || 0}
          </p>
        </div>

        {/* Review Queue */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <p className="text-xs font-medium text-slate-500 mb-2">Review Queue</p>
          <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.filter((c) => portfolioDisposition(c) === "review").length || 0}
          </p>
        </div>

        {/* Watchlist */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <p className="text-xs font-medium text-slate-500 mb-2">Watchlist</p>
          <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {cases?.filter((c) => {
              const lane = workflowLaneForCase(c);
              return lane !== "export" && lane !== "cyber";
            }).length || 0}
          </p>
        </div>

        {/* Avg Risk */}
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-4">
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
