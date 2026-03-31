import { useState, type ReactNode } from "react";
import { Globe, TrendingUp } from "lucide-react";

import { T, FS, SENSITIVITY_META, parseSensitivity, tierColor, parseTier } from "@/lib/tokens";
import { formatRecommendationLabel } from "@/lib/workflow-copy";
import type { Calibration, ScoreSnapshot } from "@/lib/types";

export function ScoreHistory({
  history,
  current,
}: {
  history: ScoreSnapshot[];
  current: { p: number; tier: string; ts: string };
}) {
  const points = [...history, { p: current.p, tier: current.tier, sc: 0, ts: current.ts }];
  if (points.length < 2) return null;

  const w = 260;
  const h = 64;
  const padX = 24;
  const padY = 10;
  const chartW = w - padX * 2;
  const chartH = h - padY * 2;
  const maxP = Math.max(0.8, ...points.map((p) => p.p), 0.15) + 0.05;

  const x = (i: number) => padX + (i / (points.length - 1)) * chartW;
  const y = (p: number) => padY + chartH - (p / maxP) * chartH;
  const linePts = points.map((pt, i) => `${x(i)},${y(pt.p)}`).join(" ");

  const thresholds = [
    { val: 0.15, label: "CLR", color: T.green },
    { val: 0.30, label: "MON", color: T.amber },
    { val: 0.60, label: "STP", color: T.red },
  ].filter((t) => t.val < maxP);

  return (
    <div className="rounded-lg p-4 glass-card animate-fade-in">
      <div className="flex items-center gap-1.5 mb-2">
        <TrendingUp size={12} color={T.muted} />
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
          Score History
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          ({points.length} assessments)
        </span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", width: "100%", maxWidth: w }}>
        {thresholds.map((threshold) => (
          <g key={threshold.label}>
            <line
              x1={padX}
              y1={y(threshold.val)}
              x2={w - padX}
              y2={y(threshold.val)}
              stroke={threshold.color}
              strokeWidth={0.5}
              strokeDasharray="3,3"
              opacity={0.4}
            />
            <text x={w - padX + 3} y={y(threshold.val) + 3} fill={threshold.color} fontSize={7} fontFamily="monospace" opacity={0.6}>
              {threshold.label}
            </text>
          </g>
        ))}

        <polyline points={linePts} fill="none" stroke={T.accent} strokeWidth={1.5} strokeLinejoin="round" />

        {points.map((pt, i) => {
          const color = tierColor(parseTier(pt.tier));
          return (
            <g key={i}>
              <circle cx={x(i)} cy={y(pt.p)} r={3.5} fill={T.bg} stroke={color} strokeWidth={1.5} />
              {(i === 0 || i === points.length - 1) && (
                <text x={x(i)} y={y(pt.p) - 7} textAnchor="middle" fill={T.dim} fontSize={8} fontFamily="monospace">
                  {Math.round(pt.p * 100)}%
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between mt-1">
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[0].ts.split("T")[0]}
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[points.length - 1].ts.split("T")[0]}
        </span>
      </div>
    </div>
  );
}

export function ExpandableSection({
  title,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  badge?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div style={{ borderBottom: `1px solid ${T.border}` }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 0",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: T.text,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
          {badge}
        </div>
        <span
          style={{
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 200ms ease-out",
            display: "inline-block",
          }}
        >
          ▾
        </span>
      </button>
      <div
        style={{
          overflow: "hidden",
          transition: "max-height 200ms ease-out, opacity 200ms ease-out",
          maxHeight: open ? "5000px" : 0,
          opacity: open ? 1 : 0,
          paddingBottom: open ? 20 : 0,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function RegulatoryPanel({ cal }: { cal: Calibration }) {
  if (!cal.regulatoryStatus || cal.regulatoryStatus === "NOT_EVALUATED") {
    return null;
  }

  return (
    <div
      className="rounded-lg"
      style={{
        padding: 16,
        background: T.surface,
        border: `1px solid ${
          cal.regulatoryStatus === "NON_COMPLIANT"
            ? T.hardStopBorder
            : cal.regulatoryStatus === "REQUIRES_REVIEW"
              ? T.amber + "66"
              : T.green + "44"
        }`,
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Globe size={16} color={T.accent} />
        <span className="font-bold" style={{ fontSize: FS.md, color: T.text }}>
          DoD Compliance Assessment
        </span>
        {cal.sensitivityContext && cal.sensitivityContext !== "COMMERCIAL" && (() => {
          const sensitivity = SENSITIVITY_META[parseSensitivity(cal.sensitivityContext)];
          return (
            <span
              className="rounded px-2 py-0.5 font-semibold"
              style={{ fontSize: FS.sm, background: sensitivity.bg, color: sensitivity.color, border: `1px solid ${sensitivity.tagColor}44` }}
            >
              {sensitivity.label}
            </span>
          );
        })()}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Regulatory Status</div>
          <div
            className="font-bold"
            style={{
              fontSize: FS.sm,
              color:
                cal.regulatoryStatus === "COMPLIANT" ? T.green : cal.regulatoryStatus === "NON_COMPLIANT" ? T.red : T.amber,
            }}
          >
            {cal.regulatoryStatus.replace(/_/g, " ")}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Recommendation</div>
          <div
            className="font-bold"
            style={{
              fontSize: FS.sm,
              color:
                cal.recommendation?.includes("APPROVED") ? T.green : cal.recommendation?.includes("DO_NOT") ? T.red : T.amber,
            }}
          >
            {formatRecommendationLabel(cal.tier)}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Eligible</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodEligible ? T.green : T.red }}>
            {cal.dodEligible ? "YES" : "NO"}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Qualified</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodQualified ? T.green : T.red }}>
            {cal.dodQualified ? "YES" : "NO"}
          </div>
        </div>
      </div>

      {cal.regulatoryFindings && cal.regulatoryFindings.length > 0 && (
        <div className="mt-3" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          <div
            style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}
          >
            Regulatory Gate Findings
          </div>
          {(cal.regulatoryFindings as Array<Record<string, unknown>>).map((finding, i) => (
            <div
              key={i}
              className="flex gap-2 mb-2 rounded p-2"
              style={{
                background: String(finding.status) === "FAIL" ? T.redBg : T.amberBg,
                border: `1px solid ${String(finding.status) === "FAIL" ? T.red + "33" : T.amber + "33"}`,
              }}
            >
              <div
                className="font-bold shrink-0"
                style={{
                  fontSize: FS.sm,
                  color: String(finding.status) === "FAIL" ? T.red : T.amber,
                  minWidth: 40,
                }}
              >
                {String(finding.status)}
              </div>
              <div>
                <div className="font-semibold" style={{ fontSize: FS.sm, color: T.text }}>
                  {String(finding.name)}
                </div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 1 }}>{String(finding.explanation)}</div>
                {finding.remediation ? (
                  <div style={{ fontSize: FS.sm, color: T.amber, marginTop: 3 }}>
                    Remediation: {String(finding.remediation)}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {cal.modelVersion && (
        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, textAlign: "right" }}>
          Engine: {cal.modelVersion}
        </div>
      )}
    </div>
  );
}
