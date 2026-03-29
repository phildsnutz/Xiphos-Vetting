import { AlertTriangle, ArrowRight, CheckCircle2, Network, Shield } from "lucide-react";
import { FS, T } from "@/lib/tokens";
import type { RiskStorylineCard as RiskStorylineCardType } from "@/lib/api";


interface RiskStorylineCardProps {
  card: RiskStorylineCardType;
  onAction: (card: RiskStorylineCardType) => void;
}


function cardIcon(card: RiskStorylineCardType) {
  switch (card.type) {
    case "trigger":
      return <AlertTriangle size={14} color={cardAccent(card)} />;
    case "impact":
      return <Shield size={14} color={cardAccent(card)} />;
    case "reach":
      return <Network size={14} color={cardAccent(card)} />;
    case "offset":
      return <CheckCircle2 size={14} color={cardAccent(card)} />;
    case "action":
    default:
      return <ArrowRight size={14} color={cardAccent(card)} />;
  }
}

function cardTypeLabel(card: RiskStorylineCardType): string {
  switch (card.type) {
    case "trigger":
      return "What changed";
    case "impact":
      return "Why it matters";
    case "reach":
      return "Who or what it touches";
    case "offset":
      return "What offsets concern";
    case "action":
    default:
      return "What to do next";
  }
}


function cardAccent(card: RiskStorylineCardType): string {
  switch (card.severity) {
    case "critical":
      return T.red;
    case "high":
      return T.orange;
    case "medium":
      return T.amber;
    case "positive":
      return T.green;
    case "low":
    default:
      return card.type === "reach" ? T.accent : T.dim;
  }
}


function cardBackground(card: RiskStorylineCardType): string {
  switch (card.severity) {
    case "critical":
      return "linear-gradient(180deg, rgba(239,68,68,0.14), rgba(16,25,37,0.94))";
    case "high":
      return "linear-gradient(180deg, rgba(249,115,22,0.12), rgba(16,25,37,0.94))";
    case "medium":
      return "linear-gradient(180deg, rgba(245,158,11,0.12), rgba(16,25,37,0.94))";
    case "positive":
      return "linear-gradient(180deg, rgba(16,185,129,0.12), rgba(16,25,37,0.94))";
    case "low":
    default:
      return "linear-gradient(180deg, rgba(96,165,250,0.08), rgba(16,25,37,0.94))";
  }
}


function severityLabel(card: RiskStorylineCardType): string {
  if (card.severity === "positive") return "Positive";
  return card.severity.charAt(0).toUpperCase() + card.severity.slice(1);
}

function evidenceLabel(card: RiskStorylineCardType): string {
  const count = card.source_refs.length;
  if (count <= 0) return "Evidence pending";
  if (count === 1) return "1 supporting source";
  return `${count} supporting sources`;
}


export function RiskStorylineCard({ card, onAction }: RiskStorylineCardProps) {
  const accent = cardAccent(card);
  const confidence = Math.max(0, Math.min(99, Math.round(card.confidence * 100)));

  return (
    <div
      className="rounded-xl flex flex-col"
      style={{
        minHeight: 196,
        background: cardBackground(card),
        border: `1px solid ${accent}33`,
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.03), 0 8px 24px rgba(0,0,0,0.18)`,
        padding: 16,
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="inline-flex items-center gap-3">
          <div
            className="rounded-lg flex items-center justify-center"
            style={{
              width: 34,
              height: 34,
              background: `${accent}14`,
              border: `1px solid ${accent}2f`,
              boxShadow: `0 0 0 1px rgba(255,255,255,0.02), 0 10px 22px ${accent}18`,
            }}
          >
            {cardIcon(card)}
          </div>
          <div>
            <div
              className="font-semibold uppercase tracking-wider"
              style={{ fontSize: 11, color: accent, letterSpacing: "0.08em" }}
            >
              {cardTypeLabel(card)}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>
              Priority {card.rank}
            </div>
          </div>
        </div>
        <div
          className="rounded-full px-2 py-1 font-semibold"
          style={{
            fontSize: 11,
            color: accent,
            background: `${accent}14`,
            border: `1px solid ${accent}2f`,
          }}
        >
          {severityLabel(card)}
        </div>
      </div>

      <div style={{ marginTop: 16, fontSize: FS.md, fontWeight: 700, color: T.text, lineHeight: 1.35 }}>
        {card.title}
      </div>

      <div
        className="rounded-lg"
        style={{
          marginTop: 10,
          padding: "10px 12px",
          background: "rgba(5,10,16,0.34)",
          border: `1px solid rgba(255,255,255,0.04)`,
        }}
      >
        <div
          className="font-semibold uppercase tracking-wider"
          style={{ fontSize: 10, color: T.muted, letterSpacing: "0.08em", marginBottom: 6 }}
        >
          Why this matters
        </div>
        <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6 }}>
        {card.body}
        </div>
      </div>

      <div className="mt-auto pt-4 flex items-center justify-between gap-3 flex-wrap">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            Confidence <span style={{ color: T.text, fontWeight: 600 }}>{confidence}%</span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                padding: "4px 8px",
                borderRadius: 999,
                fontSize: 11,
                color: T.dim,
                background: T.bg,
                border: `1px solid ${T.border}`,
                fontWeight: 600,
              }}
            >
              {evidenceLabel(card)}
            </span>
            <span
              style={{
                padding: "4px 8px",
                borderRadius: 999,
                fontSize: 11,
                color: accent,
                background: `${accent}14`,
                border: `1px solid ${accent}2f`,
                fontWeight: 700,
              }}
            >
              {severityLabel(card)}
            </span>
          </div>
        </div>
        <button
          onClick={() => onAction(card)}
          className="inline-flex items-center gap-1.5 rounded-lg border cursor-pointer"
          style={{
            padding: "9px 12px",
            background: `${accent}14`,
            color: accent,
            borderColor: `${accent}2f`,
            fontSize: FS.sm,
            fontWeight: 600,
            boxShadow: `0 10px 18px ${accent}12`,
          }}
        >
          {card.cta_label}
          <ArrowRight size={12} />
        </button>
      </div>
    </div>
  );
}
