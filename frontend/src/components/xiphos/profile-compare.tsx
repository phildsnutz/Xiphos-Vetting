/**
 * Profile Comparison Component
 *
 * Allows analysts to screen the same entity against multiple compliance profiles
 * side-by-side to understand how regulatory frameworks differ in their risk assessment.
 */

import { useState, useEffect } from "react";
import { T, FS, SP } from "@/lib/tokens";
import { compareProfiles, fetchProfiles } from "@/lib/api";
import type { CompareResult, ComplianceProfile } from "@/lib/api";
import { Loader2, BarChart3, ChevronDown, ChevronUp, Globe, GraduationCap, Landmark, Package, Shield } from "lucide-react";
import { TierBadge } from "./badges";

interface ProfileCompareProps {
  onClose?: () => void;
}

function getProfileIcon(profileId: string) {
  switch (profileId) {
    case "itar_trade_compliance":
      return <Globe size={16} />;
    case "university_research_security":
      return <GraduationCap size={16} />;
    case "grants_compliance":
      return <Landmark size={16} />;
    case "commercial_supply_chain":
      return <Package size={16} />;
    case "defense_acquisition":
    default:
      return <Shield size={16} />;
  }
}

function ProfileCheckbox({
  profile,
  checked,
  onChange,
}: {
  profile: ComplianceProfile;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3 p-3 rounded-lg border-2 cursor-pointer transition-colors" style={{
      borderColor: checked ? T.accent : T.border,
      background: checked ? T.accent + "08" : T.raised,
    }}>
      <div
        className="rounded-sm flex items-center justify-center shrink-0"
        style={{
          width: 18,
          height: 18,
          background: checked ? T.accent : T.raised,
          border: `1px solid ${checked ? T.accent : T.border}`,
        }}
        onClick={(e) => {
          e.preventDefault();
          onChange(!checked);
        }}
      >
        {checked && <span style={{ fontSize: FS.xs, color: "white" }}>✓</span>}
      </div>
      <div className="flex items-center gap-2 flex-1">
        <div style={{ color: checked ? T.accent : T.dim }}>
          {getProfileIcon(profile.id)}
        </div>
        <div>
          <div className="font-semibold" style={{ fontSize: FS.sm, color: T.text }}>
            {profile.name}
          </div>
          <div style={{ fontSize: FS.xs, color: T.muted }}>{profile.description}</div>
        </div>
      </div>
    </label>
  );
}

function HorizontalBar({
  value,
  max = 1,
  color,
}: {
  value: number;
  max?: number;
  color: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="w-full h-2 rounded" style={{ background: T.border }}>
      <div
        className="h-full rounded transition-all"
        style={{
          width: `${pct}%`,
          background: color,
        }}
      />
    </div>
  );
}

