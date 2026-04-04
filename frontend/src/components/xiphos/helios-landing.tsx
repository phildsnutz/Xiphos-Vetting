/**
 * Xiphos Helios Landing
 *
 * AI command interface with entity resolution.
 * Flow: Enter name -> Resolve entity (SEC/GLEIF/Wikidata) -> Show candidates ->
 *       User confirms -> Set context -> Create case -> Enrich -> Hand off
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowRight, CheckCircle, Loader2, XCircle, Building2, Truck, GitBranch, Zap, Sparkles, ChevronDown, Globe2 } from "lucide-react";
import { T, FS, FX, O, PAD, SP, displayName } from "@/lib/tokens";
import { createCase, resolveEntity, searchContractVehicle, batchAssessVehicle, submitResolveFeedback, fetchHealth } from "@/lib/api";
import type { EntityCandidate, VehicleVendor, VehicleSearchResult, EntityResolution, ExportAuthorizationCaseInput } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { SupplyChainGraph } from "./supply-chain-graph";
import { EnrichmentStream } from "./enrichment-stream";
import { PRODUCT_PILLAR_META, WORKFLOW_LANE_META, portfolioDisposition, workflowLaneForCase } from "./portfolio-utils";
import type { ProductPillar } from "./portfolio-utils";
import { EmptyPanel, InlineMessage, SectionEyebrow } from "./shell-primitives";

const GOLD = T.gold;
const GOLD_DIM = T.goldDim;

interface HeliosLandingProps {
  onCaseCreated: (caseId: string) => void;
  onNavigate: (tab: string) => void;
  onCasesRefresh?: () => Promise<void>;
  cases?: VettingCase[];
  preferredLane?: DecisionLane;
  preferredPillar?: ProductPillar;
  onPreferredLaneChange?: (lane: DecisionLane) => void;
  onPreferredPillarChange?: (pillar: ProductPillar) => void;
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
    title: "Core vendor assessment",
    question: "Can we trust, pursue, partner with, or approve this vendor from the core diligence record?",
    outputs: "Approved / Qualified / Review / Blocked",
    evidence: "Form 328, ownership charts, SAM.gov registration, SAM.gov subaward reporting, sanctions, and network context",
    useWhen: "Use this as the default path for supplier trust, ownership, FOCI, and pre-award adjudication.",
  },
  cyber: {
    title: "Cyber support layer",
    question: "What cyber, software, and remediation evidence should change the vendor decision?",
    outputs: "Raises trust / preserves trust / requires review / blocks work",
    evidence: "SPRS exports, OSCAL SSP or POA&M artifacts, SBOM or VEX evidence, and product vulnerability overlays",
    useWhen: "Use this when the vendor decision depends on CMMC readiness, dependency risk, or software assurance evidence.",
  },
  export: {
    title: "Export support layer",
    question: "What export-control evidence should change the vendor decision or access boundary?",
    outputs: "Likely prohibited / License required / Exception path / Likely NLR / Escalate",
    evidence: "Classification memos, license history, access-control records, and BIS or DDTC rule guidance",
    useWhen: "Use this when item transfer, technical-data release, or foreign-person access changes the vendor decision.",
  },
};

const PILLAR_BRIEFS: Record<ProductPillar, { title: string; question: string; outputs: string; evidence: string; useWhen: string }> = {
  vendor_assessment: {
    title: "Vendor Assessment",
    question: "Can we trust, clear, or block this vendor once the right supporting layers are in scope?",
    outputs: "Approved / Watch / Review / Blocked",
    evidence: "Core diligence, cyber evidence, export controls, graph context, and AXIOM gap closure.",
    useWhen: "Use this when the decision starts with a supplier, subcontractor, affiliate, or prime.",
  },
  contract_vehicle: {
    title: "Contract Vehicle Intelligence",
    question: "What does this vehicle’s prime and sub ecosystem tell us about who to pursue, partner with, or attack?",
    outputs: "Vehicle map / vendor queue / dossier leads",
    evidence: "Award spine, subaward fragments, teammate inference, AXIOM collection, and dossier closure.",
    useWhen: "Use this when the work starts from a vehicle, not a supplier.",
  },
};

const PILLAR_ICONS: Record<ProductPillar, typeof Building2> = {
  vendor_assessment: Building2,
  contract_vehicle: GitBranch,
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
    return { color: T.red, background: T.redBg, border: `${T.red}${O["30"]}` };
  }
  if (disposition === "review") {
    return { color: T.amber, background: T.amberBg, border: `${T.amber}${O["30"]}` };
  }
  if (disposition === "qualified") {
    return { color: T.accent, background: T.accentSoft, border: `${T.accent}${O["30"]}` };
  }
  return { color: T.green, background: T.greenBg, border: `${T.green}${O["30"]}` };
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
  preferredPillar = "vendor_assessment",
  onPreferredLaneChange,
  onPreferredPillarChange,
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
  const activePillar: ProductPillar = searchMode === "vehicle" ? "contract_vehicle" : "vendor_assessment";
  const activeLane: DecisionLane = searchMode === "export" ? "export" : entityWorkflow === "cyber" ? "cyber" : "counterparty";
  const activePillarBrief = PILLAR_BRIEFS[activePillar];
  const activePillarMeta = PRODUCT_PILLAR_META[activePillar];
  const activeLaneBrief = LANE_BRIEFS[activeLane];
  const activeLaneMeta = WORKFLOW_LANE_META[activeLane];
  const entityWorkflowLabel = entityWorkflow === "cyber" ? "Vendor assessment · cyber layer" : "Vendor assessment · core layer";
  const confirmIntro = entityWorkflow === "cyber"
    ? "Final check before Helios opens a vendor assessment with cyber evidence in scope."
    : "Final check before Helios opens the vendor assessment.";
  const confirmPrimaryAction = "Begin Vendor Assessment";
  const laneCases = [...cases]
    .sort((a, b) => caseTimestamp(b.created_at || b.date) - caseTimestamp(a.created_at || a.date));
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
    activePillar === "contract_vehicle"
      ? "Enter contract vehicle name, PIID, or solicitation"
      : activeLane === "cyber"
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
      if (preferredPillar === "contract_vehicle") {
        setSearchMode("vehicle");
        setEntityWorkflow("counterparty");
        return;
      }
      if (preferredLane === "export") {
        setSearchMode("export");
        return;
      }
      setSearchMode("entity");
      setEntityWorkflow(preferredLane === "cyber" ? "cyber" : "counterparty");
    }, 0);
    return () => window.clearTimeout(syncTimer);
  }, [phase, preferredLane, preferredPillar]);

  useEffect(() => {
    if (phase !== "idle") return;
    const timer = window.setInterval(() => setClockTs(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [phase]);

  const focusEntityInput = useCallback(() => {
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const openVehicleUtility = useCallback(() => {
    onPreferredPillarChange?.("contract_vehicle");
    setSearchMode("vehicle");
    setEntityWorkflow("counterparty");
    setInput("");
    setErrorText("");
    focusEntityInput();
  }, [focusEntityInput, onPreferredPillarChange]);

  const handlePillarSelect = useCallback((pillar: ProductPillar) => {
    onPreferredPillarChange?.(pillar);
    setErrorText("");
    setInput("");
    setPhase("idle");
    setStatusText("");
    if (pillar === "contract_vehicle") {
      setSearchMode("vehicle");
      setEntityWorkflow("counterparty");
      focusEntityInput();
      return;
    }
    if (preferredLane === "export") {
      setSearchMode("export");
      return;
    }
    setSearchMode("entity");
    setEntityWorkflow(preferredLane === "cyber" ? "cyber" : "counterparty");
    focusEntityInput();
  }, [focusEntityInput, onPreferredPillarChange, preferredLane]);

  const handleLaneSelect = useCallback((lane: DecisionLane) => {
    onPreferredLaneChange?.(lane);
    onPreferredPillarChange?.("vendor_assessment");
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
  }, [focusEntityInput, onPreferredLaneChange, onPreferredPillarChange]);

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
    setStatusText("Creating vendor assessment with export layer...");
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
    if (preferredPillar === "contract_vehicle") {
      setSearchMode("vehicle");
    } else if (preferredLane === "export") {
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
    if (preferredPillar !== "contract_vehicle" && preferredLane !== "export") {
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
        <div style={{ width: "100%", maxWidth: 1360 }} className="animate-slide-up">
          <div style={{ display: "flex", flexDirection: "column", gap: SP.lg, width: "100%" }}>
            <section
              className="glass-card"
              style={{
                padding: PAD.default,
                borderRadius: 18,
                display: "flex",
                flexDirection: "column",
                gap: SP.sm,
              }}
            >
              <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div style={{ minWidth: 0, flex: 1, maxWidth: 760 }}>
                  <SectionEyebrow>Start point</SectionEyebrow>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 800, marginTop: SP.xs }}>
                    Choose the object first. Helios will route the rest of the workflow around it.
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.xs }}>
                    Vendor Assessment starts from the supplier. Contract Vehicle Intelligence starts from the vehicle and spins the right vendors into assessment.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(["vendor_assessment", "contract_vehicle"] as ProductPillar[]).map((pillar) => {
                    const meta = PRODUCT_PILLAR_META[pillar];
                    const active = pillar === activePillar;
                    const PillarIcon = PILLAR_ICONS[pillar];
                    return (
                      <button
                        key={pillar}
                        type="button"
                        onClick={() => handlePillarSelect(pillar)}
                        className="helios-focus-ring"
                        aria-label={`Switch intake start point to ${meta.label}`}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: SP.xs,
                          padding: "10px 14px",
                          borderRadius: 999,
                          border: `1px solid ${active ? meta.softBorder : T.border}`,
                          background: active ? meta.softBackground : T.surface,
                          color: active ? meta.accent : T.textSecondary,
                          cursor: "pointer",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                        title={meta.description}
                      >
                        <PillarIcon size={14} />
                        {meta.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <InlineMessage
                tone={activePillar === "contract_vehicle" ? "info" : "neutral"}
                title={activePillarBrief.title}
                message={activePillarBrief.useWhen}
                icon={activePillar === "contract_vehicle" ? GitBranch : Building2}
              />

              {activePillar === "vendor_assessment" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                  <div style={{ fontSize: FS.xs, color: T.textTertiary, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    Supporting layers
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(["counterparty", "cyber", "export"] as DecisionLane[]).map((lane) => {
                      const meta = WORKFLOW_LANE_META[lane];
                      const counts = laneCounts[lane];
                      const active = lane === activeLane;
                      return (
                        <button
                          key={lane}
                          type="button"
                          onClick={() => handleLaneSelect(lane)}
                          className="helios-focus-ring"
                          aria-label={`Switch supporting layer to ${meta.label}`}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: SP.xs,
                            borderRadius: 999,
                            border: `1px solid ${active ? meta.softBorder : T.border}`,
                            background: active ? meta.softBackground : T.surface,
                            color: active ? meta.accent : T.textSecondary,
                            padding: "8px 12px",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            cursor: "pointer",
                          }}
                          title={meta.description}
                        >
                          {meta.shortLabel}
                          <span style={{ fontSize: FS.xs, color: active ? meta.accent : T.textTertiary }}>
                            {counts.total}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div style={{ fontSize: FS.xs, color: T.textTertiary, lineHeight: 1.45 }}>
                    Core is the default. Cyber and export only surface when they materially change the vendor decision.
                  </div>
                </div>
              ) : null}
            </section>

            <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.9fr)] gap-4 items-start">
              <div
                className="glass-card"
                style={{
                  padding: PAD.comfortable,
                  borderRadius: 20,
                  border: `1px solid ${activePillarMeta.softBorder}`,
                  background: FX.panelStrong,
                  display: "flex",
                  flexDirection: "column",
                  gap: SP.md,
                }}
              >
                <div style={{ minWidth: 0, flex: 1, maxWidth: 820 }}>
                  <SectionEyebrow>{activePillar === "contract_vehicle" ? "Contract vehicle intelligence" : "Vendor assessment"}</SectionEyebrow>
                  <div style={{ fontSize: "clamp(28px, 4vw, 38px)", lineHeight: 1.08, letterSpacing: "-0.04em", color: T.text, fontWeight: 800, marginTop: SP.sm }}>
                    {activePillar === "contract_vehicle"
                      ? "Start from the contract vehicle."
                      : activeLane === "export"
                        ? "Open the vendor assessment with export evidence in scope."
                        : activeLane === "cyber"
                          ? "Open the vendor assessment with cyber evidence in scope."
                          : "Open the next vendor assessment."}
                  </div>
                  <div style={{ marginTop: SP.sm, fontSize: FS.base, color: T.textSecondary, lineHeight: 1.65 }}>
                    {activePillar === "contract_vehicle" ? activePillarBrief.question : activeLaneBrief.question}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      borderRadius: 999,
                      background: activePillar === "contract_vehicle" ? activePillarMeta.softBackground : activeLaneMeta.softBackground,
                      border: `1px solid ${activePillar === "contract_vehicle" ? activePillarMeta.softBorder : activeLaneMeta.softBorder}`,
                      color: activePillar === "contract_vehicle" ? activePillarMeta.accent : activeLaneMeta.accent,
                      padding: "6px 10px",
                      fontSize: FS.xs,
                      fontWeight: 800,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                    }}
                  >
                    {activePillar === "contract_vehicle" ? activePillarBrief.outputs : activeLaneBrief.outputs}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      borderRadius: 999,
                      background: T.surface,
                      border: `1px solid ${T.border}`,
                      color: T.textSecondary,
                      padding: "6px 10px",
                      fontSize: FS.xs,
                      fontWeight: 700,
                    }}
                  >
                    {connectorCount} live connectors
                  </span>
                </div>

                {searchMode !== "export" ? (
                  <>
                    {searchMode === "vehicle" ? (
                      <InlineMessage
                        tone="info"
                        title="Vehicle mode"
                        message="Search the public contract award spine first, then pivot the right vendors into assessment and AXIOM-backed dossier closure."
                        icon={GitBranch}
                      />
                    ) : null}

                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: SP.sm,
                        borderRadius: 18,
                        border: `1px solid ${T.border}`,
                        background: T.surface,
                        padding: "10px 12px 10px 18px",
                      }}
                    >
                      <input
                        ref={inputRef}
                        value={input}
                        onChange={(event) => setInput(event.target.value)}
                        onKeyDown={(event) => event.key === "Enter" && handleSubmit()}
                        placeholder={primaryPlaceholder}
                        aria-label={primaryPlaceholder}
                        className="helios-focus-ring"
                        style={{
                          width: "100%",
                          background: "transparent",
                          border: "none",
                          outline: "none",
                          color: T.text,
                          fontSize: FS.base,
                          fontFamily: "inherit",
                          padding: "8px 0",
                        }}
                      />
                      <button
                        type="button"
                        onClick={handleSubmit}
                        className="helios-focus-ring"
                        aria-label="Start intake"
                        style={{
                          width: 44,
                          height: 44,
                          borderRadius: 14,
                          border: "none",
                          background: input.trim() ? activePillarMeta.accent : T.border,
                          color: input.trim() ? "#04101f" : T.textTertiary,
                          cursor: input.trim() ? "pointer" : "default",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        <ArrowRight size={18} />
                      </button>
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!input.trim()}
                        className="helios-focus-ring"
                        aria-label={searchMode === "vehicle" ? "Search contract vehicle" : "Start vendor assessment"}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: SP.xs,
                          padding: "12px 16px",
                          borderRadius: 14,
                          border: "none",
                          background: input.trim() ? activePillarMeta.accent : T.border,
                          color: input.trim() ? "#04101f" : T.textTertiary,
                          cursor: input.trim() ? "pointer" : "default",
                          fontSize: FS.sm,
                          fontWeight: 800,
                        }}
                      >
                        {searchMode === "vehicle" ? "Search vehicle" : "Start vendor assessment"}
                        <ArrowRight size={14} />
                      </button>

                      {activePillar === "vendor_assessment" && searchMode !== "vehicle" ? (
                        <button
                          type="button"
                          onClick={openVehicleUtility}
                          className="helios-focus-ring"
                          aria-label="Switch to contract vehicle search"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: SP.xs,
                            padding: "12px 16px",
                            borderRadius: 14,
                            border: `1px solid ${T.border}`,
                            background: "rgba(7, 12, 22, 0.58)",
                            color: T.textSecondary,
                            cursor: "pointer",
                            fontSize: FS.sm,
                            fontWeight: 700,
                          }}
                        >
                          <GitBranch size={14} />
                          Search contract vehicle
                        </button>
                      ) : null}

                      <button
                        type="button"
                        onClick={() => { void handleViewDraftCases(); }}
                        className="helios-focus-ring"
                        aria-label="Open assessment queue"
                        style={{
                          padding: "12px 16px",
                          borderRadius: 14,
                          border: `1px solid ${T.border}`,
                          background: "rgba(7, 12, 22, 0.58)",
                          color: T.textSecondary,
                          cursor: "pointer",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                      >
                        Open assessment queue
                      </button>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {[
                        `Active ${laneCases.length}`,
                        `Need decision ${blockedCount + reviewCount}`,
                        `Moving ${movingCount}`,
                        `Connectors ${connectorCount}`,
                      ].map((item) => (
                        <span
                          key={item}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            borderRadius: 999,
                            padding: "6px 10px",
                            border: `1px solid ${T.border}`,
                            background: T.surface,
                            color: T.textSecondary,
                            fontSize: FS.xs,
                            fontWeight: 700,
                          }}
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div
                    className="glass-card"
                    style={{
                      padding: PAD.comfortable,
                      borderRadius: 20,
                      border: `1px solid ${T.borderStrong}`,
                      background: "rgba(7, 12, 22, 0.62)",
                      display: "flex",
                      flexDirection: "column",
                      gap: SP.md,
                    }}
                  >
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
                        <SectionEyebrow>Authorization request</SectionEyebrow>
                        {EXPORT_REQUEST_TYPE_OPTIONS.map((option) => {
                          const active = exportForm.request_type === option.value;
                          return (
                            <button
                              key={option.value}
                              type="button"
                              onClick={() => handleExportField("request_type", option.value)}
                              className="helios-focus-ring"
                              style={{
                                textAlign: "left",
                                padding: PAD.default,
                                borderRadius: 14,
                                border: `1px solid ${active ? activeLaneMeta.softBorder : T.border}`,
                                background: active ? activeLaneMeta.softBackground : T.surface,
                                cursor: "pointer",
                              }}
                            >
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{option.label}</div>
                              <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs, lineHeight: 1.5 }}>{option.description}</div>
                            </button>
                          );
                        })}

                        <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                          <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Recipient or access subject</span>
                          <input
                            ref={exportRecipientRef}
                            value={exportForm.recipient_name ?? ""}
                            onChange={(event) => handleExportField("recipient_name", event.target.value)}
                            placeholder="Company, affiliate, foreign national, or subcontractor"
                            className="helios-focus-ring"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                          />
                        </label>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                            <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Destination or access country</span>
                            <input
                              value={exportForm.destination_country ?? ""}
                              onChange={(event) => handleExportField("destination_country", event.target.value.toUpperCase())}
                              placeholder="DE, JP, SG"
                              maxLength={3}
                              className="helios-focus-ring"
                              style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                            />
                          </label>
                          <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                            <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Jurisdiction guess</span>
                            <select
                              value={exportForm.jurisdiction_guess ?? "unknown"}
                              onChange={(event) => handleExportField("jurisdiction_guess", event.target.value as ExportAuthorizationCaseInput["jurisdiction_guess"])}
                              className="helios-focus-ring"
                              style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                            >
                              {EXPORT_JURISDICTION_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          </label>
                        </div>
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
                        <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                          <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Classification guess</span>
                          <input
                            value={exportForm.classification_guess ?? ""}
                            onChange={(event) => handleExportField("classification_guess", event.target.value)}
                            placeholder="USML Cat XI, ECCN 3A001, EAR99..."
                            className="helios-focus-ring"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                          />
                        </label>

                        <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                          <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Item, software, or data summary</span>
                          <textarea
                            value={exportForm.item_or_data_summary ?? ""}
                            onChange={(event) => handleExportField("item_or_data_summary", event.target.value)}
                            placeholder="Describe the item, technical data, source code, or controlled environment under review."
                            rows={4}
                            className="helios-focus-ring"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", resize: "vertical", fontFamily: "inherit" }}
                          />
                        </label>

                        <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                          <span style={{ fontSize: FS.sm, color: T.textSecondary }}>End use or access context</span>
                          <textarea
                            value={exportForm.end_use_summary ?? ""}
                            onChange={(event) => handleExportField("end_use_summary", event.target.value)}
                            placeholder="Program, end use, destination, collaboration, or review context."
                            rows={3}
                            className="helios-focus-ring"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none", resize: "vertical", fontFamily: "inherit" }}
                          />
                        </label>

                        <label style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                          <span style={{ fontSize: FS.sm, color: T.textSecondary }}>Foreign-person nationalities (optional)</span>
                          <input
                            value={(exportForm.foreign_person_nationalities ?? []).join(", ")}
                            onChange={(event) => handleExportField("foreign_person_nationalities", event.target.value.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean))}
                            placeholder="CN, IN, AE"
                            className="helios-focus-ring"
                            style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: FS.sm, outline: "none" }}
                          />
                        </label>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <InlineMessage
                        tone="info"
                        title="Export support layer"
                        message="Helios will open a vendor assessment, run the live screening stack, and structure the result around the export-control evidence that should change the decision."
                        icon={Globe2}
                      />
                      <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!exportForm.recipient_name?.trim() || !exportForm.destination_country?.trim()}
                        className="helios-focus-ring"
                        aria-label="Open vendor assessment with export support layer"
                        style={{
                          padding: "12px 16px",
                          borderRadius: 14,
                          border: "none",
                          background: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? activePillarMeta.accent : T.border,
                          color: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? "#04101f" : T.textTertiary,
                          cursor: exportForm.recipient_name?.trim() && exportForm.destination_country?.trim() ? "pointer" : "default",
                          fontSize: FS.sm,
                          fontWeight: 800,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: SP.xs,
                        }}
                      >
                        Open vendor assessment
                        <ArrowRight size={14} />
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: SP.md }}>
                <section
                  className="glass-card"
                  style={{
                    padding: PAD.comfortable,
                    borderRadius: 20,
                    border: `1px solid ${T.borderStrong}`,
                    background: FX.panelStrong,
                    display: "flex",
                    flexDirection: "column",
                    gap: SP.sm,
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <SectionEyebrow>Priority queue</SectionEyebrow>
                      <div style={{ fontSize: FS.base, color: T.text, fontWeight: 800, marginTop: SP.xs }}>
                        Resume active work
                      </div>
                    </div>
                    {laneCases.length > 0 ? (
                      <button
                        type="button"
                        onClick={() => { void handleViewDraftCases(); }}
                        className="helios-focus-ring"
                        style={{
                          padding: "8px 12px",
                          borderRadius: 999,
                          border: `1px solid ${T.border}`,
                          background: T.surface,
                          color: T.textSecondary,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                      >
                        See all
                      </button>
                    ) : null}
                  </div>

                  {priorityLaneCases.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
                      {priorityLaneCases.map((c) => {
                        const disposition = portfolioDisposition(c);
                        const styles = caseDispositionStyles(disposition);
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => onCaseCreated(c.id)}
                            className="helios-focus-ring"
                            style={{
                              width: "100%",
                              padding: PAD.default,
                              borderRadius: 16,
                              border: `1px solid ${T.border}`,
                              background: T.surface,
                              textAlign: "left",
                              display: "flex",
                              alignItems: "flex-start",
                              justifyContent: "space-between",
                              gap: SP.sm,
                              cursor: "pointer",
                            }}
                          >
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: SP.xs, marginBottom: SP.xs }}>
                                <span style={{ width: 8, height: 8, borderRadius: 999, background: styles.color, flexShrink: 0 }} />
                                <span style={{ fontSize: FS.base, color: T.text, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {displayName(c.name)}
                                </span>
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>
                                {caseOperatorSummary(c)}
                              </div>
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: SP.xs, flexShrink: 0 }}>
                              <span style={{ fontSize: FS.xs, color: T.textTertiary }}>{caseRelativeTime(c, clockTs)}</span>
                              <span
                                style={{
                                  fontSize: FS.xs,
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
                                {caseDispositionLabel(disposition, workflowLaneForCase(c))}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <EmptyPanel
                      title="No active assessment queue yet"
                      description="Start the first case and Helios will route the package into the portfolio, graph, and AXIOM surfaces automatically."
                    />
                  )}

                  <div
                    style={{
                      marginTop: SP.xs,
                      paddingTop: SP.sm,
                      borderTop: `1px solid ${T.border}`,
                      fontSize: FS.sm,
                      color: T.textSecondary,
                      lineHeight: 1.55,
                    }}
                  >
                    {freshCount} case{freshCount === 1 ? "" : "s"} moved in the last 24 hours. {blockedCount > 0 ? "Blocked work is still sitting in the queue." : "No hard-stop backlog is waiting here."} AXIOM and the graph should close the dark space after intake creates the case.
                  </div>
                </section>
              </div>
            </section>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Run live screening and prepare the cyber support layer</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Score the case and recommend the vendor disposition</div>
                  </>
                ) : (
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Confirm the entity and its identifiers</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Run live OSINT and ownership / FOCI screening</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}><CheckCircle size={11} color={T.green} /> Score the case and recommend the vendor disposition</div>
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
