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
