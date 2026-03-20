/**
 * Xiphos Helios Landing
 *
 * AI command interface with entity resolution.
 * Flow: Enter name -> Resolve entity (SEC/GLEIF/Wikidata) -> Show candidates ->
 *       User confirms -> Set context -> Create case -> Enrich -> Hand off
 */

import { useState, useRef, useEffect } from "react";
import { Shield, ArrowRight, CheckCircle, Loader2, XCircle, Building2, Truck, GitBranch, Zap, Sparkles, ChevronDown } from "lucide-react";
import { T, FS, tierBand, parseTier } from "@/lib/tokens";
import { createCase, enrichAndScore, resolveEntity, searchContractVehicle, batchAssessVehicle, submitResolveFeedback } from "@/lib/api";
import type { EntityCandidate, VehicleVendor, VehicleSearchResult, EntityResolution } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { SupplyChainGraph } from "./supply-chain-graph";

const GOLD = "#C4A052";
const GOLD_DIM = "#9A7B3E";

interface HeliosLandingProps {
  onCaseCreated: (caseId: string) => void;
  onNavigate: (tab: string) => void;
  cases?: VettingCase[];
}

type Phase = "idle" | "resolving" | "candidates" | "confirm" | "creating" | "enriching" | "done" | "error" | "vehicle-searching" | "vehicle-results";

interface ConfirmedEntity {
  name: string;
  legalName: string;
  country: string;
  program: string;
  cik: string;
  lei: string;
  ticker: string;
  sources: string;
  uei: string;
  cage: string;
  highestOwner: string;
  highestOwnerCountry: string;
  sbaCerts: string[];
}

function candidateFacts(candidate: EntityCandidate): string[] {
  const facts: string[] = [];

  if (candidate.country) {
    facts.push(`${candidate.country}${candidate.state ? `, ${candidate.state}` : ""}`);
  }
  if (candidate.ticker) {
    facts.push(`Ticker ${candidate.ticker}`);
  }
  if (candidate.uei) {
    facts.push(`UEI ${candidate.uei}`);
  } else if (candidate.cage) {
    facts.push(`CAGE ${candidate.cage}`);
  } else if (candidate.cik) {
    facts.push(`CIK ${candidate.cik}`);
  }
  if (candidate.highest_owner && candidate.highest_owner !== candidate.legal_name) {
    facts.push(`Owner ${candidate.highest_owner}`);
  } else if (candidate.description) {
    facts.push(candidate.description.length > 44 ? `${candidate.description.slice(0, 44)}...` : candidate.description);
  }

  return facts.slice(0, 3);
}

