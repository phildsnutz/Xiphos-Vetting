import { T, FS } from "@/lib/tokens";

interface StatCardProps {
  label: string;
  value: number;
  color: string;
  suffix?: string;
  emphasis?: boolean;
}

export function StatCard({ label, value, color, suffix, emphasis }: StatCardProps) {
  return (
    <div
      className="rounded-lg p-3 lg:p-4"
      style={{
        background: T.surface,
        border: emphasis ? `2px solid ${color}44` : `1px solid ${T.border}`,
        boxShadow: emphasis ? `0 0 16px ${color}15` : "none",
      }}
    >
      <span
        className="font-semibold uppercase tracking-wider block"
        style={{ fontSize: FS.xs, color: T.muted }}
      >
        {label}
      </span>
      <div
        className="font-bold"
        style={{
          fontSize: emphasis ? FS.xxl : FS.xl,
          color,
          marginTop: 4,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}{suffix && <span style={{ fontSize: FS.md, fontWeight: 500 }}>{suffix}</span>}
      </div>
    </div>
  );
}
