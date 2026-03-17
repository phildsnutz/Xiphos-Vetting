import { useState, useCallback } from "react";
import { T, FS } from "@/lib/tokens";
import {
  Shield, Globe, Search, ChevronDown, ChevronRight,
  AlertTriangle, CheckCircle, XOctagon, Eye, Zap,
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

/* ---- Tier styling ---- */
const TIER_CONFIG: Record<string, { color: string; bg: string; icon: typeof Shield; label: string }> = {
  hard_stop: { color: "#ef4444", bg: "rgba(239,68,68,0.12)", icon: XOctagon, label: "HARD STOP" },
  elevated:  { color: "#f97316", bg: "rgba(249,115,22,0.12)", icon: AlertTriangle, label: "ELEVATED" },
  monitor:   { color: "#eab308", bg: "rgba(234,179,8,0.12)", icon: Eye, label: "MONITOR" },
  clear:     { color: "#22c55e", bg: "rgba(34,197,94,0.12)", icon: CheckCircle, label: "CLEAR" },
};

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

/* ---- Demo Compare Component ---- */
export function DemoCompare() {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("CN");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const BASE = import.meta.env.VITE_API_URL ?? "";

  const handleSubmit = useCallback(async () => {
    if (!name.trim() || !country) return;
    setLoading(true);
    setError(null);
    setResult(null);

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

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 16px" }}>
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
        <p style={{ fontSize: FS.sm, color: T.muted, maxWidth: 520, margin: "0 auto", lineHeight: 1.6 }}>
          See how the same entity scores across five compliance verticals. Enter any vendor
          name and country to get instant risk assessments powered by Bayesian inference
          and live sanctions screening.
        </p>
      </div>

      {/* Search input */}
      <div
        className="rounded-lg flex items-stretch gap-0 overflow-hidden"
        style={{
          background: T.surface,
          border: `2px solid ${loading ? T.accent : T.border}`,
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
          </div>

          {/* Profile cards grid */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {result.profiles.map((p) => {
              const tc = TIER_CONFIG[p.tier] || TIER_CONFIG.clear;
              const pi = PROFILE_INFO[p.profile_id] || { short: p.profile_id, desc: "", icon: "shield" };
              const TierIcon = tc.icon;
              const isExpanded = expanded === p.profile_id;

              return (
                <button
                  key={p.profile_id}
                  onClick={() => setExpanded(isExpanded ? null : p.profile_id)}
                  className="rounded-lg text-left border-none cursor-pointer w-full"
                  style={{
                    background: T.surface,
                    border: `1px solid ${isExpanded ? tc.color + "44" : T.border}`,
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
                    style={{ background: tc.bg, border: `1px solid ${tc.color}22` }}
                  >
                    <TierIcon size={10} color={tc.color} />
                    <span className="font-mono font-bold" style={{ fontSize: FS.xs, color: tc.color }}>
                      {tc.label}
                    </span>
                  </div>

                  {/* Probability */}
                  <div className="font-mono font-bold" style={{ fontSize: 22, color: tc.color }}>
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
              const probs = result.profiles.map((p) => p.probability);
              const tiers = new Set(result.profiles.map((p) => p.tier));
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

          {/* CTA */}
          <div className="text-center mt-6 mb-8">
            <p style={{ fontSize: FS.sm, color: T.muted, marginBottom: 12 }}>
              This is a demo with default ownership assumptions. The full platform includes
              28-source OSINT enrichment, entity resolution, executive screening, and
              continuous monitoring.
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
