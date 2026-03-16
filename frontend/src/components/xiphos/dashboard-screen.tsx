import { useState } from "react";
import { T, TIER_META, type TierKey } from "@/lib/tokens";
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

  const hs = cases.filter((x) => x.cal?.tier === "hard_stop").length;
  const el = cases.filter((x) => x.cal?.tier === "elevated").length;
  const mo = cases.filter((x) => x.cal?.tier === "monitor").length;
  const cl = cases.filter((x) => x.cal?.tier === "clear").length;
  const pe = cases.filter((x) => !x.cal).length;

  const allTierRows: { tier: TierKey | "pending"; label: string; count: number; color: string }[] = [
    { tier: "hard_stop" as const, label: "HARD STOP", count: hs, color: TIER_META.hard_stop.color },
    { tier: "elevated" as const, label: "ELEVATED", count: el, color: TIER_META.elevated.color },
    { tier: "monitor" as const, label: "MONITOR", count: mo, color: TIER_META.monitor.color },
    { tier: "clear" as const, label: "CLEAR", count: cl, color: TIER_META.clear.color },
    { tier: "pending" as const, label: "PENDING", count: pe, color: T.muted },
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
        <StatCard label="Hard Stops" value={hs} color={hs ? T.red : T.muted} />
        <StatCard label="Elevated" value={el} color={el ? T.amber : T.muted} />
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
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
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
                <div className="font-semibold mb-1" style={{ fontSize: 14, color: T.text }}>
                  No vendors yet
                </div>
                <div style={{ fontSize: 12, color: T.muted, textAlign: "center", maxWidth: 320 }}>
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
          {/* Tier summary table */}
          <div className="rounded-lg p-3 shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
              Tier Distribution
            </div>
            {tierRows.map((r, i) => (
              <div
                key={r.tier}
                className="flex items-center justify-between"
                style={{ padding: "5px 0", borderBottom: i < tierRows.length - 1 ? `1px solid ${T.border}` : "none" }}
              >
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ background: r.color }} />
                  <span className="font-mono" style={{ fontSize: 11, color: T.dim }}>{r.label}</span>
                </div>
                <span className="font-mono font-bold" style={{ fontSize: 13, color: r.color }}>
                  {r.count}
                </span>
              </div>
            ))}
            <div
              className="flex items-center justify-between mt-1 pt-1"
              style={{ borderTop: `1px solid ${T.border}` }}
            >
              <span className="font-mono" style={{ fontSize: 11, color: T.muted }}>Total</span>
              <span className="font-mono font-bold" style={{ fontSize: 13, color: T.text }}>
                {cases.length}
              </span>
            </div>
          </div>

          {/* Portfolio Analytics */}
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <PortfolioAnalytics cases={cases} />
          </div>

          {/* Alerts */}
          <div className="rounded-lg p-3 flex-1" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
              Alerts
            </div>
            {alerts.length === 0 && (
              <div style={{ fontSize: 11, color: T.muted, padding: "8px 0" }}>No active alerts</div>
            )}
            {alerts.map((a, i) => (
              <div
                key={a.id}
                className="pb-2 mb-2"
                style={{ borderBottom: i < alerts.length - 1 ? `1px solid ${T.border}` : "none" }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold truncate mr-1" style={{ fontSize: 11, color: T.text }}>
                    {a.entity}
                  </span>
                  <SeverityBadge sev={a.sev} />
                </div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>{a.title}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
