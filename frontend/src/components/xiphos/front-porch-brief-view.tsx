import type { ReactNode } from "react";
import { ArrowLeft, ArrowUpRight, ExternalLink } from "lucide-react";
import { BriefArtifact, SectionEyebrow, StatusPill } from "./shell-primitives";
import { T, FS, PAD, SP, O } from "@/lib/tokens";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export interface FrontPorchBriefViewModel {
  kind: "vendor" | "vehicle";
  eyebrow: string;
  statusLine: string;
  title: string;
  framing: string;
  sections: Array<{
    label: string;
    detail: string;
    tone?: Tone;
  }>;
  provenance: string[];
  note: string;
}

interface FrontPorchBriefViewProps {
  artifact: FrontPorchBriefViewModel;
  isCompactViewport: boolean;
  dossierLabel?: string;
  dossierDisabled?: boolean;
  dossierLoading?: boolean;
  children?: ReactNode;
  onBack: () => void;
  onOpenWarRoom: () => void;
  onOpenGraph?: () => void;
  onOpenDossier?: () => void;
}

export function FrontPorchBriefView({
  artifact,
  isCompactViewport,
  dossierLabel,
  dossierDisabled = false,
  dossierLoading = false,
  children,
  onBack,
  onOpenWarRoom,
  onOpenGraph,
  onOpenDossier,
}: FrontPorchBriefViewProps) {
  return (
    <div style={{ width: "min(920px, 100%)", display: "grid", gap: SP.lg }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: SP.md,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: SP.xs }}>
          <SectionEyebrow>{artifact.kind === "vendor" ? "Returned brief room" : "Vehicle brief room"}</SectionEyebrow>
          <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={onBack}
              className="helios-focus-ring"
              style={{
                border: `1px solid ${T.border}`,
                background: "rgba(255,255,255,0.02)",
                color: T.textSecondary,
                borderRadius: 999,
                padding: "10px 14px",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                fontSize: FS.sm,
                fontWeight: 700,
              }}
            >
              <ArrowLeft size={14} />
              Back to thread
            </button>
            <StatusPill tone={artifact.kind === "vendor" ? "info" : "neutral"}>{artifact.statusLine}</StatusPill>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap" }}>
          {artifact.kind === "vehicle" && onOpenGraph ? (
            <button
              type="button"
              onClick={onOpenGraph}
              className="helios-focus-ring"
              style={{
                border: `1px solid rgba(7,16,26,0.12)`,
                background: "rgba(255,255,255,0.04)",
                color: T.text,
                borderRadius: 999,
                padding: "10px 14px",
                cursor: "pointer",
                fontSize: FS.sm,
                fontWeight: 700,
              }}
            >
              Trace in Graph
            </button>
          ) : null}
          <button
            type="button"
            onClick={onOpenWarRoom}
            className="helios-focus-ring"
            style={{
              border: `1px solid ${T.accent}${O["20"]}`,
              background: `${T.accent}${O["08"]}`,
              color: T.text,
              borderRadius: 999,
              padding: "10px 14px",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: SP.xs,
              fontSize: FS.sm,
              fontWeight: 700,
            }}
          >
            Take into War Room
            <ArrowUpRight size={14} />
          </button>
        </div>
      </div>

      <div
        style={{
          borderRadius: 30,
          border: `1px solid rgba(255,255,255,0.08)`,
          background: "linear-gradient(180deg, rgba(10,13,20,0.8) 0%, rgba(8,10,16,0.94) 100%)",
          boxShadow: "0 28px 80px rgba(0,0,0,0.28)",
          padding: isCompactViewport ? PAD.comfortable : PAD.spacious,
          display: "grid",
          gap: SP.lg,
        }}
      >
        <div style={{ display: "grid", gap: SP.xs }}>
          <SectionEyebrow>{artifact.kind === "vendor" ? "Returned brief" : "Preliminary picture"}</SectionEyebrow>
          <p
            style={{
              margin: 0,
              fontSize: FS.base,
              color: T.textSecondary,
              lineHeight: 1.7,
              maxWidth: 720,
            }}
          >
            This room holds the clean narrative. The thread stays behind it, and War Room stays one move away when you want to challenge the weak edge.
          </p>
        </div>

        <BriefArtifact
          surface="light"
          eyebrow={artifact.eyebrow}
          title={artifact.title}
          framing={artifact.framing}
          sections={artifact.sections}
          provenance={artifact.provenance}
          note={artifact.note}
          actions={
            artifact.kind === "vendor" && onOpenDossier && dossierLabel ? (
              <button
                type="button"
                onClick={onOpenDossier}
                disabled={dossierDisabled || dossierLoading}
                className="helios-focus-ring"
                style={{
                  border: "none",
                  background: dossierDisabled ? "rgba(7,16,26,0.12)" : T.textInverse,
                  color: dossierDisabled ? T.textSecondary : T.text,
                  borderRadius: 999,
                  padding: "11px 16px",
                  cursor: dossierDisabled || dossierLoading ? "default" : "pointer",
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                  opacity: dossierDisabled ? 0.82 : 1,
                }}
              >
                {dossierLoading ? "Opening dossier..." : dossierLabel}
                <ExternalLink size={14} />
              </button>
            ) : null
          }
        />

        {children ? <div style={{ display: "grid", gap: SP.sm }}>{children}</div> : null}
      </div>
    </div>
  );
}
