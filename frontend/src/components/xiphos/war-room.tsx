import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Bell, Eye, Grid3X3, Radar, Search } from "lucide-react";
import type { VettingCase } from "@/lib/types";
import { T, FS, PAD, SP, O } from "@/lib/tokens";
import { AxiomAlerts } from "./axiom-alerts";
import { AxiomSearchPanel } from "./axiom-search-panel";
import { AxiomWatchlist } from "./axiom-watchlist";
import { BriefArtifact, InlineMessage, SectionEyebrow, StatusPill } from "./shell-primitives";

type RoomMode = "collection" | "watch" | "alerts";
type RoomMenu = "recent" | null;

interface WarRoomProps {
  cases?: VettingCase[];
  onNavigate: (tab: string) => void;
  onOpenCase: (caseId: string) => void;
  seed?: {
    targetEntity: string;
    vehicleName?: string;
    domainFocus?: string;
    seedLabel?: string;
    autoRun?: boolean;
  } | null;
}

interface SearchResultSnapshot {
  status: string;
  iteration: number;
  entities: Array<{
    name: string;
    type: string;
    confidence: number;
  }>;
  relationships: Array<{
    source: string;
    target: string;
    relationship_type: string;
    confidence: number;
  }>;
  intelligenceGaps: Array<{
    gap_type: string;
    description: string;
    confidence: number;
  }>;
  advisory: Array<{
    opportunity_type: string;
    description: string;
    priority: string;
  }>;
  totalQueries: number;
  totalConnectorCalls: number;
  elapsedMs: number;
}

interface WatchlistSnapshot {
  id: string;
  target: string;
  vehicle?: string;
  priority: "critical" | "high" | "standard" | "low";
  last_scan?: string;
  next_scan_at?: string;
  status: "idle" | "scanning" | "inactive" | "error";
  active: boolean;
  created_at: string;
}

interface AlertSnapshot {
  id: string;
  type: "new_sub" | "departed_sub" | "hiring_surge" | "position_drop" | "activity_change" | "initial_scan";
  priority: "critical" | "high" | "medium" | "low";
  target: string;
  title: string;
  details: string;
  timestamp: string;
}

const ROOM_MODES: Array<{
  id: RoomMode;
  label: string;
  icon: typeof Search;
}> = [
  { id: "collection", label: "Work the brief", icon: Search },
  { id: "watch", label: "Keep warm", icon: Eye },
  { id: "alerts", label: "Drift", icon: Bell },
];

function sortRecentCases(cases: VettingCase[]) {
  return [...cases].sort((a, b) => {
    const aTs = Date.parse(a.created_at || a.date || "");
    const bTs = Date.parse(b.created_at || b.date || "");
    return (Number.isFinite(bTs) ? bTs : 0) - (Number.isFinite(aTs) ? aTs : 0);
  });
}

