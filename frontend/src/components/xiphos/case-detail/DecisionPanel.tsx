import React from "react";
import { AlertTriangle } from "lucide-react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { Calibration, VettingCase } from "@/lib/types";

interface DecisionPanelProps {
  c: VettingCase;
  cal: Calibration | null;
}

export const DecisionPanel: React.FC<DecisionPanelProps> = ({ c, cal }) => {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
      {/* Policy Rubric */}
      <div className="rounded-lg glass-card" style={{ padding: PAD.comfortable }}>
        <div>
          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            Policy Rubric
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: SP.sm - 2 }}>
            What procurement policy prescribes for this vendor profile
          </div>
          <div className="flex items-baseline gap-1 mb-2">
            <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {c.sc}
            </span>
            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
              /100
            </span>
            <span className="font-mono ml-2" style={{ fontSize: FS.sm, color: T.muted }}>
              ({Math.min(99, Math.max(0, Math.round((c.conf || 0.85) * 100)))}% confidence)
            </span>
          </div>
          <div className="w-full rounded-full overflow-hidden" style={{ height: SP.xs, background: T.border }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${c.sc}%`, background: c.sc > 70 ? T.red : c.sc > 40 ? T.amber : T.green }}
            />
          </div>
          {cal && (() => {
            const bayesPct = Math.round(cal.p * 100);
            const divergence = Math.abs(bayesPct - c.sc);
            if (divergence > 15) {
              return (
                <div
                  className="flex items-center gap-1.5 mt-2 rounded"
                  style={{ padding: PAD.tight, background: T.amberBg, border: `1px solid ${T.amber}33` }}
                >
                  <AlertTriangle size={10} color={T.amber} className="shrink-0" />
                  <span style={{ fontSize: FS.sm, color: T.amber }}>
                    Consensus break: Bayesian ({bayesPct}%) and Policy Rubric ({c.sc}) diverge by {divergence} points
                  </span>
                </div>
              );
            }
            return null;
          })()}
        </div>
      </div>

      {/* Bayesian Model */}
      {cal && (
        <div className="rounded-lg glass-card" style={{ padding: PAD.comfortable }}>
          <div>
            <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
              Bayesian Model
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: SP.sm - 2 }}>
              Machine-learned confidence that this entity poses risk.
            </div>
            <div className="flex items-baseline gap-1 mb-2">
              <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                {Math.round(cal.p * 100)}%
              </span>
              <span className="font-mono ml-2" style={{ fontSize: FS.sm, color: T.muted }}>
                (Coverage {Math.round(cal.cov * 100)}%)
              </span>
            </div>
            <div className="w-full rounded-full overflow-hidden" style={{ height: SP.xs, background: T.border }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: `${cal.p * 100}%`,
                  background: cal.p > 0.7 ? T.red : cal.p > 0.4 ? T.amber : T.green,
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
