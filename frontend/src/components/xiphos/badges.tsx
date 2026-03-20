import { T, FS, TIER_META, RISK_META, tierBand, type TierKey, type RiskKey } from "@/lib/tokens";
import { ShieldOff } from "lucide-react";

interface BadgeProps {
  color: string;
  bg: string;
  children: React.ReactNode;
  size?: "sm" | "md" | "lg";
}

export function XBadge({ color, bg, children, size = "sm" }: BadgeProps) {
  const sizes = {
    sm: { fontSize: FS.sm, padding: "2px 8px", borderRadius: 4 },
    md: { fontSize: FS.sm, padding: "3px 10px", borderRadius: 4 },
    lg: { fontSize: FS.md, padding: "4px 14px", borderRadius: 6 },
  };
  const s = sizes[size];
  return (
    <span
      className="inline-flex items-center whitespace-nowrap font-semibold tracking-wider"
      style={{
        ...s,
        color,
        background: bg,
        border: `1px solid ${color}33`,
      }}
    >
      {children}
    </span>
  );
}

/** Hard stop gets special treatment: white on deep red, larger, with icon */
export function TierBadge({ tier, size = "sm" }: { tier: TierKey; size?: "sm" | "md" | "lg" }) {
  const t = TIER_META[tier] || TIER_META.TIER_3_CONDITIONAL;
  if (tierBand(tier) === "critical") {
    const sizes = {
      sm: { fontSize: FS.sm, padding: "3px 10px", borderRadius: 4, iconSize: 12 },
      md: { fontSize: FS.base, padding: "4px 12px", borderRadius: 5, iconSize: 14 },
      lg: { fontSize: FS.md, padding: "6px 16px", borderRadius: 6, iconSize: 16 },
    };
    const s = sizes[size];
    return (
      <span
        className="inline-flex items-center gap-1.5 whitespace-nowrap font-bold tracking-wider"
        style={{
          fontSize: s.fontSize,
          padding: s.padding,
          borderRadius: s.borderRadius,
          color: "#ffffff",
          background: T.hardStopBg,
          border: `2px solid ${T.hardStopBorder}`,
          boxShadow: "0 0 12px rgba(220,38,38,0.3)",
        }}
      >
        <ShieldOff size={s.iconSize} />
        DISQUALIFIED
      </span>
    );
  }
  return <XBadge color={t.color} bg={t.bg} size={size}>{t.label}</XBadge>;
}

export function RiskBadge({ level }: { level: RiskKey }) {
  const r = RISK_META[level] || RISK_META.medium;
  return <XBadge color={r.color} bg={r.bg}>{r.label}</XBadge>;
}

export function SeverityBadge({ sev }: { sev: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    critical: { color: T.dRed, bg: T.dRedBg },
    high: { color: T.red, bg: T.redBg },
    medium: { color: T.amber, bg: T.amberBg },
    low: { color: T.green, bg: T.greenBg },
  };
  const m = map[sev] || map.medium;
  return <XBadge color={m.color} bg={m.bg}>{sev.toUpperCase()}</XBadge>;
}
