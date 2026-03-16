import { T } from "@/lib/tokens";

interface StatCardProps {
  label: string;
  value: number;
  color: string;
  suffix?: string;
}

export function StatCard({ label, value, color, suffix }: StatCardProps) {
  return (
    <div
      className="rounded-lg p-3 lg:p-4"
      style={{ background: T.surface, border: `1px solid ${T.border}` }}
    >
      <span
        className="font-semibold uppercase tracking-wider"
        style={{ fontSize: 10, color: T.muted }}
      >
        {label}
      </span>
      <div className="font-mono font-bold" style={{ fontSize: 22, color, marginTop: 4 }}>
        {value}{suffix && <span style={{ fontSize: 14, fontWeight: 500 }}>{suffix}</span>}
      </div>
    </div>
  );
}
