/**
 * Live Vendor Screening Form
 *
 * Type a vendor name + country, tweak risk parameters, hit Screen.
 * Creates a real case on the backend, scores via the Bayesian engine,
 * and screens against the full 31K+ sanctions database.
 *
 * One-click workflow: Screen -> Auto-Enrich -> Auto-Analyze
 */

import { useState } from "react";
import { T, FS } from "@/lib/tokens";
import { Search, Shield, ChevronDown, ChevronUp, Zap, Loader2, Radar, Brain } from "lucide-react";
import { createCase, screenVendor, enrichAndScore, runAIAnalysis } from "@/lib/api";
import type { CreateCasePayload, ScreeningResult as ApiScreeningResult } from "@/lib/api";
import { TierBadge } from "./badges";
import { Gauge } from "./gauge";
import type { VettingCase, Calibration } from "@/lib/types";
import type { TierKey } from "@/lib/tokens";

interface ScreenVendorProps {
  onAddCase: (c: VettingCase) => void;
}

type ProgramType =
  | "weapons_system"
  | "mission_critical"
  | "dual_use"
  | "standard_industrial"
  | "commercial_off_shelf"
  | "services";

const COUNTRIES = [
  "US", "GB", "DE", "FR", "CA", "AU", "JP", "KR", "IL", "SE",
  "NL", "NO", "IT", "ES", "PL", "TW", "SG", "IN", "BR", "MX",
  "TR", "AE", "SA", "AZ", "PK", "VN", "EG", "NG", "CN", "RU",
  "IR", "KP", "SY", "CU", "BY", "VE", "MM", "AF",
];

const PROGRAMS: { value: ProgramType; label: string }[] = [
  { value: "weapons_system", label: "Weapons System" },
  { value: "mission_critical", label: "Mission Critical" },
  { value: "dual_use", label: "Dual Use" },
  { value: "standard_industrial", label: "Standard Industrial" },
  { value: "commercial_off_shelf", label: "COTS" },
  { value: "services", label: "Services" },
];

