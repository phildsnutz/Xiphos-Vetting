import { useState, useCallback } from "react";
import { T, FS } from "@/lib/tokens";
import {
  Shield, ChevronRight, ChevronLeft, Search, Globe,
  Building2, Users, FileCheck, Zap, CheckCircle,
} from "lucide-react";
import type { VettingCase } from "@/lib/types";

/* ---- Step definitions ---- */
const STEPS = [
  { id: "welcome", title: "Welcome to Xiphos", icon: Shield },
  { id: "entity", title: "Enter a Vendor", icon: Building2 },
  { id: "ownership", title: "Ownership Details", icon: Users },
  { id: "profile", title: "Choose a Profile", icon: FileCheck },
  { id: "scoring", title: "View Results", icon: Zap },
] as const;

type StepId = (typeof STEPS)[number]["id"];

/* ---- Country options (subset) ---- */
const TOP_COUNTRIES = [
  { code: "US", label: "United States" }, { code: "GB", label: "United Kingdom" },
  { code: "CN", label: "China" }, { code: "RU", label: "Russia" },
  { code: "DE", label: "Germany" }, { code: "FR", label: "France" },
  { code: "JP", label: "Japan" }, { code: "KR", label: "South Korea" },
  { code: "IN", label: "India" }, { code: "IL", label: "Israel" },
  { code: "CA", label: "Canada" }, { code: "AU", label: "Australia" },
  { code: "TR", label: "Turkey" }, { code: "IR", label: "Iran" },
  { code: "BR", label: "Brazil" }, { code: "SA", label: "Saudi Arabia" },
  { code: "TW", label: "Taiwan" }, { code: "SG", label: "Singapore" },
  { code: "AE", label: "UAE" }, { code: "MX", label: "Mexico" },
];

/* ---- Profile options ---- */
const PROFILES = [
  {
    id: "defense_acquisition", name: "Defense Acquisition",
    desc: "DFARS/ITAR-adjacent procurement for DoD contractors",
    color: "#ef4444",
  },
  {
    id: "itar_trade_compliance", name: "ITAR/Export Control",
    desc: "International Traffic in Arms Regulations and EAR controls",
    color: "#f97316",
  },
  {
    id: "university_research_security", name: "Research Security",
    desc: "University/lab foreign influence and talent program screening",
    color: "#8b5cf6",
  },
  {
    id: "grants_compliance", name: "Grants Compliance",
    desc: "Federal grants, FAPIIS, debarment, Do Not Pay checks",
    color: "#3b82f6",
  },
  {
    id: "commercial_supply_chain", name: "Supply Chain",
    desc: "Commercial vendor compliance, regulatory, ESG",
    color: "#22c55e",
  },
];

interface OnboardingWizardProps {
  onComplete: (caseData: {
    name: string;
    country: string;
    profile: string;
    ownership: Record<string, unknown>;
  }) => void;
  onSkip: () => void;
}

