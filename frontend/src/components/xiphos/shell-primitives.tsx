import React from "react";
import type { LucideIcon } from "lucide-react";
import { AlertCircle, Info, Loader2 } from "lucide-react";
import { T, FS, PAD, SP, O } from "@/lib/tokens";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const TONE_META: Record<Tone, { color: string; border: string; background: string }> = {
  neutral: {
    color: T.textSecondary,
    border: T.border,
    background: T.surface,
  },
  info: {
    color: T.accent,
    border: `${T.accent}${O["30"]}`,
    background: `${T.accent}${O["08"]}`,
  },
  success: {
    color: T.green,
    border: `${T.green}${O["30"]}`,
    background: `${T.green}${O["08"]}`,
  },
  warning: {
    color: T.amber,
    border: `${T.amber}${O["30"]}`,
    background: `${T.amber}${O["08"]}`,
  },
  danger: {
    color: T.red,
    border: `${T.red}${O["30"]}`,
    background: `${T.red}${O["08"]}`,
  },
};

export function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: FS.xs,
        color: T.textTertiary,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
      }}
    >
      {children}
    </div>
  );
}

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  const meta = TONE_META[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: SP.xs,
        padding: PAD.tight,
        borderRadius: 999,
        border: `1px solid ${meta.border}`,
        background: meta.background,
        color: tone === "neutral" ? T.textSecondary : meta.color,
        fontSize: FS.xs,
        fontWeight: 700,
        letterSpacing: "0.02em",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export function BriefArtifact({
  eyebrow,
  title,
  framing,
  sections = [],
  provenance = [],
  note,
  actions,
  surface = "light",
  children,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  framing: React.ReactNode;
  sections?: Array<{
    label: string;
    detail: React.ReactNode;
    tone?: Tone;
  }>;
  provenance?: React.ReactNode[];
  note?: React.ReactNode;
  actions?: React.ReactNode;
  surface?: "light" | "dark";
  children?: React.ReactNode;
}) {
  const isLight = surface === "light";
  const borderColor = isLight ? "rgba(7,16,26,0.10)" : "rgba(255,255,255,0.06)";
  const background = isLight
    ? "linear-gradient(180deg, rgba(246,248,252,0.96) 0%, rgba(231,236,243,0.92) 100%)"
    : "linear-gradient(180deg, rgba(18,24,35,0.9) 0%, rgba(10,14,21,0.94) 100%)";
  const bodyColor = isLight ? T.textInverse : T.text;
  const secondaryColor = isLight ? "rgba(7,16,26,0.72)" : T.textSecondary;
  const tertiaryColor = isLight ? "rgba(7,16,26,0.56)" : T.textTertiary;
  const sectionBackground = isLight ? "rgba(7,16,26,0.05)" : "rgba(255,255,255,0.03)";
  const artifactPadding = "clamp(20px, 3vw, 32px)";
  const artifactGap = "clamp(16px, 2.2vw, 24px)";
  const artifactTitleSize = "clamp(1.35rem, 2.9vw, 1.95rem)";

  return (
    <div
      className="w-full"
      style={{
        borderRadius: 28,
        border: `1px solid ${borderColor}`,
        background,
        color: bodyColor,
        padding: artifactPadding,
        display: "grid",
        gap: artifactGap,
        boxShadow: isLight ? "0 28px 80px rgba(0,0,0,0.28)" : "none",
      }}
    >
      <div style={{ display: "grid", gap: SP.sm }}>
        {eyebrow ? <SectionEyebrow>{eyebrow}</SectionEyebrow> : null}
        <div style={{ fontSize: artifactTitleSize, fontWeight: 800, letterSpacing: "-0.05em", maxWidth: 780 }}>{title}</div>
        <div style={{ fontSize: FS.base, color: secondaryColor, lineHeight: 1.72, maxWidth: 760 }}>{framing}</div>
      </div>

      {sections.length > 0 ? (
        <div className={sections.length > 1 ? "grid gap-3 lg:grid-cols-2" : "grid gap-3"}>
          {sections.map((section) => {
            const toneMeta = section.tone ? TONE_META[section.tone] : null;
            return (
              <div
                key={`${section.label}`}
                style={{
                  borderRadius: 20,
                  border: `1px solid ${toneMeta ? toneMeta.border : borderColor}`,
                  background: toneMeta && !isLight ? toneMeta.background : sectionBackground,
                  padding: "clamp(14px, 2vw, 18px)",
                  display: "grid",
                  gap: SP.xs,
                }}
              >
                <div
                  style={{
                    fontSize: FS.xs,
                    color: toneMeta ? toneMeta.color : tertiaryColor,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  {section.label}
                </div>
                <div style={{ fontSize: FS.sm, color: secondaryColor, lineHeight: 1.6 }}>{section.detail}</div>
              </div>
            );
          })}
        </div>
      ) : null}

      {children ? <div style={{ display: "grid", gap: SP.sm }}>{children}</div> : null}

      {provenance.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
          {provenance.map((item, index) => (
            <span
              key={`artifact-provenance-${index}`}
              style={{
                borderRadius: 999,
                border: `1px solid ${borderColor}`,
                background: sectionBackground,
                color: tertiaryColor,
                padding: "8px 12px",
                fontSize: FS.caption,
                fontWeight: 700,
              }}
            >
              {item}
            </span>
          ))}
        </div>
      ) : null}

      {(note || actions) ? (
        <div
          className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"
          style={{
            gap: SP.md,
          }}
        >
          {note ? (
            <div style={{ fontSize: FS.caption, color: tertiaryColor, lineHeight: 1.6, maxWidth: 620 }}>
              {note}
            </div>
          ) : <div />}
          {actions ? (
            <div className="flex flex-wrap items-center gap-2 sm:justify-end" style={{ gap: SP.sm }}>
              {actions}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function PanelHeader({
  eyebrow,
  title,
  description,
  actions,
  meta,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: SP.lg,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: SP.xs, minWidth: 0, flex: "1 1 320px" }}>
        {eyebrow ? <SectionEyebrow>{eyebrow}</SectionEyebrow> : null}
        <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>{title}</div>
        {description ? (
          <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6, maxWidth: 720 }}>{description}</div>
        ) : null}
        {meta ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm, marginTop: SP.xs }}>
            {meta}
          </div>
        ) : null}
      </div>
      {actions ? (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: SP.sm }}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}

export function ShortcutBadge({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: 22,
        padding: "2px 6px",
        borderRadius: 999,
        border: `1px solid ${T.border}`,
        background: T.surface,
        color: T.textTertiary,
        fontSize: FS.xs,
        fontWeight: 700,
        fontFamily: '"SFMono-Regular", "Consolas", "Liberation Mono", "Menlo", monospace',
      }}
    >
      {children}
    </span>
  );
}

