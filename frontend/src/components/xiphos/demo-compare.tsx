import { useState, useCallback, useEffect, useRef } from "react";
import { T, FS } from "@/lib/tokens";
import { tierBand, BAND_META, TIER_META, parseTier, tierColor } from "@/lib/tokens";
import {
  Shield, Globe, Search, ChevronDown, ChevronRight,
  AlertTriangle, CheckCircle, XOctagon, Eye, Zap,
  Radar, Loader, XCircle,
} from "lucide-react";

/* ---- Types ---- */
interface ProfileResult {
  profile_id: string;
  profile_name: string;
  tier: string;
  probability: number;
  hard_stops: number;
  soft_flags: number;
  top_factor: string;
  top_factor_desc: string;
}

interface DemoResult {
  entity: { name: string; country: string };
  profiles: ProfileResult[];
  demo: boolean;
}

/* ---- Profile short labels and descriptions ---- */
const PROFILE_INFO: Record<string, { short: string; desc: string; icon: string }> = {
  defense_acquisition: {
    short: "DEFENSE",
    desc: "DoD acquisition, DFARS, ITAR-adjacent procurement",
    icon: "shield",
  },
  itar_trade_compliance: {
    short: "ITAR",
    desc: "International Traffic in Arms Regulations, EAR export controls",
    icon: "lock",
  },
  university_research_security: {
    short: "RESEARCH",
    desc: "University research security, foreign talent programs",
    icon: "graduation-cap",
  },
  grants_compliance: {
    short: "GRANTS",
    desc: "Federal grants, FAPIIS, debarment, Do Not Pay",
    icon: "file-text",
  },
  commercial_supply_chain: {
    short: "SUPPLY CHAIN",
    desc: "Commercial supply chain, regulatory compliance, ESG",
    icon: "truck",
  },
};

/* ---- Connector display names ---- */
const CONNECTOR_LABELS: Record<string, string> = {
  dod_sam_exclusions: "DoD EPLS Exclusions",
  bis_entity_list: "BIS Entity List",
  cfius_risk: "CFIUS Risk Assessment",
  trade_csl: "Consolidated Screening List",
  un_sanctions: "UN Sanctions",
  opensanctions_pep: "OpenSanctions PEP",
  worldbank_debarred: "World Bank Debarments",
  icij_offshore: "ICIJ Offshore Leaks",
  fara: "DOJ FARA",
  gdelt_media: "GDELT Adverse Media",
  sec_edgar: "SEC EDGAR",
  gleif_lei: "GLEIF LEI",
  opencorporates: "OpenCorporates",
  uk_companies_house: "UK Companies House",
  sam_gov: "SAM.gov",
  usaspending: "USASpending",
  epa_echo: "EPA ECHO",
  osha_safety: "OSHA Safety",
  courtlistener: "CourtListener",
  fdic_bankfind: "FDIC BankFind",
  usml_classifier: "USML Classifier",
  end_use_risk: "End-Use Risk",
  deemed_export: "Deemed Export",
  foreign_talent_programs: "Foreign Talent Programs",
  institutional_risk: "Institutional Risk",
  fapiis_check: "FAPIIS Check",
  do_not_pay: "Do Not Pay",
  regulatory_compliance: "Regulatory Compliance",
};

const CONNECTOR_GROUPS: Record<string, string> = {
  dod_sam_exclusions: "Sanctions & Restricted",
  bis_entity_list: "Sanctions & Restricted",
  cfius_risk: "Sanctions & Restricted",
  trade_csl: "Sanctions & Restricted",
  un_sanctions: "Sanctions & Restricted",
  opensanctions_pep: "Sanctions & Restricted",
  worldbank_debarred: "Debarment & Offshore",
  icij_offshore: "Debarment & Offshore",
  fara: "Foreign Influence",
  gdelt_media: "Adverse Media",
  sec_edgar: "Corporate Identity",
  gleif_lei: "Corporate Identity",
  opencorporates: "Corporate Identity",
  uk_companies_house: "Corporate Identity",
  sam_gov: "Government Contracts",
  usaspending: "Government Contracts",
  epa_echo: "Regulatory",
  osha_safety: "Regulatory",
  courtlistener: "Legal & Financial",
  fdic_bankfind: "Legal & Financial",
  usml_classifier: "Export Control",
  end_use_risk: "Export Control",
  deemed_export: "Export Control",
  foreign_talent_programs: "Research Security",
  institutional_risk: "Research Security",
  fapiis_check: "Grants Compliance",
  do_not_pay: "Grants Compliance",
  regulatory_compliance: "Supply Chain",
};

