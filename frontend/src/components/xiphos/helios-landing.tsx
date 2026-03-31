/**
 * Xiphos Helios Landing
 *
 * AI command interface with entity resolution.
 * Flow: Enter name -> Resolve entity (SEC/GLEIF/Wikidata) -> Show candidates ->
 *       User confirms -> Set context -> Create case -> Enrich -> Hand off
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowRight, CheckCircle, Loader2, XCircle, Building2, Truck, GitBranch, Zap, Sparkles, ChevronDown, Globe2 } from "lucide-react";
import { T, FS, FX, displayName } from "@/lib/tokens";
import { createCase, resolveEntity, searchContractVehicle, batchAssessVehicle, submitResolveFeedback, fetchHealth } from "@/lib/api";
import type { EntityCandidate, VehicleVendor, VehicleSearchResult, EntityResolution, ExportAuthorizationCaseInput } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { SupplyChainGraph } from "./supply-chain-graph";
import { EnrichmentStream } from "./enrichment-stream";
import { WORKFLOW_LANE_META, portfolioDisposition, workflowLaneForCase } from "./portfolio-utils";

const GOLD = T.gold;
const GOLD_DIM = T.goldDim;

interface HeliosLandingProps {
  onCaseCreated: (caseId: string) => void;
  onNavigate: (tab: string) => void;
  onCasesRefresh?: () => Promise<void>;
  cases?: VettingCase[];
  preferredLane?: DecisionLane;
  onPreferredLaneChange?: (lane: DecisionLane) => void;
}

type Phase = "idle" | "resolving" | "candidates" | "confirm" | "creating" | "enriching" | "done" | "error" | "vehicle-searching" | "vehicle-results";
type EntityWorkflow = "counterparty" | "cyber";
type DecisionLane = "counterparty" | "cyber" | "export";

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

const EXPORT_REQUEST_TYPE_OPTIONS: Array<{ value: ExportAuthorizationCaseInput["request_type"]; label: string; description: string }> = [
  { value: "technical_data_release", label: "Technical data release", description: "Assess whether controlled drawings, source, or engineering data can be released." },
  { value: "foreign_person_access", label: "Foreign-person access", description: "Review whether a foreign national can access a controlled environment, system, or program." },
  { value: "item_transfer", label: "Item transfer", description: "Assess whether a controlled item or component can be transferred to the named party and destination." },
];

const EXPORT_JURISDICTION_OPTIONS: Array<{ value: NonNullable<ExportAuthorizationCaseInput["jurisdiction_guess"]>; label: string }> = [
  { value: "unknown", label: "Unknown / needs classification" },
  { value: "itar", label: "ITAR / USML" },
  { value: "ear", label: "EAR / ECCN" },
  { value: "ofac_overlay", label: "OFAC / sanctions overlay" },
];

const LANE_BRIEFS: Record<DecisionLane, { title: string; question: string; outputs: string; evidence: string; useWhen: string }> = {
  counterparty: {
    title: "Defense counterparty trust",
    question: "Can we award, keep, or qualify this supplier given ownership, foreign-influence, and network evidence?",
    outputs: "Approved / Qualified / Review / Blocked",
    evidence: "Form 328, ownership charts, SAM.gov registration, SAM.gov subaward reporting, sanctions, and network context",
    useWhen: "Use this for pre-award adjudication, FOCI-sensitive review, and supplier trust decisions.",
  },
  cyber: {
    title: "Supply chain assurance",
    question: "Can this supplier, product, and dependency stack be trusted with CUI-sensitive or mission-critical work given attestation, remediation, provenance, and vulnerability evidence?",
    outputs: "Ready / Qualified / Review / Blocked",
    evidence: "SPRS exports, OSCAL SSP or POA&M artifacts, SBOM or VEX evidence, and product vulnerability overlays",
    useWhen: "Use this when the decision depends on CMMC readiness, software or firmware assurance, dependency risk, or cyber posture.",
  },
  export: {
    title: "Export authorization",
    question: "Can this item, technical-data release, or foreign-person access request move forward under current control posture?",
    outputs: "Likely prohibited / License required / Exception path / Likely NLR / Escalate",
    evidence: "Classification memos, license history, access-control records, and BIS or DDTC rule guidance",
    useWhen: "Use this for item transfers, technical-data release, and foreign-person access decisions.",
  },
};

const LANE_ICONS = {
  counterparty: Building2,
  cyber: Zap,
  export: Globe2,
} as const;

function caseTimestamp(value?: string): number {
  if (!value) return 0;
  const parsed = Date.parse(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isFinite(parsed) ? parsed : 0;
}

function caseRelativeTime(c: VettingCase, nowTs: number): string {
  const ts = caseTimestamp(c.created_at || c.date);
  if (!ts) return c.date || "";

  const diffMs = nowTs - ts;
  const diffH = Math.floor(diffMs / 3_600_000);
  const diffD = Math.floor(diffMs / 86_400_000);
  if (diffH < 1) return "Now";
  if (diffH < 24) return `${diffH}h`;
  if (diffD === 1) return "Yesterday";
  if (diffD < 7) return `${diffD}d`;
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function caseDispositionLabel(disposition: ReturnType<typeof portfolioDisposition>, lane: DecisionLane): string {
  if (disposition === "blocked") return "Blocked";
  if (disposition === "review") return "Review";
  if (disposition === "qualified") return "Qualified";
  if (lane === "cyber") return "Ready";
  if (lane === "counterparty") return "Approved";
  return "Clear";
}

function caseDispositionStyles(disposition: ReturnType<typeof portfolioDisposition>) {
  if (disposition === "blocked") {
    return { color: "#ef4444", background: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.28)" };
  }
  if (disposition === "review") {
    return { color: "#f97316", background: "rgba(249,115,22,0.12)", border: "rgba(249,115,22,0.28)" };
  }
  if (disposition === "qualified") {
    return { color: T.gold, background: `${T.gold}12`, border: `${T.gold}33` };
  }
  return { color: "#10b981", background: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.26)" };
}

function casePriorityScore(c: VettingCase, nowTs: number): number {
  const disposition = portfolioDisposition(c);
  const base =
    disposition === "blocked"
      ? 400
      : disposition === "review"
        ? 260
        : disposition === "qualified"
          ? 160
          : 80;
  const stopWeight = (c.cal?.stops?.length ?? 0) * 20;
  const flagWeight = (c.cal?.flags?.length ?? 0) * 12;
  const recentBoost = Math.max(0, 72 - Math.floor((nowTs - caseTimestamp(c.created_at || c.date)) / 3_600_000));
  return base + stopWeight + flagWeight + recentBoost;
}

function caseOperatorSummary(c: VettingCase): string {
  const stopText = c.cal?.stops?.[0]?.x?.trim();
  if (stopText) return stopText;
  const flagText = c.cal?.flags?.[0]?.x?.trim();
  if (flagText) return flagText;
  const recText = c.cal?.recommendation?.trim();
  if (recText) return recText;
  const sensitivity = c.cal?.sensitivityContext?.trim();
  if (sensitivity) return sensitivity;
  const regulatory = c.cal?.regulatoryStatus?.trim();
  if (regulatory) return regulatory;
  const find = c.cal?.finds?.[0]?.trim();
  if (find) return find;
  return c.program || c.profile || "Ready to continue analyst review.";
}

function createEmptyExportForm(): ExportAuthorizationCaseInput {
  return {
    request_type: "technical_data_release",
    recipient_name: "",
    recipient_type: "subcontractor",
    destination_country: "",
    jurisdiction_guess: "unknown",
    classification_guess: "",
    item_or_data_summary: "",
    end_use_summary: "",
    access_context: "",
    foreign_person_nationalities: [],
  };
}

function defaultExportProgram(input: ExportAuthorizationCaseInput): string {
  if (input.jurisdiction_guess === "itar") return "cat_xxi_misc";
  return "dual_use_ear";
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

export function HeliosLanding({
  onCaseCreated,
  onNavigate,
  onCasesRefresh,
  cases = [],
  preferredLane = "counterparty",
  onPreferredLaneChange,
}: HeliosLandingProps) {
  const [input, setInput] = useState("");
  const [searchMode, setSearchMode] = useState<"entity" | "vehicle" | "export">("entity");
  const [entityWorkflow, setEntityWorkflow] = useState<EntityWorkflow>("counterparty");
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
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [connectorCount, setConnectorCount] = useState(29);
  const [clockTs, setClockTs] = useState(() => Date.now());
  const [exportForm, setExportForm] = useState<ExportAuthorizationCaseInput>(() => createEmptyExportForm());
  const inputRef = useRef<HTMLInputElement>(null);
  const exportRecipientRef = useRef<HTMLInputElement>(null);
  const recommendedCandidate =
    resolution?.status === "recommended"
      ? candidates.find((candidate) => candidate.candidate_id === resolution.recommended_candidate_id) ?? null
      : null;
  const fallbackCandidates = recommendedCandidate
    ? candidates.filter((candidate) => candidate.candidate_id !== recommendedCandidate.candidate_id)
    : candidates;
  const entityWorkflowLabel = entityWorkflow === "cyber" ? "Supply chain assurance" : "Defense counterparty trust";
  const confirmIntro = entityWorkflow === "cyber"
    ? "Final check before Helios begins supply chain assurance review."
    : "Final check before Helios begins defense counterparty review.";
  const confirmPrimaryAction = entityWorkflow === "cyber" ? "Begin Cyber Review" : "Begin Counterparty Review";
  const activeLane: DecisionLane = searchMode === "export" ? "export" : entityWorkflow === "cyber" ? "cyber" : "counterparty";
  const activeLaneBrief = LANE_BRIEFS[activeLane];
  const activeLaneMeta = WORKFLOW_LANE_META[activeLane];
  const laneCases = cases
    .filter((c) => workflowLaneForCase(c) === activeLane)
    .sort((a, b) => caseTimestamp(b.created_at || b.date) - caseTimestamp(a.created_at || a.date));
  const recentLaneCases = laneCases.slice(0, 6);
  const priorityLaneCases = [...laneCases]
    .sort((a, b) => casePriorityScore(b, clockTs) - casePriorityScore(a, clockTs))
    .slice(0, 4);
  const laneCounts = (["counterparty", "cyber", "export"] as DecisionLane[]).reduce<Record<DecisionLane, { total: number; blocked: number; review: number }>>((acc, lane) => {
    const laneItems = cases.filter((c) => workflowLaneForCase(c) === lane);
    const dispositions = laneItems.map((c) => portfolioDisposition(c));
    acc[lane] = {
      total: laneItems.length,
      blocked: dispositions.filter((disposition) => disposition === "blocked").length,
      review: dispositions.filter((disposition) => disposition === "review").length,
    };
    return acc;
  }, {
    counterparty: { total: 0, blocked: 0, review: 0 },
    cyber: { total: 0, blocked: 0, review: 0 },
    export: { total: 0, blocked: 0, review: 0 },
  });
  const blockedCount = laneCases.filter((c) => portfolioDisposition(c) === "blocked").length;
  const reviewCount = laneCases.filter((c) => portfolioDisposition(c) === "review").length;
  const movingCount = laneCases.filter((c) => {
    const disposition = portfolioDisposition(c);
    return disposition === "clear" || disposition === "qualified";
  }).length;
  const freshCount = laneCases.filter((c) => clockTs - caseTimestamp(c.created_at || c.date) <= 86_400_000).length;
  const primaryPlaceholder =
    activeLane === "cyber"
      ? "Enter supplier, product vendor, or software provider"
      : activeLane === "counterparty"
        ? "Enter supplier, subcontractor, or prime contractor"
        : "Enter recipient, foreign person, or item destination";

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    fetchHealth()
      .then((health) => {
        if ((health.osint_connector_count ?? 0) > 0) {
          setConnectorCount(health.osint_connector_count ?? 29);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (phase !== "idle") return;
    const syncTimer = window.setTimeout(() => {
      if (preferredLane === "export") {
        setSearchMode("export");
        return;
      }
      setSearchMode("entity");
      setEntityWorkflow(preferredLane === "cyber" ? "cyber" : "counterparty");
    }, 0);
    return () => window.clearTimeout(syncTimer);
  }, [phase, preferredLane]);

  useEffect(() => {
    if (phase !== "idle") return;
    const timer = window.setInterval(() => setClockTs(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [phase]);

  const focusEntityInput = useCallback(() => {
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const openVehicleUtility = useCallback(() => {
    setSearchMode("vehicle");
    setEntityWorkflow("counterparty");
    setInput("");
    setErrorText("");
    focusEntityInput();
  }, [focusEntityInput]);

  const handleLaneSelect = useCallback((lane: DecisionLane) => {
    onPreferredLaneChange?.(lane);
    setErrorText("");
    setInput("");
    setPhase("idle");
    setStatusText("");
    if (lane === "export") {
      setSearchMode("export");
      return;
    }
    setSearchMode("entity");
    setEntityWorkflow(lane === "cyber" ? "cyber" : "counterparty");
    focusEntityInput();
  }, [focusEntityInput, onPreferredLaneChange]);

  // Step 1: User submits a name -> resolve entity
  const handleSubmit = async () => {
    if (searchMode === "vehicle") {
      await handleVehicleSearch();
      return;
    }
    if (searchMode === "export") {
      await handleExportSubmit();
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

  const handleExportField = <K extends keyof ExportAuthorizationCaseInput>(field: K, value: ExportAuthorizationCaseInput[K]) => {
    setExportForm((current) => ({ ...current, [field]: value }));
  };

  const handleExportSubmit = async () => {
    const recipientName = exportForm.recipient_name?.trim() || "";
    const destinationCountry = exportForm.destination_country?.trim().toUpperCase() || "";

    if (!recipientName || !destinationCountry || phase !== "idle") {
      return;
    }

    setEntityName(recipientName);
    setPhase("creating");
    setStatusText("Creating export authorization case...");
    setErrorText("");

    try {
      const createResp = await createCase({
        name: recipientName,
        country: destinationCountry,
        ownership: {
          publicly_traded: false,
          state_owned: false,
          beneficial_owner_known: false,
          ownership_pct_resolved: 0.2,
          shell_layers: 0,
          pep_connection: false,
        },
        data_quality: {
          has_lei: false,
          has_cage: false,
          has_duns: false,
          has_tax_id: false,
          has_audited_financials: false,
          years_of_records: 0,
        },
        exec: { known_execs: 0, adverse_media: 0, pep_execs: 0, litigation_history: 0 },
        program: defaultExportProgram(exportForm),
        profile: "itar_trade_compliance",
        export_authorization: {
          ...exportForm,
          recipient_name: recipientName,
          destination_country: destinationCountry,
          classification_guess: exportForm.classification_guess?.trim() || "",
          item_or_data_summary: exportForm.item_or_data_summary?.trim() || "",
          end_use_summary: exportForm.end_use_summary?.trim() || "",
          access_context: exportForm.access_context?.trim() || "",
          foreign_person_nationalities: (exportForm.foreign_person_nationalities ?? []).filter(Boolean),
        },
      });

      const caseId = createResp.case_id;
      setActiveCaseId(caseId);
      setPhase("enriching");
      setStatusText(`Running ${connectorCount} live OSINT connectors and 10 regulatory gates...`);
    } catch (err: unknown) {
      setPhase("error");
      setErrorText((err as Error)?.message || "Export authorization request failed.");
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
      setActiveCaseId(caseId);
      setPhase("enriching");
      setStatusText(`Running ${connectorCount} live OSINT connectors and 10 regulatory gates...`);
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
    setEntityWorkflow("counterparty");
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
      await onCasesRefresh?.();
      setBatchResults({ total: result.total, created: result.created });
      setBatchStatus("done");
    } catch {
      setBatchStatus("idle");
    }
  };

  const handleViewDraftCases = async () => {
    await onCasesRefresh?.();
    onNavigate("portfolio");
  };

  const reset = () => {
    setPhase("idle"); setStatusText(""); setErrorText("");
    if (preferredLane === "export") {
      setSearchMode("export");
    } else {
      setSearchMode("entity");
      setEntityWorkflow(preferredLane === "cyber" ? "cyber" : "counterparty");
    }
    setExportForm(createEmptyExportForm());
    setEntityName(""); setCandidates([]); setConfirmed(null);
    setResolution(null); setShowRationale(false);
    setVehicleResults(null);
    setShowGraph(false); setBatchStatus("idle"); setBatchResults(null);
    setActiveCaseId(null);
    if (preferredLane !== "export") {
      inputRef.current?.focus();
    }
  };

  const handleInitialEnrichmentComplete = () => {
    if (!activeCaseId) return;
    setPhase("done");
    setStatusText("Assessment complete.");
    setTimeout(() => { onCaseCreated(activeCaseId); }, 700);
  };



  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "82vh", padding: "8px 24px 24px", width: "100%" }}>

      {/* ── IDLE ── */}
      {phase === "idle" && (
        <div style={{ width: "100%", maxWidth: 1400 }} className="animate-slide-up">
          <div className="stagger-children" style={{ display: "flex", flexDirection: "column", gap: 18, width: "100%" }}>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {(["counterparty", "cyber", "export"] as DecisionLane[]).map((lane) => {
                const meta = WORKFLOW_LANE_META[lane];
                const brief = LANE_BRIEFS[lane];
                const counts = laneCounts[lane];
                const active = lane === activeLane;
                const LaneIcon = LANE_ICONS[lane];
                return (
                  <button
                    key={lane}
                    onClick={() => handleLaneSelect(lane)}
                    className="glass-card card-interactive helios-focus-ring"
                    style={{
                      padding: 18,
                      borderRadius: 22,
                      border: `1px solid ${active ? meta.softBorder : T.borderStrong}`,
                      background: active
                        ? `linear-gradient(145deg, ${meta.softBackground}, rgba(10, 18, 30, 0.88))`
                        : FX.panelStrong,
                      boxShadow: active ? FX.cardGlow : FX.softShadow,
                      textAlign: "left",
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 36,
                            height: 36,
                            borderRadius: 12,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            background: active ? `${meta.accent}22` : T.surfaceElevated,
                            border: `1px solid ${active ? `${meta.accent}44` : T.border}`,
                            color: meta.accent,
                          }}
                        >
                          <LaneIcon size={18} />
                        </div>
                        <div>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                            {meta.shortLabel}
                          </div>
                          <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700 }}>{brief.title}</div>
                        </div>
                      </div>
                      {active && (
                        <span style={{ fontSize: 11, color: meta.accent, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                          Active
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.5 }}>{meta.description}</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: FS.caption, color: T.text, padding: "5px 8px", borderRadius: 999, background: T.surfaceElevated, border: `1px solid ${T.border}` }}>
                        {counts.total} active
                      </span>
                      <span style={{ fontSize: FS.caption, color: T.textSecondary, padding: "5px 8px", borderRadius: 999, background: "rgba(249,115,22,0.10)", border: "1px solid rgba(249,115,22,0.2)" }}>
                        {counts.review} review
                      </span>
                      <span style={{ fontSize: FS.caption, color: T.textSecondary, padding: "5px 8px", borderRadius: 999, background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.2)" }}>
                        {counts.blocked} blocked
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 items-start">
              <div className="xl:col-span-2 flex flex-col gap-5">
                <section
                  className="glass-panel"
                  style={{
                    padding: 28,
                    borderRadius: 28,
                    border: `1px solid ${activeLaneMeta.softBorder}`,
                    background: `linear-gradient(145deg, ${activeLaneMeta.softBackground}, rgba(10, 18, 30, 0.9))`,
                    boxShadow: FX.cardGlow,
                  }}
                >
                  <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_260px] gap-5 items-start">
                    <div>
                      <div style={{ fontSize: 11, color: activeLaneMeta.accent, marginBottom: 10, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                        Helios command desk
                      </div>
                      <h1 style={{ margin: 0, fontSize: "clamp(30px, 4vw, 46px)", lineHeight: 1.04, letterSpacing: "-0.04em", color: T.text, fontWeight: 800 }}>
                        Start the next {activeLaneMeta.shortLabel.toLowerCase()} decision.
                      </h1>
                      <p style={{ marginTop: 14, marginBottom: 0, fontSize: FS.base, color: T.textSecondary, lineHeight: 1.65, maxWidth: 760 }}>
                        {activeLaneBrief.question} Land here to open a new case, resume the queue, or pivot lanes without leaving the dashboard.
                      </p>
                    </div>
                    <div
                      className="glass-card"
                      style={{
                        padding: 18,
                        borderRadius: 20,
                        border: `1px solid ${activeLaneMeta.softBorder}`,
                        background: "rgba(7, 12, 22, 0.62)",
                      }}
                    >
                      <div style={{ fontSize: 11, color: T.muted, marginBottom: 8, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                        Decision frame
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginBottom: 12 }}>
                        {activeLaneBrief.outputs}
                      </div>
                      <div style={{ fontSize: FS.caption, color: T.muted, lineHeight: 1.55 }}>
                        {activeLaneBrief.evidence}
                      </div>
                    </div>
                  </div>

                  {searchMode !== "export" ? (
                    <>
                      <div style={{ position: "relative", width: "100%", marginTop: 24 }}>
                        <input
                          ref={inputRef}
                          value={input}
                          onChange={e => setInput(e.target.value)}
                          onKeyDown={e => e.key === "Enter" && handleSubmit()}
                          placeholder={primaryPlaceholder}
                          className="helios-focus-ring"
                          style={{
                            width: "100%",
                            padding: "18px 64px 18px 20px",
                            borderRadius: 18,
                            border: `1px solid ${T.border}`,
                            background: "rgba(7, 12, 22, 0.7)",
                            color: T.text,
                            fontSize: FS.base,
                            outline: "none",
                            transition: "all 0.3s",
                            fontFamily: "inherit",
                          }}
                          onFocus={e => {
                            e.target.style.borderColor = activeLaneMeta.softBorder;
                            e.target.style.boxShadow = `0 0 0 3px ${activeLaneMeta.softBackground}`;
                          }}
                          onBlur={e => {
                            e.target.style.borderColor = T.border;
                            e.target.style.boxShadow = "none";
                          }}
                        />
                        <button
                          onClick={handleSubmit}
                          className="helios-focus-ring"
                          style={{
                            position: "absolute",
                            right: 8,
                            top: "50%",
                            transform: "translateY(-50%)",
                            width: 44,
                            height: 44,
                            borderRadius: 14,
                            border: "none",
                            background: input.trim() ? activeLaneMeta.accent : T.border,
                            color: input.trim() ? "#04101f" : T.textTertiary,
                            cursor: input.trim() ? "pointer" : "default",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <ArrowRight size={18} />
                        </button>
                      </div>

                      <div className="flex flex-wrap items-center gap-3" style={{ marginTop: 16 }}>
                        <button
                          onClick={handleSubmit}
                          disabled={!input.trim()}
                          className="btn-interactive helios-focus-ring"
                          style={{
                            padding: "12px 16px",
                            borderRadius: 14,
                            border: "none",
                            background: input.trim() ? activeLaneMeta.accent : T.border,
                            color: input.trim() ? "#04101f" : T.textTertiary,
                            cursor: input.trim() ? "pointer" : "default",
                            fontSize: FS.sm,
                            fontWeight: 800,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          {activeLane === "cyber" ? "Start cyber review" : "Start counterparty review"}
                          <ArrowRight size={14} />
                        </button>

                        {activeLane === "counterparty" && (
                          <button
                            onClick={openVehicleUtility}
                            className="btn-interactive helios-focus-ring"
                            style={{
                              padding: "12px 16px",
                              borderRadius: 14,
                              border: `1px solid ${T.border}`,
                              background: "rgba(7, 12, 22, 0.6)",
                              color: T.textSecondary,
                              cursor: "pointer",
                              fontSize: FS.sm,
                              fontWeight: 700,
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 8,
                            }}
                          >
                            <GitBranch size={14} />
                            Search contract vehicle
                          </button>
                        )}

                        <button
                          onClick={() => { void handleViewDraftCases(); }}
                          className="btn-interactive helios-focus-ring"
                          style={{
                            padding: "12px 16px",
                            borderRadius: 14,
                            border: `1px solid ${T.border}`,
                            background: "rgba(7, 12, 22, 0.6)",
                            color: T.textSecondary,
                            cursor: "pointer",
                            fontSize: FS.sm,
                            fontWeight: 700,
                          }}
                        >
                          Open lane portfolio
                        </button>
                      </div>
                    </>
                  ) : (
                    <div
                      className="glass-card"
                      style={{
                        width: "100%",
                        marginTop: 24,
                        padding: 20,
                        borderRadius: 24,
                        background: "rgba(7, 12, 22, 0.62)",
                        border: `1px solid ${T.borderStrong}`,
                      }}
                    >
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <div>
                          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Authorization request
                          </div>
                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Request type</label>
                          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                            {EXPORT_REQUEST_TYPE_OPTIONS.map((option) => {
                              const active = exportForm.request_type === option.value;
                              return (
                                <button
                                  key={option.value}
                                  onClick={() => handleExportField("request_type", option.value)}
                                  style={{
                                    textAlign: "left",
                                    padding: "11px 12px",
                                    borderRadius: 12,
                                    border: `1px solid ${active ? `${GOLD}44` : T.border}`,
                                    background: active ? `${GOLD}10` : T.surface,
                                    cursor: "pointer",
                                  }}
                                >
                                  <div style={{ fontSize: FS.sm, color: active ? T.text : T.dim, fontWeight: 700 }}>{option.label}</div>
                                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4, lineHeight: 1.45 }}>{option.description}</div>
                                </button>
                              );
                            })}
                          </div>

                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Recipient or access subject</label>
                          <input
                            ref={exportRecipientRef}
                            value={exportForm.recipient_name ?? ""}
                            onChange={(e) => handleExportField("recipient_name", e.target.value)}
                            placeholder="Company, affiliate, foreign national, or subcontractor"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", marginBottom: 12 }}
                          />

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div>
                              <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Destination or access country</label>
                              <input
                                value={exportForm.destination_country ?? ""}
                                onChange={(e) => handleExportField("destination_country", e.target.value.toUpperCase())}
                                placeholder="DE, JP, SG"
                                maxLength={3}
                                style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                              />
                            </div>
                            <div>
                              <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Jurisdiction guess</label>
                              <select
                                value={exportForm.jurisdiction_guess ?? "unknown"}
                                onChange={(e) => handleExportField("jurisdiction_guess", e.target.value as ExportAuthorizationCaseInput["jurisdiction_guess"])}
                                style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                              >
                                {EXPORT_JURISDICTION_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                              </select>
                            </div>
                          </div>
                        </div>

                        <div>
                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Classification guess</label>
                          <input
                            value={exportForm.classification_guess ?? ""}
                            onChange={(e) => handleExportField("classification_guess", e.target.value)}
                            placeholder="USML Cat XI, ECCN 3A001, EAR99..."
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", marginBottom: 12 }}
                          />

                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Item, software, or data summary</label>
                          <textarea
                            value={exportForm.item_or_data_summary ?? ""}
                            onChange={(e) => handleExportField("item_or_data_summary", e.target.value)}
                            placeholder="Briefly describe the item, technical data, source code, or controlled environment under review."
                            rows={4}
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", resize: "vertical", marginBottom: 12, fontFamily: "inherit" }}
                          />

                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>End use or access context</label>
                          <textarea
                            value={exportForm.end_use_summary ?? ""}
                            onChange={(e) => handleExportField("end_use_summary", e.target.value)}
                            placeholder="Program, end use, destination, collaboration, or review context."
                            rows={3}
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", resize: "vertical", marginBottom: 12, fontFamily: "inherit" }}
                          />

                          <label style={{ display: "block", fontSize: FS.sm, color: T.dim, marginBottom: 6 }}>Foreign-person nationalities (optional)</label>
                          <input
                            value={(exportForm.foreign_person_nationalities ?? []).join(", ")}
                            onChange={(e) => handleExportField("foreign_person_nationalities", e.target.value.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean))}
                            placeholder="CN, IN, AE"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                          />
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginTop: 16 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, color: T.muted, fontSize: FS.sm }}>
                          <Globe2 size={14} color={GOLD} />
                          Helios will open a case, run the live screening stack, and structure the decision around likely prohibited, license required, or escalation paths.
                        </div>
                        <button
                          onClick={handleSubmit}
                          disabled={!exportForm.recipient_name?.trim() || !exportForm.destination_country?.trim()}
                          className="btn-interactive helios-focus-ring"
                          style={{
                            padding: "11px 16px",
                            borderRadius: 12,
                            border: "none",
                            background: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? GOLD : T.border,
                            color: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? "#000" : T.muted,
                            cursor: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? "pointer" : "default",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          Open export authorization case
                          <ArrowRight size={14} />
                        </button>
                      </div>
                    </div>
                  )}
                </section>

                <section
                  className="glass-card"
                  style={{
                    padding: 22,
                    borderRadius: 24,
                    border: `1px solid ${T.borderStrong}`,
                    background: FX.panelStrong,
                  }}
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginBottom: 14 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                        Priority queue
                      </div>
                      <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 4 }}>
                        What needs operator attention now
                      </div>
                    </div>
                    {laneCases.length > 0 && (
                      <button
                        onClick={() => { void handleViewDraftCases(); }}
                        className="btn-interactive helios-focus-ring"
                        style={{
                          padding: "10px 14px",
                          borderRadius: 12,
                          border: `1px solid ${T.border}`,
                          background: T.surface,
                          color: T.textSecondary,
                          cursor: "pointer",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                      >
                        See all {laneCases.length} lane cases
                      </button>
                    )}
                  </div>

                  {priorityLaneCases.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {priorityLaneCases.map((c) => {
                        const disposition = portfolioDisposition(c);
                        const styles = caseDispositionStyles(disposition);
                        return (
                          <button
                            key={c.id}
                            onClick={() => onCaseCreated(c.id)}
                            className="card-interactive helios-focus-ring"
                            style={{
                              width: "100%",
                              padding: 16,
                              borderRadius: 18,
                              border: `1px solid ${T.border}`,
                              background: "rgba(7, 12, 22, 0.56)",
                              textAlign: "left",
                              display: "flex",
                              alignItems: "flex-start",
                              justifyContent: "space-between",
                              gap: 14,
                            }}
                          >
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                                <span style={{ width: 8, height: 8, borderRadius: 999, background: styles.color, flexShrink: 0 }} />
                                <span style={{ fontSize: FS.base, color: T.text, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {displayName(c.name)}
                                </span>
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>
                                {caseOperatorSummary(c)}
                              </div>
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0 }}>
                              <span style={{ fontSize: FS.caption, color: T.muted, fontVariantNumeric: "tabular-nums" }}>
                                {caseRelativeTime(c, clockTs)}
                              </span>
                              <span
                                style={{
                                  fontSize: FS.caption,
                                  fontWeight: 800,
                                  letterSpacing: "0.06em",
                                  padding: "5px 8px",
                                  borderRadius: 999,
                                  color: styles.color,
                                  background: styles.background,
                                  border: `1px solid ${styles.border}`,
                                  textTransform: "uppercase",
                                }}
                              >
                                {caseDispositionLabel(disposition, activeLane)}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div
                      className="glass-card"
                      style={{
                        padding: 18,
                        borderRadius: 18,
                        border: `1px dashed ${T.borderStrong}`,
                        background: "rgba(7, 12, 22, 0.42)",
                      }}
                    >
                      <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginBottom: 6 }}>
                        No active {activeLaneMeta.shortLabel.toLowerCase()} queue yet.
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>
                        Use this page to start the first case in this lane, then Helios will route the decision package into the portfolio and graph surfaces automatically.
                      </div>
                    </div>
                  )}
                </section>
              </div>

              <div className="flex flex-col gap-5">
                <section
                  className="glass-card"
                  style={{
                    padding: 22,
                    borderRadius: 24,
                    border: `1px solid ${T.borderStrong}`,
                    background: FX.panelStrong,
                  }}
                >
                  <div style={{ fontSize: 11, color: T.muted, marginBottom: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    Lane status
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { label: "Active", value: laneCases.length, tone: T.text },
                      { label: "Needs decision", value: blockedCount + reviewCount, tone: "#f97316" },
                      { label: "Moving", value: movingCount, tone: "#10b981" },
                      { label: "Live connectors", value: connectorCount, tone: activeLaneMeta.accent },
                    ].map((metric) => (
                      <div
                        key={metric.label}
                        className="glass-card"
                        style={{
                          padding: 14,
                          borderRadius: 18,
                          border: `1px solid ${T.border}`,
                          background: "rgba(7, 12, 22, 0.52)",
                        }}
                      >
                        <div style={{ fontSize: 11, color: T.muted, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 700 }}>
                          {metric.label}
                        </div>
                        <div style={{ fontSize: "clamp(24px, 3vw, 34px)", fontWeight: 800, lineHeight: 1, color: metric.tone }}>
                          {metric.value}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6, marginTop: 14 }}>
                    {freshCount} case{freshCount === 1 ? "" : "s"} moved in the last 24 hours. {blockedCount > 0 ? "Blocked work is still sitting in this lane." : "No hard-stop backlog is waiting here."}
                  </div>
                </section>

                <section
                  className="glass-card"
                  style={{
                    padding: 22,
                    borderRadius: 24,
                    border: `1px solid ${T.borderStrong}`,
                    background: FX.panelStrong,
                  }}
                >
                  <div style={{ fontSize: 11, color: T.muted, marginBottom: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    Quick actions
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <button
                      onClick={() => { void handleViewDraftCases(); }}
                      className="btn-interactive helios-focus-ring"
                      style={{
                        padding: "13px 14px",
                        borderRadius: 16,
                        border: `1px solid ${T.border}`,
                        background: T.surface,
                        color: T.text,
                        cursor: "pointer",
                        textAlign: "left",
                        fontWeight: 700,
                      }}
                    >
                      Open portfolio workbench
                    </button>
                    <button
                      onClick={() => onNavigate("graph")}
                      className="btn-interactive helios-focus-ring"
                      style={{
                        padding: "13px 14px",
                        borderRadius: 16,
                        border: `1px solid ${T.border}`,
                        background: T.surface,
                        color: T.text,
                        cursor: "pointer",
                        textAlign: "left",
                        fontWeight: 700,
                      }}
                    >
                      Open graph intelligence
                    </button>
                    <button
                      onClick={() => onNavigate("dashboard")}
                      className="btn-interactive helios-focus-ring"
                      style={{
                        padding: "13px 14px",
                        borderRadius: 16,
                        border: `1px solid ${T.border}`,
                        background: T.surface,
                        color: T.text,
                        cursor: "pointer",
                        textAlign: "left",
                        fontWeight: 700,
                      }}
                    >
                      Open compliance dashboard
                    </button>
                    {activeLane === "counterparty" && (
                      <button
                        onClick={openVehicleUtility}
                        className="btn-interactive helios-focus-ring"
                        style={{
                          padding: "13px 14px",
                          borderRadius: 16,
                          border: `1px solid ${T.border}`,
                          background: T.surface,
                          color: T.text,
                          cursor: "pointer",
                          textAlign: "left",
                          fontWeight: 700,
                        }}
                      >
                        Search contract vehicle
                      </button>
                    )}
                  </div>
                </section>

                <section
                  className="glass-card"
                  style={{
                    padding: 22,
                    borderRadius: 24,
                    border: `1px solid ${T.borderStrong}`,
                    background: FX.panelStrong,
                  }}
                >
                  <div style={{ fontSize: 11, color: T.muted, marginBottom: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    Recent activity
                  </div>
                  {recentLaneCases.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {recentLaneCases.slice(0, 3).map((c) => {
                        const disposition = portfolioDisposition(c);
                        const styles = caseDispositionStyles(disposition);
                        return (
                          <button
                            key={c.id}
                            onClick={() => onCaseCreated(c.id)}
                            className="card-interactive helios-focus-ring"
                            style={{
                              width: "100%",
                              padding: 14,
                              borderRadius: 16,
                              border: `1px solid ${T.border}`,
                              background: "rgba(7, 12, 22, 0.48)",
                              textAlign: "left",
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {displayName(c.name)}
                              </div>
                              <div style={{ fontSize: FS.caption, color: T.muted }}>{caseRelativeTime(c, clockTs)}</div>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ width: 7, height: 7, borderRadius: 999, background: styles.color, flexShrink: 0 }} />
                              <span style={{ fontSize: FS.caption, color: T.textSecondary }}>
                                {caseDispositionLabel(disposition, activeLane)}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>
                      No recent case movement in this lane yet.
                    </div>
                  )}
                </section>
              </div>
            </div>
          </div>
        </div>
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
                <button onClick={() => { void handleViewDraftCases(); }}
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
          <div style={{ fontSize: 12, color: GOLD_DIM, letterSpacing: "0.08em", fontWeight: 600, marginBottom: 12 }}>{entityWorkflowLabel}</div>
          <div style={{ fontSize: FS.xl, fontWeight: 600, color: T.text, marginBottom: 8 }}>Ready to assess</div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginBottom: 24 }}>
            {confirmIntro}
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
                <label style={{ fontSize: 11, color: T.muted, fontWeight: 600, letterSpacing: "0.02em", display: "block", marginBottom: 6 }}>Mission context</label>
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
                {entityWorkflow === "cyber" ? (
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Confirm the supplier and identifiers</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Run live screening and prepare cyber-readiness evidence lanes</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Score the case and recommend a supplier trust posture</div>
                  </>
                ) : (
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Confirm the entity and its identifiers</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Run live OSINT and ownership / FOCI screening</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Score the case and recommend a counterparty disposition</div>
                  </>
                )}
              </div>
              <div style={{ fontSize: 11, color: T.muted, marginTop: 8 }}>Estimated: 30-60 seconds</div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={handleEdit} style={{ flex: 1, padding: "14px", borderRadius: 10, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, fontWeight: 600, cursor: "pointer" }}>
              Cancel
            </button>
            <button onClick={handleConfirm} style={{ flex: 2, padding: "14px 20px", borderRadius: 10, border: "none", background: GOLD, color: "#000", fontSize: FS.base, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <CheckCircle size={16} /> {confirmPrimaryAction}
            </button>
          </div>
        </div>
      )}

      {/* ── CREATING / ENRICHING ── */}
      {(phase === "creating" || phase === "enriching") && (
        <div style={{ width: "100%", maxWidth: 760 }}>
          {phase === "creating" && (
            <div style={{ textAlign: "center", maxWidth: 480, margin: "0 auto" }}>
              <Loader2 size={40} color={GOLD} style={{ animation: "hs 1.5s linear infinite", marginBottom: 20 }} />
              <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 8 }}>{confirmed?.legalName || entityName}</div>
              <div style={{ fontSize: FS.base, color: T.dim, marginBottom: 16 }}>{statusText}</div>
            </div>
          )}

          {phase === "enriching" && activeCaseId && (
            <div>
              <div style={{ textAlign: "center", marginBottom: 16 }}>
                <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 8 }}>{confirmed?.legalName || entityName}</div>
                <div style={{ fontSize: FS.base, color: T.dim }}>{statusText}</div>
              </div>
              <EnrichmentStream
                caseId={activeCaseId}
                apiBase={import.meta.env.VITE_API_URL ?? ""}
                onComplete={handleInitialEnrichmentComplete}
              />
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
      `}</style>
    </div>
  );
}
