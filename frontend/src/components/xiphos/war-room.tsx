import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Bell, Eye, Grid3X3, Radar, Search } from "lucide-react";
import type { VettingCase } from "@/lib/types";
import { T, FS, PAD, SP, O, FX } from "@/lib/tokens";
import { AxiomAlerts } from "./axiom-alerts";
import { AxiomSearchPanel } from "./axiom-search-panel";
import { AxiomWatchlist } from "./axiom-watchlist";
import { InlineMessage, SectionEyebrow, StatusPill } from "./shell-primitives";

type RoomMode = "collection" | "watch" | "alerts";
type RoomMenu = "recent" | null;

interface WarRoomProps {
  cases?: VettingCase[];
  onNavigate: (tab: string) => void;
  onOpenCase: (caseId: string) => void;
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

function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

function priorityTone(priority: string): "danger" | "warning" | "info" | "neutral" {
  if (priority === "critical") return "danger";
  if (priority === "high" || priority === "medium") return "warning";
  if (priority === "standard") return "info";
  return "neutral";
}

export function WarRoom({ cases = [], onNavigate, onOpenCase }: WarRoomProps) {
  const [mode, setMode] = useState<RoomMode>("collection");
  const [menu, setMenu] = useState<RoomMenu>(null);
  const [searchResults, setSearchResults] = useState<SearchResultSnapshot | null>(null);
  const [watchEntries, setWatchEntries] = useState<WatchlistSnapshot[]>([]);
  const [alerts, setAlerts] = useState<AlertSnapshot[]>([]);
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
    return "Bring the knot, not the taxonomy. AXIOM will work the public picture, keep the weak residue explicit, and only push what holds.";
  }, [mode, searchResults]);

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
      return `${searchResults.totalQueries} query${searchResults.totalQueries === 1 ? "" : "ies"} • ${searchResults.totalConnectorCalls} connector calls • iteration ${searchResults.iteration}`;
    }
    return "War Room is ready";
  }, [activeWatchEntries.length, alerts.length, criticalAlerts.length, mode, searchResults]);

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
            padding: `${SP.lg}px ${PAD.spacious}`,
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
                    right: 96,
                    width: 320,
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
          className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_320px] lg:grid-cols-[240px_minmax(0,1fr)]"
          style={{
            flex: 1,
            padding: PAD.spacious,
            alignItems: "start",
          }}
        >
          <aside
            style={{
              background: "rgba(255,255,255,0.02)",
              border: `1px solid rgba(255,255,255,0.06)`,
              borderRadius: 24,
              padding: PAD.comfortable,
              display: "grid",
              gap: SP.lg,
            }}
          >
            <div style={{ display: "grid", gap: SP.xs }}>
              <SectionEyebrow>Mission frame</SectionEyebrow>
              <div style={{ fontSize: FS.base, color: T.text, lineHeight: 1.6 }}>
                {mode === "collection"
                  ? "AXIOM leads collection. You step in when the trail gets ambiguous or the judgment needs pressure."
                  : mode === "watch"
                    ? "Warm the right targets between dossier pulls and keep the room ready for the next change."
                    : "Only the movements that alter the case belong in view here."}
              </div>
            </div>

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>Open threads</SectionEyebrow>
              {openThreads.map((thread) => (
                <div
                  key={`${thread.label}-${thread.detail}`}
                  style={{
                    borderRadius: 18,
                    border: `1px solid rgba(255,255,255,0.06)`,
                    background: "rgba(255,255,255,0.02)",
                    padding: PAD.default,
                    display: "grid",
                    gap: SP.xs,
                  }}
                >
                  <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{thread.label}</div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>{thread.detail}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>Recent engagements</SectionEyebrow>
              {recentCases.slice(0, 4).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onOpenCase(item.id)}
                  className="helios-focus-ring"
                  style={{
                    border: `1px solid rgba(255,255,255,0.06)`,
                    background: "transparent",
                    borderRadius: 16,
                    padding: PAD.default,
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{item.name}</div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs }}>
                    {item.created_at || item.date}
                  </div>
                </button>
              ))}
            </div>
          </aside>

          <section
            style={{
              minWidth: 0,
              display: "grid",
              gap: SP.lg,
            }}
          >
            <div
              style={{
                borderRadius: 28,
                border: `1px solid rgba(255,255,255,0.06)`,
                background: "linear-gradient(180deg, rgba(18,24,35,0.92) 0%, rgba(11,15,22,0.94) 100%)",
                padding: PAD.spacious,
                boxShadow: FX.cardHover,
                display: "grid",
                gap: SP.lg,
              }}
            >
              <div style={{ display: "grid", gap: SP.sm }}>
                <SectionEyebrow>AXIOM lead</SectionEyebrow>
                <div style={{ fontSize: FS.xl, fontWeight: 800, letterSpacing: "-0.04em", color: T.text }}>
                  {mode === "collection"
                    ? "Work the brief together."
                    : mode === "watch"
                      ? "Keep the right targets warm."
                      : "Separate drift from noise."}
                </div>
                <div style={{ fontSize: FS.base, color: T.textSecondary, lineHeight: 1.65, maxWidth: 900 }}>
                  {leadStatement}
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
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
              }}
            >
              {mode === "collection" ? (
                <AxiomSearchPanel onResultsChange={(next) => setSearchResults(next)} />
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
            className="xl:block lg:hidden"
            style={{
              background: "rgba(255,255,255,0.02)",
              border: `1px solid rgba(255,255,255,0.06)`,
              borderRadius: 24,
              padding: PAD.comfortable,
              display: "grid",
              gap: SP.lg,
            }}
          >
            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>Evidence wall</SectionEyebrow>
              {mode === "collection" ? (
                searchResults ? (
                  <>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                      <StatusPill tone="info">{searchResults.entities.length} entities</StatusPill>
                      <StatusPill tone="neutral">{searchResults.relationships.length} relationships</StatusPill>
                      <StatusPill tone={searchResults.intelligenceGaps.length > 0 ? "warning" : "neutral"}>
                        {searchResults.intelligenceGaps.length} gaps
                      </StatusPill>
                    </div>
                    <div style={{ display: "grid", gap: SP.sm }}>
                      {searchResults.entities.slice(0, 4).map((entity) => (
                        <div
                          key={`${entity.name}-${entity.type}`}
                          style={{
                            borderRadius: 18,
                            border: `1px solid rgba(255,255,255,0.06)`,
                            background: "rgba(255,255,255,0.02)",
                            padding: PAD.default,
                            display: "grid",
                            gap: SP.xs,
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.sm }}>
                            <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{entity.name}</div>
                            <StatusPill tone="neutral">{formatConfidence(entity.confidence)}</StatusPill>
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.textSecondary }}>{entity.type}</div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <InlineMessage
                    tone="neutral"
                    message="Run a collection pass and the live evidence trail will populate here without leaving the room."
                  />
                )
              ) : mode === "watch" ? (
                activeWatchEntries.length > 0 ? (
                  <div style={{ display: "grid", gap: SP.sm }}>
                    {activeWatchEntries.slice(0, 4).map((entry) => (
                      <div
                        key={entry.id}
                        style={{
                          borderRadius: 18,
                          border: `1px solid rgba(255,255,255,0.06)`,
                          background: "rgba(255,255,255,0.02)",
                          padding: PAD.default,
                          display: "grid",
                          gap: SP.xs,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: SP.sm, alignItems: "center" }}>
                          <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{entry.target}</div>
                          <StatusPill tone={priorityTone(entry.priority)}>{entry.priority}</StatusPill>
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.textSecondary }}>
                          {entry.vehicle ? `Watching ${entry.vehicle}` : "Monitoring vendor drift without a pinned vehicle."}
                        </div>
                        <div style={{ fontSize: FS.xs, color: T.textTertiary }}>
                          {entry.last_scan ? `Last scan ${formatRelativeTime(entry.last_scan)}` : "Waiting for the first scan"}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <InlineMessage
                    tone="neutral"
                    message="No active watch targets yet. Add the vendors or vehicles AXIOM should keep warm between pulls."
                  />
                )
              ) : alerts.length > 0 ? (
                <div style={{ display: "grid", gap: SP.sm }}>
                  {alerts.slice(0, 4).map((alert) => (
                    <div
                      key={alert.id}
                      style={{
                        borderRadius: 18,
                        border: `1px solid rgba(255,255,255,0.06)`,
                        background: "rgba(255,255,255,0.02)",
                        padding: PAD.default,
                        display: "grid",
                        gap: SP.xs,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: SP.sm, alignItems: "center" }}>
                        <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{alert.title}</div>
                        <StatusPill tone={priorityTone(alert.priority)}>{alert.priority}</StatusPill>
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>{alert.details}</div>
                      <div style={{ fontSize: FS.xs, color: T.textTertiary }}>{alert.target} • {formatRelativeTime(alert.timestamp)}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <InlineMessage
                  tone="neutral"
                  message="No drift signals are visible yet. When AXIOM sees movement that changes the picture, it will land here."
                />
              )}
            </div>

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>Priority movement</SectionEyebrow>
              {(criticalAlerts.length > 0 ? criticalAlerts : alerts).length > 0 ? (criticalAlerts.length > 0 ? criticalAlerts : alerts).slice(0, 3).map((alert) => (
                <div
                  key={alert.id}
                  style={{
                    borderRadius: 18,
                    border: `1px solid rgba(255,255,255,0.06)`,
                    background: "rgba(255,255,255,0.02)",
                    padding: PAD.default,
                    display: "grid",
                    gap: SP.xs,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: SP.sm, alignItems: "center" }}>
                    <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{alert.title}</div>
                    <StatusPill tone={priorityTone(alert.priority)}>{alert.priority}</StatusPill>
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>{alert.details}</div>
                  <div style={{ fontSize: FS.xs, color: T.textTertiary }}>{alert.target} • {formatRelativeTime(alert.timestamp)}</div>
                </div>
              )) : (
                <InlineMessage
                  tone="neutral"
                  message={activeWatchEntries.length > 0
                    ? "No material drift is visible right now. The warm targets are holding."
                    : "No material drift is visible yet. Add watch targets to keep the room live between dossier pulls."}
                />
              )}
            </div>

            <div style={{ display: "grid", gap: SP.sm }}>
              <SectionEyebrow>Room tools</SectionEyebrow>
              <button
                type="button"
                onClick={() => onNavigate("graph")}
                className="helios-focus-ring"
                style={{
                  border: `1px solid ${T.border}`,
                  background: "rgba(255,255,255,0.02)",
                  color: T.textSecondary,
                  borderRadius: 18,
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
                Open Graph Intel
              </button>
              <button
                type="button"
                onClick={() => onNavigate("portfolio")}
                className="helios-focus-ring"
                style={{
                  border: `1px solid ${T.border}`,
                  background: "rgba(255,255,255,0.02)",
                  color: T.textSecondary,
                  borderRadius: 18,
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
                Open Workbench
              </button>
            </div>
          </aside>
        </main>
      </div>
    </div>
  );
}
