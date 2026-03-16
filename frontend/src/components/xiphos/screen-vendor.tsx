/**
 * Live Vendor Screening Form
 *
 * Type a vendor name + country, tweak risk parameters, hit Screen.
 * The Bayesian engine scores it in real time and produces a full case.
 * This is the feature that proves the engine is real.
 */

import { useState } from "react";
import { T } from "@/lib/tokens";
import { Search, Shield, ChevronDown, ChevronUp, Zap } from "lucide-react";
import { scoreVendor, type VendorInput, type ProgramType } from "@/lib/scoring";
import { screenName } from "@/lib/ofac";
import { TierBadge } from "./badges";
import { Gauge } from "./gauge";
import type { VettingCase } from "@/lib/types";

interface ScreenVendorProps {
  onAddCase: (c: VettingCase) => void;
}

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
      <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: 9, color: T.muted }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded outline-none font-mono"
        style={{
          padding: "6px 8px", fontSize: 11,
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
    <label className="flex items-center gap-2 cursor-pointer" style={{ fontSize: 11, color: T.dim }}>
      <div
        className="rounded-sm flex items-center justify-center"
        style={{
          width: 16, height: 16,
          background: checked ? T.accent : T.raised,
          border: `1px solid ${checked ? T.accent : T.border}`,
        }}
        onClick={() => onChange(!checked)}
      >
        {checked && <span style={{ fontSize: 10, color: "white" }}>&#10003;</span>}
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
        <span style={{ fontSize: 10, color: T.muted }}>{label}</span>
        <span className="font-mono" style={{ fontSize: 10, color: T.dim }}>{(value * 100).toFixed(0)}%</span>
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
  const [screening, setScreening] = useState<ReturnType<typeof screenName> | null>(null);

  const handleScreen = () => {
    if (!name.trim()) return;

    const input: VendorInput = {
      name: name.trim(),
      country,
      ownership: {
        publiclyTraded,
        stateOwned,
        beneficialOwnerKnown: boKnown,
        ownershipPctResolved: ownershipPct,
        shellLayers: shells,
        pepConnection: pep,
      },
      dataQuality: {
        hasLEI, hasCAGE, hasDUNS, hasTaxId,
        hasAuditedFinancials: hasAudit,
        yearsOfRecords: years,
      },
      exec: {
        knownExecs,
        adverseMedia,
        pepExecs,
        litigationHistory: litigation,
      },
      program,
    };

    const sr = scoreVendor(input);
    const scr = screenName(name.trim());
    setScreening(scr);

    const id = `c-${Date.now().toString(36)}`;
    const c: VettingCase = {
      id,
      name: name.trim(),
      cc: country,
      date: new Date().toISOString().split("T")[0],
      rl: sr.calibration.tier === "clear" ? "low" :
        sr.calibration.tier === "monitor" ? "medium" :
        sr.calibration.tier === "elevated" ? "elevated" : "critical",
      sc: sr.rubricScore,
      conf: sr.rubricConfidence,
      cal: sr.calibration,
    };

    setResult(c);
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
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
            Screen New Vendor
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_100px_160px_auto] gap-2 items-end">
          <div>
            <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: 9, color: T.muted }}>
              Vendor Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleScreen()}
              placeholder="e.g. Rostec Corporation"
              className="w-full rounded outline-none"
              style={{
                padding: "6px 10px", fontSize: 12,
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
            disabled={!name.trim()}
            className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
            style={{
              padding: "6px 16px", fontSize: 12,
              background: T.accent,
              opacity: name.trim() ? 1 : 0.4,
              height: 33, marginBottom: 0,
            }}
          >
            <Zap size={12} />
            Screen
          </button>
        </div>

        {/* Advanced parameters toggle */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer mt-3"
          style={{ fontSize: 10, color: T.muted }}
        >
          {showAdvanced ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          Advanced Parameters
        </button>

        {showAdvanced && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-3 pt-3" style={{ borderTop: `1px solid ${T.border}` }}>
            {/* Ownership */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: 9, color: T.accent }}>
                Ownership
              </div>
              <div className="flex flex-col gap-2">
                <Toggle label="Publicly traded" checked={publiclyTraded} onChange={setPubliclyTraded} />
                <Toggle label="State-owned" checked={stateOwned} onChange={setStateOwned} />
                <Toggle label="Beneficial owner known" checked={boKnown} onChange={setBoKnown} />
                <Toggle label="PEP connection" checked={pep} onChange={setPep} />
                <SliderField label="Ownership resolved" value={ownershipPct} onChange={setOwnershipPct} />
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: 10, color: T.muted }}>Shell layers</span>
                  <input
                    type="number" min={0} max={5} value={shells}
                    onChange={(e) => setShells(parseInt(e.target.value) || 0)}
                    className="rounded outline-none font-mono"
                    style={{
                      width: 50, padding: "3px 6px", fontSize: 11,
                      background: T.raised, color: T.text,
                      border: `1px solid ${T.border}`,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Data Quality */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: 9, color: T.accent }}>
                Data Quality
              </div>
              <div className="flex flex-col gap-2">
                <Toggle label="LEI" checked={hasLEI} onChange={setHasLEI} />
                <Toggle label="CAGE code" checked={hasCAGE} onChange={setHasCAGE} />
                <Toggle label="DUNS number" checked={hasDUNS} onChange={setHasDUNS} />
                <Toggle label="Tax ID" checked={hasTaxId} onChange={setHasTaxId} />
                <Toggle label="Audited financials" checked={hasAudit} onChange={setHasAudit} />
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: 10, color: T.muted }}>Years of records</span>
                  <input
                    type="number" min={0} max={100} value={years}
                    onChange={(e) => setYears(parseInt(e.target.value) || 0)}
                    className="rounded outline-none font-mono"
                    style={{
                      width: 50, padding: "3px 6px", fontSize: 11,
                      background: T.raised, color: T.text,
                      border: `1px solid ${T.border}`,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Executive */}
            <div>
              <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: 9, color: T.accent }}>
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
                    <span style={{ fontSize: 10, color: T.muted }}>{f.label}</span>
                    <input
                      type="number" min={0} max={f.max} value={f.value}
                      onChange={(e) => f.set(parseInt(e.target.value) || 0)}
                      className="rounded outline-none font-mono"
                      style={{
                        width: 50, padding: "3px 6px", fontSize: 11,
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
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: screening.matched ? T.red : T.green }}>
              OFAC / Sanctions Screening
            </span>
          </div>
          {screening.matched ? (
            <div>
              <div className="font-semibold" style={{ fontSize: 12, color: T.red }}>
                MATCH FOUND
              </div>
              {screening.allMatches.map((m, i) => (
                <div key={i} className="mt-2 rounded p-2" style={{ background: "rgba(239,68,68,0.06)" }}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium" style={{ fontSize: 11, color: T.text }}>
                      {m.matchedOn}
                    </span>
                    <span className="font-mono font-bold" style={{ fontSize: 12, color: T.red }}>
                      {(m.score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                    {m.entry.list} | {m.entry.program} | {m.entry.country}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div>
              <div className="font-semibold" style={{ fontSize: 12, color: T.green }}>NO MATCHES</div>
              <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                Screened against OFAC SDN, Entity List, CAATSA, SSI, FSE databases.
                {screening.bestScore > 0.5 && (
                  <span> Closest match: "{screening.matchedName}" at {(screening.bestScore * 100).toFixed(0)}% (below threshold).</span>
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
              <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
                Assessment Result
              </span>
              <TierBadge tier={result.cal.tier} />
            </div>
            <button
              onClick={handleAdd}
              className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
              style={{ padding: "5px 12px", fontSize: 11, background: T.green }}
            >
              + Add to Portfolio
            </button>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="flex flex-col items-center">
              <Gauge value={result.cal.p} lo={result.cal.lo} hi={result.cal.hi} />
              <span className="font-mono mt-1" style={{ fontSize: 9, color: T.muted }}>Bayesian Posterior</span>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.text }}>
                {result.sc}
              </div>
              <div className="font-mono" style={{ fontSize: 9, color: T.muted }}>/100 Policy Rubric</div>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.muted }}>
                {Math.round(result.cal.lo * 100)}%&ndash;{Math.round(result.cal.hi * 100)}%
              </div>
              <div className="font-mono" style={{ fontSize: 9, color: T.muted }}>95% CI</div>
            </div>
            <div className="text-center">
              <div className="font-mono font-bold" style={{ fontSize: 24, color: T.text }}>
                {Math.round(result.cal.cov * 100)}%
              </div>
              <div className="font-mono" style={{ fontSize: 9, color: T.muted }}>Coverage</div>
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
                  <div className="font-bold" style={{ fontSize: 11, color: T.dRed }}>{s.t}</div>
                  <div style={{ fontSize: 10, color: T.red, marginTop: 1 }}>{s.x}</div>
                </div>
              ))}
            </div>
          )}

          {/* Factor contributions */}
          <div className="mt-3">
            <div className="font-mono uppercase tracking-wider mb-2" style={{ fontSize: 9, color: T.muted }}>
              Factor Contributions
            </div>
            {[...result.cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s)).map((ct, i) => (
              <div
                key={i}
                className="flex items-center justify-between"
                style={{ padding: "4px 0", borderBottom: `1px solid ${T.border}` }}
              >
                <span style={{ fontSize: 11, color: T.dim }}>{ct.n}</span>
                <div className="flex items-center gap-3">
                  <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                    {(ct.raw * 100).toFixed(0)}/100
                  </span>
                  <span
                    className="font-mono font-semibold"
                    style={{
                      fontSize: 11, minWidth: 60, textAlign: "right",
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
              <div className="font-mono uppercase tracking-wider mb-1" style={{ fontSize: 9, color: T.muted }}>
                Key Findings
              </div>
              {result.cal.finds.map((f, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: 3 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: 10, color: T.accent }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: 11, color: T.dim, lineHeight: 1.4 }}>{f}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