export function MetricTile({
  label,
  value,
  detail,
  tone = "neutral",
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  tone?: Tone;
  icon?: LucideIcon;
}) {
  const meta = TONE_META[tone];
  return (
    <div
      className="glass-card"
      style={{
        padding: PAD.comfortable,
        borderRadius: 16,
        border: `1px solid ${meta.border}`,
        background: tone === "neutral" ? "rgba(17, 17, 24, 0.6)" : meta.background,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.sm }}>
        <div>
          <div style={{ fontSize: FS.xs, color: T.textTertiary, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {label}
          </div>
          <div style={{ fontSize: FS.lg, fontWeight: 800, color: tone === "neutral" ? T.text : meta.color, marginTop: SP.sm }}>
            {value}
          </div>
        </div>
        {Icon ? <Icon size={16} color={tone === "neutral" ? T.textTertiary : meta.color} /> : null}
      </div>
      {detail ? (
        <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.5, marginTop: SP.sm }}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

export function InlineMessage({
  tone = "info",
  title,
  message,
  action,
  icon: Icon = tone === "danger" ? AlertCircle : Info,
}: {
  tone?: Tone;
  title?: React.ReactNode;
  message: React.ReactNode;
  action?: React.ReactNode;
  icon?: LucideIcon;
}) {
  const meta = TONE_META[tone];
  return (
    <div
      className="rounded-xl"
      role={tone === "danger" ? "alert" : "status"}
      aria-live={tone === "danger" ? "assertive" : "polite"}
      style={{
        display: "flex",
        gap: SP.sm,
        alignItems: "flex-start",
        padding: PAD.default,
        border: `1px solid ${meta.border}`,
        background: meta.background,
      }}
    >
      <Icon size={16} color={meta.color} style={{ flexShrink: 0, marginTop: 2 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        {title ? (
          <div style={{ fontSize: FS.sm, fontWeight: 700, color: tone === "neutral" ? T.text : meta.color, marginBottom: 2 }}>
            {title}
          </div>
        ) : null}
        <div style={{ fontSize: FS.sm, color: tone === "neutral" ? T.textSecondary : meta.color, lineHeight: 1.5 }}>
          {message}
        </div>
      </div>
      {action ? <div style={{ flexShrink: 0 }}>{action}</div> : null}
    </div>
  );
}

export function LoadingPanel({ label, detail }: { label: string; detail?: string }) {
  return (
    <div
      className="glass-card animate-fade-in"
      role="status"
      aria-live="polite"
      style={{
        padding: PAD.spacious,
        borderRadius: 18,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: SP.sm,
        minHeight: 160,
      }}
    >
      <Loader2 className="animate-spin" size={20} color={T.accent} />
      <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>{label}</div>
      {detail ? (
        <div style={{ fontSize: FS.sm, color: T.textSecondary, textAlign: "center", maxWidth: 420 }}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

export function EmptyPanel({
  icon: Icon = Info,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: React.ReactNode;
  description: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      className="glass-card animate-fade-in"
      role="note"
      style={{
        padding: PAD.spacious,
        borderRadius: 18,
        border: `1px dashed ${T.borderStrong}`,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: SP.sm,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 12,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: `${T.accent}${O["08"]}`,
          border: `1px solid ${T.accent}${O["20"]}`,
        }}
      >
        <Icon size={16} color={T.accent} />
      </div>
      <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>{title}</div>
      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>{description}</div>
      {action ? <div style={{ marginTop: SP.xs }}>{action}</div> : null}
    </div>
  );
}
