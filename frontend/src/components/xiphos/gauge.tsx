import { T, FS, probColor, probLabel } from "@/lib/tokens";

interface GaugeProps {
  value: number;
  lo?: number;
  hi?: number;
}

/** Full-width probability bar replacing the semicircular gauge */
export function Gauge({ value, lo, hi }: GaugeProps) {
  const pct = Math.round(value * 100);
  const color = probColor(value);
  const label = probLabel(value);
  const loPct = lo != null ? Math.round(lo * 100) : pct;
  const hiPct = hi != null ? Math.round(hi * 100) : pct;

  return (
    <div style={{ width: "100%" }}>
      {/* Main probability number */}
      <div className="flex items-baseline gap-2 mb-1">
        <span className="font-bold" style={{ fontSize: 38, color, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
          {pct}%
        </span>
        <span style={{ fontSize: FS.sm, color: T.dim, fontWeight: 500 }}>
          {label}
        </span>
      </div>

      {/* Probability bar */}
      <div className="relative w-full" style={{ height: 12, marginTop: 8, marginBottom: 6 }}>
        {/* Track */}
        <div
          className="absolute inset-0 rounded-full overflow-hidden"
          style={{ background: T.border }}
        >
          {/* Gradient zone markers */}
          <div className="absolute inset-0 flex">
            <div style={{ width: "15%", background: "rgba(16,185,129,0.15)" }} />
            <div style={{ width: "15%", background: "rgba(245,158,11,0.15)" }} />
            <div style={{ width: "20%", background: "rgba(249,115,22,0.12)" }} />
            <div style={{ width: "50%", background: "rgba(239,68,68,0.12)" }} />
          </div>
        </div>

        {/* Confidence interval band */}
        {lo != null && hi != null && (
          <div
            className="absolute top-0 bottom-0 rounded-full"
            style={{
              left: `${loPct}%`,
              width: `${hiPct - loPct}%`,
              background: `${color}35`,
              border: `1px solid ${color}40`,
            }}
          />
        )}

        {/* Value indicator */}
        <div
          className="absolute top-0 bottom-0 rounded-full"
          style={{
            left: 0,
            width: `${pct}%`,
            background: color,
            opacity: 0.85,
            transition: "width 0.3s ease",
          }}
        />

        {/* Threshold markers */}
        {[15, 30, 50].map((threshold) => (
          <div
            key={threshold}
            className="absolute top-0 bottom-0"
            style={{
              left: `${threshold}%`,
              width: 1,
              background: `${T.text}20`,
            }}
          />
        ))}
      </div>

      {/* CI label */}
      {lo != null && hi != null && (
        <div className="flex items-center gap-3" style={{ marginTop: 4 }}>
          <span style={{ fontSize: FS.xs, color: T.muted, fontVariantNumeric: "tabular-nums" }}>
            95% CI: {loPct}% to {hiPct}%
          </span>
        </div>
      )}
    </div>
  );
}