export function ProfileCompare(_props: ProfileCompareProps) {
  const [profiles, setProfiles] = useState<ComplianceProfile[]>([]);
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [country, setCountry] = useState("CN");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null);

  // Load profiles on mount
  useEffect(() => {
    fetchProfiles()
      .then((loaded) => {
        setProfiles(loaded);
      })
      .catch((err) => {
        setError(`Failed to load profiles: ${err instanceof Error ? err.message : "Unknown error"}`);
      });
  }, []);

  const handleToggleProfile = (profileId: string, checked: boolean) => {
    const newSet = new Set(selectedProfiles);
    if (checked) {
      newSet.add(profileId);
    } else {
      newSet.delete(profileId);
    }
    setSelectedProfiles(newSet);
  };

  const handleCompare = async () => {
    if (!name.trim()) {
      setError("Please enter a vendor name");
      return;
    }

    if (selectedProfiles.size === 0) {
      setError("Please select at least one profile");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const compareResult = await compareProfiles(
        name.trim(),
        country,
        Array.from(selectedProfiles),
      );
      setResult(compareResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Input Section */}
      <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
            Compare Entity Across Frameworks
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_120px_auto] gap-3 items-end mb-4">
          <div>
            <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: FS.xs, color: T.muted }}>
              Entity Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && handleCompare()}
              placeholder="e.g., Rostec Corporation"
              className="w-full rounded outline-none"
              style={{
                padding: "6px 10px",
                fontSize: FS.sm,
                background: T.raised,
                color: T.text,
                border: `1px solid ${T.border}`,
              }}
            />
          </div>
          <div>
            <label className="font-mono uppercase tracking-wider block mb-1" style={{ fontSize: FS.xs, color: T.muted }}>
              Country
            </label>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-full rounded outline-none font-mono"
              style={{
                padding: "6px 8px",
                fontSize: FS.sm,
                background: T.raised,
                color: T.text,
                border: `1px solid ${T.border}`,
              }}
            >
              {["US", "CN", "RU", "IR", "KP", "SY", "VE", "BY", "GB", "DE", "FR", "JP", "IN"].map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <button
            onClick={handleCompare}
            disabled={!name.trim() || selectedProfiles.size === 0 || loading}
            className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
            style={{
              padding: "6px 16px",
              fontSize: FS.sm,
              background: T.accent,
              opacity: name.trim() && selectedProfiles.size > 0 && !loading ? 1 : 0.4,
              height: 33,
              marginBottom: 0,
            }}
          >
            {loading ? <Loader2 size={12} className="animate-spin" /> : <BarChart3 size={12} />}
            {loading ? "Comparing..." : "Compare"}
          </button>
        </div>

        {/* Profile Selection */}
        <div>
          <div className="font-mono uppercase tracking-wider mb-3" style={{ fontSize: FS.xs, color: T.muted }}>
            Select Profiles to Compare ({selectedProfiles.size} selected)
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {profiles.map((profile) => (
              <ProfileCheckbox
                key={profile.id}
                profile={profile}
                checked={selectedProfiles.has(profile.id)}
                onChange={(checked) => handleToggleProfile(profile.id, checked)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div
          className="rounded-lg p-3"
          style={{ background: "rgba(239,68,68,0.08)", border: `1px solid ${T.red}44` }}
        >
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      {/* Results Section */}
      {result && (
        <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-semibold" style={{ fontSize: FS.md, color: T.text }}>
                {result.entity.name}
              </div>
              <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted }}>
                {result.entity.country}
              </div>
            </div>
          </div>

          {/* Comparison Grid */}
          <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${result.comparisons.length}, 1fr)` }}>
            {result.comparisons.map((comp) => (
              <div
                key={comp.profile_id}
                className="rounded-lg p-3"
                style={{ background: T.raised, border: `1px solid ${T.border}` }}
              >
                {/* Profile Name */}
                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600, marginBottom: SP.sm }}>
                  {comp.profile_name}
                </div>

                {comp.error ? (
                  <div style={{ fontSize: FS.xs, color: T.red }}>
                    Error: {comp.error}
                  </div>
                ) : (
                  <>
                    {/* Tier Badge */}
                    <div style={{ marginBottom: SP.md }}>
                      <TierBadge tier={comp.tier as any} />
                      <div className="font-mono" style={{ fontSize: FS.xs, color: T.muted, marginTop: 2 }}>
                        {(comp.posterior * 100).toFixed(1)}% Risk
                      </div>
                    </div>

                    {/* Posterior Bar */}
                    <div style={{ marginBottom: SP.md }}>
                      <div style={{ fontSize: FS.xs, color: T.muted, marginBottom: 2 }}>
                        Risk Distribution
                      </div>
                      <HorizontalBar value={comp.posterior} color={comp.posterior > 0.5 ? T.red : comp.posterior > 0.3 ? T.orange : comp.posterior > 0.15 ? T.amber : T.green} />
                    </div>

                    {/* Hard Stops / Soft Flags */}
                    <div style={{ marginBottom: SP.md }}>
                      {comp.hard_stops.length > 0 && (
                        <div
                          className="inline-block rounded px-2 py-1 text-white text-center font-mono"
                          style={{
                            fontSize: FS.xs,
                            background: T.dRed,
                            marginRight: 6,
                            marginBottom: 4,
                          }}
                        >
                          {comp.hard_stops.length} HARD STOP{comp.hard_stops.length !== 1 ? "S" : ""}
                        </div>
                      )}
                      {comp.soft_flags.length > 0 && (
                        <div
                          className="inline-block rounded px-2 py-1 text-white text-center font-mono"
                          style={{
                            fontSize: FS.xs,
                            background: T.amber,
                            marginRight: 6,
                            marginBottom: 4,
                          }}
                        >
                          {comp.soft_flags.length} FLAG{comp.soft_flags.length !== 1 ? "S" : ""}
                        </div>
                      )}
                    </div>

                    {/* Top Contributions */}
                    {comp.contributions.length > 0 && (
                      <div style={{ marginBottom: SP.md }}>
                        <div style={{ fontSize: FS.xs, color: T.muted, marginBottom: 2, fontWeight: 600 }}>
                          Top Factors
                        </div>
                        {comp.contributions.map((c, i) => (
                          <div key={i} style={{ fontSize: FS.xs, color: T.dim, marginBottom: 2 }}>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                              <span>{c.factor}</span>
                              <span style={{ color: c.signed_contribution > 0 ? T.red : T.green, fontWeight: 600 }}>
                                {c.signed_contribution > 0 ? "+" : ""}{(c.signed_contribution * 100).toFixed(0)}pp
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Expandable Details */}
                    <button
                      onClick={() => setExpandedProfile(expandedProfile === comp.profile_id ? null : comp.profile_id)}
                      className="w-full text-left inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer"
                      style={{ fontSize: FS.xs, color: T.muted }}
                    >
                      {expandedProfile === comp.profile_id ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                      Details
                    </button>

                    {/* Expanded Details */}
                    {expandedProfile === comp.profile_id && (
                      <div style={{ marginTop: SP.sm, paddingTop: SP.sm, borderTop: `1px solid ${T.border}` }}>
                        {comp.hard_stops.length > 0 && (
                          <div style={{ marginBottom: SP.sm }}>
                            <div style={{ fontSize: FS.xs, color: T.red, fontWeight: 600, marginBottom: 2 }}>
                              Hard Stops
                            </div>
                            {comp.hard_stops.map((h, i) => (
                              <div key={i} style={{ fontSize: FS.xs, color: T.dim, marginBottom: 2 }}>
                                <div style={{ fontWeight: 600, color: T.text }}>{h.trigger}</div>
                                <div style={{ lineHeight: 1.3 }}>{h.explanation}</div>
                              </div>
                            ))}
                          </div>
                        )}
                        {comp.soft_flags.length > 0 && (
                          <div>
                            <div style={{ fontSize: FS.xs, color: T.amber, fontWeight: 600, marginBottom: 2 }}>
                              Soft Flags
                            </div>
                            {comp.soft_flags.map((f, i) => (
                              <div key={i} style={{ fontSize: FS.xs, color: T.dim, marginBottom: 2 }}>
                                <div style={{ fontWeight: 600, color: T.text }}>{f.trigger}</div>
                                <div style={{ lineHeight: 1.3 }}>{f.explanation}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Key Insights */}
          {result.comparisons.length > 1 && (
            <div
              className="rounded-lg p-4 mt-4"
              style={{ background: T.accent + "08", border: `1px solid ${T.accent}33` }}
            >
              <div className="font-semibold mb-2" style={{ fontSize: FS.sm, color: T.accent }}>
                Key Insights
              </div>

              {(() => {
                const posteriors = result.comparisons
                  .filter((c) => !c.error)
                  .map((c) => ({ id: c.profile_id, name: c.profile_name, p: c.posterior }));

                if (posteriors.length === 0) return null;

                const sorted = [...posteriors].sort((a, b) => b.p - a.p);
                const highest = sorted[0];
                const lowest = sorted[sorted.length - 1];

                const hardStopsCount = result.comparisons.reduce((sum, c) => sum + (c.hard_stops?.length || 0), 0);
                const softFlagsCount = result.comparisons.reduce((sum, c) => sum + (c.soft_flags?.length || 0), 0);

                return (
                  <div className="flex flex-col gap-2" style={{ fontSize: FS.xs, color: T.dim }}>
                    <div>
                      <span style={{ color: T.text, fontWeight: 600 }}>Strictest Framework:</span> {highest.name} ({(highest.p * 100).toFixed(0)}% risk)
                    </div>
                    <div>
                      <span style={{ color: T.text, fontWeight: 600 }}>Most Lenient:</span> {lowest.name} ({(lowest.p * 100).toFixed(0)}% risk)
                    </div>
                    <div>
                      <span style={{ color: T.text, fontWeight: 600 }}>Total Risk Signals:</span> {hardStopsCount} hard stops, {softFlagsCount} soft flags across all frameworks
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
