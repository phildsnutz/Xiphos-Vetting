import { useState, useMemo } from "react";
import { T, FS } from "@/lib/tokens";
import {
  Radar, ChevronDown, ChevronRight, ExternalLink, Clock,
  XCircle, Database, Zap, Filter,
} from "lucide-react";
import type { EnrichmentReport, EnrichmentFinding, ConnectorStatus } from "@/lib/api";

/* ---- Severity config ---- */
const SEV = {
  critical: { color: "#ef4444", bg: "rgba(239,68,68,0.12)", label: "CRITICAL", order: 0 },
  high:     { color: "#f97316", bg: "rgba(249,115,22,0.12)", label: "HIGH", order: 1 },
  medium:   { color: "#eab308", bg: "rgba(234,179,8,0.12)",  label: "MEDIUM", order: 2 },
  low:      { color: "#3b82f6", bg: "rgba(59,130,246,0.12)", label: "LOW", order: 3 },
  info:     { color: "#64748b", bg: "rgba(100,116,139,0.08)", label: "INFO", order: 4 },
} as const;

type Severity = keyof typeof SEV;

/* ---- Connector metadata ---- */
const CONNECTOR_META: Record<string, { label: string; icon: string }> = {
  trade_csl:          { label: "Trade CSL",          icon: "shield" },
  un_sanctions:       { label: "UN Sanctions",       icon: "shield" },
  opensanctions_pep:  { label: "OpenSanctions PEP",  icon: "shield" },
  worldbank_debarred: { label: "World Bank",         icon: "shield" },
  icij_offshore:      { label: "ICIJ Offshore",      icon: "search" },
  gdelt_media:        { label: "GDELT Media",        icon: "newspaper" },
  sec_edgar:          { label: "SEC EDGAR",           icon: "building" },
  gleif_lei:          { label: "GLEIF LEI",           icon: "building" },
  opencorporates:     { label: "OpenCorporates",      icon: "building" },
  uk_companies_house: { label: "UK Companies House",  icon: "building" },
  sam_gov:            { label: "SAM.gov",             icon: "flag" },
  usaspending:        { label: "USASpending",          icon: "flag" },
  epa_echo:           { label: "EPA ECHO",             icon: "leaf" },
  osha_safety:        { label: "OSHA Safety",          icon: "hardhat" },
  courtlistener:      { label: "CourtListener",        icon: "gavel" },
  fdic_bankfind:      { label: "FDIC BankFind",        icon: "bank" },
  fara:               { label: "DOJ FARA",             icon: "shield" },
};

function connectorLabel(name: string): string {
  return CONNECTOR_META[name]?.label ?? name;
}