export function HeliosLanding({ onCaseCreated, onNavigate, cases = [] }: HeliosLandingProps) {
  const [input, setInput] = useState("");
  const [searchMode, setSearchMode] = useState<"entity" | "vehicle">("entity");
  const [phase, setPhase] = useState<Phase>("idle");
  const [statusText, setStatusText] = useState("");
  const [errorText, setErrorText] = useState("");
  const [entityName, setEntityName] = useState("");
  const [candidates, setCandidates] = useState<EntityCandidate[]>([]);
  const [resolution, setResolution] = useState<EntityResolution | null>(null);
  const [showRationale, setShowRationale] = useState(false);
  const [confirmed, setConfirmed] = useState<ConfirmedEntity | null>(null);
  const [vehicleResults, setVehicleResults] = useState<VehicleSearchResult | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [batchStatus, setBatchStatus] = useState<"idle" | "running" | "done">("idle");
  const [batchResults, setBatchResults] = useState<{total: number; created: number} | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const priorityReviewCount = cases.filter((c) => {
    const hasStops = (c.cal?.stops?.length ?? 0) > 0;
    if (hasStops) return true;
    if (!c.cal?.tier) return false;
    const band = tierBand(parseTier(c.cal.tier));
    return band === "critical" || band === "elevated";
  }).length;
  const recommendedCandidate =
    resolution?.status === "recommended"
      ? candidates.find((candidate) => candidate.candidate_id === resolution.recommended_candidate_id) ?? null
      : null;
  const fallbackCandidates = recommendedCandidate
    ? candidates.filter((candidate) => candidate.candidate_id !== recommendedCandidate.candidate_id)
    : candidates;

  useEffect(() => { inputRef.current?.focus(); }, []);

  // Step 1: User submits a name -> resolve entity
  const handleSubmit = async () => {
    if (searchMode === "vehicle") {
      await handleVehicleSearch();
      return;
    }

    const name = input.trim();
    if (!name || phase !== "idle") return;

    setInput("");
    setEntityName(name);
    setPhase("resolving");
    setStatusText("Resolving entity...");

    try {
      const result = await resolveEntity(name, { use_ai: true, max_candidates: 6 });
      if (result.candidates.length > 0) {
        setCandidates(result.candidates);
        setResolution(result.resolution || null);
        setPhase("candidates");
      } else {
        setConfirmed({
          name, legalName: name, country: "US", program: "dod_unclassified",
          cik: "", lei: "", ticker: "", sources: "manual",
          uei: "", cage: "", highestOwner: "", highestOwnerCountry: "", sbaCerts: [],
        });
        setPhase("confirm");
      }
      setStatusText("");
    } catch {
      setConfirmed({
        name, legalName: name, country: "US", program: "dod_unclassified",
        cik: "", lei: "", ticker: "", sources: "manual",
        uei: "", cage: "", highestOwner: "", highestOwnerCountry: "", sbaCerts: [],
      });
      setPhase("confirm");
      setStatusText("");
    }
  };

  // Step 2: User selects a candidate (with feedback tracking)
  const selectCandidate = (c: EntityCandidate) => {
    if (resolution?.request_id && c.candidate_id) {
      submitResolveFeedback(resolution.request_id, c.candidate_id).catch(() => {});
    }
    setConfirmed({
      name: entityName,
      legalName: c.legal_name,
      country: c.country || "US",
      program: "dod_unclassified",
      cik: c.cik || "",
      lei: c.lei || "",
      ticker: c.ticker || "",
      sources: c.source || "",
      uei: c.uei || "",
      cage: c.cage || "",
      highestOwner: c.highest_owner || "",
      highestOwnerCountry: c.highest_owner_country || "",
      sbaCerts: c.sba_certifications || [],
    });
    setPhase("confirm");
  };

  // Step 3: User confirms -> create and enrich
  const handleConfirm = async () => {
    if (!confirmed) return;
    setPhase("creating");
    setStatusText("Creating case...");

    try {
      const hasSamData = !!confirmed.uei || !!confirmed.cage;
      const hasOwnerData = !!confirmed.cik || hasSamData;

      // Detect foreign ownership from SAM.gov corporate chain
      const ALLIED = new Set(["US","GB","CA","AU","NZ","DE","FR","NL","NO","DK","SE","FI","IT","ES","PL","CZ","JP","KR","IL","SG","TW"]);
      const ownerCountry = confirmed.highestOwnerCountry?.toUpperCase() || "";
      const vendorCountry = confirmed.country?.toUpperCase() || "US";
      const isForeignOwned = ownerCountry && ownerCountry !== vendorCountry && ownerCountry !== "";
      const foreignOwnershipPct = isForeignOwned ? 0.51 : 0.0; // Default to majority if SAM shows foreign parent
      const isAllied = ALLIED.has(ownerCountry);

      const createResp = await createCase({
        name: confirmed.legalName || confirmed.name,
        country: confirmed.country,
        ownership: {
          publicly_traded: !!confirmed.ticker,
          state_owned: false,
          beneficial_owner_known: !!confirmed.highestOwner || hasOwnerData,
          ownership_pct_resolved: confirmed.highestOwner ? 0.8 : (hasOwnerData ? 0.6 : 0),
          shell_layers: 0,
          pep_connection: false,
          foreign_ownership_pct: foreignOwnershipPct,
          foreign_ownership_is_allied: isAllied,
        },
        data_quality: {
          has_lei: !!confirmed.lei,
          has_cage: !!confirmed.cage,
          has_duns: !!confirmed.uei,  // UEI replaces DUNS for federal registration
          has_tax_id: !!confirmed.cik || hasSamData,
          has_audited_financials: !!confirmed.cik,
          years_of_records: hasSamData ? 5 : 0,
        },
        exec: { known_execs: 0, adverse_media: 0, pep_execs: 0, litigation_history: 0 },
        program: confirmed.program,
        profile: "defense_acquisition",
      });

      const caseId = createResp.case_id;
      setPhase("enriching");
      setStatusText("Running 27 live OSINT connectors and 10 regulatory gates...");

      await enrichAndScore(caseId);

      setPhase("done");
      setStatusText("Assessment complete.");
      setTimeout(() => { onCaseCreated(caseId); }, 800);
    } catch (err: unknown) {
      setPhase("error");
      setErrorText((err as Error)?.message || "Assessment failed.");
    }
  };

  const handleEdit = () => {
    setPhase("idle");
    setSearchMode("entity");
    setInput(entityName);
    setCandidates([]);
    setConfirmed(null);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  // Vehicle search handler
  const handleVehicleSearch = async (vehicleName?: string) => {
    const term = vehicleName || input.trim();
    if (!term || phase !== "idle") return;
    setInput("");
    setEntityName(term);
    setPhase("vehicle-searching");
    setStatusText(`Searching USAspending for "${term}" awards...`);

    try {
      const result = await searchContractVehicle(term);
      setVehicleResults(result);
      setPhase("vehicle-results");
      setStatusText("");
    } catch (err) {
      setPhase("error");
      const message = err instanceof Error ? err.message.replace(/^API \d+:\s*/, "") : "Contract vehicle search failed. Try again.";
      setErrorText(message || "Contract vehicle search failed. Try again.");
    }
  };

  // Assess a vendor from vehicle results
  const assessVehicleVendor = (v: VehicleVendor) => {
    setConfirmed({
      name: v.vendor_name,
      legalName: v.vendor_name,
      country: "US",
      program: "dod_unclassified",
      cik: "", lei: "", ticker: "",
      sources: "usaspending",
      uei: "", cage: "", highestOwner: "", highestOwnerCountry: "", sbaCerts: [],
    });
    setPhase("confirm");
  };

  // Batch assess all vendors from vehicle search
  const handleBatchAssess = async () => {
    if (!vehicleResults || batchStatus === "running") return;
    setBatchStatus("running");
    try {
      const allVendors = vehicleResults.unique_vendors;
      const result = await batchAssessVehicle(allVendors);
      setBatchResults({ total: result.total, created: result.created });
      setBatchStatus("done");
    } catch {
      setBatchStatus("idle");
    }
  };

  const reset = () => {
    setPhase("idle"); setStatusText(""); setErrorText("");
    setSearchMode("entity");
    setEntityName(""); setCandidates([]); setConfirmed(null);
    setResolution(null); setShowRationale(false);
    setVehicleResults(null);
    setShowGraph(false); setBatchStatus("idle"); setBatchResults(null);
    inputRef.current?.focus();
  };



  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "80vh", padding: "0 24px" }}>

      {/* ── IDLE ── */}
      {phase === "idle" && (
        <>
          <div style={{ position: "relative", width: 72, height: 72, marginBottom: 28 }}>
            <div style={{ position: "absolute", inset: -8, borderRadius: "50%", border: `1px solid ${GOLD}15`, animation: "hr 4s ease-in-out infinite" }} />
            <div style={{ position: "absolute", inset: -16, borderRadius: "50%", border: `1px solid ${GOLD}08`, animation: "hr 4s ease-in-out 0.5s infinite" }} />
            <div style={{ width: 72, height: 72, borderRadius: "50%", background: `linear-gradient(135deg, ${GOLD}18, ${GOLD}08)`, border: `1px solid ${GOLD}25`, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Shield size={28} color={GOLD} strokeWidth={1.5} />
            </div>
          </div>
          <div style={{ fontSize: 12, color: GOLD_DIM, letterSpacing: "0.12em", fontWeight: 600, marginBottom: 10 }}>Helios</div>
          <div style={{ fontSize: 32, fontWeight: 300, color: T.text, lineHeight: 1.3, textAlign: "center", maxWidth: 480, fontFamily: "Georgia, 'Times New Roman', serif", marginBottom: 6 }}>What do you want to assess?</div>
          <div style={{ fontSize: FS.base, color: T.dim, textAlign: "center", maxWidth: 400, lineHeight: 1.5, marginBottom: 24 }}>
            {searchMode === "vehicle"
              ? "Enter a contract vehicle name to search public award relationships."
              : "Enter a company name to begin assessment."}
          </div>

          <div style={{ position: "relative", width: "100%", maxWidth: 560, marginBottom: 24 }}>
            <input ref={inputRef} value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSubmit()}
              placeholder={searchMode === "vehicle" ? "Enter contract vehicle (OASIS, CIO-SP3, SEWP...)" : "Enter company name to assess..."}
              style={{ width: "100%", padding: "16px 56px 16px 20px", borderRadius: 28, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.md, outline: "none", transition: "border-color 0.3s", fontFamily: "inherit" }}
              onFocus={e => e.target.style.borderColor = GOLD + "55"} onBlur={e => e.target.style.borderColor = T.border} />
            <button onClick={handleSubmit} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", width: 40, height: 40, borderRadius: 20, border: "none", background: input.trim() ? GOLD : T.border, color: input.trim() ? "#000" : T.muted, cursor: input.trim() ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.25s" }}>
              <ArrowRight size={18} />
            </button>
          </div>

          <div style={{ marginBottom: 24 }}>
            <button
              onClick={() => {
                setSearchMode((current) => current === "entity" ? "vehicle" : "entity");
                setInput("");
                setTimeout(() => inputRef.current?.focus(), 0);
              }}
              style={{ fontSize: FS.sm, color: T.accent, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", padding: 0 }}
            >
              {searchMode === "vehicle" ? "Back to company search" : "Or search by contract vehicle"}
            </button>
          </div>

          {cases && cases.length > 0 && (
            <div style={{ marginBottom: 24, width: "100%", maxWidth: 560 }}>
              <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.muted, marginBottom: 8 }}>Recent work</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {cases.slice(0, 5).map((c) => (
                  <button
                    key={c.id}
                    onClick={() => onCaseCreated(c.id)}
                    style={{
                      width: "100%",
                      padding: "10px 12px",
                      borderRadius: 6,
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      color: T.text,
                      fontSize: FS.sm,
                      textAlign: "left",
                      cursor: "pointer",
                      transition: "all 0.2s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = T.hover; e.currentTarget.style.borderColor = T.accent; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = T.surface; e.currentTarget.style.borderColor = T.border; }}
                  >
                    <div style={{ fontWeight: 500 }}>{c.name}</div>
                    <div style={{ fontSize: FS.sm, color: T.muted }}>{c.date}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {cases && cases.length > 0 && (
            <div style={{ marginTop: 24, fontSize: FS.sm, color: T.muted, display: "flex", alignItems: "center", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
              <span>{cases.length} vendors</span><span style={{ color: T.border }}>•</span>
              <span>{priorityReviewCount} priority reviews</span><span style={{ color: T.border }}>•</span>
              <span>{cases.filter(c => (c.cal?.stops?.length ?? 0) > 0).length} blocked</span>
            </div>
          )}
        </>
      )}

      {/* ── RESOLVING ── */}
      {phase === "resolving" && (
        <div style={{ textAlign: "center" }}>
          <Loader2 size={36} color={GOLD} style={{ animation: "hs 1.5s linear infinite", marginBottom: 20 }} />
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 6 }}>"{entityName}"</div>
          <div style={{ fontSize: FS.base, color: T.dim }}>Searching SEC EDGAR, GLEIF, and Wikidata...</div>
        </div>
      )}

      {/* ── CANDIDATES: entity disambiguation with AI recommendation ── */}
      {phase === "candidates" && candidates.length > 0 && (
        <div style={{ maxWidth: 560, width: "100%", textAlign: "center" }}>
          <div style={{ fontSize: 12, color: GOLD_DIM, letterSpacing: "0.08em", fontWeight: 600, marginBottom: 10 }}>Entity resolution</div>
          <div style={{ fontSize: FS.xl, fontWeight: 600, color: T.text, marginBottom: 6 }}>Which entity?</div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginBottom: 12 }}>
            Found {candidates.length} match{candidates.length !== 1 ? "es" : ""} for "{entityName}"
            {resolution?.mode === "deterministic_plus_ai" && (
              <span style={{ color: GOLD, marginLeft: 8 }}>
                <Sparkles size={11} style={{ display: "inline", verticalAlign: "middle", marginRight: 3 }} />
                AI-assisted
              </span>
            )}
          </div>

          {/* Ambiguous warning */}
          {resolution?.status === "ambiguous" && (
            <div style={{ padding: "8px 14px", borderRadius: 8, background: `${T.amber}08`, border: `1px solid ${T.amber}20`,
              textAlign: "left", marginBottom: 16, fontSize: FS.sm, color: T.amber }}>
              No strong recommendation. Review candidates manually.
            </div>
          )}

          {resolution?.status === "abstained" && (
            <div style={{ padding: "8px 14px", borderRadius: 8, background: `${T.border}35`, border: `1px solid ${T.border}`,
              textAlign: "left", marginBottom: 16, fontSize: FS.sm, color: T.dim }}>
              {resolution.reason_summary || "The reranker abstained. Review candidates manually."}
            </div>
          )}

          {resolution?.status === "unavailable" && (
            <div style={{ padding: "8px 14px", borderRadius: 8, background: `${T.accent}08`, border: `1px solid ${T.accent}20`,
              textAlign: "left", marginBottom: 16, fontSize: FS.sm, color: T.dim }}>
              {resolution.reason_summary || "AI reranking is unavailable. Review candidates manually."}
            </div>
          )}

          {resolution?.status === "disabled" && (
            <div style={{ padding: "8px 14px", borderRadius: 8, background: `${T.border}40`, border: `1px solid ${T.border}`,
              textAlign: "left", marginBottom: 16, fontSize: FS.sm, color: T.dim }}>
              {resolution.reason_summary || "AI reranking is disabled for this lookup. Review candidates manually."}
            </div>
          )}

          {recommendedCandidate && resolution?.status === "recommended" && (
            <div
              style={{
                padding: "18px 18px 16px",
                borderRadius: 12,
                background: `linear-gradient(135deg, ${GOLD}10, ${GOLD}04)`,
                border: `1px solid ${GOLD}28`,
                textAlign: "left",
                marginBottom: 18,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: `${GOLD}14`, border: `1px solid ${GOLD}25`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Sparkles size={16} color={GOLD} />
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: GOLD_DIM, fontWeight: 700, letterSpacing: "0.04em" }}>Recommended match</div>
                    <div style={{ fontSize: FS.lg, fontWeight: 700, color: T.text }}>{recommendedCandidate.legal_name}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: T.muted }}>
                  {Math.round((resolution.confidence || 0) * 100)}% confidence
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                {candidateFacts(recommendedCandidate).map((fact) => (
                  <span
                    key={fact}
                    style={{
                      padding: "4px 9px",
                      borderRadius: 999,
                      fontSize: 11,
                      color: T.dim,
                      background: T.bg,
                      border: `1px solid ${T.border}`,
                    }}
                  >
                    {fact}
                  </span>
                ))}
              </div>

              {resolution.reason_summary && (
                <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginBottom: 10 }}>
                  {resolution.reason_summary}
                </div>
              )}

              {resolution.reason_detail && resolution.reason_detail.length > 0 && (
                <>
                  <button
                    onClick={() => setShowRationale(!showRationale)}
                    style={{ background: "none", border: "none", color: GOLD, fontSize: 11, cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 4, marginBottom: showRationale ? 8 : 0 }}
                  >
                    <ChevronDown size={12} style={{ transform: showRationale ? "rotate(180deg)" : "none", transition: "0.2s" }} />
                    {showRationale ? "Hide details" : "Why this match?"}
                  </button>
                  {showRationale && (
                    <div style={{ marginBottom: 12, paddingLeft: 12, borderLeft: `2px solid ${GOLD}20`, fontSize: 11, color: T.muted }}>
                      {resolution.reason_detail.map((reason, index) => (
                        <div key={index} style={{ marginBottom: 4 }}>{reason}</div>
                      ))}
                    </div>
                  )}
                </>
              )}

              <button
                onClick={() => selectCandidate(recommendedCandidate)}
                style={{
                  padding: "11px 16px",
                  borderRadius: 9,
                  border: "none",
                  background: GOLD,
                  color: "#000",
                  fontSize: FS.sm,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Use this entity
              </button>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8, textAlign: "left" }}>
            {fallbackCandidates.slice(0, 6).map((candidate, i) => (
              <button
                key={candidate.candidate_id ?? `${candidate.legal_name}-${i}`}
                onClick={() => selectCandidate(candidate)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "14px 16px",
                  borderRadius: 10,
                  border: `1px solid ${T.border}`,
                  background: T.surface,
                  cursor: "pointer",
                  transition: "all 0.2s",
                  width: "100%",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = GOLD + "35";
                  e.currentTarget.style.transform = "translateX(3px)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = T.border;
                  e.currentTarget.style.transform = "translateX(0)";
                }}
              >
                <Building2 size={16} color={T.dim} style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>{candidate.legal_name}</div>
                  <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {candidateFacts(candidate).map((fact) => (
                      <span key={fact}>
                        {fact}
                      </span>
                    ))}
                  </div>
                </div>
                <ArrowRight size={14} color={T.muted} />
              </button>
            ))}
          </div>

          <button onClick={handleEdit} style={{ marginTop: 16, padding: "10px 20px", borderRadius: 8, border: `1px solid ${T.border}`, background: "transparent", color: T.dim, fontSize: FS.sm, cursor: "pointer" }}>
            None of these. Try a different name.
          </button>
        </div>
      )}

      {/* ── VEHICLE SEARCHING ── */}
      {phase === "vehicle-searching" && (
        <div style={{ textAlign: "center" }}>
          <Loader2 size={36} color={GOLD} style={{ animation: "hs 1.5s linear infinite", marginBottom: 20 }} />
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 6 }}>"{entityName}"</div>
          <div style={{ fontSize: FS.base, color: T.dim }}>Searching USAspending for contract awards...</div>
        </div>
      )}

      {/* ── VEHICLE RESULTS ── */}
      {phase === "vehicle-results" && vehicleResults && (
        <div style={{ maxWidth: 680, width: "100%" }}>
          <div style={{ textAlign: "center", marginBottom: 24 }}>
            <div style={{ fontSize: 12, color: GOLD_DIM, letterSpacing: "0.08em", fontWeight: 600, marginBottom: 8 }}>Contract vehicle search</div>
            <div style={{ fontSize: FS.xl, fontWeight: 600, color: T.text, marginBottom: 4 }}>{vehicleResults.vehicle_name}</div>
            <div style={{ fontSize: FS.sm, color: T.dim }}>
              {vehicleResults.total_primes} prime contractor{vehicleResults.total_primes !== 1 ? "s" : ""} and {vehicleResults.total_subs} subcontractor{vehicleResults.total_subs !== 1 ? "s" : ""} found ({vehicleResults.total_unique} unique)
            </div>
          </div>

          {/* Action bar: graph toggle + batch assess */}
          {vehicleResults.total_unique > 0 && (
            <div style={{ display: "flex", gap: 8, marginBottom: 20, justifyContent: "center" }}>
              <button onClick={() => setShowGraph(!showGraph)}
                style={{ padding: "8px 16px", borderRadius: 8, border: `1px solid ${showGraph ? GOLD + "40" : T.border}`,
                  background: showGraph ? `${GOLD}10` : "transparent", color: showGraph ? GOLD : T.dim,
                  fontSize: 12, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
                <GitBranch size={14} /> {showGraph ? "Hide" : "Show"} Supply Chain Map
              </button>
              <button onClick={handleBatchAssess} disabled={batchStatus === "running"}
                style={{ padding: "8px 16px", borderRadius: 8, border: `1px solid ${GOLD}40`,
                  background: batchStatus === "done" ? `${T.green}12` : `${GOLD}10`,
                  color: batchStatus === "done" ? T.green : GOLD,
                  fontSize: 12, fontWeight: 600, cursor: batchStatus === "running" ? "wait" : "pointer",
                  display: "flex", alignItems: "center", gap: 6, opacity: batchStatus === "running" ? 0.6 : 1 }}>
                {batchStatus === "running" ? <Loader2 size={14} style={{ animation: "hs 1s linear infinite" }} /> :
                 batchStatus === "done" ? <CheckCircle size={14} /> : <Zap size={14} />}
                {batchStatus === "idle" ? `Create draft cases for ${vehicleResults.total_unique} vendors` :
                 batchStatus === "running" ? "Creating draft cases..." :
                 `${batchResults?.created || 0} draft cases created`}
              </button>
              {batchStatus === "done" && (
                <button onClick={() => onNavigate("portfolio")}
                  style={{ padding: "8px 16px", borderRadius: 8, border: `1px solid ${T.green}40`,
                    background: `${T.green}10`, color: T.green, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  View Draft Cases
                </button>
              )}
            </div>
          )}

          {vehicleResults.total_unique > 0 && (
            <div style={{ marginBottom: 16, fontSize: 12, color: T.muted, textAlign: "center" }}>
              Batch actions create scored draft cases only. Run full enrichment per case when deeper review is warranted.
            </div>
          )}

          {vehicleResults.errors && vehicleResults.errors.length > 0 && (
            <div style={{ marginBottom: 16, padding: "10px 12px", borderRadius: 8, background: T.amberBg, border: `1px solid ${T.amber}33`, color: T.amber, fontSize: 12 }}>
              Some upstream contract data calls returned warnings: {vehicleResults.errors.slice(0, 2).map((item) => item.message).join(" | ")}
            </div>
          )}

          {/* Supply chain graph */}
          {showGraph && vehicleResults.total_unique > 0 && (
            <div style={{ marginBottom: 20 }}>
              <SupplyChainGraph data={vehicleResults} onSelectVendor={assessVehicleVendor} />
            </div>
          )}

          {vehicleResults.total_unique === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 20px", borderRadius: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: FS.base, color: T.muted, marginBottom: 16 }}>No awards found for this contract vehicle. Try a different name or abbreviation.</div>
              <button onClick={reset} style={{ padding: "10px 24px", borderRadius: 8, border: `1px solid ${T.border}`, background: "transparent", color: T.text, fontSize: FS.sm, cursor: "pointer" }}>Search Again</button>
            </div>
          ) : (
            <>
              {/* Prime contractors */}
              {vehicleResults.primes.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.1em", marginBottom: 8 }}>PRIME CONTRACTORS ({vehicleResults.total_primes})</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {vehicleResults.primes.slice(0, 10).map((p, i) => (
                      <button key={i} onClick={() => assessVehicleVendor(p)}
                        style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.surface, cursor: "pointer", transition: "all 0.2s", width: "100%", textAlign: "left" }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = GOLD + "40"; }} onMouseLeave={e => { e.currentTarget.style.borderColor = T.border; }}>
                        <Building2 size={16} color={GOLD} style={{ flexShrink: 0 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.vendor_name}</div>
                          <div style={{ fontSize: 11, color: T.muted, display: "flex", gap: 10, marginTop: 2, flexWrap: "wrap" }}>
                            {p.award_amount ? <span style={{ color: T.green }}>${(p.award_amount / 1e6).toFixed(1)}M</span> : null}
                            {p.awarding_agency && <span>{p.awarding_agency}</span>}
                            {p.award_id && <span style={{ fontFamily: "monospace", fontSize: 10 }}>{p.award_id}</span>}
                          </div>
                        </div>
                        <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: `${GOLD}12`, color: GOLD, fontWeight: 600 }}>Review</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Subcontractors */}
              {vehicleResults.subs.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.1em", marginBottom: 8 }}>SUBCONTRACTORS ({vehicleResults.total_subs})</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {vehicleResults.subs.slice(0, 10).map((s, i) => (
                      <button key={i} onClick={() => assessVehicleVendor(s)}
                        style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.surface, cursor: "pointer", transition: "all 0.2s", width: "100%", textAlign: "left" }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = T.amber + "40"; }} onMouseLeave={e => { e.currentTarget.style.borderColor = T.border; }}>
                        <Truck size={16} color={T.amber} style={{ flexShrink: 0 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.vendor_name}</div>
                          <div style={{ fontSize: 11, color: T.muted, display: "flex", gap: 10, marginTop: 2, flexWrap: "wrap" }}>
                            {s.award_amount ? <span style={{ color: T.green }}>${(s.award_amount / 1e6).toFixed(1)}M</span> : null}
                            {s.prime_recipient && <span>Prime: {s.prime_recipient}</span>}
                          </div>
                        </div>
                        <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: `${T.amber}12`, color: T.amber, fontWeight: 600 }}>Review</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button onClick={reset} style={{ width: "100%", padding: "12px", borderRadius: 8, border: `1px solid ${T.border}`, background: "transparent", color: T.dim, fontSize: FS.sm, cursor: "pointer", marginTop: 8 }}>
                Search another vehicle
              </button>
            </>
          )}
        </div>
      )}

      {/* ── CONFIRM ── */}
      {phase === "confirm" && confirmed && (
        <div style={{ maxWidth: 540, width: "100%", textAlign: "center" }}>
          <div style={{ fontSize: 12, color: GOLD_DIM, letterSpacing: "0.08em", fontWeight: 600, marginBottom: 12 }}>Confirm entity</div>
          <div style={{ fontSize: FS.xl, fontWeight: 600, color: T.text, marginBottom: 8 }}>Ready to assess</div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginBottom: 24 }}>
            Final check before Helios begins screening.
          </div>

          <div style={{ padding: "24px", borderRadius: 12, background: T.surface, border: `1px solid ${GOLD}20`, textAlign: "left", marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              <div style={{ width: 48, height: 48, borderRadius: 10, background: `${GOLD}10`, border: `1px solid ${GOLD}18`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Building2 size={22} color={GOLD} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: FS.lg, fontWeight: 700, color: T.text }}>{confirmed.legalName}</div>
                {confirmed.legalName !== confirmed.name && (
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>Searched as: "{confirmed.name}"</div>
                )}
              </div>
            </div>

            {(confirmed.ticker || confirmed.uei || confirmed.cage || confirmed.highestOwner) && (
              <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 14, lineHeight: 1.5 }}>
                {[
                  confirmed.ticker ? `Ticker ${confirmed.ticker}` : null,
                  confirmed.uei ? `UEI ${confirmed.uei}` : null,
                  confirmed.cage ? `CAGE ${confirmed.cage}` : null,
                  confirmed.highestOwner ? `Parent ${confirmed.highestOwner}` : null,
                ].filter(Boolean).join(" • ")}
              </div>
            )}

            {/* Context selectors */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.02em", display: "block", marginBottom: 6 }}>Country</label>
                <select value={confirmed.country} onChange={e => setConfirmed({ ...confirmed, country: e.target.value })}
                  style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.bg, color: T.text, fontSize: FS.sm, outline: "none" }}>
                  <option value="US">United States</option><option value="GB">United Kingdom</option><option value="FR">France</option>
                  <option value="DE">Germany</option><option value="IL">Israel</option><option value="KR">South Korea</option>
                  <option value="JP">Japan</option><option value="AU">Australia</option><option value="CA">Canada</option>
                  <option value="TR">Turkey</option><option value="CN">China</option><option value="IN">India</option>
                  <option value="IT">Italy</option><option value="TW">Taiwan</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.02em", display: "block", marginBottom: 6 }}>Contract type</label>
                <select value={confirmed.program} onChange={e => setConfirmed({ ...confirmed, program: e.target.value })}
                  style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.bg, color: T.text, fontSize: FS.sm, outline: "none" }}>
                  <option value="dod_classified" title="Classified programs, SAP/SCI, intelligence community. Highest scrutiny.">DoD / IC (Classified)</option>
                  <option value="dod_unclassified" title="Unclassified DoD contracts, ITAR-controlled items, major weapons programs.">DoD (Unclassified)</option>
                  <option value="federal_non_dod" title="DHS, DOE, NASA, and other civilian agency contracts with security requirements.">Federal (Non-DoD)</option>
                  <option value="regulated_commercial" title="Defense-adjacent commercial work, dual-use items, export-controlled technology.">Regulated Commercial</option>
                  <option value="commercial" title="Standard commercial procurement with no special security requirements.">Commercial</option>
                </select>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 4, lineHeight: 1.4 }}>
                  Screening thresholds adapt to the contract type you choose here.
                </div>
              </div>
            </div>

            <div style={{ padding: "12px 14px", borderRadius: 8, background: T.bg, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.02em", marginBottom: 6 }}>What Helios will do</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: FS.sm, color: T.dim }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Confirm the entity and its identifiers</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Run live OSINT and regulatory screening</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Score the case and recommend a disposition</div>
              </div>
              <div style={{ fontSize: 11, color: T.muted, marginTop: 8 }}>Estimated: 30-60 seconds</div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={handleEdit} style={{ flex: 1, padding: "14px", borderRadius: 10, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, fontWeight: 600, cursor: "pointer" }}>
              Cancel
            </button>
            <button onClick={handleConfirm} style={{ flex: 2, padding: "14px 20px", borderRadius: 10, border: "none", background: GOLD, color: "#000", fontSize: FS.base, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <CheckCircle size={16} /> Begin Assessment
            </button>
          </div>
        </div>
      )}

      {/* ── CREATING / ENRICHING ── */}
      {(phase === "creating" || phase === "enriching") && (
        <div style={{ textAlign: "center", maxWidth: 480 }}>
          <Loader2 size={40} color={GOLD} style={{ animation: "hs 1.5s linear infinite", marginBottom: 20 }} />
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 8 }}>{confirmed?.legalName || entityName}</div>
          <div style={{ fontSize: FS.base, color: T.dim, marginBottom: 16 }}>{statusText}</div>
          {phase === "enriching" && (
            <div style={{ width: "100%", maxWidth: 320, margin: "0 auto" }}>
              <div style={{ height: 4, borderRadius: 2, background: `${GOLD}15`, overflow: "hidden" }}>
                <div style={{ width: "60%", height: "100%", borderRadius: 2, background: GOLD, animation: "hp 2s ease-in-out infinite" }} />
              </div>
              <div style={{ fontSize: 11, color: T.muted, marginTop: 8 }}>This typically takes 30-60 seconds</div>
            </div>
          )}
        </div>
      )}

      {/* ── DONE ── */}
      {phase === "done" && (
        <div style={{ textAlign: "center" }}>
          <CheckCircle size={40} color={T.green} style={{ marginBottom: 16 }} />
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 8 }}>{confirmed?.legalName || entityName}</div>
          <div style={{ fontSize: FS.base, color: T.green }}>Assessment complete. Loading results...</div>
        </div>
      )}

      {/* ── ERROR ── */}
      {phase === "error" && (
        <div style={{ textAlign: "center", maxWidth: 480 }}>
          <XCircle size={40} color={T.red} style={{ marginBottom: 16 }} />
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 8 }}>{entityName}</div>
          <div style={{ fontSize: FS.base, color: T.red, marginBottom: 16 }}>{errorText}</div>
          <button onClick={reset} style={{ padding: "10px 24px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, fontWeight: 600, cursor: "pointer" }}>Try Again</button>
        </div>
      )}

      <style>{`
        @keyframes hr { 0%,100% { opacity:0.3; transform:scale(1) } 50% { opacity:0.7; transform:scale(1.08) } }
        @keyframes hs { from { transform:rotate(0deg) } to { transform:rotate(360deg) } }
        @keyframes hp { 0% { width:10% } 50% { width:80% } 100% { width:10% } }
      `}</style>
    </div>
  );
}