/* ---- Country code options (common) ---- */
const COUNTRIES = [
  { code: "US", label: "United States" },
  { code: "GB", label: "United Kingdom" },
  { code: "CN", label: "China" },
  { code: "RU", label: "Russia" },
  { code: "DE", label: "Germany" },
  { code: "FR", label: "France" },
  { code: "JP", label: "Japan" },
  { code: "KR", label: "South Korea" },
  { code: "IN", label: "India" },
  { code: "IL", label: "Israel" },
  { code: "BR", label: "Brazil" },
  { code: "CA", label: "Canada" },
  { code: "AU", label: "Australia" },
  { code: "TR", label: "Turkey" },
  { code: "IR", label: "Iran" },
  { code: "KP", label: "North Korea" },
  { code: "SA", label: "Saudi Arabia" },
  { code: "AE", label: "UAE" },
  { code: "TW", label: "Taiwan" },
  { code: "SG", label: "Singapore" },
  { code: "PK", label: "Pakistan" },
  { code: "MX", label: "Mexico" },
  { code: "UA", label: "Ukraine" },
  { code: "SY", label: "Syria" },
  { code: "CU", label: "Cuba" },
];

/* ---- Enrichment stream types ---- */
type ConnectorState = "pending" | "running" | "done" | "error";

interface ConnectorProgress {
  name: string;
  state: ConnectorState;
  hasData?: boolean;
  findingsCount?: number;
  elapsedMs?: number;
  error?: string;
}

