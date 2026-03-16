import { T, TIER_META, RISK_META, type TierKey, type RiskKey } from "@/lib/tokens";

interface BadgeProps {
  color: string;
  bg: string;
  children: React.ReactNode;
}

export function XBadge({ color, bg, children }: BadgeProps) {
  return (
    <span
      className="inline-block whitespace-nowrap font-mono font-bold tracking-wider"
      style={{
        padding: "2px 6px",
        borderRadius: 3,
        fontSize: 10,
        color,
        background: bg,
        border: `1px solid ${color}33`,
      }}
    >
      {children}
    </span>
  );
}

export function TierBadge({ tier }: { tier: TierKey }) {
  const t = TIER_META[tier] || TIER_META.monitor;
  return <XBadge color={t.color} bg={t.bg}>{t.label}</XBadge>;
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
