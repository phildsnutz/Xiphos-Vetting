import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Grid3X3, LayoutDashboard, Shield, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { T, FS, O, PAD, SP, displayName, parseTier, tierBand } from "@/lib/tokens";
import { fetchMonitorChanges, fetchPortfolioAnomalies } from "@/lib/api";
import type { MonitorChangeEntry } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { emit } from "@/lib/telemetry";
import { EmptyPanel, InlineMessage, MetricTile, SectionEyebrow } from "./shell-primitives";
import { portfolioDisposition, workflowLaneForCase, WORKFLOW_LANE_META } from "./portfolio-utils";
import type { WorkflowLane } from "./portfolio-utils";

interface PortfolioScreenProps {
  allCases: VettingCase[];
  cases: VettingCase[];
  query?: string;
  onSelect: (c: VettingCase) => void;
  globalLane?: WorkflowLane;
  onGlobalLaneChange?: (lane: WorkflowLane) => void;
  onNavigate?: (tab: string) => void;
  laneSummary?: {
    lane: WorkflowLane;
    label: string;
    shortLabel: string;
    description: string;
    activeCount: number;
    reviewCount: number;
    blockedCount: number;
    watchCount: number;
    summary: string;
    topCaseName: string | null;
  };
}

type SortBy = "score" | "name" | "date";
type LaneFilter = "all" | "counterparty" | "cyber" | "export";

function caseTimestamp(c: VettingCase): number {
  const raw = c.created_at || c.date;
  if (!raw) return 0;
  const parsed = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
  return Number.isFinite(parsed) ? parsed : 0;
}

