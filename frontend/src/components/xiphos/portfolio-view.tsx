/**
 * Portfolio Risk Analytics
 *
 * Three views packed into the dashboard sidebar:
 * 1. Geographic risk heatmap (country bubbles)
 * 2. Factor exposure summary (aggregate across portfolio)
 * 3. Confidence distribution (how sure are we across the board?)
 */

import { T, TIER_META, type TierKey } from "@/lib/tokens";
import type { VettingCase } from "@/lib/types";

interface PortfolioProps {
  cases: VettingCase[];
}

/* ---- Geographic concentration ---- */

function GeoConcentration({ cases }: PortfolioProps) {
  const byCountry: Record<string, { count: number; maxP: number; tier: TierKey }> = {};
  for (const c of cases) {
    if (!c.cal) continue;
    const prev = byCountry[c.cc];
    if (!prev || c.cal.p > prev.maxP) {
      byCountry[c.cc] = {
        count: (prev?.count ?? 0) + 1,
        maxP: c.cal.p,
        tier: c.cal.tier,
      };
    } else {
      prev.count++;
    }
  }

  const entries = Object.entries(byCountry).sort((a, b) => b[1].maxP - a[1].maxP);

  return (
    <div>
      <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
        Geographic Exposure
      </div>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([cc, data]) => (
          <div
            key={cc}
            className="flex items-center gap-1.5 rounded"
            style={{
              padding: "4px 8px",
              background: TIER_META[data.tier]?.bg ?? T.surface,
              border: `1px solid ${TIER_META[data.tier]?.color ?? T.border}33`,
            }}
          >
            <span className="font-mono font-bold" style={{ fontSize: 11, color: TIER_META[data.tier]?.color ?? T.dim }}>
              {cc}
            </span>
            <span className="font-mono" style={{ fontSize: 9, color: T.muted }}>
              {data.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- Aggregate Factor Exposure ---- */

const FACTORS = ["Sanctions", "Geography", "Ownership", "Data Quality", "Executive"];

function FactorExposure({ cases }: PortfolioProps) {
  const scored = cases.filter((c) => c.cal);
  if (scored.length === 0) return null;

  // Average raw score per factor across portfolio
  const avgByFactor: Record<string, number> = {};
  for (const f of FACTORS) {
    const vals = scored.map((c) => {
      const ct = c.cal!.ct.find((x) => x.n === f);
      return ct?.raw ?? 0;
    });
    avgByFactor[f] = vals.reduce((s, v) => s + v, 0) / vals.length;
  }

  const sorted = FACTORS.map((f) => ({ name: f, avg: avgByFactor[f] })).sort((a, b) => b.avg - a.avg);

  return (
    <div>
      <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
        Portfolio Factor Exposure
      </div>
      {sorted.map((f) => {
        const pct = Math.round(f.avg * 100);
        const color = f.avg < 0.15 ? T.green : f.avg < 0.35 ? T.amber : f.avg < 0.60 ? T.orange : T.red;
        return (
          <div key={f.name} className="mb-2">
            <div className="flex items-center justify-between mb-0.5">
              <span style={{ fontSize: 10, color: T.dim }}>{f.name}</span>
              <span className="font-mono font-semibold" style={{ fontSize: 10, color }}>{pct}</span>
            </div>
            <div className="w-full rounded-full overflow-hidden" style={{ height: 4, background: T.border }}>
              <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---- Confidence Distribution ---- */

function ConfidenceDistribution({ cases }: PortfolioProps) {
  const scored = cases.filter((c) => c.cal);
  if (scored.length === 0) return null;

  // Bucket CIs by width
  const buckets = { tight: 0, moderate: 0, wide: 0 };
  for (const c of scored) {
    const width = (c.cal!.hi - c.cal!.lo) * 100;
    if (width < 15) buckets.tight++;
    else if (width < 30) buckets.moderate++;
    else buckets.wide++;
  }

  const total = scored.length;
  const avgCov = scored.reduce((s, c) => s + c.cal!.cov, 0) / total;

  return (
    <div>
      <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
        Confidence Quality
      </div>
      <div className="flex items-center gap-2 mb-2">
        <span className="font-mono font-bold" style={{ fontSize: 18, color: avgCov > 0.75 ? T.green : avgCov > 0.60 ? T.amber : T.red }}>
          {Math.round(avgCov * 100)}%
        </span>
        <span style={{ fontSize: 10, color: T.muted }}>mean coverage</span>
      </div>
      <div className="flex gap-1" style={{ height: 20 }}>
        {buckets.tight > 0 && (
          <div
            className="rounded flex items-center justify-center font-mono"
            style={{
              flex: buckets.tight,
              background: T.greenBg,
              border: `1px solid ${T.green}33`,
              fontSize: 9, color: T.green,
            }}
            title={`${buckets.tight} tight CI (&lt;15pp)`}
          >
            {buckets.tight}
          </div>
        )}
        {buckets.moderate > 0 && (
          <div
            className="rounded flex items-center justify-center font-mono"
            style={{
              flex: buckets.moderate,
              background: T.amberBg,
              border: `1px solid ${T.amber}33`,
              fontSize: 9, color: T.amber,
            }}
            title={`${buckets.moderate} moderate CI (15-30pp)`}
          >
            {buckets.moderate}
          </div>
        )}
        {buckets.wide > 0 && (
          <div
            className="rounded flex items-center justify-center font-mono"
            style={{
              flex: buckets.wide,
              background: T.redBg,
              border: `1px solid ${T.red}33`,
              fontSize: 9, color: T.red,
            }}
            title={`${buckets.wide} wide CI (&gt;30pp)`}
          >
            {buckets.wide}
          </div>
        )}
      </div>
      <div className="flex justify-between mt-1">
        <span style={{ fontSize: 8, color: T.muted }}>Tight</span>
        <span style={{ fontSize: 8, color: T.muted }}>Wide</span>
      </div>
    </div>
  );
}

/* ---- Combined Portfolio View ---- */

export function PortfolioAnalytics({ cases }: PortfolioProps) {
  return (
    <div className="flex flex-col gap-3">
      <GeoConcentration cases={cases} />
      <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12 }}>
        <FactorExposure cases={cases} />
      </div>
      <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12 }}>
        <ConfidenceDistribution cases={cases} />
      </div>
    </div>
  );
}
