import React from "react";
import { AlertTriangle } from "lucide-react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { Calibration, VettingCase } from "@/lib/types";
import { SectionEyebrow } from "../shell-primitives";

interface DecisionPanelProps {
  c: VettingCase;
  cal: Calibration | null;
}

export const DecisionPanel: React.FC<DecisionPanelProps> = ({ c, cal }) => {
  const bayesPct = cal ? Math.round(cal.p * 100) : null;
  const divergence = bayesPct != null ? Math.abs(bayesPct - c.sc) : 0;

  return (
    <div
      style={{
        borderRadius: SP.lg,
        border: `1px solid ${T.border}`,
        background: T.surface,
        padding: PAD.comfortable,
      }}
    >
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: SP.sm,
            paddingRight: SP.sm,
            borderRight: cal ? `1px solid ${T.border}` : "none",
          }}
        >
          <SectionEyebrow>Decision baseline</SectionEyebrow>
          <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>
            What procurement policy is telling the reviewer right now.
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {c.sc}
            </span>
            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
              /100
            </span>
            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
              {Math.min(99, Math.max(0, Math.round((c.conf || 0.85) * 100)))}% confidence
            </span>
          </div>
          <div className="w-full rounded-full overflow-hidden" style={{ height: SP.xs, background: T.border }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${c.sc}%`, background: c.sc > 70 ? T.red : c.sc > 40 ? T.amber : T.green }}
            />
          </div>
        </div>

        {cal ? (
          <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
            <SectionEyebrow>Model pressure</SectionEyebrow>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>
              The calibrated model view. Use it to pressure-test the rubric, not replace it.
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                {bayesPct}%
              </span>
              <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                Coverage {Math.round(cal.cov * 100)}%
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

            {divergence > 15 ? (
              <div
                className="flex items-start gap-2 rounded"
                style={{ padding: PAD.tight, background: T.amberBg, border: `1px solid ${T.amber}33` }}
              >
                <AlertTriangle size={12} color={T.amber} className="shrink-0" style={{ marginTop: 2 }} />
                <span style={{ fontSize: FS.sm, color: T.amber, lineHeight: 1.5 }}>
                  Consensus break. Bayesian ({bayesPct}%) and policy rubric ({c.sc}) diverge by {divergence} points.
                </span>
              </div>
            ) : (
              <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.5 }}>
                Bayesian and rubric views are materially aligned.
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
};