function relativeCaseTime(c: VettingCase): string {
  const ts = caseTimestamp(c);
  if (!ts) return c.date || "";
  const diffMs = Date.now() - ts;
  const diffMinutes = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);
  if (diffMinutes < 1) return "Now";
  if (diffMinutes < 60) return `${diffMinutes}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function operatorPriorityScore(c: VettingCase): number {
  const disposition = portfolioDisposition(c);
  const base =
    disposition === "blocked"
      ? 400
      : disposition === "review"
        ? 260
        : disposition === "qualified"
          ? 140
          : 80;
  const stopWeight = (c.cal?.stops?.length ?? 0) * 20;
  const flagWeight = (c.cal?.flags?.length ?? 0) * 10;
  const recencyBoost = Math.max(0, 72 - Math.floor((Date.now() - caseTimestamp(c)) / 3_600_000));
  return base + stopWeight + flagWeight + recencyBoost;
}

function operatorSummary(c: VettingCase): string {
  const stop = c.cal?.stops?.[0]?.x?.trim();
  if (stop) return stop;
  const flag = c.cal?.flags?.[0]?.x?.trim();
  if (flag) return flag;
  const recommendation = c.cal?.recommendation?.trim();
  if (recommendation) return recommendation;
  const regulatory = c.cal?.regulatoryStatus?.trim();
  if (regulatory) return regulatory;
  const context = c.cal?.sensitivityContext?.trim();
  if (context) return context;
  const finding = c.cal?.finds?.[0]?.trim();
  if (finding) return finding;
  return c.program || c.profile || "Ready for analyst review.";
}

function averageRisk(cases: VettingCase[]): number {
  if (cases.length === 0) return 0;
  return Math.round(
    cases.reduce((sum, c) => {
      const band = tierBand(parseTier(c.cal?.tier || "green"));
      const riskMap: Record<string, number> = {
        critical: 95,
        elevated: 72,
        conditional: 48,
        clear: 18,
      };
      return sum + (riskMap[band] || 0);
    }, 0) / cases.length,
  );
}

function dispositionTone(disposition: ReturnType<typeof portfolioDisposition>) {
  if (disposition === "blocked") {
    return { label: "Blocked", color: T.red, border: `${T.red}${O["30"]}`, background: T.redBg };
  }
  if (disposition === "review") {
    return { label: "Review", color: T.amber, border: `${T.amber}${O["30"]}`, background: T.amberBg };
  }
  if (disposition === "qualified") {
    return { label: "Watch", color: T.accent, border: `${T.accent}${O["30"]}`, background: T.accentSoft };
  }
  return { label: "Clear", color: T.green, border: `${T.green}${O["30"]}`, background: T.greenBg };
}

function bandTone(c: VettingCase) {
  const band = tierBand(parseTier(c.cal?.tier || "green"));
  if (band === "critical") {
    return { label: "Critical", color: T.red, background: T.redBg, border: `${T.red}${O["30"]}` };
  }
  if (band === "elevated") {
    return { label: "Elevated", color: T.amber, background: T.amberBg, border: `${T.amber}${O["30"]}` };
  }
  if (band === "conditional") {
    return { label: "Conditional", color: T.accent, background: T.accentSoft, border: `${T.accent}${O["30"]}` };
  }
  return { label: "Clear", color: T.green, background: T.greenBg, border: `${T.green}${O["30"]}` };
}

export function PortfolioScreen({
  allCases,
  cases,
  query,
  onSelect,
  globalLane,
  onNavigate,
  laneSummary,
}: PortfolioScreenProps) {
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [anomalies, setAnomalies] = useState<Record<string, unknown>[]>([]);
  const [monitorChanges, setMonitorChanges] = useState<MonitorChangeEntry[]>([]);
  const laneFilter: LaneFilter = globalLane ?? "all";

  useEffect(() => {
    fetchPortfolioAnomalies(20).then((result) => setAnomalies(result.anomalies ?? [])).catch(() => undefined);
    fetchMonitorChanges(20).then((result) => setMonitorChanges(result.changes ?? [])).catch(() => undefined);
  }, []);

  const activeLaneMeta = laneFilter === "all" ? null : WORKFLOW_LANE_META[laneFilter];
  const blockedCases = useMemo(() => cases.filter((c) => portfolioDisposition(c) === "blocked"), [cases]);
  const reviewCases = useMemo(() => cases.filter((c) => portfolioDisposition(c) === "review"), [cases]);
  const watchCases = useMemo(() => cases.filter((c) => portfolioDisposition(c) === "qualified"), [cases]);
  const priorityCases = useMemo(
    () => [...cases].sort((a, b) => operatorPriorityScore(b) - operatorPriorityScore(a)).slice(0, 5),
    [cases],
  );
  const sortedCases = useMemo(() => {
    const scopedCases = laneFilter === "all"
      ? cases
      : cases.filter((c) => workflowLaneForCase(c) === laneFilter);
    const sorted = [...scopedCases];
    if (sortBy === "score") {
      sorted.sort((a, b) => operatorPriorityScore(b) - operatorPriorityScore(a));
    } else if (sortBy === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else {
      sorted.sort((a, b) => caseTimestamp(b) - caseTimestamp(a));
    }
    return sorted;
  }, [cases, laneFilter, sortBy]);

  const topCase = priorityCases[0] ?? null;
  const queueSummary = laneSummary?.summary
    || activeLaneMeta?.description
    || "Review the cases that need a disposition next, clear blockers, and move the lane forward.";

  return (
    <div
      style={{
        minHeight: "100%",
        display: "flex",
        flexDirection: "column",
        gap: SP.lg,
        padding: PAD.default,
      }}
    >
      <section
        className="glass-card animate-slide-up"
        style={{
          padding: PAD.spacious,
          borderRadius: 20,
          display: "flex",
          flexDirection: "column",
          gap: SP.lg,
        }}
      >
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div style={{ minWidth: 0, flex: 1, maxWidth: 840 }}>
            <SectionEyebrow>Operator workbench</SectionEyebrow>
            <div style={{ fontSize: FS.xl, fontWeight: 800, letterSpacing: "-0.04em", color: T.text, marginTop: SP.sm }}>
              {activeLaneMeta ? `${activeLaneMeta.shortLabel} queue` : "Work the queue, not the chrome."}
            </div>
            <div style={{ fontSize: FS.base, color: T.textSecondary, lineHeight: 1.65, marginTop: SP.sm }}>
              {queueSummary}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => topCase && onSelect(topCase)}
              disabled={!topCase}
              className="helios-focus-ring"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                border: "none",
                borderRadius: 999,
                padding: "10px 14px",
                background: topCase ? T.accent : T.border,
                color: topCase ? "#04101f" : T.textTertiary,
                fontSize: FS.sm,
                fontWeight: 800,
                cursor: topCase ? "pointer" : "default",
              }}
            >
              Open top priority
              <ArrowRight size={14} />
            </button>
            <button
              type="button"
              onClick={() => onNavigate?.("helios")}
              className="helios-focus-ring"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                border: `1px solid ${T.border}`,
                borderRadius: 999,
                padding: "10px 14px",
                background: T.surface,
                color: T.text,
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <Shield size={14} />
              New intake
            </button>
            <button
              type="button"
              onClick={() => onNavigate?.("graph")}
              className="helios-focus-ring"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                border: `1px solid ${T.border}`,
                borderRadius: 999,
                padding: "10px 14px",
                background: T.surface,
                color: T.text,
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <Grid3X3 size={14} />
              Graph intel
            </button>
            <button
              type="button"
              onClick={() => onNavigate?.("dashboard")}
              className="helios-focus-ring"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                border: `1px solid ${T.border}`,
                borderRadius: 999,
                padding: "10px 14px",
                background: T.surface,
                color: T.text,
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <LayoutDashboard size={14} />
              Overview
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <MetricTile label="Cases in scope" value={cases.length} detail={laneSummary?.label || "All active work in this queue."} />
          <MetricTile label="Blocked" value={blockedCases.length} detail={topCase ? `Highest priority: ${displayName(topCase.name)}` : "No blocked cases in scope."} tone={blockedCases.length > 0 ? "danger" : "neutral"} />
          <MetricTile label="Review" value={reviewCases.length} detail="Needs analyst judgement or additional evidence." tone={reviewCases.length > 0 ? "warning" : "neutral"} />
          <MetricTile label="Average risk" value={`${averageRisk(cases)}%`} detail={`${watchCases.length} cases remain on watch.`} tone={watchCases.length > 0 ? "info" : "neutral"} />
        </div>
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4">
        <div
          className="glass-card"
          style={{
            padding: PAD.comfortable,
            borderRadius: 18,
            display: "flex",
            flexDirection: "column",
            gap: SP.sm,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.sm }}>
            <div>
              <SectionEyebrow>Priority queue</SectionEyebrow>
              <div style={{ fontSize: FS.base, fontWeight: 800, color: T.text, marginTop: SP.xs }}>
                Start where the lane breaks first.
              </div>
            </div>
            <div style={{ fontSize: FS.xs, color: T.textTertiary }}>
              {priorityCases.length} surfaced
            </div>
          </div>

          {priorityCases.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
              {priorityCases.map((item) => {
                const disposition = dispositionTone(portfolioDisposition(item));
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item)}
                    className="helios-focus-ring"
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "flex-start",
                      justifyContent: "space-between",
                      gap: SP.sm,
                      textAlign: "left",
                      borderRadius: 16,
                      border: `1px solid ${disposition.border}`,
                      background: disposition.background,
                      padding: PAD.default,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>
                        {displayName(item.name)}
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
                        {operatorSummary(item)}
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: SP.xs, flexShrink: 0 }}>
                      <span style={{ fontSize: FS.xs, color: T.textTertiary }}>{relativeCaseTime(item)}</span>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          borderRadius: 999,
                          border: `1px solid ${disposition.border}`,
                          background: T.surface,
                          color: disposition.color,
                          padding: "4px 8px",
                          fontSize: FS.xs,
                          fontWeight: 800,
                        }}
                      >
                        {disposition.label}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyPanel
              title="No active cases in this lane"
              description="Open a new intake or switch lanes if the work is sitting somewhere else."
              action={
                <button
                  type="button"
                  onClick={() => onNavigate?.("helios")}
                  className="helios-focus-ring"
                  style={{
                    borderRadius: 999,
                    border: "none",
                    background: T.accent,
                    color: "#04101f",
                    padding: "10px 14px",
                    fontSize: FS.sm,
                    fontWeight: 800,
                    cursor: "pointer",
                  }}
                >
                  Open intake
                </button>
              }
            />
          )}
        </div>

        <div
          className="glass-card"
          style={{
            padding: PAD.comfortable,
            borderRadius: 18,
            display: "flex",
            flexDirection: "column",
            gap: SP.sm,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.sm }}>
            <div>
              <SectionEyebrow>Operational pulse</SectionEyebrow>
              <div style={{ fontSize: FS.base, fontWeight: 800, color: T.text, marginTop: SP.xs }}>
                What changed since the last decision?
              </div>
            </div>
            {anomalies.length > 0 ? (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                  borderRadius: 999,
                  background: T.amberBg,
                  border: `1px solid ${T.amber}${O["30"]}`,
                  color: T.amber,
                  padding: "6px 10px",
                  fontSize: FS.xs,
                  fontWeight: 800,
                }}
              >
                <AlertTriangle size={12} />
                {anomalies.length} anomal{anomalies.length === 1 ? "y" : "ies"}
              </div>
            ) : null}
          </div>

          {monitorChanges.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
              {monitorChanges.slice(0, 5).map((change, index) => {
                const caseMatch = allCases.find((item) => item.id === change.vendor_id);
                const name = change.vendor_name || (caseMatch ? displayName(caseMatch.name) : change.vendor_id.slice(0, 8));
                const isIncrease = change.change_type === "risk_increase" || (!change.change_type && (change.current_risk ?? "") > (change.previous_risk ?? ""));
                const ChangeIcon = isIncrease ? TrendingUp : TrendingDown;
                const changeColor = isIncrease ? T.red : T.green;
                return (
                  <button
                    key={`${change.vendor_id}-${index}`}
                    type="button"
                    onClick={() => {
                      if (caseMatch) {
                        onSelect(caseMatch);
                        emit("what_changed_clicked", {
                          screen: "portfolio",
                          case_id: change.vendor_id,
                          metadata: { vendor_name: change.vendor_name || caseMatch.name, change_type: change.change_type },
                        });
                      }
                    }}
                    className="helios-focus-ring"
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: SP.sm,
                      borderRadius: 14,
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      padding: PAD.default,
                      textAlign: "left",
                      cursor: caseMatch ? "pointer" : "default",
                    }}
                    title={change.delta_summary || undefined}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: SP.sm, minWidth: 0, flex: 1 }}>
                      <div
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: 10,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          background: `${changeColor}${O["08"]}`,
                          border: `1px solid ${changeColor}${O["20"]}`,
                          flexShrink: 0,
                        }}
                      >
                        <ChangeIcon size={14} color={changeColor} />
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>
                          {name}
                        </div>
                        <div style={{ fontSize: FS.xs, color: T.textSecondary, lineHeight: 1.5 }}>
                          {change.delta_summary || `${isIncrease ? "Risk increased" : "Risk eased"} in monitoring.`}
                        </div>
                      </div>
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.textTertiary }}>
                      {change.current_risk || "monitor"}
                    </div>
                  </button>
                );
              })}

              <InlineMessage
                tone="info"
                title="AXIOM signal"
                message="Watchlist drift is only the first layer. AXIOM should keep expanding the evidence picture when the dossier still has dark space."
                icon={Sparkles}
              />
            </div>
          ) : (
            <InlineMessage
              tone="neutral"
              title="No recent portfolio changes"
              message="The queue is stable right now. Use AXIOM or Graph Intel when you need to close gaps, not just react to drift."
            />
          )}
        </div>
      </section>

      <section
        className="glass-card"
        style={{
          padding: PAD.comfortable,
          borderRadius: 18,
          display: "flex",
          flexDirection: "column",
          gap: SP.sm,
        }}
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <SectionEyebrow>Case list</SectionEyebrow>
            <div style={{ fontSize: FS.base, fontWeight: 800, color: T.text, marginTop: SP.xs }}>
              All active cases in scope
            </div>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs }}>
              {query ? `Filtered by "${query}"` : `Sorted by ${sortBy === "score" ? "priority score" : sortBy}.`}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="portfolio-sort" style={{ fontSize: FS.sm, color: T.textSecondary }}>Sort</label>
            <select
              id="portfolio-sort"
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as SortBy)}
              className="helios-focus-ring"
              style={{
                borderRadius: 12,
                border: `1px solid ${T.border}`,
                background: T.surface,
                color: T.text,
                padding: "8px 12px",
                fontSize: FS.sm,
              }}
            >
              <option value="score">Priority</option>
              <option value="date">Date</option>
              <option value="name">Vendor</option>
            </select>
          </div>
        </div>

        {sortedCases.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
            <div
              className="hidden lg:grid"
              style={{
                gridTemplateColumns: "minmax(0,2.2fr) minmax(0,1fr) minmax(0,0.9fr) minmax(0,0.8fr) minmax(0,0.8fr) minmax(0,0.8fr)",
                gap: SP.sm,
                padding: `0 ${SP.sm}px`,
                fontSize: FS.xs,
                color: T.textTertiary,
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              <span>Vendor</span>
              <span>Lane</span>
              <span>Tier</span>
              <span>Disposition</span>
              <span style={{ textAlign: "right" }}>Risk</span>
              <span style={{ textAlign: "right" }}>Updated</span>
            </div>

            {sortedCases.map((item, index) => {
              const lane = WORKFLOW_LANE_META[workflowLaneForCase(item)];
              const band = bandTone(item);
              const disposition = dispositionTone(portfolioDisposition(item));
              const riskScore = Math.round((item.cal?.p ?? item.sc) * 100);
              const updatedLabel = item.date
                ? new Date(item.date).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })
                : "N/A";

              return (
                <button
                  key={item.id}
                  type="button"
                  data-case-row="true"
                  onClick={() => onSelect(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(item);
                    }
                  }}
                  className="helios-focus-ring"
                  aria-label={`Open case for ${displayName(item.name)}`}
                  style={{
                    width: "100%",
                    borderRadius: 16,
                    border: `1px solid ${index % 2 === 0 ? T.border : `${T.border}${O["50"]}`}`,
                    background: index % 2 === 0 ? `${T.surfaceElevated}${O["50"]}` : T.surface,
                    padding: PAD.default,
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div
                    className="grid"
                    style={{
                      gridTemplateColumns: "minmax(0,1fr)",
                      gap: SP.sm,
                    }}
                  >
                    <div className="lg:grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,2.2fr) minmax(0,1fr) minmax(0,0.9fr) minmax(0,0.8fr) minmax(0,0.8fr) minmax(0,0.8fr)", gap: SP.sm, alignItems: "center" }}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>
                          {displayName(item.name)}
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
                          {operatorSummary(item)}
                        </div>
                      </div>

                      <div>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            borderRadius: 999,
                            background: lane.softBackground,
                            border: `1px solid ${lane.softBorder}`,
                            color: lane.accent,
                            padding: "4px 8px",
                            fontSize: FS.xs,
                            fontWeight: 800,
                          }}
                        >
                          {lane.shortLabel}
                        </span>
                      </div>

                      <div>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            borderRadius: 999,
                            background: band.background,
                            border: `1px solid ${band.border}`,
                            color: band.color,
                            padding: "4px 8px",
                            fontSize: FS.xs,
                            fontWeight: 800,
                          }}
                        >
                          {band.label}
                        </span>
                      </div>

                      <div>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            borderRadius: 999,
                            background: disposition.background,
                            border: `1px solid ${disposition.border}`,
                            color: disposition.color,
                            padding: "4px 8px",
                            fontSize: FS.xs,
                            fontWeight: 800,
                          }}
                        >
                          {disposition.label}
                        </span>
                      </div>

                      <div style={{ fontSize: FS.base, fontWeight: 800, color: T.text, textAlign: "right" }}>
                        {riskScore}%
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: SP.xs }}>
                        <span style={{ fontSize: FS.sm, color: T.textSecondary }}>{updatedLabel}</span>
                        <span style={{ fontSize: FS.xs, color: T.textTertiary }}>{relativeCaseTime(item)}</span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <EmptyPanel
            title="No active cases in this lane"
            description="Open a new intake to start the queue, or switch lanes if the work is sitting somewhere else."
            action={
              <button
                type="button"
                onClick={() => onNavigate?.("helios")}
                className="helios-focus-ring"
                style={{
                  borderRadius: 999,
                  border: "none",
                  background: T.accent,
                  color: "#04101f",
                  padding: "10px 14px",
                  fontSize: FS.sm,
                  fontWeight: 800,
                  cursor: "pointer",
                }}
              >
                Open intake
              </button>
            }
          />
        )}
      </section>
    </div>
  );
}
