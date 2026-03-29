import { Sparkles } from "lucide-react";
import { FS, T } from "@/lib/tokens";
import type { RiskStoryline as RiskStorylineType, RiskStorylineCard as RiskStorylineCardType } from "@/lib/api";
import { RiskStorylineCard } from "./risk-storyline-card";


interface RiskStorylineProps {
  storyline: RiskStorylineType;
  onAction: (card: RiskStorylineCardType) => void;
}


export function RiskStoryline({ storyline, onAction }: RiskStorylineProps) {
  if (!storyline.cards || storyline.cards.length === 0) return null;

  const averageConfidence = Math.round(
    storyline.cards.reduce((sum, card) => sum + card.confidence, 0) / storyline.cards.length * 100,
  );
  const totalSourceRefs = storyline.cards.reduce((sum, card) => sum + card.source_refs.length, 0);

  return (
    <div
      className="mt-4 rounded-xl"
      style={{
        background: "linear-gradient(180deg, rgba(16,25,37,0.98), rgba(11,17,25,0.98))",
        border: `1px solid ${T.borderLight}`,
        padding: 16,
      }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="inline-flex items-center gap-2">
            <Sparkles size={14} color={T.accent} />
            <span
              className="font-semibold uppercase tracking-wider"
              style={{ fontSize: FS.sm, color: T.muted }}
            >
              Risk Storyline
            </span>
          </div>
          <div style={{ marginTop: 6, fontSize: FS.base, color: T.dim, maxWidth: 760, lineHeight: 1.6 }}>
            Helios arranges the most important signals in the order an analyst needs them: what changed, why it matters, who or what it touches, and what to do next.
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 999,
              background: `${T.accent}12`,
              color: T.accent,
              fontSize: FS.sm,
              fontWeight: 700,
            }}
          >
            {storyline.cards.length} evidence-backed card{storyline.cards.length === 1 ? "" : "s"}
          </div>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 999,
              background: T.raised,
              color: T.dim,
              fontSize: FS.sm,
              fontWeight: 600,
              border: `1px solid ${T.border}`,
            }}
          >
            {averageConfidence}% average confidence
          </div>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 999,
              background: T.raised,
              color: T.dim,
              fontSize: FS.sm,
              fontWeight: 600,
              border: `1px solid ${T.border}`,
            }}
          >
            {totalSourceRefs} supporting sources
          </div>
        </div>
      </div>

      <div
        className="grid gap-3 mt-4"
        style={{
          gridTemplateColumns: storyline.cards.length <= 3
            ? "repeat(auto-fit, minmax(240px, 1fr))"
            : "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {storyline.cards.map((card) => (
          <RiskStorylineCard key={card.id} card={card} onAction={onAction} />
        ))}
      </div>
    </div>
  );
}
