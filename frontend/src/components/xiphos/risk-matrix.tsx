/**
 * Cross-Vendor Risk Factor Comparison Matrix
 *
 * "The most important chart you're not showing" -- Tufte review
 *
 * Renders a heat-map grid: vendors on rows, risk factors on columns.
 * Cell color encodes raw risk score. Sorted by posterior probability.
 * Enables instant visual comparison of WHERE risk concentrates.
 */

import { T, probColor } from "@/lib/tokens";
import { TierBadge } from "./badges";
import type { VettingCase } from "@/lib/types";

interface RiskMatrixProps {
  cases: VettingCase[];
  onSelect: (c: VettingCase) => void;
}

const FACTORS = ["Sanctions", "Geography", "Ownership", "Data Quality", "Executive"];

function cellColor(raw: number): string {
  if (raw < 0.15) return T.green;
  if (raw < 0.35) return T.amber;
  if (raw < 0.60) return T.orange;
  return T.red;
}

function cellBg(raw: number): string {
  const c = cellColor(raw);
  return c + "22";
}

export function RiskMatrix({ cases, onSelect }: RiskMatrixProps) {
  // Only show cases with calibration data, sorted by posterior desc
  const scored = cases
    .filter((c) => c.cal)
    .sort((a, b) => (b.cal?.p ?? 0) - (a.cal?.p ?? 0));

  if (scored.length === 0) return null;

  return (
    <div className="rounded-lg overflow-hidden" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
      <div className="p-3 pb-0">
        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
          Cross-Vendor Risk Comparison
        </div>
        <div style={{ fontSize: 9, color: T.muted, marginTop: 2 }}>
          Raw factor scores across all vendors. Click a row to drill in.
        </div>
      </div>

      <div className="overflow-x-auto p-3">
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 500 }}>
          <thead>
            <tr>
              <th
                style={{
                  textAlign: "left", padding: "6px 8px", fontSize: 9,
                  color: T.muted, fontWeight: 600, borderBottom: `1px solid ${T.border}`,
                  position: "sticky", left: 0, background: T.surface, zIndex: 1,
                  minWidth: 140,
                }}
              >
                VENDOR
              </th>
              <th
                style={{
                  textAlign: "center", padding: "6px 4px", fontSize: 9,
                  color: T.muted, fontWeight: 600, borderBottom: `1px solid ${T.border}`,
                  width: 50,
                }}
              >
                P(RISK)
              </th>
              {FACTORS.map((f) => (
                <th
                  key={f}
                  style={{
                    textAlign: "center", padding: "6px 4px", fontSize: 9,
                    color: T.muted, fontWeight: 600, borderBottom: `1px solid ${T.border}`,
                    minWidth: 70,
                  }}
                >
                  {f.toUpperCase()}
                </th>
              ))}
              <th
                style={{
                  textAlign: "center", padding: "6px 4px", fontSize: 9,
                  color: T.muted, fontWeight: 600, borderBottom: `1px solid ${T.border}`,
                  width: 70,
                }}
              >
                TIER
              </th>
            </tr>
          </thead>
          <tbody>
            {scored.map((c) => {
              const cal = c.cal!;
              // Build factor lookup
              const factorMap: Record<string, number> = {};
              for (const ct of cal.ct) {
                factorMap[ct.n] = ct.raw;
              }

              return (
                <tr
                  key={c.id}
                  onClick={() => onSelect(c)}
                  className="cursor-pointer"
                  style={{ borderBottom: `1px solid ${T.border}` }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = T.hover;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "transparent";
                  }}
                >
                  <td
                    style={{
                      padding: "6px 8px", fontSize: 11, color: T.text,
                      fontWeight: 500, whiteSpace: "nowrap",
                      position: "sticky", left: 0, background: T.surface,
                      zIndex: 1,
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="font-mono font-bold shrink-0"
                        style={{ fontSize: 9, color: T.dim, width: 20 }}
                      >
                        {c.cc}
                      </span>
                      <span className="truncate" style={{ maxWidth: 110 }}>{c.name}</span>
                    </div>
                  </td>
                  <td style={{ padding: "6px 4px", textAlign: "center" }}>
                    <span
                      className="font-mono font-bold"
                      style={{ fontSize: 12, color: probColor(cal.p) }}
                    >
                      {Math.round(cal.p * 100)}%
                    </span>
                  </td>
                  {FACTORS.map((f) => {
                    const raw = factorMap[f] ?? 0;
                    return (
                      <td key={f} style={{ padding: "4px 3px", textAlign: "center" }}>
                        <div
                          className="rounded mx-auto font-mono font-semibold"
                          style={{
                            width: 42, padding: "3px 0",
                            fontSize: 10,
                            color: cellColor(raw),
                            background: cellBg(raw),
                          }}
                        >
                          {(raw * 100).toFixed(0)}
                        </div>
                      </td>
                    );
                  })}
                  <td style={{ padding: "6px 4px", textAlign: "center" }}>
                    <TierBadge tier={cal.tier} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