export function OnboardingWizard({ onComplete, onSkip }: OnboardingWizardProps) {
  const [stepIdx, setStepIdx] = useState(0);
  const [name, setName] = useState("");
  const [country, setCountry] = useState("US");
  const [publiclyTraded, setPubliclyTraded] = useState(false);
  const [stateOwned, setStateOwned] = useState(false);
  const [profile, setProfile] = useState("defense_acquisition");

  const step = STEPS[stepIdx];
  const canNext = stepIdx === 0 || (stepIdx === 1 && name.trim().length >= 2) || stepIdx >= 2;

  const handleNext = () => {
    if (stepIdx < STEPS.length - 1) {
      setStepIdx(stepIdx + 1);
    } else {
      onComplete({
        name: name.trim(),
        country,
        profile,
        ownership: {
          publicly_traded: publiclyTraded,
          state_owned: stateOwned,
          beneficial_owner_known: true,
          ownership_pct_resolved: 0.85,
          shell_layers: 0,
          pep_connection: false,
        },
      });
    }
  };

  const handleBack = () => {
    if (stepIdx > 0) setStepIdx(stepIdx - 1);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center" style={{ padding: 24 }}>
      {/* Progress dots */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            className="rounded-full transition-all duration-300"
            style={{
              width: i === stepIdx ? 24 : 8,
              height: 8,
              background: i <= stepIdx ? T.accent : T.border,
            }}
          />
        ))}
      </div>

      {/* Step card */}
      <div
        className="rounded-xl w-full"
        style={{
          maxWidth: 520,
          background: T.surface,
          border: `1px solid ${T.border}`,
          padding: 32,
        }}
      >
        {/* Step 0: Welcome */}
        {step.id === "welcome" && (
          <div className="text-center">
            <Shield size={40} color={T.accent} className="mx-auto mb-4" />
            <h2 style={{ fontSize: 22, color: T.text, fontWeight: 700, margin: "0 0 8px" }}>
              Welcome to Xiphos
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.7, margin: "0 0 24px" }}>
              Let's walk through creating your first vendor case. In about 60 seconds you'll
              have a full risk assessment powered by Bayesian inference, sanctions screening,
              and multi-vertical compliance profiles.
            </p>
            <div className="grid grid-cols-3 gap-3 text-center">
              {[
                { n: "28", l: "OSINT Sources" },
                { n: "5", l: "Profiles" },
                { n: "<20s", l: "Full Score" },
              ].map((stat) => (
                <div key={stat.l} className="rounded-lg p-3" style={{ background: T.raised }}>
                  <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.accent }}>
                    {stat.n}
                  </div>
                  <div style={{ fontSize: "9px", color: T.muted }}>{stat.l}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 1: Entity name & country */}
        {step.id === "entity" && (
          <div>
            <h2 style={{ fontSize: 18, color: T.text, fontWeight: 700, margin: "0 0 4px" }}>
              Who are you vetting?
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.6, margin: "0 0 20px" }}>
              Enter the vendor or entity name and their country of incorporation.
            </p>

            <label style={{ fontSize: FS.xs, color: T.muted, fontWeight: 600, display: "block", marginBottom: 6 }}>
              Vendor Name
            </label>
            <div className="flex items-center rounded-lg overflow-hidden mb-4" style={{ border: `1px solid ${T.border}` }}>
              <div className="px-3 flex items-center" style={{ background: T.raised }}>
                <Building2 size={14} color={T.muted} />
              </div>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Huawei Technologies"
                className="flex-1 outline-none bg-transparent border-none"
                style={{ padding: "12px 14px", fontSize: FS.sm, color: T.text }}
                autoFocus
              />
            </div>

            <label style={{ fontSize: FS.xs, color: T.muted, fontWeight: 600, display: "block", marginBottom: 6 }}>
              Country of Incorporation
            </label>
            <div className="flex items-center rounded-lg overflow-hidden" style={{ border: `1px solid ${T.border}` }}>
              <div className="px-3 flex items-center" style={{ background: T.raised }}>
                <Globe size={14} color={T.muted} />
              </div>
              <select
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                className="flex-1 outline-none bg-transparent border-none cursor-pointer"
                style={{ padding: "12px 14px", fontSize: FS.sm, color: T.text }}
              >
                {TOP_COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>{c.label} ({c.code})</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Step 2: Ownership */}
        {step.id === "ownership" && (
          <div>
            <h2 style={{ fontSize: 18, color: T.text, fontWeight: 700, margin: "0 0 4px" }}>
              Ownership structure
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.6, margin: "0 0 20px" }}>
              These inputs help calibrate ownership risk. You can refine later.
            </p>

            {[
              { label: "Publicly traded?", desc: "Listed on a regulated stock exchange", value: publiclyTraded, set: setPubliclyTraded },
              { label: "State-owned?", desc: "Government entity or SOE", value: stateOwned, set: setStateOwned },
            ].map((item) => (
              <button
                key={item.label}
                onClick={() => item.set(!item.value)}
                className="w-full flex items-center justify-between rounded-lg mb-2 border-none cursor-pointer"
                style={{
                  padding: "14px 16px",
                  background: item.value ? T.accent + "12" : T.raised,
                  border: `1px solid ${item.value ? T.accent + "44" : T.border}`,
                  textAlign: "left",
                }}
              >
                <div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>{item.label}</div>
                  <div style={{ fontSize: FS.xs, color: T.muted }}>{item.desc}</div>
                </div>
                <div
                  className="rounded-full flex items-center justify-center shrink-0"
                  style={{
                    width: 20, height: 20,
                    background: item.value ? T.accent : T.border,
                    transition: "background 0.2s",
                  }}
                >
                  {item.value && <CheckCircle size={12} color="#fff" />}
                </div>
              </button>
            ))}

            <div
              className="rounded-lg mt-4 p-3"
              style={{ background: T.raised, border: `1px solid ${T.border}` }}
            >
              <div style={{ fontSize: FS.xs, color: T.muted, lineHeight: 1.5 }}>
                Default assumptions: Beneficial ownership known, 85% resolved, no shell layers,
                no PEP connections. These can all be adjusted after scoring.
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Profile selection */}
        {step.id === "profile" && (
          <div>
            <h2 style={{ fontSize: 18, color: T.text, fontWeight: 700, margin: "0 0 4px" }}>
              Which compliance profile?
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.6, margin: "0 0 16px" }}>
              Each profile applies different risk weights and thresholds. You can compare
              across profiles later.
            </p>

            {PROFILES.map((p) => (
              <button
                key={p.id}
                onClick={() => setProfile(p.id)}
                className="w-full flex items-center gap-3 rounded-lg mb-2 border-none cursor-pointer"
                style={{
                  padding: "12px 14px",
                  background: profile === p.id ? p.color + "12" : T.raised,
                  border: `1px solid ${profile === p.id ? p.color + "44" : T.border}`,
                  textAlign: "left",
                }}
              >
                <div
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ background: profile === p.id ? p.color : T.border }}
                />
                <div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>{p.name}</div>
                  <div style={{ fontSize: FS.xs, color: T.muted }}>{p.desc}</div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Step 4: Ready to score */}
        {step.id === "scoring" && (
          <div className="text-center">
            <Zap size={36} color={T.accent} className="mx-auto mb-4" />
            <h2 style={{ fontSize: 18, color: T.text, fontWeight: 700, margin: "0 0 8px" }}>
              Ready to score
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.6, margin: "0 0 20px" }}>
              We'll create a case for <strong style={{ color: T.text }}>{name}</strong> ({country}) under
              the <strong style={{ color: T.text }}>{PROFILES.find((p) => p.id === profile)?.name}</strong> profile,
              run sanctions screening, compute Bayesian risk scores, and present your results.
            </p>

            <div
              className="rounded-lg p-4 text-left"
              style={{ background: T.raised, border: `1px solid ${T.border}` }}
            >
              {[
                { l: "Entity", v: `${name} (${country})` },
                { l: "Profile", v: PROFILES.find((p) => p.id === profile)?.name },
                { l: "Public", v: publiclyTraded ? "Yes" : "No" },
                { l: "State-owned", v: stateOwned ? "Yes" : "No" },
              ].map((row) => (
                <div
                  key={row.l}
                  className="flex justify-between py-1.5"
                  style={{ borderBottom: `1px solid ${T.border}22`, fontSize: FS.sm }}
                >
                  <span style={{ color: T.muted }}>{row.l}</span>
                  <span className="font-mono" style={{ color: T.text }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Navigation buttons */}
        <div className="flex items-center justify-between mt-6 pt-4" style={{ borderTop: `1px solid ${T.border}` }}>
          <div>
            {stepIdx > 0 ? (
              <button
                onClick={handleBack}
                className="flex items-center gap-1 rounded px-3 py-2 cursor-pointer border-none"
                style={{ fontSize: FS.sm, color: T.muted, background: "transparent" }}
              >
                <ChevronLeft size={14} /> Back
              </button>
            ) : (
              <button
                onClick={onSkip}
                className="rounded px-3 py-2 cursor-pointer border-none"
                style={{ fontSize: FS.sm, color: T.muted, background: "transparent" }}
              >
                Skip tutorial
              </button>
            )}
          </div>
          <button
            onClick={handleNext}
            disabled={!canNext}
            className="flex items-center gap-1 rounded-lg px-5 py-2.5 cursor-pointer border-none font-semibold"
            style={{
              fontSize: FS.sm,
              background: canNext ? T.accent : T.raised,
              color: canNext ? "#fff" : T.muted,
              opacity: canNext ? 1 : 0.5,
            }}
          >
            {stepIdx === STEPS.length - 1 ? "Create Case & Score" : "Continue"}
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
