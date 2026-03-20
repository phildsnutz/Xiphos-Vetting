import { T, probColor, FS } from "@/lib/tokens";
import { TierBadge, RiskBadge } from "./badges";
import { XCircle, AlertTriangle } from "lucide-react";
import type { VettingCase } from "@/lib/types";

interface CaseRowProps {
  c: VettingCase;
  onClick: () => void;
}

const PROGRAM_LABELS: Record<string, string> = {
  dod_classified: "DoD/IC",
  dod_unclassified: "DoD",
  federal_non_dod: "Federal",
  regulated_commercial: "Regulated",
  commercial: "Commercial",
  // Legacy
  weapons_system: "DoD",
  mission_critical: "Federal",
  critical_infrastructure: "Federal",
  dual_use: "Regulated",
  standard_industrial: "Commercial",
  commercial_off_shelf: "Commercial",
  services: "Commercial",
};

export function CaseRow({ c, onClick }: CaseRowProps) {
  const programLabel = c.program ? PROGRAM_LABELS[c.program] || c.program : "";
  return (
    <div
      className="rounded-lg cursor-pointer transition-colors"
      style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "10px 12px" }}
      onClick={onClick}
      onMouseEnter={(e) => (e.currentTarget.style.background = T.hover)}
      onMouseLeave={(e) => (e.currentTarget.style.background = T.surface)}
    >
      <div className="flex items-center gap-3">
        {/* Country chip */}
        <div
          className="flex items-center justify-center shrink-0 rounded font-bold"
          style={{
            width: 34, height: 34, fontSize: FS.sm,
            background: T.raised, color: T.dim,
            border: `1px solid ${T.border}`,
          }}
        >
          {c.cc}
        </div>

        {/* Name + date + profile */}
        <div className="flex-1 min-w-0 overflow-hidden">
          <div className="flex items-center gap-2">
            <div className="font-semibold truncate" style={{ fontSize: FS.base, color: T.text }}>
              {c.name}
            </div>
            {programLabel && (
              <div
                className="rounded px-1.5 py-0.5 shrink-0"
                style={{
                  fontSize: 10,
                  background: T.accent + "18",
                  color: T.accent,
                  fontWeight: 600,
                  letterSpacing: "0.03em",
                }}
              >
                {programLabel}
              </div>
            )}
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 1 }}>{c.date}</div>
        </div>

        {/* Score / tier */}
        <div className="shrink-0 flex items-center gap-2">
          {c.cal ? (
            <>
              <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: probColor(c.cal.p) }}>
                {Math.round(c.cal.p * 100)}%
              </span>
              <TierBadge tier={c.cal.tier} />
            </>
          ) : (
            <>
              <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                {c.sc}/100
              </span>
              <RiskBadge level={c.rl} />
            </>
          )}
        </div>
      </div>

      {/* Hard stop inline */}
      {c.cal?.stops && c.cal.stops.length > 0 && (
        <div
          className="flex items-center gap-1.5 mt-2 rounded"
          style={{ padding: "5px 10px", background: T.dRedBg, border: `1px solid ${T.dRed}33` }}
        >
          <XCircle size={12} color={T.dRed} className="shrink-0" />
          <span className="font-semibold truncate" style={{ fontSize: FS.sm, color: T.dRed }}>
            {c.cal.stops[0].t}
          </span>
        </div>
      )}

      {/* Flags inline */}
      {c.cal?.flags && c.cal.flags.length > 0 && !(c.cal?.stops?.length) && (
        <div
          className="flex items-center gap-1.5 mt-2 rounded"
          style={{ padding: "5px 10px", background: T.amberBg, border: `1px solid ${T.amber}33` }}
        >
          <AlertTriangle size={12} color={T.amber} className="shrink-0" />
          <span className="font-semibold" style={{ fontSize: FS.sm, color: T.amber }}>
            {c.cal.flags.length} flag{c.cal.flags.length > 1 ? "s" : ""}
          </span>
        </div>
      )}
    </div>
  );
}
