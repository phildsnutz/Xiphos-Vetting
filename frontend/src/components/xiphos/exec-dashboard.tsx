import { useMemo } from "react";
import { T, FS, tierBand, TIER_BANDS, BAND_META, tierColor, parseTier } from "@/lib/tokens";
import {
  Shield, TrendingUp, AlertTriangle,
  CheckCircle, XOctagon, Clock, Users, BarChart3,
} from "lucide-react";
import type { VettingCase, Alert } from "@/lib/types";

/* ---- Props ---- */
interface ExecDashboardProps {
  cases: VettingCase[];
  alerts: Alert[];
  onSelectCase: (c: VettingCase) => void;
}

export function ExecDashboard({ cases, alerts, onSelectCase }: ExecDashboardProps) {
  // Compute portfolio metrics
  const metrics = useMemo(() => {
    const total = cases.length;
    const byBand: Record<string, VettingCase[]> = Object.fromEntries(TIER_BANDS.map(b => [b, []]));
    for (const c of cases) {
      const tierKey = c.cal?.tier ? parseTier(c.cal.tier) : "TIER_4_CLEAR";
      const band = tierBand(tierKey);
      (byBand[band] ??= []).push(c);
    }

    const avgRisk = total > 0
      ? cases.reduce((s, c) => s + (c.cal?.p ?? 0), 0) / total
      : 0;

    // Stale vendors: last scored > 30 days ago
    const now = Date.now();
    const thirtyDays = 30 * 24 * 60 * 60 * 1000;
    const stale = cases.filter((c) => {
      const dt = new Date(c.date).getTime();
      return now - dt > thirtyDays;
    });

    // Critical alerts
    const critAlerts = alerts.filter((a) => a.sev === "critical");
    const highAlerts = alerts.filter((a) => a.sev === "high");

    // Top risk entities
    const topRisk = [...cases]
      .sort((a, b) => (b.cal?.p ?? 0) - (a.cal?.p ?? 0))
      .slice(0, 5);

    // Recent additions (last 7 days)
    const sevenDays = 7 * 24 * 60 * 60 * 1000;
    const recent = cases.filter((c) => now - new Date(c.date).getTime() < sevenDays);

    return { total, byBand, avgRisk, stale, critAlerts, highAlerts, topRisk, recent };
  }, [cases, alerts]);

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} color={T.accent} />
          <span className="font-bold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.text, letterSpacing: "0.1em" }}>
            Executive Risk Overview
          </span>
        </div>
        <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
          {new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        </span>
      </div>

      {/* KPI cards row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <KPICard
          label="Portfolio Size"
          value={String(metrics.total)}
          sub={`${metrics.recent.length} added this week`}
          icon={<Users size={14} color={T.accent} />}
        />
        <KPICard
          label="Avg Risk Score"
          value={`${Math.round(metrics.avgRisk * 100)}%`}
          sub={metrics.avgRisk > 0.25 ? "Above threshold" : "Within tolerance"}
          icon={<TrendingUp size={14} color={metrics.avgRisk > 0.25 ? "#f97316" : T.green} />}
          valueColor={metrics.avgRisk > 0.25 ? "#f97316" : T.green}
        />
        <KPICard
          label="Active Alerts"
          value={String(metrics.critAlerts.length + metrics.highAlerts.length)}
          sub={`${metrics.critAlerts.length} critical, ${metrics.highAlerts.length} high`}
          icon={<AlertTriangle size={14} color={metrics.critAlerts.length > 0 ? T.red : T.amber} />}
          valueColor={metrics.critAlerts.length > 0 ? T.red : T.amber}
        />
        <KPICard
          label="Stale Reviews"
          value={String(metrics.stale.length)}
          sub={metrics.stale.length > 0 ? "Overdue for refresh" : "All current"}
          icon={<Clock size={14} color={metrics.stale.length > 0 ? T.amber : T.green} />}
          valueColor={metrics.stale.length > 0 ? T.amber : T.green}
        />
      </div>

      {/* Tier distribution + Top risk entities */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* Tier distribution */}
        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-center gap-1.5 mb-3">
            <Shield size={12} color={T.muted} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
              Tier Distribution
            </span>
          </div>

          {/* Visual bar */}
          {metrics.total > 0 && (
            <div className="flex rounded-full overflow-hidden mb-3" style={{ height: 12 }}>
              {TIER_BANDS.map((band) => {
                const count = metrics.byBand[band]?.length ?? 0;
                const pct = (count / metrics.total) * 100;
                if (pct === 0) return null;
                return (
                  <div
                    key={band}
                    style={{ width: `${pct}%`, background: BAND_META[band].color, minWidth: pct > 0 ? 4 : 0 }}
                    title={`${BAND_META[band].label}: ${count} (${Math.round(pct)}%)`}
                  />
                );
              })}
            </div>
          )}

          {/* Band rows */}
          {TIER_BANDS.map((band) => {
            const count = metrics.byBand[band]?.length ?? 0;
            const pct = metrics.total > 0 ? Math.round((count / metrics.total) * 100) : 0;
            return (
              <div
                key={band}
                className="flex items-center justify-between py-1.5"
                style={{ borderBottom: `1px solid ${T.border}22` }}
              >
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: BAND_META[band].color }} />
                  <span style={{ fontSize: FS.sm, color: T.dim }}>{BAND_META[band].label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold" style={{ fontSize: FS.sm, color: T.text }}>
                    {count}
                  </span>
                  <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted, width: 36, textAlign: "right" }}>
                    {pct}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Top risk entities */}
        <div className="lg:col-span-2 rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-center gap-1.5 mb-3">
            <TrendingUp size={12} color={T.red} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
              Highest Risk Entities
            </span>
          </div>

          {metrics.topRisk.length === 0 && (
            <div className="text-center py-6" style={{ fontSize: FS.sm, color: T.muted }}>
              No vendor cases in portfolio yet.
            </div>
          )}

          {metrics.topRisk.map((c, i) => {
            const tierKey = c.cal?.tier ? parseTier(c.cal.tier) : "TIER_4_CLEAR";
            const prob = c.cal?.p ?? 0;
            const color = tierColor(tierKey);
            const stops = c.cal?.stops?.length ?? 0;
            const flags = c.cal?.flags?.length ?? 0;

            return (
              <button
                key={c.id}
                onClick={() => onSelectCase(c)}
                className="w-full flex items-center gap-3 rounded-lg mb-1.5 border-none cursor-pointer text-left"
                style={{
                  padding: "10px 12px",
                  background: i === 0 ? color + "08" : "transparent",
                  border: `1px solid ${i === 0 ? color + "22" : "transparent"}`,
                }}
              >
                <span className="font-mono font-bold" style={{ fontSize: FS.xs, color: T.muted, width: 16 }}>
                  #{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-semibold" style={{ fontSize: FS.sm, color: T.text }}>
                      {c.name}
                    </span>
                    {c.cc && (
                      <span className="font-mono shrink-0" style={{ fontSize: FS.xs, color: T.muted }}>
                        {c.cc}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {stops > 0 && (
                      <span className="font-mono" style={{ fontSize: "9px", color: T.red }}>
                        {stops} STOP
                      </span>
                    )}
                    {flags > 0 && (
                      <span className="font-mono" style={{ fontSize: "9px", color: T.amber }}>
                        {flags} flags
                      </span>
                    )}
                  </div>
                </div>

                {/* Risk bar */}
                <div className="flex items-center gap-2 shrink-0">
                  <div className="rounded-full overflow-hidden" style={{ width: 60, height: 6, background: T.raised }}>
                    <div className="h-full rounded-full" style={{ width: `${prob * 100}%`, background: color }} />
                  </div>
                  <span className="font-mono font-bold" style={{ fontSize: FS.sm, color, width: 36, textAlign: "right" }}>
                    {Math.round(prob * 100)}%
                  </span>
                </div>

                {/* Tier badge */}
                <span
                  className="font-mono font-bold rounded-sm px-1.5 py-0.5 shrink-0"
                  style={{ fontSize: "9px", color, background: color + "15", border: `1px solid ${color}22` }}
                >
                  {tierKey}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Action queue: Stale + Critical alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Stale vendor alerts */}
        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-center gap-1.5 mb-3">
            <Clock size={12} color={T.amber} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
              Overdue for Re-evaluation ({metrics.stale.length})
            </span>
          </div>

          {metrics.stale.length === 0 && (
            <div className="flex items-center gap-2 py-4 justify-center">
              <CheckCircle size={14} color={T.green} />
              <span style={{ fontSize: FS.sm, color: T.green }}>All vendors reviewed within 30 days</span>
            </div>
          )}

          {metrics.stale.slice(0, 5).map((c) => {
            const daysOld = Math.round((Date.now() - new Date(c.date).getTime()) / (24 * 60 * 60 * 1000));
            return (
              <button
                key={c.id}
                onClick={() => onSelectCase(c)}
                className="w-full flex items-center justify-between rounded py-2 border-none cursor-pointer text-left bg-transparent"
                style={{ borderBottom: `1px solid ${T.border}22` }}
              >
                <span className="truncate" style={{ fontSize: FS.sm, color: T.dim }}>{c.name}</span>
                <span className="font-mono shrink-0" style={{ fontSize: FS.xs, color: T.amber }}>
                  {daysOld}d ago
                </span>
              </button>
            );
          })}
        </div>

        {/* Critical alerts queue */}
        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-center gap-1.5 mb-3">
            <AlertTriangle size={12} color={T.red} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
              Priority Alerts ({metrics.critAlerts.length + metrics.highAlerts.length})
            </span>
          </div>

          {metrics.critAlerts.length + metrics.highAlerts.length === 0 && (
            <div className="flex items-center gap-2 py-4 justify-center">
              <CheckCircle size={14} color={T.green} />
              <span style={{ fontSize: FS.sm, color: T.green }}>No outstanding critical/high alerts</span>
            </div>
          )}

          {[...metrics.critAlerts, ...metrics.highAlerts].slice(0, 8).map((a) => {
            const color = a.sev === "critical" ? T.red : "#f97316";
            return (
              <div
                key={a.id}
                className="flex items-start gap-2 py-2"
                style={{ borderBottom: `1px solid ${T.border}22` }}
              >
                {a.sev === "critical" ? (
                  <XOctagon size={10} color={color} className="shrink-0 mt-0.5" />
                ) : (
                  <AlertTriangle size={10} color={color} className="shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <div className="truncate" style={{ fontSize: FS.sm, color: T.dim }}>{a.title}</div>
                  <div style={{ fontSize: "9px", color: T.muted }}>{a.entity}</div>
                </div>
                <span
                  className="font-mono shrink-0 rounded-sm px-1 py-0.5"
                  style={{ fontSize: "8px", color, background: color + "15" }}
                >
                  {a.sev.toUpperCase()}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ---- KPI Card ---- */
function KPICard({
  label, value, sub, icon, valueColor,
}: {
  label: string; value: string; sub: string; icon: React.ReactNode; valueColor?: string;
}) {
  return (
    <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 14 }}>
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: "9px", color: T.muted }}>
          {label}
        </span>
      </div>
      <div className="font-mono font-bold" style={{ fontSize: 24, color: valueColor || T.text }}>
        {value}
      </div>
      <div style={{ fontSize: FS.xs, color: T.muted, marginTop: 2 }}>{sub}</div>
    </div>
  );
}
