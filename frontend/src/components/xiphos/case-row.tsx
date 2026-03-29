import { T, probColor, FS, displayName, parseTier, TIER_META } from "@/lib/tokens";
import { TierBadge, RiskBadge } from "./badges";
import { XCircle, AlertTriangle, CheckCircle2, Shield } from "lucide-react";
import type { VettingCase } from "@/lib/types";
import { portfolioDisposition, workflowLaneForCase, WORKFLOW_LANE_META } from "./portfolio-utils";
import { formatProgramLabel, formatCaseDateLabel } from "@/lib/workflow-copy";

interface CaseRowProps {
  c: VettingCase;
  onClick: () => void;
}

function portfolioTierLabel(c: VettingCase): string {
  if (!c.cal?.tier) {
    return "";
  }
  const tier = parseTier(c.cal.tier);
  return TIER_META[tier]?.label ?? tier.replace(/_/g, " ");
}

function portfolioReason(c: VettingCase): string {
  const disposition = portfolioDisposition(c);
  if (disposition === "blocked" && c.cal?.stops && c.cal.stops.length > 0) {
    return c.cal.stops[0].t;
  }
  if (c.cal?.flags && c.cal.flags.length > 0 && (disposition === "review" || disposition === "qualified")) {
    return c.cal.flags[0].t;
  }
  if (disposition === "qualified") {
    return `${portfolioTierLabel(c)} approval with watch conditions`;
  }
  if (c.cal?.recommendation) {
    return c.cal.recommendation.replace(/_/g, " ");
  }
  if (c.cal?.finds && c.cal.finds.length > 0 && disposition !== "clear") {
    return c.cal.finds[0];
  }
  return "Cleared for standard processing.";
}

function portfolioDetail(c: VettingCase): string {
  const disposition = portfolioDisposition(c);
  const lane = workflowLaneForCase(c);
  if (disposition === "blocked" && c.cal?.stops && c.cal.stops.length > 0) {
    return c.cal.stops[0].x || "Escalate to compliance before any procurement action.";
  }
  if (disposition === "blocked") {
    if (lane === "export") {
      return "Next step: do not release the item, data, or access request. Escalate to trade compliance immediately.";
    }
    if (lane === "cyber") {
      return "Next step: hold sensitive scope and escalate the supplier cyber review before any approval.";
    }
    return "Next step: halt procurement and escalate to compliance before any award decision.";
  }
  if (c.cal?.flags && c.cal.flags.length > 0 && disposition === "review") {
    return c.cal.flags[0].x || "Enhanced diligence recommended before approval.";
  }
  if (c.cal?.flags && c.cal.flags.length > 0 && disposition === "qualified") {
    return c.cal.flags[0].x || "Qualified approval: proceed, but keep the flagged concern in active view.";
  }
  if (disposition === "qualified") {
    if (lane === "cyber") {
      return "Next step: proceed with scoped approval and keep remediation milestones on active watch.";
    }
    if (lane === "export") {
      return "Next step: proceed only within the documented authorization boundary and keep export controls under review.";
    }
    return "Next step: proceed with qualified approval and keep enhanced monitoring on the named concern.";
  }
  if (disposition === "review") {
    if (lane === "cyber") {
      return "Next step: confirm SPRS posture and open remediation items before allowing broader CUI-sensitive scope.";
    }
    if (lane === "export") {
      return "Next step: stop the request and obtain formal export-control review before any transfer or foreign-person access.";
    }
    return "Next step: complete enhanced due diligence before approval.";
  }
  if (lane === "cyber") {
    return "Next step: proceed with current scope and keep routine supplier-readiness checks in place.";
  }
  if (lane === "export") {
    return "Next step: proceed only within the current authorization boundary and keep change monitoring active.";
  }
  return "Next step: proceed with standard workflow and keep routine monitoring in place.";
}

function portfolioTone(c: VettingCase) {
  const disposition = portfolioDisposition(c);
  if (disposition === "blocked") {
    return {
      label: "Blocked",
      color: T.dRed,
      background: T.dRedBg,
      border: `${T.dRed}33`,
      icon: XCircle,
    };
  }
  if (disposition === "review") {
    return {
      label: "Needs review",
      color: T.amber,
      background: T.amberBg,
      border: `${T.amber}33`,
      icon: AlertTriangle,
    };
  }
  if (disposition === "qualified") {
    return {
      label: "Qualified",
      color: T.accent,
      background: `${T.accent}12`,
      border: `${T.accent}30`,
      icon: Shield,
    };
  }
  return {
    label: "Clear",
    color: T.green,
    background: `${T.green}10`,
    border: `${T.green}2d`,
    icon: CheckCircle2,
  };
}

export function CaseRow({ c, onClick }: CaseRowProps) {
  const programLabel = formatProgramLabel(c.program);
  const tone = portfolioTone(c);
  const ToneIcon = tone.icon;
  const lane = workflowLaneForCase(c);
  const laneMeta = WORKFLOW_LANE_META[lane];
  return (
    <div
      className="rounded-lg cursor-pointer transition-all duration-200 hover:shadow-md"
      style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "14px 16px", borderLeft: `2px solid ${tone.color}` }}
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
          {c.cc || "\u2014"}
        </div>

        {/* Name + date + profile */}
        <div className="flex-1 min-w-0 overflow-hidden">
          <div className="flex items-center gap-2">
            <div className="font-bold truncate" style={{ fontSize: FS.lg, color: T.text }}>
              {displayName(c.name)}
            </div>
            {programLabel && (
              <div
                className="rounded px-1.5 py-0.5 shrink-0 border"
                style={{
                  fontSize: 10,
                  background: T.raised,
                  color: T.accent,
                  border: `1px solid ${T.accent}40`,
                  fontWeight: 600,
                  letterSpacing: "0.03em",
                }}
              >
                {programLabel}
              </div>
            )}
            <div
              className="rounded px-1.5 py-0.5 shrink-0"
              style={{
                fontSize: 10,
                background: T.raised,
                color: T.text,
                border: `1px solid ${T.border}`,
                fontWeight: 700,
                letterSpacing: "0.03em",
              }}
            >
              {laneMeta.shortLabel}
            </div>
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 1 }}>
            {formatCaseDateLabel(c.date)}
          </div>
        </div>

        {/* Score / tier */}
        <div className="shrink-0 flex flex-col items-end gap-1.5">
          {c.cal ? (
            <>
              <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: probColor(c.cal.p) }}>
                {Math.round(c.cal.p * 100)}%
              </span>
              <TierBadge tier={c.cal.tier} size="sm" />
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

      <div
        className="mt-2 rounded-lg"
        style={{ padding: "8px 10px", background: tone.background, border: `1px solid ${tone.border}` }}
      >
        <div className="flex items-start gap-2">
          <ToneIcon size={12} color={tone.color} className="shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold" style={{ fontSize: FS.sm, color: tone.color }}>
                {tone.label}
              </span>
              <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                {portfolioReason(c)}
              </span>
            </div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 3, lineHeight: 1.5 }}>
              {portfolioDetail(c)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