/* ---- Demo Compare Component ---- */
export function DemoCompare() {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("CN");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  // Enrichment stream state
  const [enriching, setEnriching] = useState(false);
  const [enrichPhase, setEnrichPhase] = useState<"idle" | "connecting" | "enriching" | "scoring" | "done" | "error">("idle");
  const [connectors, setConnectors] = useState<ConnectorProgress[]>([]);
  const [totalConnectors, setTotalConnectors] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalFindings, setTotalFindings] = useState(0);
  const [enrichedProfiles, setEnrichedProfiles] = useState<ProfileResult[] | null>(null);
  const [enrichStartTime, setEnrichStartTime] = useState(0);
  const [enrichElapsed, setEnrichElapsed] = useState(0);
  const timerRef = useRef<number>(0);
  const esRef = useRef<EventSource | null>(null);

  const BASE = import.meta.env.VITE_API_URL ?? "";

  // Elapsed timer for enrichment
  useEffect(() => {
    if (enriching && enrichStartTime > 0) {
      timerRef.current = window.setInterval(() => {
        setEnrichElapsed(Date.now() - enrichStartTime);
      }, 100);
      return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }
  }, [enriching, enrichStartTime]);

  const handleSubmit = useCallback(async () => {
    if (!name.trim() || !country) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setEnrichedProfiles(null);
    setEnrichPhase("idle");
    setEnriching(false);

    try {
      const res = await fetch(`${BASE}/api/demo/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), country }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to score entity");
    } finally {
      setLoading(false);
    }
  }, [name, country, BASE]);

  const handleEnrich = useCallback(() => {
    if (!result || enriching) return;

    // Clean up any prior stream
    if (esRef.current) { esRef.current.close(); esRef.current = null; }

    setEnriching(true);
    setEnrichPhase("connecting");
    setConnectors([]);
    setTotalConnectors(0);
    setCompletedCount(0);
    setTotalFindings(0);
    setEnrichedProfiles(null);
    setEnrichStartTime(Date.now());
    setEnrichElapsed(0);

    const params = new URLSearchParams({
      name: result.entity.name,
      country: result.entity.country,
    });
    const url = `${BASE}/api/demo/enrich-stream?${params.toString()}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("start", (e) => {
      const data = JSON.parse(e.data);
      setTotalConnectors(data.total_connectors);
      setEnrichPhase("enriching");
      setConnectors(
        data.connector_names.map((n: string) => ({
          name: n,
          state: "running" as ConnectorState,
        }))
      );
    });

    es.addEventListener("connector_done", (e) => {
      const data = JSON.parse(e.data);
      setConnectors((prev) =>
        prev.map((c) =>
          c.name === data.name
            ? { ...c, state: "done", hasData: data.has_data, findingsCount: data.findings_count, elapsedMs: data.elapsed_ms }
            : c
        )
      );
      setCompletedCount(data.index);
      setTotalFindings((prev) => prev + (data.findings_count || 0));
    });

    es.addEventListener("connector_error", (e) => {
      const data = JSON.parse(e.data);
      setConnectors((prev) =>
        prev.map((c) =>
          c.name === data.name
            ? { ...c, state: "error", error: data.error }
            : c
        )
      );
      setCompletedCount(data.index);
    });

    es.addEventListener("complete", () => {
      setEnrichPhase("scoring");
    });

    es.addEventListener("scored", (e) => {
      const data = JSON.parse(e.data);
      if (data.profiles) {
        setEnrichedProfiles(data.profiles);
      }
    });

    es.addEventListener("done", () => {
      setEnrichPhase("done");
      setEnriching(false);
      if (timerRef.current) clearInterval(timerRef.current);
      es.close();
    });

    es.onerror = () => {
      setEnrichPhase("error");
      setEnriching(false);
      if (timerRef.current) clearInterval(timerRef.current);
      es.close();
    };
  }, [result, enriching, BASE]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const enrichPct = totalConnectors > 0 ? Math.round((completedCount / totalConnectors) * 100) : 0;
  const dataConnectors = connectors.filter((c) => c.state === "done" && c.hasData).length;

  // Group connectors by category
  const grouped = connectors.reduce<Record<string, ConnectorProgress[]>>((acc, c) => {
    const group = CONNECTOR_GROUPS[c.name] || "Other";
    if (!acc[group]) acc[group] = [];
    acc[group].push(c);
    return acc;
  }, {});

  // Choose which profiles to display (enriched or initial)
  const displayProfiles = enrichedProfiles || (result?.profiles ?? []);

  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "0 16px" }}>
      {/* Hero header */}
      <div className="text-center" style={{ padding: "40px 0 24px" }}>
        <div className="flex items-center justify-center gap-2 mb-3">
          <Shield size={24} color={T.accent} />
          <span
            className="font-mono font-bold uppercase tracking-wider"
            style={{ fontSize: 18, color: T.text, letterSpacing: "0.12em" }}
          >
            XIPHOS
          </span>
        </div>
        <h1
          className="font-bold"
          style={{ fontSize: 28, color: T.text, lineHeight: 1.3, margin: "0 0 8px" }}
        >
          Multi-Vertical Compliance Scoring
        </h1>
        <p style={{ fontSize: FS.sm, color: T.muted, maxWidth: 560, margin: "0 auto", lineHeight: 1.6 }}>
          See how the same entity scores across five compliance verticals. Enter any vendor
          name and country to get instant risk assessments powered by Bayesian inference,
          live sanctions screening, and 28-source OSINT intelligence.
        </p>
      </div>

      {/* Search input */}
      <div
        className="rounded-lg flex items-stretch gap-0 overflow-hidden"
        style={{
          background: T.surface,
          border: `2px solid ${loading || enriching ? T.accent : T.border}`,
          transition: "border-color 0.2s",
        }}
      >
        <div className="flex items-center px-3" style={{ background: T.raised }}>
          <Globe size={16} color={T.muted} />
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="font-mono outline-none cursor-pointer bg-transparent border-none"
            style={{ fontSize: FS.sm, color: T.dim, padding: "12px 8px", minWidth: 50 }}
          >
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>{c.code}</option>
            ))}
          </select>
        </div>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Enter vendor name (e.g., Huawei Technologies)"
          className="flex-1 outline-none bg-transparent border-none"
          style={{ fontSize: FS.sm, color: T.text, padding: "14px 16px" }}
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !name.trim()}
          className="flex items-center gap-2 border-none cursor-pointer font-semibold"
          style={{
            padding: "12px 24px",
            background: loading ? T.raised : T.accent,
            color: loading ? T.muted : "#fff",
            fontSize: FS.sm,
            opacity: !name.trim() ? 0.5 : 1,
            transition: "all 0.2s",
          }}
        >
          {loading ? (
            <Zap size={14} className="animate-pulse" />
          ) : (
            <Search size={14} />
          )}
          {loading ? "Scoring..." : "Score"}
        </button>
      </div>

      {error && (
        <div
          className="flex items-center gap-2 mt-3 rounded"
          style={{ padding: "10px 14px", background: "rgba(239,68,68,0.08)", border: `1px solid ${T.red}33` }}
        >
          <XOctagon size={12} color={T.red} />
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {result.entity.name}
            </span>
            <span
              className="font-mono rounded px-1.5 py-0.5"
              style={{ fontSize: FS.xs, background: T.raised, color: T.muted }}
            >
              {result.entity.country}
            </span>
            {enrichedProfiles && (
              <span
                className="font-mono rounded px-1.5 py-0.5"
                style={{ fontSize: FS.xs, background: T.accent + "18", color: T.accent }}
              >
                OSINT ENRICHED
              </span>
            )}
          </div>

          {/* Profile cards grid */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {displayProfiles.map((p) => {
              const parsedTier = parseTier(p.tier);
              const band = tierBand(parsedTier);
              const bandMeta = BAND_META[band];
              const tierMeta = TIER_META[parsedTier];
              const pi = PROFILE_INFO[p.profile_id] || { short: p.profile_id, desc: "", icon: "shield" };
              const color = tierColor(parsedTier);
              const bg = tierMeta?.bg || bandMeta?.bg || "rgba(148,163,184,0.12)";
              // Map band to icon
              const iconMap: Record<typeof band, typeof Shield> = {
                critical: XOctagon,
                elevated: AlertTriangle,
                conditional: Eye,
                clear: CheckCircle,
              };
              const TierIcon = iconMap[band];
              const label = tierMeta?.shortLabel || bandMeta?.label || "UNKNOWN";
              const isExpanded = expanded === p.profile_id;

              return (
                <button
                  key={p.profile_id}
                  onClick={() => setExpanded(isExpanded ? null : p.profile_id)}
                  className="rounded-lg text-left border-none cursor-pointer w-full"
                  style={{
                    background: T.surface,
                    border: `1px solid ${isExpanded ? color + "44" : T.border}`,
                    padding: 14,
                    transition: "border-color 0.2s",
                  }}
                >
                  {/* Profile label */}
                  <div
                    className="font-mono font-bold uppercase tracking-wider mb-2"
                    style={{ fontSize: "9px", color: T.muted, letterSpacing: "0.1em" }}
                  >
                    {pi.short}
                  </div>

                  {/* Tier badge */}
                  <div
                    className="inline-flex items-center gap-1 rounded-sm px-2 py-1 mb-2"
                    style={{ background: bg, border: `1px solid ${color}22` }}
                  >
                    <TierIcon size={10} color={color} />
                    <span className="font-mono font-bold" style={{ fontSize: FS.xs, color: color }}>
                      {label}
                    </span>
                  </div>

                  {/* Probability */}
                  <div className="font-mono font-bold" style={{ fontSize: 22, color: color }}>
                    {Math.round(p.probability * 100)}%
                  </div>
                  <div style={{ fontSize: "9px", color: T.muted }}>risk probability</div>

                  {/* Stats row */}
                  <div className="flex items-center gap-2 mt-2 pt-2" style={{ borderTop: `1px solid ${T.border}` }}>
                    {p.hard_stops > 0 && (
                      <span className="font-mono" style={{ fontSize: "9px", color: T.red }}>
                        {p.hard_stops} STOP
                      </span>
                    )}
                    {p.soft_flags > 0 && (
                      <span className="font-mono" style={{ fontSize: "9px", color: T.amber }}>
                        {p.soft_flags} flags
                      </span>
                    )}
                  </div>

                  {/* Expand indicator */}
                  <div className="flex items-center gap-1 mt-2" style={{ fontSize: "9px", color: T.muted }}>
                    {isExpanded ? <ChevronDown size={8} /> : <ChevronRight size={8} />}
                    details
                  </div>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div
                      className="mt-2 pt-2"
                      style={{ borderTop: `1px solid ${T.border}`, fontSize: FS.xs, color: T.dim }}
                    >
                      <div className="mb-1">
                        <span style={{ color: T.muted }}>Top factor:</span>{" "}
                        {p.top_factor}
                      </div>
                      <div style={{ lineHeight: 1.5 }}>{p.top_factor_desc}</div>
                      <div className="mt-1" style={{ fontSize: "9px", color: T.muted }}>
                        {pi.desc}
                      </div>
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {/* Risk spread analysis */}
          <div
            className="rounded-lg mt-4"
            style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 14 }}
          >
            <div className="flex items-center gap-2 mb-2">
              <Zap size={12} color={T.accent} />
              <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                Cross-Profile Risk Analysis
              </span>
            </div>
            {(() => {
              const probs = displayProfiles.map((p) => p.probability);
              const tiers = new Set(displayProfiles.map((p) => p.tier));
              const min = Math.min(...probs);
              const max = Math.max(...probs);
              const spread = max - min;

              return (
                <div className="grid grid-cols-3 gap-4 mt-1">
                  <div>
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {tiers.size}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Distinct Tiers</div>
                  </div>
                  <div>
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {Math.round(min * 100)}% - {Math.round(max * 100)}%
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Probability Range</div>
                  </div>
                  <div>
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {Math.round(spread * 100)}pp
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Risk Spread</div>
                  </div>
                </div>
              );
            })()}
          </div>

          {/* Enrichment stream section */}
          {enrichPhase === "idle" && !enrichedProfiles && (
            <div className="text-center mt-5">
              <button
                onClick={handleEnrich}
                className="inline-flex items-center gap-2 rounded-lg font-semibold border-none cursor-pointer"
                style={{
                  padding: "12px 28px",
                  background: `linear-gradient(135deg, ${T.accent}, ${T.accent}dd)`,
                  color: "#fff",
                  fontSize: FS.sm,
                  boxShadow: `0 2px 12px ${T.accent}44`,
                  transition: "transform 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.02)")}
                onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
              >
                <Radar size={16} />
                Run Live OSINT Enrichment
              </button>
              <p style={{ fontSize: FS.xs, color: T.muted, marginTop: 8 }}>
                Watch 28 intelligence sources scan this entity in real time
              </p>
            </div>
          )}

          {/* Live enrichment stream */}
          {enrichPhase !== "idle" && (
            <div className="mt-5">
              {/* Stream header with progress */}
              <div
                className="rounded-lg"
                style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <Radar
                    size={14}
                    color={T.accent}
                    className={enrichPhase === "enriching" ? "animate-pulse" : ""}
                  />
                  <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                    {enrichPhase === "connecting" && "Connecting to OSINT pipeline..."}
                    {enrichPhase === "enriching" && "Live Intelligence Collection"}
                    {enrichPhase === "scoring" && "Re-scoring with enrichment data..."}
                    {enrichPhase === "done" && "Enrichment Complete"}
                    {enrichPhase === "error" && "Connection Error"}
                  </span>
                  <span className="ml-auto font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                    {(enrichElapsed / 1000).toFixed(1)}s
                  </span>
                </div>

                {/* Progress bar */}
                <div className="rounded-full overflow-hidden" style={{ height: 6, background: T.raised }}>
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${enrichPhase === "done" ? 100 : enrichPct}%`,
                      background: enrichPhase === "error"
                        ? T.red
                        : enrichPhase === "done"
                        ? T.green
                        : `linear-gradient(90deg, ${T.accent}, ${T.accent}cc)`,
                    }}
                  />
                </div>

                {/* Live counters */}
                <div className="grid grid-cols-4 gap-3 mt-3">
                  <div className="text-center">
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {completedCount}/{totalConnectors}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Sources</div>
                  </div>
                  <div className="text-center">
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {totalFindings}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Findings</div>
                  </div>
                  <div className="text-center">
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {dataConnectors}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>With Data</div>
                  </div>
                  <div className="text-center">
                    <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
                      {enrichedProfiles
                        ? `${Math.round(Math.max(...enrichedProfiles.map(p => p.probability)) * 100)}%`
                        : "--"}
                    </div>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Peak Risk</div>
                  </div>
                </div>
              </div>

              {/* Connector grid by group */}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 mt-2">
                {Object.entries(grouped).map(([group, conns]) => (
                  <div
                    key={group}
                    className="rounded-lg"
                    style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 10 }}
                  >
                    <div
                      className="font-semibold uppercase tracking-wider mb-1.5"
                      style={{ fontSize: "9px", color: T.muted, letterSpacing: "0.08em" }}
                    >
                      {group}
                    </div>
                    {conns.map((c) => {
                      const label = CONNECTOR_LABELS[c.name] || c.name;
                      let iconEl: React.ReactNode;
                      let statusColor: string;

                      switch (c.state) {
                        case "running":
                          iconEl = <Loader size={10} color={T.accent} className="animate-spin" />;
                          statusColor = T.accent;
                          break;
                        case "done":
                          iconEl = <CheckCircle size={10} color={c.hasData ? T.green : T.muted} />;
                          statusColor = c.hasData ? T.green : T.muted;
                          break;
                        case "error":
                          iconEl = <XCircle size={10} color={T.red} />;
                          statusColor = T.red;
                          break;
                        default:
                          iconEl = <div className="w-2.5 h-2.5 rounded-full" style={{ background: T.border }} />;
                          statusColor = T.muted;
                      }

                      return (
                        <div
                          key={c.name}
                          className="flex items-center gap-1.5"
                          style={{ padding: "3px 0", borderBottom: `1px solid ${T.border}22` }}
                          title={c.error || `${c.findingsCount ?? 0} findings, ${c.elapsedMs ?? 0}ms`}
                        >
                          {iconEl}
                          <span
                            className="flex-1 truncate"
                            style={{ fontSize: FS.xs, color: c.state === "running" ? T.text : T.dim }}
                          >
                            {label}
                          </span>
                          {c.state === "done" && (
                            <>
                              <span className="font-mono" style={{ fontSize: "9px", color: statusColor }}>
                                {c.findingsCount || 0}
                              </span>
                              <span className="font-mono" style={{ fontSize: "9px", color: T.muted }}>
                                {c.elapsedMs ? `${(c.elapsedMs / 1000).toFixed(1)}s` : ""}
                              </span>
                            </>
                          )}
                          {c.state === "running" && (
                            <span className="font-mono" style={{ fontSize: "9px", color: T.accent }}>
                              ...
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* CTA */}
          <div className="text-center mt-6 mb-8">
            <p style={{ fontSize: FS.sm, color: T.muted, marginBottom: 12 }}>
              {enrichedProfiles
                ? "Full enrichment complete. Sign in to save cases, generate dossiers, and enable continuous monitoring."
                : "This is a demo with default ownership assumptions. The full platform includes entity resolution, executive screening, and continuous monitoring."}
            </p>
            <a
              href="/login"
              className="inline-flex items-center gap-2 rounded-lg font-semibold no-underline"
              style={{
                padding: "12px 32px",
                background: T.accent,
                color: "#fff",
                fontSize: FS.sm,
                textDecoration: "none",
              }}
            >
              <Shield size={14} />
              Sign In for Full Access
            </a>
          </div>
        </div>
      )}

      {/* Pre-loaded examples if no result yet */}
      {!result && !loading && (
        <div className="mt-8">
          <div style={{ fontSize: FS.xs, color: T.muted, marginBottom: 8, textAlign: "center" }}>
            Try these examples:
          </div>
          <div className="flex items-center justify-center gap-2 flex-wrap">
            {[
              { name: "Huawei Technologies", country: "CN" },
              { name: "BAE Systems", country: "GB" },
              { name: "Lockheed Martin", country: "US" },
              { name: "Kaspersky Lab", country: "RU" },
              { name: "Tsinghua University", country: "CN" },
            ].map((ex) => (
              <button
                key={ex.name}
                onClick={() => { setName(ex.name); setCountry(ex.country); }}
                className="rounded-lg border-none cursor-pointer"
                style={{
                  padding: "8px 14px",
                  background: T.raised,
                  color: T.dim,
                  fontSize: FS.xs,
                  transition: "background 0.15s",
                }}
              >
                {ex.name} <span style={{ color: T.muted }}>({ex.country})</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