function formatRelativeTime(value?: string) {
  if (!value) return "No recent scan";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function priorityTone(priority: string): "danger" | "warning" | "info" | "neutral" {
  if (priority === "critical") return "danger";
  if (priority === "high" || priority === "medium") return "warning";
  if (priority === "standard") return "info";
  return "neutral";
}

export function WarRoom({ cases = [], onNavigate, onOpenCase, seed = null }: WarRoomProps) {
  const [mode, setMode] = useState<RoomMode>("collection");
  const [menu, setMenu] = useState<RoomMenu>(null);
  const [searchResults, setSearchResults] = useState<SearchResultSnapshot | null>(null);
  const [watchEntries, setWatchEntries] = useState<WatchlistSnapshot[]>([]);
  const [alerts, setAlerts] = useState<AlertSnapshot[]>([]);
  const [isCompactViewport, setIsCompactViewport] = useState(() => window.innerWidth < 1024);
  const menuRef = useRef<HTMLDivElement>(null);

  const recentCases = useMemo(() => sortRecentCases(cases).slice(0, 6), [cases]);
  const activeWatchEntries = useMemo(() => watchEntries.filter((entry) => entry.active), [watchEntries]);
  const criticalAlerts = useMemo(() => alerts.filter((alert) => alert.priority === "critical" || alert.priority === "high"), [alerts]);

  useEffect(() => {
    if (!menu) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenu(null);
      }
    };
    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, [menu]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const handleChange = (event: MediaQueryListEvent) => setIsCompactViewport(event.matches);
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  const leadStatement = useMemo(() => {
    if (mode === "watch") {
      return "AXIOM is keeping live targets warm between dossier pulls and only surfaces drift that changes the picture.";
    }
    if (mode === "alerts") {
      return "This room is for material changes, not noise. If it is visible here, it should alter the working judgment.";
    }
    if (searchResults) {
      return `AXIOM surfaced ${searchResults.entities.length} entities, ${searchResults.relationships.length} relationships, and ${searchResults.intelligenceGaps.length} open gaps from the current brief.`;
    }
    if (seed?.targetEntity) {
      return `AXIOM picked up ${seed.seedLabel || seed.targetEntity} from Front Porch and is working the public picture from there.`;
    }
    return "Bring the knot, not the taxonomy. AXIOM will work the public picture, keep the weak residue explicit, and only push what holds.";
  }, [mode, searchResults, seed]);

  const roomStatus = useMemo(() => {
    if (mode === "watch") {
      return activeWatchEntries.length > 0
        ? `${activeWatchEntries.length} warm target${activeWatchEntries.length === 1 ? "" : "s"} under watch`
        : "No active watch targets yet";
    }
    if (mode === "alerts") {
      return criticalAlerts.length > 0
        ? `${criticalAlerts.length} material drift signal${criticalAlerts.length === 1 ? "" : "s"} visible`
        : `${alerts.length} alert${alerts.length === 1 ? "" : "s"} in the room`;
    }
    if (searchResults) {
      return `${searchResults.totalQueries} queries • ${searchResults.intelligenceGaps.length} open gaps`;
    }
    if (seed?.targetEntity) {
      return "Front Porch brief warming";
    }
    return "Awaiting a live brief";
  }, [activeWatchEntries.length, alerts.length, criticalAlerts.length, mode, searchResults, seed]);

  const currentFrame = useMemo(() => {
    if (mode === "watch") {
      return "Keep the right targets warm between dossier pulls and only interrupt when the picture actually moves.";
    }
    if (mode === "alerts") {
      return "This room is only for movement that should alter the working judgment.";
    }
    return "AXIOM leads the collection. You step in when the trail gets ambiguous, the picture feels thin, or the judgment needs pressure.";
  }, [mode]);

  const roomExchange = useMemo(() => {
    if (mode === "alerts" && alerts.length > 0) {
      const leadAlert = (criticalAlerts.length > 0 ? criticalAlerts : alerts)[0];
      return {
        eyebrow: "AXIOM exchange",
        title: "A material signal crossed the line.",
        lead: `${leadAlert.title} is now active around ${leadAlert.target}. ${leadAlert.details}`,
        follow: "Challenge it if the claim is thin. If it holds, redirect the room around the thread that most changes the call.",
      };
    }

    if (mode === "watch") {
      if (activeWatchEntries.length > 0) {
        const leadEntry = activeWatchEntries[0];
        return {
          eyebrow: "AXIOM exchange",
          title: "The room is keeping the right things warm.",
          lead: leadEntry.vehicle
            ? `${leadEntry.target} is being held against ${leadEntry.vehicle}. I’ll surface movement only when it changes the picture.`
            : `${leadEntry.target} is being held warm at the vendor level until the vehicle context sharpens.`,
          follow: "Add a vendor or vehicle when you want AXIOM watching the edge between dossier pulls.",
        };
      }
      return {
        eyebrow: "AXIOM exchange",
        title: "Nothing is warm yet.",
        lead: "Give me the vendor or vehicle that needs quiet persistence between pulls, and I’ll keep the drift below the line until it matters.",
        follow: "War Room should stay quiet until a warm target or material signal earns attention.",
      };
    }

    if (searchResults) {
      const leadGap = searchResults.intelligenceGaps[0];
      const leadAdvisory = searchResults.advisory[0];
      return {
        eyebrow: "AXIOM exchange",
        title: "The first public picture is in hand.",
        lead: leadGap
          ? `The clean record starts to thin at ${leadGap.description}. I’m keeping that weakness explicit instead of bluffing past it.`
          : "The first pass is comparatively clean. Nothing in the public trail is strong enough to force a hard turn yet.",
        follow: leadAdvisory
          ? leadAdvisory.description
          : "If you want, I can keep pressing the weakest thread or move into Graph Intel when structure matters more than the surface story.",
      };
    }

    if (seed?.targetEntity) {
      return {
        eyebrow: "AXIOM exchange",
        title: "The Front Porch brief is now live in the room.",
        lead: seed.vehicleName
          ? `I picked up ${seed.seedLabel || seed.targetEntity} with ${seed.vehicleName} already in frame. I’m working the thread from there.`
          : `I picked up ${seed.seedLabel || seed.targetEntity} from Front Porch and I’m working the first public picture from there.`,
        follow: seed.domainFocus
          ? `I’m weighting ${seed.domainFocus} first unless you redirect me.`
          : "Redirect me only if the first thread is wrong. Otherwise I’ll work the full picture from the current brief.",
      };
    }

    return {
      eyebrow: "AXIOM exchange",
      title: "Bring me the knot, not the taxonomy.",
      lead: "Start with the entity, vehicle, incumbent, teammate, or weak point that still feels unresolved. I’ll work outward from there and keep the dark space explicit.",
      follow: "Reply with the redirect, the harder question, or the thread you want pressed first.",
    };
  }, [activeWatchEntries, alerts, criticalAlerts, mode, searchResults, seed]);

  const openThreads = useMemo(() => {
    if (mode === "watch") {
      return activeWatchEntries.slice(0, 4).map((entry) => ({
        label: entry.target,
        detail: entry.vehicle ? `Watching ${entry.vehicle}` : `Next scan ${formatRelativeTime(entry.next_scan_at)}`,
      }));
    }
    if (mode === "alerts") {
      return alerts.slice(0, 4).map((alert) => ({
        label: alert.title,
        detail: `${alert.target} • ${formatRelativeTime(alert.timestamp)}`,
      }));
    }
    if (searchResults?.intelligenceGaps.length) {
      return searchResults.intelligenceGaps.slice(0, 4).map((gap) => ({
        label: gap.gap_type.replace(/_/g, " "),
        detail: gap.description,
      }));
    }
    return [
      { label: "Incumbent lineage", detail: "Trace the follow-on path and where continuity likely holds." },
      { label: "Teammate network", detail: "Separate visible partners from the dark-space sub network." },
      { label: "Ownership path", detail: "Push until the control story either holds or breaks." },
      { label: "Gap pressure", detail: "Keep the unknowns explicit and prioritize the one that changes the call." },
    ];
  }, [activeWatchEntries, alerts, mode, searchResults]);

  const workingArtifact = useMemo(() => {
    if (mode === "collection" && searchResults) {
      return {
        eyebrow: "Working artifact",
        title: "Initial collection picture",
        framing: `AXIOM pulled the first public picture from the brief and kept the weak residue separate from what currently holds.`,
        sections: [
          {
            label: "What holds",
            detail: searchResults.entities.length > 0
              ? `The strongest visible entities are ${searchResults.entities.slice(0, 3).map((entity) => entity.name).join(", ")}.`
              : "The first pass did not surface enough settled entities to overstate the picture yet.",
          },
          {
            label: "Still dark",
            detail: searchResults.intelligenceGaps.length > 0
              ? searchResults.intelligenceGaps[0].description
              : "No material public gap is dominant yet, which means the first pass is comparatively clean.",
            tone: searchResults.intelligenceGaps.length > 0 ? "warning" : "neutral",
          },
          {
            label: "Next push",
            detail: searchResults.advisory.length > 0
              ? searchResults.advisory[0].description
              : "Move into Graph Intel only if the path structure matters more than the headline picture.",
          },
        ] as Array<{ label: string; detail: string; tone?: "neutral" | "info" | "success" | "warning" | "danger" }>,
        provenance: [
          `${searchResults.totalQueries} queries`,
          `${searchResults.totalConnectorCalls} connector calls`,
          `Iteration ${searchResults.iteration}`,
        ],
      };
    }

    if (mode === "watch" && activeWatchEntries.length > 0) {
      const leadEntry = activeWatchEntries[0];
      return {
        eyebrow: "Working artifact",
        title: "Warm target posture",
        framing: "AXIOM is keeping the right things warm between dossier pulls and only surfacing movement that should change the call.",
        sections: [
          {
            label: "What is warm",
            detail: activeWatchEntries.slice(0, 3).map((entry) => entry.target).join(", "),
          },
          {
            label: "Where to watch",
            detail: leadEntry.vehicle
              ? `${leadEntry.target} is pinned to ${leadEntry.vehicle}, which keeps the room oriented around the live vehicle picture.`
              : `${leadEntry.target} is being watched as a vendor-level target until the vehicle context sharpens.`,
          },
          {
            label: "Next scan",
            detail: leadEntry.next_scan_at
              ? `Next scan ${formatRelativeTime(leadEntry.next_scan_at)}.`
              : leadEntry.last_scan
                ? `Last scan ${formatRelativeTime(leadEntry.last_scan)}.`
                : "Waiting for the first scan cycle.",
          },
        ] as Array<{ label: string; detail: string; tone?: "neutral" | "info" | "success" | "warning" | "danger" }>,
        provenance: [
          `${activeWatchEntries.length} active targets`,
          `${criticalAlerts.length} critical signals`,
        ],
      };
    }

    if (mode === "alerts" && alerts.length > 0) {
      const leadAlert = (criticalAlerts.length > 0 ? criticalAlerts : alerts)[0];
      return {
        eyebrow: "Working artifact",
        title: "Material drift picture",
        framing: "This room only shows movement that should change the working judgment. Everything else stays below the line.",
        sections: [
          {
            label: "What changed",
            detail: leadAlert.details,
            tone: priorityTone(leadAlert.priority),
          },
          {
            label: "Why it matters",
            detail: `${leadAlert.target} is now carrying a ${leadAlert.priority} signal through ${leadAlert.title.toLowerCase()}.`,
          },
          {
            label: "Best next move",
            detail: "Challenge the new claim if it is thin, or redirect AXIOM into the thread that most changes the case.",
          },
        ] as Array<{ label: string; detail: string; tone?: "neutral" | "info" | "success" | "warning" | "danger" }>,
        provenance: [
          `${alerts.length} total alerts`,
          `${criticalAlerts.length} material signals`,
          `${formatRelativeTime(leadAlert.timestamp)}`,
        ],
      };
    }

    return null;
  }, [activeWatchEntries, alerts, criticalAlerts, mode, searchResults]);

  const movementFeed = useMemo(() => {
    if (mode === "alerts") {
      return (criticalAlerts.length > 0 ? criticalAlerts : alerts).slice(0, 3).map((alert) => ({
        key: alert.id,
        title: alert.title,
        detail: alert.details,
        meta: `${alert.target} • ${formatRelativeTime(alert.timestamp)}`,
        tone: priorityTone(alert.priority),
      }));
    }

    if (mode === "watch") {
      return activeWatchEntries.slice(0, 3).map((entry) => ({
        key: entry.id,
        title: entry.target,
        detail: entry.vehicle ? `Watching ${entry.vehicle}` : "Monitoring vendor drift without a pinned vehicle.",
        meta: entry.last_scan ? `Last scan ${formatRelativeTime(entry.last_scan)}` : "Waiting for the first scan",
        tone: priorityTone(entry.priority),
      }));
    }

    if (searchResults?.intelligenceGaps.length) {
      return searchResults.intelligenceGaps.slice(0, 3).map((gap) => ({
        key: `${gap.gap_type}-${gap.description}`,
        title: gap.gap_type.replace(/_/g, " "),
        detail: gap.description,
        meta: `Confidence ${Math.round(gap.confidence * 100)}%`,
        tone: "warning" as const,
      }));
    }

    return [];
  }, [activeWatchEntries, alerts, criticalAlerts, mode, searchResults]);

  const headerBackground = "linear-gradient(180deg, rgba(10,13,19,0.98) 0%, rgba(7,9,14,0.98) 100%)";

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "radial-gradient(circle at 50% 0%, rgba(14,165,233,0.08), transparent 28%), linear-gradient(180deg, #05070b 0%, #090d13 100%)",
        color: T.text,
        overflow: "auto",
      }}
    >
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          ref={menuRef}
          style={{
            position: "sticky",
            top: 0,
            zIndex: 20,
            padding: `${SP.lg}px ${isCompactViewport ? SP.lg : PAD.spacious}`,
            borderBottom: `1px solid rgba(255,255,255,0.06)`,
            background: headerBackground,
            backdropFilter: "blur(18px)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.lg, flexWrap: "wrap", position: "relative" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: SP.xs, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap" }}>
                <div style={{ fontSize: FS.lg, fontWeight: 800, letterSpacing: "-0.04em" }}>Helios</div>
                <StatusPill tone="info">War Room</StatusPill>
                {seed?.targetEntity ? <StatusPill tone="neutral">Brief carried from Front Porch</StatusPill> : null}
              </div>
              <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6, maxWidth: 760 }}>
                {leadStatement}
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap", position: "relative" }}>
              <StatusPill tone={mode === "alerts" && criticalAlerts.length > 0 ? "warning" : "neutral"}>
                {roomStatus}
              </StatusPill>
              <button
                type="button"
                onClick={() => onNavigate("helios")}
                className="helios-focus-ring"
                aria-label="Return to Front Porch"
                style={{
                  border: `1px solid ${T.border}`,
                  background: "transparent",
                  color: T.textSecondary,
                  borderRadius: 999,
                  padding: PAD.default,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                  cursor: "pointer",
                }}
              >
                <ArrowLeft size={14} />
                Front Porch
              </button>
              <button
                type="button"
                onClick={() => setMenu((current) => current === "recent" ? null : "recent")}
                className="helios-focus-ring"
                aria-label="Open recent engagements"
                style={{
                  border: `1px solid ${T.border}`,
                  background: "transparent",
                  color: T.textSecondary,
                  borderRadius: 999,
                  padding: PAD.default,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Recent
              </button>
              <button
                type="button"
                onClick={() => onNavigate("graph")}
                className="helios-focus-ring"
                aria-label="Open Graph Intel"
                style={{
                  border: `1px solid ${T.accent}${O["20"]}`,
                  background: `${T.accent}${O["08"]}`,
                  color: T.text,
                  borderRadius: 999,
                  padding: PAD.default,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                  cursor: "pointer",
                }}
              >
                Graph Intel
                <ArrowUpRight size={14} />
              </button>

              {menu === "recent" ? (
                <div
                  style={{
                    position: "absolute",
                    top: "calc(100% + 10px)",
                    right: 0,
                    width: isCompactViewport ? "min(calc(100vw - 32px), 360px)" : 320,
                    borderRadius: 18,
                    border: `1px solid ${T.borderStrong}`,
                    background: T.surfaceElevated,
                    boxShadow: "0 18px 48px rgba(0,0,0,0.38)",
                    padding: PAD.default,
                    display: "flex",
                    flexDirection: "column",
                    gap: SP.xs,
                  }}
                >
                  <SectionEyebrow>Recent engagements</SectionEyebrow>
                  {recentCases.length > 0 ? recentCases.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setMenu(null);
                        onOpenCase(item.id);
                      }}
                      className="helios-focus-ring"
                      style={{
                        border: `1px solid ${T.border}`,
                        background: T.surface,
                        borderRadius: 14,
                        padding: PAD.default,
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                    >
                      <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{item.name}</div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs }}>
                        {item.created_at || item.date}
                      </div>
                    </button>
                  )) : (
                    <InlineMessage tone="neutral" message="No recent engagements yet. The first one starts in Front Porch." />
                  )}
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <main
          className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)_320px] lg:grid-cols-[220px_minmax(0,1fr)]"
          style={{
            flex: 1,
            padding: isCompactViewport ? SP.lg : PAD.spacious,
            alignItems: "start",
          }}
        >
          <aside
            className="order-3 lg:order-1"
            style={{
              paddingTop: SP.md,
              display: "grid",
              gap: SP.lg,
            }}
          >
            <div style={{ display: "grid", gap: SP.xs }}>
              <SectionEyebrow>Current frame</SectionEyebrow>
              <div style={{ fontSize: FS.base, color: T.text, lineHeight: 1.6 }}>
                {currentFrame}
              </div>
            </div>

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>{mode === "alerts" ? "What moved" : "Pressure threads"}</SectionEyebrow>
              {openThreads.map((thread) => (
                <div
                  key={`${thread.label}-${thread.detail}`}
                  style={{
                    padding: `0 0 0 ${SP.md}px`,
                    borderLeft: `2px solid rgba(255,255,255,0.12)`,
                    display: "grid",
                    gap: 6,
                  }}
                >
                  <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{thread.label}</div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>{thread.detail}</div>
                </div>
              ))}
            </div>
          </aside>

          <section
            className="order-1"
            style={{
              minWidth: 0,
              display: "grid",
              gap: SP.lg,
            }}
          >
            <div
              style={{
                borderRadius: 30,
                border: `1px solid rgba(255,255,255,0.06)`,
                background: "linear-gradient(180deg, rgba(17,21,30,0.92) 0%, rgba(10,13,20,0.96) 100%)",
                padding: isCompactViewport ? PAD.comfortable : PAD.spacious,
                display: "grid",
                gap: SP.lg,
                position: isCompactViewport ? "relative" : "sticky",
                top: isCompactViewport ? undefined : PAD.spacious,
                zIndex: isCompactViewport ? undefined : 6,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: SP.md, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ display: "grid", gap: SP.sm, minWidth: 0, flex: "1 1 420px" }}>
                  <SectionEyebrow>{roomExchange.eyebrow}</SectionEyebrow>
                  <div style={{ fontSize: FS.xl, fontWeight: 800, letterSpacing: "-0.04em", color: T.text }}>
                    {roomExchange.title}
                  </div>
                </div>
                <StatusPill tone={mode === "alerts" && criticalAlerts.length > 0 ? "warning" : "neutral"}>
                  {roomStatus}
                </StatusPill>
              </div>

              <div
                style={{
                  borderRadius: 24,
                  border: `1px solid rgba(255,255,255,0.06)`,
                  background: "rgba(255,255,255,0.025)",
                  padding: PAD.comfortable,
                  display: "grid",
                  gap: SP.sm,
                }}
              >
                <div style={{ fontSize: FS.xs, color: T.textTertiary, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                  AXIOM
                </div>
                <div style={{ fontSize: FS.md, color: T.text, lineHeight: 1.75, maxWidth: 920 }}>
                  {roomExchange.lead}
                </div>
                <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.65, maxWidth: 920 }}>
                  {roomExchange.follow}
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm, alignItems: "center" }}>
                {ROOM_MODES.map((item) => {
                  const Icon = item.icon;
                  const active = item.id === mode;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setMode(item.id)}
                      className="helios-focus-ring"
                      aria-pressed={active}
                      style={{
                        border: `1px solid ${active ? `${T.accent}${O["20"]}` : T.border}`,
                        background: active ? `${T.accent}${O["08"]}` : "rgba(255,255,255,0.02)",
                        color: active ? T.text : T.textSecondary,
                        borderRadius: 999,
                        padding: PAD.default,
                        fontSize: FS.sm,
                        fontWeight: 700,
                        cursor: "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: SP.xs,
                      }}
                    >
                      <Icon size={14} color={active ? T.accent : T.textTertiary} />
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div
              style={{
                borderRadius: 28,
                border: `1px solid rgba(255,255,255,0.06)`,
                background: "rgba(9,12,18,0.92)",
                overflow: "hidden",
                minHeight: 420,
              }}
            >
              {mode === "collection" ? (
                <AxiomSearchPanel seed={seed} onResultsChange={(next) => setSearchResults(next)} />
              ) : null}
              {mode === "watch" ? (
                <AxiomWatchlist onEntriesChange={(next) => setWatchEntries(next)} />
              ) : null}
              {mode === "alerts" ? (
                <AxiomAlerts onAlertsChange={(next) => setAlerts(next)} />
              ) : null}
            </div>
          </section>

          <aside
            className="order-2 xl:order-3"
            style={{
              paddingTop: SP.md,
              gap: SP.lg,
              display: "grid",
            }}
          >
            {workingArtifact ? (
              <BriefArtifact
                surface="dark"
                eyebrow={workingArtifact.eyebrow}
                title={workingArtifact.title}
                framing={workingArtifact.framing}
                sections={workingArtifact.sections}
                provenance={workingArtifact.provenance}
                note="Stay in the room if the next move is to challenge, redirect, or keep pressure on the weak point. Leave only when you need the wider map."
                actions={
                  <>
                    <button
                      type="button"
                      onClick={() => onNavigate("graph")}
                      className="helios-focus-ring"
                      style={{
                        border: `1px solid ${T.border}`,
                        background: "rgba(255,255,255,0.02)",
                        color: T.textSecondary,
                        borderRadius: 999,
                        padding: PAD.default,
                        fontSize: FS.sm,
                        fontWeight: 700,
                        cursor: "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: SP.sm,
                      }}
                    >
                      <Grid3X3 size={14} />
                      Graph Intel
                    </button>
                    <button
                      type="button"
                      onClick={() => onNavigate("portfolio")}
                      className="helios-focus-ring"
                      style={{
                        border: `1px solid ${T.border}`,
                        background: "rgba(255,255,255,0.02)",
                        color: T.textSecondary,
                        borderRadius: 999,
                        padding: PAD.default,
                        fontSize: FS.sm,
                        fontWeight: 700,
                        cursor: "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: SP.sm,
                      }}
                    >
                      <Radar size={14} />
                      Workbench
                    </button>
                  </>
                }
              />
            ) : (
              <InlineMessage
                tone="neutral"
                message={mode === "collection"
                  ? "Run a collection pass and AXIOM will turn the first picture into a readable working artifact here."
                  : mode === "watch"
                    ? "No active watch targets yet. Add the vendors or vehicles AXIOM should keep warm between pulls."
                    : "No drift signals are visible yet. When movement changes the picture, it will land here."}
              />
            )}

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>{mode === "alerts" ? "What moved" : mode === "watch" ? "Warm signals" : "Open pressure"}</SectionEyebrow>
              {movementFeed.length > 0 ? movementFeed.map((item) => (
                <div
                  key={item.key}
                  style={{
                    padding: `0 0 0 ${SP.md}px`,
                    borderLeft: `2px solid rgba(255,255,255,0.12)`,
                    display: "grid",
                    gap: 6,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: SP.sm, alignItems: "center" }}>
                    <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{item.title}</div>
                    <StatusPill tone={item.tone}>{item.tone}</StatusPill>
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>{item.detail}</div>
                  <div style={{ fontSize: FS.xs, color: T.textTertiary }}>{item.meta}</div>
                </div>
              )) : (
                <InlineMessage
                  tone="neutral"
                  message={activeWatchEntries.length > 0
                    ? "No material drift is visible right now. The warm targets are holding."
                    : "The room is quiet because nothing has moved enough to justify attention."}
                />
              )}
            </div>
          </aside>
        </main>
      </div>
    </div>
  );
}