function SelectField({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: FS.xs, color: T.muted }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded outline-none font-mono"
        style={{
          padding: "6px 8px", fontSize: FS.sm,
          background: T.raised, color: T.text,
          border: `1px solid ${T.border}`,
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

function Toggle({
  label, checked, onChange,
}: {
  label: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer" style={{ fontSize: FS.sm, color: T.dim }}>
      <div
        className="rounded-sm flex items-center justify-center"
        style={{
          width: 16, height: 16,
          background: checked ? T.accent : T.raised,
          border: `1px solid ${checked ? T.accent : T.border}`,
        }}
        onClick={() => onChange(!checked)}
      >
        {checked && <span style={{ fontSize: FS.xs, color: "white" }}>&#10003;</span>}
      </div>
      {label}
    </label>
  );
}

function SliderField({
  label, value, onChange, min = 0, max = 1, step = 0.05,
}: {
  label: string; value: number; onChange: (v: number) => void;
  min?: number; max?: number; step?: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span style={{ fontSize: FS.xs, color: T.muted }}>{label}</span>
        <span className="font-mono" style={{ fontSize: FS.xs, color: T.dim }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full"
        style={{ accentColor: T.accent, height: 4 }}
      />
    </div>
  );
}

/** Convert backend calibration response to our Calibration type */
function mapBackendCalibration(apiCal: Record<string, unknown>): Calibration {
  const cal = apiCal as {
    calibrated_probability: number;
    calibrated_tier: string;
    interval: { lower: number; upper: number; coverage: number };
    contributions: Array<{
      factor: string; raw_score: number; confidence: number;
      signed_contribution: number; description: string;
    }>;
    hard_stop_decisions: Array<{ trigger: string; explanation: string; confidence: number }>;
    soft_flags: Array<{ trigger: string; explanation: string; confidence: number }>;
    narratives: { findings: string[] };
    marginal_information_values: Array<{
      recommendation: string; expected_info_gain_pp: number; tier_change_probability: number;
    }>;
  };

  const meanConf = cal.contributions.length > 0
    ? cal.contributions.reduce((s, c) => s + c.confidence, 0) / cal.contributions.length : 0;

  return {
    p: cal.calibrated_probability,
    tier: cal.calibrated_tier as TierKey,
    lo: cal.interval.lower,
    hi: cal.interval.upper,
    cov: cal.interval.coverage,
    mc: meanConf,
    ct: cal.contributions.map((c) => ({
      n: c.factor, raw: c.raw_score, c: c.confidence, s: c.signed_contribution, d: c.description,
    })),
    stops: cal.hard_stop_decisions.map((h) => ({ t: h.trigger, x: h.explanation, c: h.confidence })),
    flags: cal.soft_flags.map((f) => ({ t: f.trigger, x: f.explanation, c: f.confidence })),
    finds: cal.narratives?.findings ?? [],
    miv: (cal.marginal_information_values ?? []).map((m) => ({
      t: m.recommendation, i: m.expected_info_gain_pp, tp: m.tier_change_probability,
    })),
  };
}

export function ScreenVendor({ onAddCase }: ScreenVendorProps) {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("US");
  const [program, setProgram] = useState<ProgramType>("standard_industrial");
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Ownership
  const [publiclyTraded, setPubliclyTraded] = useState(false);
  const [stateOwned, setStateOwned] = useState(false);
  const [boKnown, setBoKnown] = useState(true);
  const [ownershipPct, setOwnershipPct] = useState(0.85);
  const [shells, setShells] = useState(0);
  const [pep, setPep] = useState(false);

  // Data quality
  const [hasLEI, setHasLEI] = useState(true);
  const [hasCAGE, setHasCAGE] = useState(false);
  const [hasDUNS, setHasDUNS] = useState(true);
  const [hasTaxId, setHasTaxId] = useState(true);
  const [hasAudit, setHasAudit] = useState(true);
  const [years, setYears] = useState(10);

  // Executive
  const [knownExecs, setKnownExecs] = useState(5);
  const [adverseMedia, setAdverseMedia] = useState(0);
  const [pepExecs, setPepExecs] = useState(0);
  const [litigation, setLitigation] = useState(0);

  // Result
  const [result, setResult] = useState<VettingCase | null>(null);
  const [screening, setScreening] = useState<ApiScreeningResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pipeline status
  const [pipelineStep, setPipelineStep] = useState<string | null>(null);
  const [autoEnrich, setAutoEnrich] = useState(true);
  const [autoAnalyze, setAutoAnalyze] = useState(true);

  const handleScreen = async () => {
    if (!name.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setScreening(null);
    setPipelineStep("Screening against 31K+ sanctions entities...");

    try {
      // Step 1: Backend sanctions screening (31K entities)
      const scrResult = await screenVendor(name.trim());
      setScreening(scrResult);

      // Step 2: Create case on backend with full scoring
      setPipelineStep("Creating case and running Bayesian scoring...");
      const payload: CreateCasePayload = {
        name: name.trim(),
        country,
        ownership: {
          publicly_traded: publiclyTraded,
          state_owned: stateOwned,
          beneficial_owner_known: boKnown,
          ownership_pct_resolved: ownershipPct,
          shell_layers: shells,
          pep_connection: pep,
        },
        data_quality: {
          has_lei: hasLEI,
          has_cage: hasCAGE,
          has_duns: hasDUNS,
          has_tax_id: hasTaxId,
          has_audited_financials: hasAudit,
          years_of_records: years,
        },
        exec: {
          known_execs: knownExecs,
          adverse_media: adverseMedia,
          pep_execs: pepExecs,
          litigation_history: litigation,
        },
        program,
      };

      const caseResult = await createCase(payload);

      // Map calibrated result to our Calibration type
      const cal = mapBackendCalibration(caseResult.calibrated);
      const mc = cal.ct.length > 0 ? cal.ct.reduce((s, c) => s + c.c, 0) / cal.ct.length : 0;

      const c: VettingCase = {
        id: caseResult.case_id,
        name: name.trim(),
        cc: country,
        date: new Date().toISOString().split("T")[0],
        rl: cal.tier === "clear" ? "low" :
          cal.tier === "monitor" ? "medium" :
          cal.tier === "elevated" ? "elevated" : "critical",
        sc: caseResult.composite_score,
        conf: mc,
        cal,
      };

      setResult(c);

      // Step 3: Auto-enrich if enabled (runs OSINT across 17 connectors)
      if (autoEnrich) {
        setPipelineStep("Running OSINT enrichment across 17 connectors...");
        try {
          await enrichAndScore(caseResult.case_id);
          setPipelineStep(autoAnalyze ? "Running AI analysis..." : null);
        } catch {
          // Enrichment is non-blocking; case is already scored
          setPipelineStep(null);
        }
      }

      // Step 4: Auto-analyze if enabled
      if (autoAnalyze) {
        setPipelineStep("Running AI risk analysis...");
        try {
          await runAIAnalysis(caseResult.case_id);
        } catch {
          // AI analysis is non-blocking
        }
      }

      setPipelineStep(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Screening failed. Check API connection.");
      setPipelineStep(null);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    if (result) {
      onAddCase(result);
      setResult(null);
      setScreening(null);
      setName("");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Input form */}
      <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2 mb-3">
          <Shield size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
            Screen New Vendor
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_100px_160px_auto] gap-2 items-end">
          <div>
            <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: FS.xs, color: T.muted }}>
              Vendor Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && handleScreen()}
              placeholder="e.g. Rostec Corporation"
              className="w-full rounded outline-none"
              style={{
                padding: "6px 10px", fontSize: FS.sm,
                background: T.raised, color: T.text,
                border: `1px solid ${T.border}`,
              }}
            />
          </div>
          <SelectField
            label="Country"
            value={country}
            onChange={(v) => setCountry(v)}
            options={COUNTRIES.map((c) => ({ value: c, label: c }))}
          />
          <SelectField
            label="Program"
            value={program}
            onChange={(v) => setProgram(v as ProgramType)}
            options={PROGRAMS}
          />
          <button
            onClick={handleScreen}
            disabled={!name.trim() || loading}
            className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
            style={{
              padding: "6px 16px", fontSize: FS.sm,
              background: T.accent,
              opacity: name.trim() && !loading ? 1 : 0.4,
              height: 33, marginBottom: 0,
            }}
          >
            {loading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
            {loading ? "Running..." : "Screen"}
          </button>
        </div>

        {/* Automation toggles */}
        <div className="flex items-center gap-4 mt-3">
          <label className="flex items-center gap-1.5 cursor-pointer" style={{ fontSize: FS.xs, color: T.dim }}>
            <div
              className="rounded-sm flex items-center justify-center"
              style={{
                width: 14, height: 14,
                background: autoEnrich ? T.accent : T.raised,
                border: `1px solid ${autoEnrich ? T.accent : T.border}`,
              }}
              onClick={() => setAutoEnrich(!autoEnrich)}
            >
              {autoEnrich && <span style={{ fontSize: FS.xs, color: "white" }}>&#10003;</span>}
            </div>
            <Radar size={10} /> Auto-Enrich (OSINT)
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer" style={{ fontSize: FS.xs, color: T.dim }}>
            <div
              className="rounded-sm flex items-center justify-center"
              style={{
                width: 14, height: 14,
                background: autoAnalyze ? "#8b5cf6" : T.raised,
                border: `1px solid ${autoAnalyze ? "#8b5cf6" : T.border}`,
              }}
              onClick={() => setAutoAnalyze(!autoAnalyze)}
            >
              {autoAnalyze && <span style={{ fontSize: FS.xs, color: "white" }}>&#10003;</span>}
            </div>
            <Brain size={10} /> Auto-Analyze (AI)
          </label>
        </div>

        {/* Advanced parameters toggle */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer mt-3"
          style={{ fontSize: FS.xs, color: T.muted }}
        >
          {showAdvanced ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          Advanced Parameters
        </button>

        {showAdvanced && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-3 pt-3" style={{ borderTop: `1px solid ${T.border}` }}>
            {/* Ownership */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: FS.xs, color: T.accent }}>
                Ownership
              </div>
              <div className="flex flex-col gap-2">
                <Toggle label="Publicly traded" checked={publiclyTraded} onChange={setPubliclyTraded} />
                <Toggle label="State-owned" checked={stateOwned} onChange={setStateOwned} />
                <Toggle label="Beneficial owner known" checked={boKnown} onChange={setBoKnown} />
                <Toggle label="PEP connection" checked={pep} onChange={setPep} />
                <SliderField label="Ownership resolved" value={ownershipPct} onChange={setOwnershipPct} />
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: FS.xs, color: T.muted }}>Shell layers</span>
                  <input
                    type="number" min={0} max={5} value={shells}
                    onChange={(e) => setShells(parseInt(e.target.value) || 0)}
                    className="rounded outline-none font-mono"
                    style={{
                      width: 50, padding: "3px 6px", fontSize: FS.sm,
                      background: T.raised, color: T.text,
                      border: `1px solid ${T.border}`,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Data Quality */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: FS.xs, color: T.accent }}>
                Data Quality
              </div>
              <div className="flex flex-col gap-2">
                <Toggle label="LEI" checked={hasLEI} onChange={setHasLEI} />
                <Toggle label="CAGE code" checked={hasCAGE} onChange={setHasCAGE} />
                <Toggle label="DUNS number" checked={hasDUNS} onChange={setHasDUNS} />
                <Toggle label="Tax ID" checked={hasTaxId} onChange={setHasTaxId} />
                <Toggle label="Audited financials" checked={hasAudit} onChange={setHasAudit} />
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: FS.xs, color: T.muted }}>Years of records</span>
                  <input
                    type="number" min={0} max={100} value={years}
                    onChange={(e) => setYears(parseInt(e.target.value) || 0)}
                    className="rounded outline-none font-mono"
                    style={{
                      width: 50, padding: "3px 6px", fontSize: FS.sm,
                      background: T.raised, color: T.text,
                      border: `1px solid ${T.border}`,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Executive */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: FS.xs, color: T.accent }}>
                Executive Risk
              </div>
              <div className="flex flex-col gap-2">
                {[
                  { label: "Known executives", value: knownExecs, set: setKnownExecs, max: 30 },
                  { label: "Adverse media hits", value: adverseMedia, set: setAdverseMedia, max: 10 },
                  { label: "PEP executives", value: pepExecs, set: setPepExecs, max: 10 },
                  { label: "Litigation events", value: litigation, set: setLitigation, max: 10 },
                ].map((f) => (
                  <div key={f.label} className="flex items-center justify-between">
                    <span style={{ fontSize: FS.xs, color: T.muted }}>{f.label}</span>
                    <input
                      type="number" min={0} max={f.max} value={f.value}
                      onChange={(e) => f.set(parseInt(e.target.value) || 0)}
                      className="rounded outline-none font-mono"
                      style={{
                        width: 50, padding: "3px 6px", fontSize: FS.sm,
                        background: T.raised, color: T.text,
                        border: `1px solid ${T.border}`,
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Pipeline status indicator */}
      {pipelineStep && (
        <div
          className="rounded-lg flex items-center gap-3 p-3"
          style={{ background: T.accent + "11", border: `1px solid ${T.accent}33` }}
        >
          <Loader2 size={14} color={T.accent} className="animate-spin shrink-0" />
          <span className="font-mono" style={{ fontSize: FS.sm, color: T.accent }}>{pipelineStep}</span>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div
          className="rounded-lg p-3"
          style={{ background: "rgba(239,68,68,0.08)", border: `1px solid ${T.red}44` }}
        >
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      {/* OFAC Screening Result */}
      {screening && (
        <div
          className="rounded-lg p-4"
          style={{
            background: screening.matched
              ? "rgba(239,68,68,0.08)"
              : "rgba(16,185,129,0.08)",
            border: `1px solid ${screening.matched ? T.red + "44" : T.green + "44"}`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Search size={12} color={screening.matched ? T.red : T.green} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: screening.matched ? T.red : T.green }}>
              Sanctions Screening
            </span>
            {screening.screening_db && (
              <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                {screening.screening_db} | {screening.screening_ms}ms
              </span>
            )}
          </div>
          {screening.matched ? (
            <div>
              <div className="font-semibold" style={{ fontSize: FS.sm, color: T.red }}>
                MATCH FOUND
              </div>
              {screening.all_matches.map((m, i) => (
                <div key={i} className="mt-2 rounded p-2" style={{ background: "rgba(239,68,68,0.06)" }}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>
                      {m.matched_on}
                    </span>
                    <span className="font-mono font-bold" style={{ fontSize: FS.sm, color: T.red }}>
                      {(m.score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                    {m.list} | {m.name} | {m.source}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div>
              <div className="font-semibold" style={{ fontSize: FS.sm, color: T.green }}>NO MATCHES</div>
              <div style={{ fontSize: FS.xs, color: T.muted, marginTop: 2 }}>
                Screened against {screening.screening_db || "OFAC SDN, Entity List, CAATSA, SSI, UK, EU, UN"} databases.
                {screening.best_score > 0.5 && (
                  <span> Closest match: "{screening.matched_name}" at {(screening.best_score * 100).toFixed(0)}% (below threshold).</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Scoring Result */}
      {result && result.cal && (
        <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                Assessment Result
              </span>
              <TierBadge tier={result.cal.tier} />
            </div>
            <button
              onClick={handleAdd}
              className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
              style={{ padding: "5px 12px", fontSize: FS.sm, background: T.green }}
            >
              + Add to Portfolio
            </button>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="flex flex-col items-center">
              <Gauge value={result.cal.p} lo={result.cal.lo} hi={result.cal.hi} />
              <span className="font-mono mt-1" style={{ fontSize: FS.xs, color: T.muted }}>Bayesian Posterior</span>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.text }}>
                {result.sc}
              </div>
              <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>/100 Policy Rubric</div>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.muted }}>
                {Math.round(result.cal.lo * 100)}%&ndash;{Math.round(result.cal.hi * 100)}%
              </div>
              <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>95% CI</div>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.text }}>
                {Math.round(result.cal.cov * 100)}%
              </div>
              <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>Coverage</div>
            </div>
          </div>

          {/* Hard stops */}
          {result.cal.stops.length > 0 && (
            <div
              className="mt-3 rounded p-3"
              style={{ background: "rgba(220,38,38,0.12)", border: `1px solid rgba(220,38,38,0.3)` }}
            >
              {result.cal.stops.map((s, i) => (
                <div key={i}>
                  <div className="font-bold" style={{ fontSize: FS.sm, color: T.dRed }}>{s.t}</div>
                  <div style={{ fontSize: FS.xs, color: T.red, marginTop: 1 }}>{s.x}</div>
                </div>
              ))}
            </div>
          )}

          {/* Factor contributions */}
          <div className="mt-3">
            <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: FS.xs, color: T.muted }}>
              Factor Contributions
            </div>
            {[...result.cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s)).map((ct, i) => (
              <div
                key={i}
                className="flex items-center justify-between"
                style={{ padding: "4px 0", borderBottom: `1px solid ${T.border}` }}
              >
                <span style={{ fontSize: FS.sm, color: T.dim }}>{ct.n}</span>
                <div className="flex items-center gap-3">
                  <span className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                    {(ct.raw * 100).toFixed(0)}/100
                  </span>
                  <span
                    className="font-mono font-semibold"
                    style={{
                      fontSize: FS.sm, minWidth: 60, textAlign: "right",
                      color: ct.s > 0 ? T.red : ct.s < 0 ? T.green : T.muted,
                    }}
                  >
                    {ct.s > 0 ? "+" : ""}{(ct.s * 100).toFixed(1)} pp
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Key findings */}
          {result.cal.finds.length > 0 && (
            <div className="mt-3">
              <div className="font-mono uppercase tracking-wider mb-1" style={{ fontSize: FS.xs, color: T.muted }}>
                Key Findings
              </div>
              {result.cal.finds.map((f, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: 3 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.xs, color: T.accent }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.4 }}>{f}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
