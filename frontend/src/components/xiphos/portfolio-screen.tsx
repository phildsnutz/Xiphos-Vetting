import { useState, useMemo } from "react";
import { T, FS, tierBand, TIER_BANDS, BAND_META, parseTier } from "@/lib/tokens";
import { AlertTriangle, AlertCircle } from "lucide-react";
import { CaseRow } from "./case-row";
import type { VettingCase } from "@/lib/types";

interface PortfolioScreenProps {
  cases: VettingCase[];
  onSelect: (c: VettingCase) => void;
}

type SortBy = "score" | "name" | "date";

export function PortfolioScreen({ cases, onSelect }: PortfolioScreenProps) {
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [renderNow] = useState(() => Date.now());

  // Compute portfolio metrics
  const metrics = useMemo(() => {
    const total = cases.length;
    
    // Count by tier
    const bandCounts = Object.fromEntries(
      TIER_BANDS.map((band) => [
        band,
        cases.filter((x) => x.cal?.tier && tierBand(parseTier(x.cal.tier)) === band).length,
      ])
    );
    
    // Priority reviews: TIER_1 or TIER_2 (review/elevated/critical)
    const priorityReviews = cases.filter((c) => {
      if (!c.cal?.tier) return false;
      const band = tierBand(parseTier(c.cal.tier));
      return band === "critical" || band === "elevated";
    }).length;
    
    // Blocked: hard stops
    const blocked = cases.filter((c) => c.cal?.stops && c.cal.stops.length > 0).length;
    
    // Stale: > 30 days old
    const thirtyDays = 30 * 24 * 60 * 60 * 1000;
    const stale = cases.filter((c) => renderNow - new Date(c.date).getTime() > thirtyDays).length;
    
    return { total, bandCounts, priorityReviews, blocked, stale };
  }, [cases, renderNow]);

  // Priority queue: cases with hard stops or high risk, sorted by risk
  const priorityCases = useMemo(() => {
    return [...cases]
      .filter((c) => {
        const hasStops = (c.cal?.stops?.length ?? 0) > 0;
        if (hasStops) return true;
        if (!c.cal?.tier) return false;
        const band = tierBand(parseTier(c.cal.tier));
        return band === "critical" || band === "elevated";
      })
      .sort((a, b) => {
        const aBlocked = (a.cal?.stops?.length ?? 0) > 0 ? 1 : 0;
        const bBlocked = (b.cal?.stops?.length ?? 0) > 0 ? 1 : 0;
        if (aBlocked !== bBlocked) return bBlocked - aBlocked;
        return (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc);
      })
      .slice(0, 5);
  }, [cases]);

  // Sorted case list
  const sortedCases = useMemo(() => {
    const sorted = [...cases];
    if (sortBy === "score") {
      sorted.sort((a, b) => (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc));
    } else if (sortBy === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "date") {
      sorted.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    }
    return sorted;
  }, [cases, sortBy]);

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Status strip */}
      <div className="rounded-lg p-3 shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1">
              <span style={{ fontSize: FS.sm, color: T.muted }}>Vendors</span>
              <span className="font-bold" style={{ fontSize: FS.lg, color: T.text }}>{metrics.total}</span>
            </div>
            <div className="w-px h-5" style={{ background: T.border }} />
            <div className="flex items-center gap-1">
              <span style={{ fontSize: FS.sm, color: T.muted }}>Needs review</span>
              <span className="font-bold" style={{ fontSize: FS.lg, color: T.amber }}>{metrics.priorityReviews}</span>
            </div>
            <div className="flex items-center gap-1">
              <span style={{ fontSize: FS.sm, color: T.muted }}>Blocked</span>
              <span className="font-bold" style={{ fontSize: FS.lg, color: T.red }}>{metrics.blocked}</span>
            </div>
            <div className="flex items-center gap-1">
              <span style={{ fontSize: FS.sm, color: T.muted }}>Stale Reviews</span>
              <span className="font-bold" style={{ fontSize: FS.lg, color: T.dim }}>{metrics.stale}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Priority Queue */}
      {priorityCases.length > 0 && (
        <div className="rounded-lg p-3 shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle size={14} color={T.red} />
            <span className="font-semibold" style={{ fontSize: FS.sm, color: T.text }}>
              Priority Queue
            </span>
          </div>
          <div className="space-y-2">
            {priorityCases.map((c) => (
              (() => {
                const hasStops = (c.cal?.stops?.length ?? 0) > 0;
                const band = c.cal?.tier ? tierBand(parseTier(c.cal.tier)) : "clear";
                return (
              <div
                key={c.id}
                className="rounded-lg p-3 cursor-pointer transition-colors"
                style={{ background: T.raised, border: `1px solid ${T.border}` }}
                onClick={() => onSelect(c)}
                onMouseEnter={(e) => (e.currentTarget.style.background = T.hover)}
                onMouseLeave={(e) => (e.currentTarget.style.background = T.raised)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="font-semibold truncate" style={{ fontSize: FS.base, color: T.text }}>
                      {c.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {hasStops && (
                      <div
                        className="rounded px-2 py-1 text-center"
                        style={{
                          fontSize: FS.sm,
                          background: T.dRedBg,
                          color: T.dRed,
                          fontWeight: 600,
                        }}
                      >
                        Blocked
                      </div>
                    )}
                    {!hasStops && (band === "critical" || band === "elevated") && (
                      <div
                        className="rounded px-2 py-1 text-center"
                        style={{
                          fontSize: FS.sm,
                          background: T.amberBg,
                          color: T.amber,
                          fontWeight: 600,
                        }}
                      >
                        Review
                      </div>
                    )}
                  </div>
                </div>
                {hasStops && c.cal?.stops && c.cal.stops[0] && (
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                    {c.cal.stops[0].t}
                  </div>
                )}
                {!hasStops && (band === "critical" || band === "elevated") && (
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                    Elevated risk profile requires analyst review.
                  </div>
                )}
              </div>
                );
              })()
            ))}
          </div>
        </div>
      )}

      {/* Tier distribution bar */}
      <div className="rounded-lg p-3 shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <span className="font-semibold" style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 8 }}>
          Portfolio Posture
        </span>
        <div className="flex items-center gap-2 h-8 rounded overflow-hidden" style={{ background: T.raised }}>
          {TIER_BANDS.map((band) => {
            const count = metrics.bandCounts[band] || 0;
            const pct = cases.length > 0 ? (count / cases.length) * 100 : 0;
            return (
              <div
                key={band}
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: BAND_META[band].color,
                  minWidth: pct > 0 ? 4 : 0,
                }}
                title={`${BAND_META[band].label}: ${count}`}
              />
            );
          })}
        </div>
        <div className="flex items-center justify-between gap-2 mt-2 flex-wrap">
          {TIER_BANDS.map((band) => {
            const count = metrics.bandCounts[band] || 0;
            return count > 0 ? (
              <div key={band} className="flex items-center gap-1.5">
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ background: BAND_META[band].color }}
                />
                <span style={{ fontSize: FS.sm, color: T.dim }}>
                  {BAND_META[band].label}
                </span>
                <span className="font-bold" style={{ fontSize: FS.sm, color: BAND_META[band].color }}>
                  {count}
                </span>
              </div>
            ) : null;
          })}
        </div>
      </div>

      {/* All vendors list */}
      <div className="flex-1 min-h-0 flex flex-col rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center justify-between mb-3 shrink-0">
          <span className="font-semibold" style={{ fontSize: FS.sm, color: T.muted }}>
            All Vendors
          </span>
          <div className="flex gap-1">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortBy)}
              style={{
                fontSize: FS.sm,
                padding: "4px 8px",
                background: T.raised,
                border: `1px solid ${T.border}`,
                color: T.text,
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              <option value="score">Sort by Score</option>
              <option value="name">Sort by Name</option>
              <option value="date">Sort by Date</option>
            </select>
          </div>
        </div>

        <div className="flex-1 overflow-auto pr-1">
          {cases.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full" style={{ minHeight: 300 }}>
              <AlertCircle size={24} color={T.accent} className="mb-3" />
              <div className="font-semibold mb-1" style={{ fontSize: FS.md, color: T.text }}>
                No vendors yet
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted, textAlign: "center", maxWidth: 320 }}>
                Navigate to Helios to add your first vendor.
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {sortedCases.map((c) => (
                <CaseRow key={c.id} c={c} onClick={() => onSelect(c)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