/* ---- Finding Card ---- */
function FindingCard({ f }: { f: EnrichmentFinding }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV[f.severity as Severity] ?? SEV.info;

  return (
    <div
      className="rounded"
      style={{
        background: T.surface,
        border: `1px solid ${T.border}`,
        marginBottom: 6,
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-start gap-2 text-left bg-transparent border-none cursor-pointer"
        style={{ padding: "10px 12px" }}
      >
        {expanded
          ? <ChevronDown size={12} color={T.muted} className="shrink-0 mt-0.5" />
          : <ChevronRight size={12} color={T.muted} className="shrink-0 mt-0.5" />
        }
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono font-bold uppercase"
              style={{ fontSize: FS.xs, color: sev.color, background: sev.bg, border: `1px solid ${sev.color}22` }}
            >
              {sev.label}
            </span>
            <span
              className="font-mono rounded-sm px-1.5 py-0.5"
              style={{ fontSize: FS.xs, color: T.muted, background: T.raised }}
            >
              {connectorLabel(f.source)}
            </span>
            {f.confidence > 0 && (
              <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                {Math.round(f.confidence * 100)}%
              </span>
            )}
          </div>
          <div className="mt-1" style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.4 }}>
            {f.title}
          </div>
        </div>
      </button>

      {expanded && (
        <div style={{ padding: "0 12px 12px 32px" }}>
          <pre
            className="whitespace-pre-wrap font-mono"
            style={{ fontSize: FS.xs, color: T.dim, lineHeight: 1.6, margin: 0 }}
          >
            {f.detail}
          </pre>
          {f.url && (
            <a
              href={f.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 mt-2"
              style={{ fontSize: FS.xs, color: T.accent, textDecoration: "none" }}
            >
              <ExternalLink size={9} /> Source
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/* ---- Connector Status Row ---- */
function ConnectorRow({ name, status }: { name: string; status: ConnectorStatus }) {
  const hasError = !!status.error;
  const col = hasError ? T.red : status.has_data ? T.green : T.muted;

  return (
    <div
      className="flex items-center gap-2"
      style={{ padding: "4px 0", borderBottom: `1px solid ${T.border}` }}
    >
      <div className="w-2 h-2 rounded-full shrink-0" style={{ background: col }} />
      <span className="flex-1 truncate" style={{ fontSize: FS.sm, color: T.dim }}>
        {connectorLabel(name)}
      </span>
      <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
        {status.findings_count}
      </span>
      <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted, width: 50, textAlign: "right" }}>
        {status.elapsed_ms > 0 ? `${(status.elapsed_ms / 1000).toFixed(1)}s` : "--"}
      </span>
    </div>
  );
}

/* ---- Main Panel ---- */
interface EnrichmentPanelProps {
  report: EnrichmentReport;
}

export function EnrichmentPanel({ report }: EnrichmentPanelProps) {
  const [severityFilter, setSeverityFilter] = useState<Severity | "all">("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  // Distinct sources from findings
  const sources = useMemo(() => {
    const s = new Set(report.findings.map((f) => f.source));
    return Array.from(s).sort();
  }, [report.findings]);

  // Filtered findings
  const filtered = useMemo(() => {
    let ff = report.findings;
    if (severityFilter !== "all") {
      ff = ff.filter((f) => f.severity === severityFilter);
    }
    if (sourceFilter !== "all") {
      ff = ff.filter((f) => f.source === sourceFilter);
    }
    return ff;
  }, [report.findings, severityFilter, sourceFilter]);

  // Sort connector status by elapsed time (slowest first for visibility)
  const sortedConnectors = useMemo(() => {
    return Object.entries(report.connector_status)
      .sort(([, a], [, b]) => b.elapsed_ms - a.elapsed_ms);
  }, [report.connector_status]);

  return (
    <div className="flex flex-col gap-3">
      {/* Summary banner */}
      <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 14 }}>
        <div className="flex items-center gap-2 mb-3">
          <Radar size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
            OSINT Intelligence Summary
          </span>
          {report._cached && (
            <span
              className="font-mono rounded px-1.5 py-0.5"
              style={{ fontSize: FS.xs, color: T.amber, background: T.amberBg }}
            >
              CACHED
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <div className="font-mono font-bold" style={{ fontSize: FS.xl, color: T.text }}>
              {report.summary.findings_total}
            </div>
            <div style={{ fontSize: FS.xs, color: T.muted }}>Total Findings</div>
          </div>
          <div>
            <div className="font-mono font-bold" style={{ fontSize: FS.xl, color: T.text }}>
              {report.summary.connectors_run}
            </div>
            <div style={{ fontSize: FS.xs, color: T.muted }}>Sources Queried</div>
          </div>
          <div>
            <div className="font-mono font-bold" style={{ fontSize: FS.xl, color: T.text }}>
              {(report.total_elapsed_ms / 1000).toFixed(1)}s
            </div>
            <div style={{ fontSize: FS.xs, color: T.muted }}>Collection Time</div>
          </div>
          <div>
            <div className="font-mono font-bold" style={{ fontSize: FS.xl, color: T.text }}>
              {Object.keys(report.identifiers).length}
            </div>
            <div style={{ fontSize: FS.xs, color: T.muted }}>IDs Discovered</div>
          </div>
        </div>

        {/* Severity counts */}
        <div className="flex items-center gap-3 mt-3 pt-3" style={{ borderTop: `1px solid ${T.border}` }}>
          {(["critical", "high", "medium", "low"] as const).map((sev) => {
            const count = report.findings.filter((f) => f.severity === sev).length;
            if (count === 0) return null;
            const s = SEV[sev];
            return (
              <div key={sev} className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                <span className="font-mono" style={{ fontSize: FS.xs, color: s.color }}>
                  {count} {s.label}
                </span>
              </div>
            );
          })}
          {report.summary.errors > 0 && (
            <div className="flex items-center gap-1">
              <XCircle size={10} color={T.red} />
              <span className="font-mono" style={{ fontSize: FS.xs, color: T.red }}>
                {report.summary.errors} errors
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Two-column layout: Findings + Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* Findings list (2 cols) */}
        <div className="lg:col-span-2 flex flex-col gap-2">
          {/* Filters */}
          <div className="flex items-center gap-2 flex-wrap">
            <Filter size={11} color={T.muted} />
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as Severity | "all")}
              className="rounded font-mono outline-none cursor-pointer"
              style={{
                fontSize: FS.xs, padding: "4px 8px",
                background: T.raised, color: T.dim, border: `1px solid ${T.border}`,
              }}
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="info">Info</option>
            </select>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="rounded font-mono outline-none cursor-pointer"
              style={{
                fontSize: FS.xs, padding: "4px 8px",
                background: T.raised, color: T.dim, border: `1px solid ${T.border}`,
              }}
            >
              <option value="all">All Sources ({sources.length})</option>
              {sources.map((s) => (
                <option key={s} value={s}>{connectorLabel(s)}</option>
              ))}
            </select>
            <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
              {filtered.length} / {report.findings.length}
            </span>
          </div>

          {/* Findings grouped by severity */}
          <div>
            {(() => {
              const critical = filtered.filter(f => f.severity === "critical" || f.severity === "high" || f.severity === "medium");
              const info = filtered.filter(f => f.severity === "info" || f.severity === "low");
              return (
                <>
                  {critical.map((f, i) => (
                    <FindingCard key={`${f.source}-${i}`} f={f} />
                  ))}
                  {info.length > 0 && critical.length > 0 && (
                    <div className="flex items-center gap-2 my-3">
                      <div style={{ flex: 1, height: 1, background: T.border }} />
                      <span style={{ fontSize: FS.xs, color: T.muted }}>
                        Clean Checks ({info.length})
                      </span>
                      <div style={{ flex: 1, height: 1, background: T.border }} />
                    </div>
                  )}
                  {info.map((f, i) => (
                    <FindingCard key={`info-${f.source}-${i}`} f={f} />
                  ))}
                  {filtered.length === 0 && (
                    <div
                      className="text-center rounded py-8"
                      style={{ background: T.surface, border: `1px solid ${T.border}`, fontSize: FS.sm, color: T.muted }}
                    >
                      No findings match current filters.
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>

        {/* Sidebar: Connector status + Identifiers */}
        <div className="flex flex-col gap-3">
          {/* Connector status */}
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="flex items-center gap-1.5 mb-2">
              <Database size={11} color={T.muted} />
              <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                Source Status
              </span>
            </div>
            {sortedConnectors.map(([name, status]) => (
              <ConnectorRow key={name} name={name} status={status} />
            ))}
          </div>

          {/* Discovered identifiers */}
          {Object.keys(report.identifiers).length > 0 && (
            <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="flex items-center gap-1.5 mb-2">
                <Zap size={11} color={T.muted} />
                <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                  Discovered Identifiers
                </span>
              </div>
              {Object.entries(report.identifiers).map(([key, val]) => (
                <div
                  key={key}
                  className="flex items-start justify-between gap-2"
                  style={{ padding: "3px 0", borderBottom: `1px solid ${T.border}` }}
                >
                  <span className="font-mono truncate" style={{ fontSize: FS.xs, color: T.muted }}>{key}</span>
                  <span className="font-mono text-right" style={{ fontSize: FS.xs, color: T.dim, maxWidth: 120 }}>
                    {String(val).substring(0, 30)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Enrichment metadata */}
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="flex items-center gap-1.5 mb-2">
              <Clock size={11} color={T.muted} />
              <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                Collection Metadata
              </span>
            </div>
            {[
              ["Enriched At", report.enriched_at?.split("T")[0] ?? "N/A"],
              ["Overall Risk", report.overall_risk],
              ["Total Time", `${(report.total_elapsed_ms / 1000).toFixed(1)}s`],
              ["Sources Run", String(report.summary.connectors_run)],
              ["With Data", String(report.summary.connectors_with_data)],
              ["Errors", String(report.summary.errors)],
            ].map(([k, v]) => (
              <div
                key={k}
                className="flex items-center justify-between"
                style={{ padding: "3px 0", borderBottom: `1px solid ${T.border}` }}
              >
                <span style={{ fontSize: FS.xs, color: T.muted }}>{k}</span>
                <span className="font-mono" style={{ fontSize: FS.xs, color: T.dim }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
