import { T } from "@/lib/tokens";

/* ---- Contribution bar (for detail view) ---- */

interface ContribBarProps {
  value: number;
  max?: number;
  color: string;
}

export function ContribBar({ value, max = 1, color }: ContribBarProps) {
  return (
    <div className="w-full rounded-full overflow-hidden" style={{ height: 5, background: T.border }}>
      <div
        className="h-full rounded-full transition-all duration-300"
        style={{ width: `${(value / max) * 100}%`, background: color }}
      />
    </div>
  );
}
