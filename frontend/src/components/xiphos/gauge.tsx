import { T, probColor } from "@/lib/tokens";

interface GaugeProps {
  value: number;
  lo?: number;
  hi?: number;
}

export function Gauge({ value, lo, hi }: GaugeProps) {
  const pct = Math.round(value * 100);
  const color = probColor(value);
  const R = 38;
  const SW = 7;
  const W = 100;
  const H = 56;
  const cx = W / 2;
  const halfCirc = Math.PI * R;
  const dash = halfCirc * (pct / 100);

  // CI band: render as a thicker, translucent arc behind the main arc
  const loFrac = lo != null ? lo : value;
  const hiFrac = hi != null ? hi : value;
  const ciStart = halfCirc * loFrac;
  const ciLen = halfCirc * (hiFrac - loFrac);

  return (
    <div className="text-center mx-auto" style={{ width: W }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* Track */}
        <path
          d={`M ${cx - R} ${H - 2} A ${R} ${R} 0 0 1 ${cx + R} ${H - 2}`}
          fill="none"
          stroke={T.border}
          strokeWidth={SW}
          strokeLinecap="round"
        />
        {/* CI band */}
        {lo != null && hi != null && (
          <path
            d={`M ${cx - R} ${H - 2} A ${R} ${R} 0 0 1 ${cx + R} ${H - 2}`}
            fill="none"
            stroke={color}
            strokeWidth={SW + 6}
            strokeLinecap="butt"
            strokeDasharray={`0 ${ciStart} ${ciLen} ${halfCirc}`}
            opacity={0.18}
          />
        )}
        {/* Value arc */}
        <path
          d={`M ${cx - R} ${H - 2} A ${R} ${R} 0 0 1 ${cx + R} ${H - 2}`}
          fill="none"
          stroke={color}
          strokeWidth={SW}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${halfCirc}`}
        />
      </svg>
      <div className="font-mono font-bold -mt-0.5" style={{ fontSize: 22, color }}>
        {pct}%
      </div>
      {lo != null && hi != null && (
        <div className="font-mono mt-0.5" style={{ fontSize: 9, color: T.muted }}>
          {Math.round(lo * 100)}&ndash;{Math.round(hi * 100)}%
        </div>
      )}
    </div>
  );
}
