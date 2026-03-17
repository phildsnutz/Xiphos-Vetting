import { useState } from "react";
import { T, FS, TIER_META, type TierKey, tierBand, TIER_BANDS, BAND_META, parseTier } from "@/lib/tokens";
import { BarChart3, List } from "lucide-react";
import { StatCard } from "./stat-card";
import { CaseRow } from "./case-row";
import { SeverityBadge } from "./badges";
import { RiskMatrix } from "./risk-matrix";
import { PortfolioAnalytics } from "./portfolio-view";
import type { VettingCase, Alert } from "@/lib/types";

interface DashboardScreenProps {
  cases: VettingCase[];
  alerts: Alert[];
  onSelect: (c: VettingCase) => void;
}

export function DashboardScreen({ cases, alerts, onSelect }: DashboardScreenProps) {
  const [view, setView] = useState<"list" | "matrix">("list");

  const bandCounts = Object.fromEntries(
    TIER_BANDS.map((band) => [
      band,
      cases.filter((x) => x.cal?.tier && tierBand(parseTier(x.cal.tier)) === band).length,
    ])
  );
  const pe = cases.filter((x) => !x.cal).length;

  const allTierRows: { band: typeof TIER_BANDS[number] | "pending"; label: string; count: number; color: string }[] = [
    ...TIER_BANDS.map((band) => ({
      band,
      label: BAND_META[band].label,
      count: bandCounts[band],
      color: BAND_META[band].color,
    })),
    { band: "pending" as const, label: "PENDING", count: pe, color: T.muted },
  ];
  const tierRows = allTierRows.filter((r) => r.count > 0);

  // Portfolio risk score (weighted avg posterior)
  const scored = cases.filter((c) => c.cal);
  const portfolioRisk = scored.length > 0
    ? scored.reduce((s, c) => s + (c.cal?.p ?? 0), 0) / scored.length
    : 0;

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2 shrink-0">
        <StatCard label="Vendors" value={cases.length} color={T.text} />
        <StatCard label="Critical" value={bandCounts.critical} color={bandCounts.critical ? T.red : T.muted} emphasis={bandCounts.critical > 0} />
        <StatCard label="Elevated" value={bandCounts.elevated} color={bandCounts.elevated ? T.amber : T.muted} />
        <StatCard label="Alerts" value={alerts.length} color={alerts.length ? T.amber : T.muted} />
        <StatCard
          label="Portfolio Risk"
          value={Math.round(portfolioRisk * 100)}
          color={portfolioRisk > 0.35 ? T.red : portfolioRisk > 0.18 ? T.amber : T.green}
          suffix="%"
        />
      </div>

      {/* Main content: two-column on wide screens */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-3">
        {/* Left: case list or matrix */}
        <div className="flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-2 shrink-0">
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
              Assessments
            </span>
            {/* View toggle */}
            <div className="flex gap-1">
              <button
                onClick={() => setView("list")}
                className="rounded p-1.5 border-none cursor-pointer"
                style={{
                  background: view === "list" ? T.accent + "22" : "transparent",
                  color: view === "list" ? T.accent : T.muted,
                }}
                title="List view"
              >
                <List size={14} />
              </button>
              <button
                onClick={() => setView("matrix")}
                className="rounded p-1.5 border-none cursor-pointer"
                style={{
                  background: view === "matrix" ? T.accent + "22" : "transparent",
                  color: view === "matrix" ? T.accent : T.muted,
                }}
                title="Risk matrix"
              >
                <BarChart3 size={14} />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-auto pr-1">
            {cases.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full" style={{ minHeight: 300 }}>
                <div className="rounded-full flex items-center justify-center mb-3"
                  style={{ width: 56, height: 56, background: T.accent + "15" }}>
                  <BarChart3 size={24} color={T.accent} />
                </div>
                <div className="font-semibold mb-1" style={{ fontSize: FS.md, color: T.text }}>
                  No vendors yet
                </div>
                <div style={{ fontSize: FS.sm, color: T.muted, textAlign: "center", maxWidth: 320 }}>
                  Use the Screen Vendor tab to add your first vendor. The scoring engine will analyze risk factors and assign a tier automatically.
                </div>
              </div>
            ) : view === "list" ? (
              <div className="space-y-2">
                {cases.map((c) => (
                  <CaseRow key={c.id} c={c} onClick={() => onSelect(c)} />
                ))}
              </div>
            ) : (
              <RiskMatrix cases={cases} onSelect={onSelect} />
            )}
          </div>
        </div>

        {/* Right: sidebar */}
        <div className="flex flex-col gap-2 min-h-0 overflow-auto">
          {/* Tier distribution with donut */}
          <div className="rounded-lg p-3 shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.xs, color: T.muted }}>
              Tier Distribution
            </div>
            {cases.length > 0 ? (
              <div className="flex items-center gap-4">
                {/* SVG Donut */}
                <svg width={80} height={80} viewBox="0 0 36 36" className="shrink-0">
                  {(() => {
                    const total = cases.length || 1;
                    let offset = 0;
                    return tierRows.map((r) => {
                      const pct = (r.count / total) * 100;
                      const segment = (
                        <circle
                          key={r.band}
                          cx="18" cy="18" r="14"
                          fill="none"
                          stroke={r.color}
                          strokeWidth="5"
                          strokeDasharray={`${pct * 0.88} ${88 - pct * 0.88}`}
                          strokeDashoffset={-offset * 0.88}
                          transform="rotate(-90 18 18)"
                        />
                      );
                      offset += pct;
                      return segment;
                    });
                  })()}
                  <text x="18" y="19" textAnchor="middle" dominantBaseline="middle" fill={T.text} fontSize="8" fontWeight="bold">
                    {cases.length}
                  </text>
                </svg>
                {/* Legend */}
                <div className="flex-1">
                  {tierRows.map((r) => (
                    <div key={r.band} className="flex items-center justify-between" style={{ padding: "3px 0" }}>
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: r.color }} />
                        <span style={{ fontSize: FS.sm, color: T.dim }}>{r.label}</span>
                      </div>
                      <span className="font-bold" style={{ fontSize: FS.base, color: r.color }}>
                        {r.count}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ fontSize: FS.xs, color: T.muted, padding: "12px 0" }}>No data</div>
            )}
          </div>

          {/* Portfolio Analytics */}
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <PortfolioAnalytics cases={cases} />
          </div>

          {/* Alerts */}
          <div className="rounded-lg p-3 flex-1" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.xs, color: T.muted }}>
              Alerts
            </div>
            {alerts.length === 0 && (
              <div style={{ fontSize: FS.sm, color: T.muted, padding: "8px 0" }}>No active alerts</div>
            )}
            {alerts.map((a, i) => (
              <div
                key={a.id}
                className="pb-2 mb-2"
                style={{ borderBottom: i < alerts.length - 1 ? `1px solid ${T.border}` : "none" }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold truncate mr-1" style={{ fontSize: FS.sm, color: T.text }}>
                    {a.entity}
                  </span>
                  <SeverityBadge sev={a.sev} />
                </div>
                <div style={{ fontSize: FS.xs, color: T.muted, marginTop: 2 }}>{a.title}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
