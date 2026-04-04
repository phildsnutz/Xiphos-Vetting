import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChevronDown, ExternalLink, Loader2, MessageSquareText, Sparkles } from "lucide-react";
import { createCase, fetchHealth, resolveEntity, searchContractVehicle, submitResolveFeedback, type EntityCandidate, type EntityResolution, type VehicleSearchResult } from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { EnrichmentStream } from "./enrichment-stream";
import { InlineMessage, SectionEyebrow, StatusPill } from "./shell-primitives";
import { T, FS, SP, PAD, O, FX, MOTION } from "@/lib/tokens";

type RoomMenu = "recent" | "examples" | null;
type ObjectType = "vendor" | "vehicle";
type SupportLayer = "counterparty" | "cyber" | "export";
type VendorGoal = "trust" | "partner" | "compete" | "attack";
type VehicleTiming = "current" | "expired" | "pre_solicitation";

type MessageRole = "axiom" | "user" | "status";

interface FrontPorchLandingProps {
  cases?: VettingCase[];
  onNavigate: (tab: string) => void;
  onOpenCase: (caseId: string) => void;
}

interface ThreadMessage {
  id: string;
  role: MessageRole;
  content: string;
}

interface IntakeSession {
  objectType: ObjectType | null;
  vendorName: string | null;
  vehicleName: string | null;
  vendorGoal: VendorGoal | null;
  supportLayer: SupportLayer;
  vehicleTiming: VehicleTiming | null;
  followOn: boolean | null;
  incumbentPrime: string | null;
}

interface VendorArtifact {
  caseId: string;
  title: string;
  summary: string;
  anchors: string[];
  note: string;
}

const FRONT_PORCH_EXAMPLES = [
  "ILS 2 follow-on. We think Amentum is the incumbent.",
  "Need a quick read on SMX as a potential teammate.",
  "Who matters under LEIA and where is it vulnerable?",
  "Thin-data vendor with a suspicious ownership trail.",
];

const PROGRESS_LINES = [
  "Collecting the public picture and checking for gaps.",
  "Validating what holds before bringing the picture back.",
  "Building the briefing and keeping the dark space explicit.",
];

function nextId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function sortRecentCases(cases: VettingCase[]): VettingCase[] {
  return [...cases].sort((a, b) => {
    const aTs = Date.parse(a.created_at || a.date || "");
    const bTs = Date.parse(b.created_at || b.date || "");
    return (Number.isFinite(bTs) ? bTs : 0) - (Number.isFinite(aTs) ? aTs : 0);
  });
}

function inferObjectType(value: string): ObjectType | null {
  const lower = value.toLowerCase();
  if (/\b(vehicle|recompete|follow-on|follow on|pre-solicitation|pre solicitation|solicitation|piid|award|task order)\b/.test(lower)) {
    return "vehicle";
  }
  if (/\b(vendor|supplier|teammate|partner|prime|subcontractor|company)\b/.test(lower)) {
    return "vendor";
  }
  return null;
}

function inferSupportLayer(value: string): SupportLayer | null {
  const lower = value.toLowerCase();
  if (/\b(export|itar|ear|ddtc|bis|deemed export)\b/.test(lower)) return "export";
  if (/\b(cyber|cmmc|sprs|ssp|poam|sbom|vex|software assurance|rmf)\b/.test(lower)) return "cyber";
  return null;
}

function inferVendorGoal(value: string): VendorGoal | null {
  const lower = value.toLowerCase();
  if (/\b(trust|clear|screen)\b/.test(lower)) return "trust";
  if (/\b(partner|teammate|team with)\b/.test(lower)) return "partner";
  if (/\b(compete|competitor|against)\b/.test(lower)) return "compete";
  if (/\b(attack|vulnerable|weak point|pressure)\b/.test(lower)) return "attack";
  return null;
}

function inferVehicleTiming(value: string): VehicleTiming | null {
  const lower = value.toLowerCase();
  if (/\b(pre-solicitation|pre solicitation|pre-rfp|pre rfp)\b/.test(lower)) return "pre_solicitation";
  if (/\b(expired|closed|retired)\b/.test(lower)) return "expired";
  if (/\b(current|active|live)\b/.test(lower)) return "current";
  return null;
}

function inferBoolean(value: string): boolean | null {
  const lower = value.toLowerCase();
  if (/\b(yes|yep|yeah|correct|it is|is a|follow-on|follow on)\b/.test(lower)) return true;
  if (/\b(no|nope|not|net new|new start)\b/.test(lower)) return false;
  return null;
}

function stripObjectLabel(value: string) {
  return value
    .replace(/\b(contract vehicle|specific vendor|vendor|vehicle)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function looksLikeObjectOnlyAnswer(value: string) {
  const normalized = stripObjectLabel(value).toLowerCase();
  return normalized === "" || normalized === "a" || normalized === "a specific";
}

function compactText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function summarizeVehicle(result: VehicleSearchResult, session: IntakeSession): string {
  const primeText = result.total_primes > 0
    ? `${result.total_primes} prime contractor${result.total_primes === 1 ? "" : "s"}`
    : "no clear primes";
  const subText = result.total_subs > 0
    ? `${result.total_subs} subcontractor trace${result.total_subs === 1 ? "" : "s"}`
    : "thin subcontractor visibility";
  const timingLead = session.vehicleTiming === "pre_solicitation"
    ? "The vehicle is still ahead of release, so lineage and continuity matter more than surface noise."
    : "The current public picture is good enough to start mapping the ecosystem.";
  return `${timingLead} I found ${primeText} and ${subText} tied to ${result.vehicle_name}.`;
}

function vendorArtifactSummary(candidate: EntityCandidate | null, session: IntakeSession) {
  const layerLine = session.supportLayer === "export"
    ? "Export exposure will stay in scope as a supporting thread."
    : session.supportLayer === "cyber"
      ? "Cyber posture will stay in scope as a supporting thread."
      : "The first pass will stay centered on trust, ownership, and capability fit.";
  if (candidate?.highest_owner && candidate.highest_owner !== candidate.legal_name) {
    return `The assessment is warming around ${candidate.legal_name}. Public control signals already point beyond the surface entity. ${layerLine}`;
  }
  return `The assessment is warming around ${candidate?.legal_name ?? session.vendorName ?? "the vendor"}. ${layerLine}`;
}

function buildCasePayload(candidate: EntityCandidate | null, session: IntakeSession) {
  const legalName = candidate?.legal_name || session.vendorName || "Unknown vendor";
  const country = candidate?.country || "US";
  const hasSamData = Boolean(candidate?.uei || candidate?.cage);
  const hasOwnerData = Boolean(candidate?.cik || hasSamData || candidate?.highest_owner);
  const ownerCountry = (candidate?.highest_owner_country || "").toUpperCase();
  const vendorCountry = country.toUpperCase();
  const isForeignOwned = ownerCountry !== "" && ownerCountry !== vendorCountry;

  return {
    name: legalName,
    country,
    ownership: {
      publicly_traded: Boolean(candidate?.ticker),
      state_owned: false,
      beneficial_owner_known: hasOwnerData,
      ownership_pct_resolved: candidate?.highest_owner ? 0.8 : hasOwnerData ? 0.6 : 0.2,
      shell_layers: 0,
      pep_connection: false,
      foreign_ownership_pct: isForeignOwned ? 0.51 : 0,
      foreign_ownership_is_allied: ownerCountry !== "" && ["US", "GB", "CA", "AU", "NZ", "DE", "FR", "NL", "JP", "KR"].includes(ownerCountry),
    },
    data_quality: {
      has_lei: Boolean(candidate?.lei),
      has_cage: Boolean(candidate?.cage),
      has_duns: Boolean(candidate?.uei),
      has_tax_id: Boolean(candidate?.cik || hasSamData),
      has_audited_financials: Boolean(candidate?.cik),
      years_of_records: hasOwnerData ? 5 : 0,
    },
    exec: {
      known_execs: 0,
      adverse_media: 0,
      pep_execs: 0,
      litigation_history: 0,
    },
    program: "dod_unclassified",
    profile: "defense_acquisition",
  };
}

const INITIAL_MESSAGES: ThreadMessage[] = [
  {
    id: nextId("axiom"),
    role: "axiom",
    content: "What are we looking at today: a contract vehicle, a specific vendor, or something still unclear?",
  },
];

export function FrontPorchLanding({ cases = [], onNavigate, onOpenCase }: FrontPorchLandingProps) {
  const [menu, setMenu] = useState<RoomMenu>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>(INITIAL_MESSAGES);
  const [session, setSession] = useState<IntakeSession>({
    objectType: null,
    vendorName: null,
    vehicleName: null,
    vendorGoal: null,
    supportLayer: "counterparty",
    vehicleTiming: null,
    followOn: null,
    incumbentPrime: null,
  });
  const [isWorking, setIsWorking] = useState(false);
  const [workingCaseId, setWorkingCaseId] = useState<string | null>(null);
  const [progressIndex, setProgressIndex] = useState(0);
  const [resolution, setResolution] = useState<EntityResolution | null>(null);
  const [candidateChoices, setCandidateChoices] = useState<EntityCandidate[]>([]);
  const [vehicleArtifact, setVehicleArtifact] = useState<VehicleSearchResult | null>(null);
  const [vendorArtifact, setVendorArtifact] = useState<VendorArtifact | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [connectorCount, setConnectorCount] = useState<number>(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const recentCases = useMemo(() => sortRecentCases(cases).slice(0, 6), [cases]);

  const appendMessage = useCallback((role: MessageRole, content: string) => {
    setMessages((current) => [...current, { id: nextId(role), role, content }]);
  }, []);

  const resetArtifacts = useCallback(() => {
    setCandidateChoices([]);
    setResolution(null);
    setVehicleArtifact(null);
    setVendorArtifact(null);
    setErrorText(null);
  }, []);

  useEffect(() => {
    composerRef.current?.focus();
    fetchHealth()
      .then((health) => setConnectorCount(health.osint_connector_count ?? 0))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!isWorking) return undefined;
    const timer = window.setInterval(() => {
      setProgressIndex((current) => (current + 1) % PROGRESS_LINES.length);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [isWorking]);

  useEffect(() => {
    if (!menu) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenu(null);
      }
    };
    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, [menu]);

  const openWarRoom = useCallback(() => {
    onNavigate("axiom");
  }, [onNavigate]);

  const handleEnrichmentComplete = useCallback(() => {
    if (!workingCaseId) return;
    setIsWorking(false);
    appendMessage("axiom", "The preliminary picture is ready. I opened the assessment and kept the first pass disciplined about what holds and what still needs to be closed.");
    setVendorArtifact((current) => current ? current : {
      caseId: workingCaseId,
      title: "Vendor Assessment Ready",
      summary: "The assessment is warm and the first dossier pass is ready to open.",
      anchors: ["Trust read", "Ownership path", "Graph context"],
      note: "Open the case workspace for the working dossier and evidence trail.",
    });
  }, [appendMessage, workingCaseId]);

  const startCaseCreation = useCallback(async (candidate: EntityCandidate | null) => {
    const payload = buildCasePayload(candidate, session);
    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);
    appendMessage("axiom", "That is enough to start. I am opening the assessment now and warming the first picture.");

    try {
      const created = await createCase(payload);
      setWorkingCaseId(created.case_id);
      setVendorArtifact({
        caseId: created.case_id,
        title: payload.name,
        summary: vendorArtifactSummary(candidate, session),
        anchors: session.supportLayer === "export"
          ? ["Trust read", "Ownership path", "Export thread"]
          : session.supportLayer === "cyber"
            ? ["Trust read", "Ownership path", "Cyber thread"]
            : ["Trust read", "Ownership path", "Capability fit"],
        note: "The dossier is warming. Open the case when you want the working surface.",
      });
    } catch (error) {
      setIsWorking(false);
      const message = error instanceof Error ? error.message : "Unable to open the vendor assessment.";
      setErrorText(message);
      appendMessage("axiom", "I could not open the assessment cleanly. Stay here and I will let you retry without losing the thread.");
    }
  }, [appendMessage, session]);

  const handleCandidateChoice = useCallback(async (candidate: EntityCandidate) => {
    setCandidateChoices([]);
    if (resolution?.request_id && candidate.candidate_id) {
      void submitResolveFeedback(
        resolution.request_id,
        candidate.candidate_id,
        resolution.recommended_candidate_id === candidate.candidate_id,
      ).catch(() => undefined);
    }
    appendMessage("axiom", `Good. I’m using ${candidate.legal_name} and opening the assessment from that entity.`);
    await startCaseCreation(candidate);
  }, [appendMessage, resolution, startCaseCreation]);

  const startVendorFlow = useCallback(async (nextSession: IntakeSession) => {
    const name = compactText(nextSession.vendorName || "");
    if (!name) {
      appendMessage("axiom", "Which vendor are we looking at?");
      return;
    }

    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);
    appendMessage("axiom", nextSession.vendorGoal === "partner"
      ? "Understood. I’ll start with trust and teammate fit, then warm the assessment from there."
      : nextSession.vendorGoal === "compete" || nextSession.vendorGoal === "attack"
        ? "Understood. I’ll frame this as a competitive read and warm the assessment from there."
        : "Understood. I’ll start with trust, ownership, and the public record that could change the decision.");

    try {
      const result = await resolveEntity(name, {
        use_ai: true,
        max_candidates: 6,
        context: nextSession.vendorGoal ? `Goal: ${nextSession.vendorGoal}` : undefined,
      });
      setIsWorking(false);
      setResolution(result.resolution || null);

      const recommendedCandidate =
        result.resolution?.status === "recommended"
          ? result.candidates.find((candidate) => candidate.candidate_id === result.resolution?.recommended_candidate_id) ?? null
          : null;

      if (recommendedCandidate) {
        appendMessage("axiom", `I believe you mean ${recommendedCandidate.legal_name}. I’m going to use that entity unless you redirect me.`);
        await startCaseCreation(recommendedCandidate);
        return;
      }

      if (result.candidates.length > 1) {
        setCandidateChoices(result.candidates.slice(0, 4));
        appendMessage("axiom", "I found a few plausible matches. Pick the entity you want me to work and I’ll take it from there.");
        return;
      }

      if (result.candidates.length === 1) {
        appendMessage("axiom", `I found a clean entity match on ${result.candidates[0].legal_name}. I’m opening the assessment from there.`);
        await startCaseCreation(result.candidates[0]);
        return;
      }

      appendMessage("axiom", "The record is thin on entity resolution, but that is not a blocker. I’m opening the assessment from the provided name and keeping the ambiguity explicit.");
      await startCaseCreation(null);
    } catch (error) {
      setIsWorking(false);
      const message = error instanceof Error ? error.message : "Unable to resolve the vendor cleanly.";
      setErrorText(message);
      appendMessage("axiom", "The clean entity match did not hold. If you still want me to proceed, give me the vendor name again or add one more fact.");
    }
  }, [appendMessage, startCaseCreation]);

  const startVehicleFlow = useCallback(async (nextSession: IntakeSession) => {
    const vehicleName = compactText(nextSession.vehicleName || "");
    if (!vehicleName) {
      appendMessage("axiom", "Which vehicle are we looking at?");
      return;
    }

    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);
    appendMessage(
      "axiom",
      nextSession.incumbentPrime
        ? `That is enough to start. I’m going to work from ${vehicleName}, the incumbent prime, and the likely transition path.`
        : `That is enough to start. I’m going to work from ${vehicleName} and build the public ecosystem picture from there.`,
    );

    try {
      const result = await searchContractVehicle(vehicleName);
      setIsWorking(false);
      setVehicleArtifact(result);
      appendMessage("axiom", summarizeVehicle(result, nextSession));
    } catch (error) {
      setIsWorking(false);
      const message = error instanceof Error ? error.message : "Unable to search the vehicle right now.";
      setErrorText(message);
      appendMessage("axiom", "The vehicle search did not come back cleanly. Stay here and either refine the vehicle name or send me one more identifying detail.");
    }
  }, [appendMessage]);

  const decideVehicleNext = useCallback(async (input: string, current: IntakeSession) => {
    const nextSession = { ...current };
    const stripped = compactText(stripObjectLabel(input));
    const lower = input.toLowerCase();

    if (!nextSession.vehicleName && stripped && !looksLikeObjectOnlyAnswer(input)) {
      nextSession.vehicleName = stripped;
    }
    if (!nextSession.vehicleTiming) {
      const inferredTiming = inferVehicleTiming(input);
      if (inferredTiming) nextSession.vehicleTiming = inferredTiming;
    }
    if (nextSession.followOn === null && /\bfollow-on|follow on|net-new|net new\b/.test(lower)) {
      nextSession.followOn = inferBoolean(input);
    }
    if (!nextSession.incumbentPrime && /\bprime\b/.test(lower) && stripped) {
      nextSession.incumbentPrime = stripped.replace(/^.*?\bprime\b[:\s-]*/i, "").trim() || stripped;
    }

    setSession(nextSession);

    if (!nextSession.vehicleName) {
      appendMessage("axiom", "Which contract vehicle are we looking at?");
      return;
    }
    if (!nextSession.vehicleTiming) {
      appendMessage("axiom", "Is this a current vehicle, an expired vehicle, or something still in pre-solicitation?");
      return;
    }
    if (nextSession.vehicleTiming === "pre_solicitation" && nextSession.followOn === null) {
      appendMessage("axiom", "Good. Is it a follow-on contract, or does it look net-new?");
      return;
    }
    if (nextSession.followOn === true && !nextSession.incumbentPrime) {
      appendMessage("axiom", "Do you know who holds the current prime position?");
      return;
    }

    await startVehicleFlow(nextSession);
  }, [appendMessage, startVehicleFlow]);

  const decideVendorNext = useCallback(async (input: string, current: IntakeSession) => {
    const nextSession = { ...current };
    const stripped = compactText(stripObjectLabel(input));

    if (!nextSession.vendorName && stripped && !looksLikeObjectOnlyAnswer(input)) {
      nextSession.vendorName = stripped;
    }
    if (!nextSession.vendorGoal) {
      const inferredGoal = inferVendorGoal(input);
      if (inferredGoal) nextSession.vendorGoal = inferredGoal;
    }
    if (nextSession.supportLayer === "counterparty") {
      const inferredLayer = inferSupportLayer(input);
      if (inferredLayer) nextSession.supportLayer = inferredLayer;
    }

    setSession(nextSession);

    if (!nextSession.vendorName) {
      appendMessage("axiom", "Which vendor are we looking at?");
      return;
    }
    if (!nextSession.vendorGoal) {
      appendMessage("axiom", "Are you trying to trust them, partner with them, or compete against them?");
      return;
    }

    await startVendorFlow(nextSession);
  }, [appendMessage, startVendorFlow]);

  const handleUserTurn = useCallback(async (raw: string) => {
    const text = compactText(raw);
    if (!text || isWorking) return;

    appendMessage("user", text);
    resetArtifacts();

    const nextSession = { ...session };

    if (!nextSession.objectType) {
      const inferredObject = inferObjectType(text);
      if (!inferredObject) {
        appendMessage("axiom", "Are we looking for a contract vehicle or a specific vendor?");
        return;
      }
      nextSession.objectType = inferredObject;
      if (inferredObject === "vendor") {
        nextSession.supportLayer = inferSupportLayer(text) || nextSession.supportLayer;
      }
      setSession(nextSession);
    }

    if (nextSession.objectType === "vehicle") {
      await decideVehicleNext(text, nextSession);
      return;
    }

    await decideVendorNext(text, nextSession);
  }, [appendMessage, decideVehicleNext, decideVendorNext, isWorking, resetArtifacts, session]);

  const submitDraft = useCallback(async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await handleUserTurn(text);
  }, [draft, handleUserTurn]);

  const handleExample = useCallback(async (example: string) => {
    setMenu(null);
    setDraft(example);
    window.setTimeout(() => {
      setDraft("");
      void handleUserTurn(example);
    }, 0);
  }, [handleUserTurn]);

  const shellBackground = `radial-gradient(circle at 18% 20%, ${T.accent}${O["12"]}, transparent 28%), radial-gradient(circle at 82% 18%, ${T.statusQualified}${O["12"]}, transparent 22%), linear-gradient(180deg, ${T.bg} 0%, #06080c 100%)`;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: shellBackground,
        color: T.text,
        padding: PAD.spacious,
        overflow: "auto",
      }}
    >
      <div
        style={{
          width: "min(1520px, 100%)",
          margin: "0 auto",
          minHeight: `calc(100vh - ${SP.xxxl}px)`,
          borderRadius: 36,
          border: `1px solid ${T.borderStrong}`,
          background: "linear-gradient(180deg, rgba(8, 11, 18, 0.94) 0%, rgba(5, 7, 11, 0.97) 100%)",
          boxShadow: "0 40px 120px rgba(0,0,0,0.42)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <header
          ref={menuRef}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: SP.lg,
            padding: `${SP.lg}px ${PAD.spacious}`,
            borderBottom: `1px solid ${T.border}`,
            position: "relative",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: SP.sm }}>
            <div style={{ fontSize: FS.md, fontWeight: 800, letterSpacing: "-0.04em" }}>Helios</div>
            <StatusPill tone="info">Front Porch</StatusPill>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: SP.sm, position: "relative" }}>
            <button
              type="button"
              onClick={() => setMenu((current) => current === "recent" ? null : "recent")}
              className="helios-focus-ring"
              style={{
                border: "none",
                background: "transparent",
                color: T.textSecondary,
                fontSize: FS.sm,
                fontWeight: 700,
                padding: PAD.default,
                borderRadius: 999,
                cursor: "pointer",
              }}
            >
              Recent
            </button>
            <button
              type="button"
              onClick={() => setMenu((current) => current === "examples" ? null : "examples")}
              className="helios-focus-ring"
              style={{
                border: "none",
                background: "transparent",
                color: T.textSecondary,
                fontSize: FS.sm,
                fontWeight: 700,
                padding: PAD.default,
                borderRadius: 999,
                cursor: "pointer",
              }}
            >
              Examples
            </button>
            <button
              type="button"
              onClick={openWarRoom}
              className="helios-focus-ring"
              style={{
                border: `1px solid ${T.accent}${O["20"]}`,
                background: `${T.accent}${O["08"]}`,
                color: T.text,
                fontSize: FS.sm,
                fontWeight: 700,
                padding: PAD.default,
                borderRadius: 999,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
              }}
            >
              War Room
              <ArrowUpRight size={14} />
            </button>

            {menu === "recent" ? (
              <div
                style={{
                  position: "absolute",
                  top: "calc(100% + 10px)",
                  right: 124,
                  width: 320,
                  borderRadius: 18,
                  border: `1px solid ${T.borderStrong}`,
                  background: T.surfaceElevated,
                  boxShadow: "0 18px 48px rgba(0,0,0,0.38)",
                  padding: PAD.default,
                  display: "flex",
                  flexDirection: "column",
                  gap: SP.xs,
                  zIndex: 20,
                }}
              >
                <SectionEyebrow>Recent engagements</SectionEyebrow>
                {recentCases.length > 0 ? recentCases.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      setMenu(null);
                      onOpenCase(item.id);
                    }}
                    className="helios-focus-ring"
                    style={{
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      borderRadius: 14,
                      padding: PAD.default,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{item.name}</div>
                    <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs }}>
                      {item.created_at || item.date}
                    </div>
                  </button>
                )) : (
                  <InlineMessage tone="neutral" message="No recent engagements yet. The first one starts here." />
                )}
              </div>
            ) : null}

            {menu === "examples" ? (
              <div
                style={{
                  position: "absolute",
                  top: "calc(100% + 10px)",
                  right: 12,
                  width: 380,
                  borderRadius: 18,
                  border: `1px solid ${T.borderStrong}`,
                  background: T.surfaceElevated,
                  boxShadow: "0 18px 48px rgba(0,0,0,0.38)",
                  padding: PAD.default,
                  display: "flex",
                  flexDirection: "column",
                  gap: SP.xs,
                  zIndex: 20,
                }}
              >
                <SectionEyebrow>Try an opening</SectionEyebrow>
                {FRONT_PORCH_EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => { void handleExample(example); }}
                    className="helios-focus-ring"
                    style={{
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      borderRadius: 14,
                      padding: PAD.default,
                      cursor: "pointer",
                      textAlign: "left",
                      fontSize: FS.sm,
                      color: T.textSecondary,
                      lineHeight: 1.55,
                    }}
                  >
                    {example}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </header>

        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: `${SP.xxxl}px ${PAD.spacious}`,
            gap: SP.xl,
          }}
        >
          <div style={{ width: "min(940px, 100%)", display: "flex", flexDirection: "column", alignItems: "center", gap: SP.lg }}>
            <SectionEyebrow>Briefing</SectionEyebrow>
            <h1
              style={{
                margin: 0,
                fontSize: "clamp(44px, 7vw, 84px)",
                lineHeight: 0.96,
                letterSpacing: "-0.07em",
                textAlign: "center",
                maxWidth: "12ch",
              }}
            >
              Tell me what you are trying to understand.
            </h1>
            <p
              style={{
                margin: 0,
                fontSize: FS.md,
                color: T.textSecondary,
                lineHeight: 1.6,
                textAlign: "center",
                maxWidth: 760,
              }}
            >
              A vehicle, a vendor, or a live pursuit problem. Start with whatever you know and AXIOM will work from there.
            </p>

            <div
              style={{
                width: "min(860px, 100%)",
                borderRadius: 28,
                border: `1px solid ${T.borderStrong}`,
                background: "linear-gradient(180deg, rgba(14,18,27,0.9) 0%, rgba(10,13,20,0.92) 100%)",
                boxShadow: FX.cardHover,
                padding: `${SP.lg + SP.xs}px ${PAD.comfortable}`,
              }}
            >
              <div style={{ fontSize: FS.caption, color: T.textTertiary, marginBottom: SP.md }}>
                AXIOM is listening
              </div>
              <textarea
                ref={composerRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitDraft();
                  }
                }}
                placeholder="ILS 2 follow-on. We think Amentum is the incumbent."
                aria-label="Brief AXIOM"
                className="helios-focus-ring"
                style={{
                  width: "100%",
                  minHeight: 104,
                  resize: "none",
                  border: "none",
                  outline: "none",
                  background: "transparent",
                  color: T.text,
                  fontSize: FS.md,
                  lineHeight: 1.55,
                  fontFamily: "inherit",
                }}
              />
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.md, marginTop: SP.md }}>
                <div style={{ fontSize: FS.sm, color: isWorking ? T.accent : T.textSecondary }}>
                  {isWorking ? PROGRESS_LINES[progressIndex] : `${connectorCount > 0 ? connectorCount : 49} source connectors stay behind the curtain.`}
                </div>
                <button
                  type="button"
                  onClick={() => { void submitDraft(); }}
                  disabled={!draft.trim() || isWorking}
                  className="helios-focus-ring"
                  style={{
                    border: "none",
                    background: draft.trim() && !isWorking ? T.text : `${T.border}`,
                    color: draft.trim() && !isWorking ? T.textInverse : T.textTertiary,
                    borderRadius: 999,
                    padding: "12px 18px",
                    cursor: draft.trim() && !isWorking ? "pointer" : "default",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: SP.xs,
                    fontSize: FS.sm,
                    fontWeight: 800,
                    transition: `all ${MOTION.fast} ${MOTION.easing}`,
                  }}
                >
                  {isWorking ? <Loader2 size={14} className="animate-spin" /> : <MessageSquareText size={14} />}
                  Send to AXIOM
                </button>
              </div>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: SP.sm, maxWidth: 920 }}>
              {FRONT_PORCH_EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => { void handleExample(example); }}
                  className="helios-focus-ring"
                  style={{
                    border: `1px solid ${T.border}`,
                    background: "rgba(255,255,255,0.03)",
                    color: T.textSecondary,
                    borderRadius: 999,
                    padding: "10px 14px",
                    fontSize: FS.sm,
                    cursor: "pointer",
                  }}
                >
                  {example}
                </button>
              ))}
            </div>

            <div style={{ width: "min(760px, 100%)", display: "flex", flexDirection: "column", gap: SP.sm }}>
              {messages.map((message) => (
                <div
                  key={message.id}
                  style={{
                    alignSelf: message.role === "user" ? "flex-end" : "stretch",
                    marginLeft: message.role === "user" ? 72 : 0,
                    borderRadius: 24,
                    border: message.role === "status" ? "none" : `1px solid ${message.role === "user" ? `${T.accent}${O["20"]}` : T.border}`,
                    background: message.role === "status"
                      ? "transparent"
                      : message.role === "user"
                        ? `${T.accent}${O["08"]}`
                        : "rgba(255,255,255,0.03)",
                    padding: message.role === "status" ? "2px 0" : `${SP.lg}px ${PAD.comfortable}`,
                    color: message.role === "status" ? T.accent : T.text,
                    fontSize: message.role === "status" ? FS.sm : FS.base,
                    lineHeight: 1.65,
                  }}
                >
                  {message.content}
                </div>
              ))}
            </div>

            {candidateChoices.length > 0 ? (
              <div style={{ width: "min(760px, 100%)", display: "grid", gap: SP.sm }}>
                {candidateChoices.map((candidate) => (
                  <button
                    key={candidate.candidate_id || candidate.legal_name}
                    type="button"
                    onClick={() => { void handleCandidateChoice(candidate); }}
                    className="helios-focus-ring"
                    style={{
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      borderRadius: 18,
                      padding: PAD.comfortable,
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: SP.sm }}>
                      <div>
                        <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700 }}>{candidate.legal_name}</div>
                        <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs }}>
                          {[candidate.country, candidate.ticker ? `Ticker ${candidate.ticker}` : null, candidate.uei ? `UEI ${candidate.uei}` : null].filter(Boolean).join(" • ")}
                        </div>
                      </div>
                      <ChevronDown size={14} color={T.textTertiary} style={{ transform: "rotate(-90deg)" }} />
                    </div>
                  </button>
                ))}
              </div>
            ) : null}

            {vehicleArtifact ? (
              <div
                style={{
                  width: "min(760px, 100%)",
                  borderRadius: 28,
                  background: "linear-gradient(180deg, rgba(246,248,252,0.96) 0%, rgba(231,236,243,0.92) 100%)",
                  color: T.textInverse,
                  padding: PAD.spacious,
                  display: "grid",
                  gap: SP.md,
                  boxShadow: "0 28px 80px rgba(0,0,0,0.28)",
                }}
              >
                <div style={{ fontSize: FS.lg, fontWeight: 800, letterSpacing: "-0.05em" }}>
                  {vehicleArtifact.vehicle_name}
                </div>
                <div style={{ fontSize: FS.base, color: "rgba(7,16,26,0.78)", lineHeight: 1.65 }}>
                  {summarizeVehicle(vehicleArtifact, session)}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                  <StatusPill tone="neutral">{vehicleArtifact.total_primes} primes</StatusPill>
                  <StatusPill tone="neutral">{vehicleArtifact.total_subs} subcontractor traces</StatusPill>
                  <StatusPill tone="neutral">{vehicleArtifact.total_unique} unique vendors</StatusPill>
                </div>
                {vehicleArtifact.unique_vendors.length > 0 ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                    {vehicleArtifact.unique_vendors.slice(0, 4).map((vendor) => (
                      <button
                        key={`${vendor.vendor_name}-${vendor.role}`}
                        type="button"
                        onClick={async () => {
                          setVehicleArtifact(null);
                          const nextSession = {
                            ...session,
                            objectType: "vendor" as const,
                            vendorName: vendor.vendor_name,
                            vendorGoal: session.vendorGoal || "partner",
                          };
                          setSession(nextSession);
                          appendMessage("user", `Open a vendor assessment on ${vendor.vendor_name}.`);
                          await startVendorFlow(nextSession);
                        }}
                        className="helios-focus-ring"
                        style={{
                          border: `1px solid rgba(7,16,26,0.12)`,
                          background: "rgba(7,16,26,0.06)",
                          color: T.textInverse,
                          borderRadius: 999,
                          padding: "10px 14px",
                          cursor: "pointer",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                      >
                        Assess {vendor.vendor_name}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: SP.md, flexWrap: "wrap" }}>
                  <div style={{ fontSize: FS.caption, color: "rgba(7,16,26,0.56)" }}>
                    Open the deeper room when you want the working trail, not just the picture.
                  </div>
                  <div style={{ display: "flex", gap: SP.sm, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      onClick={() => onNavigate("graph")}
                      className="helios-focus-ring"
                      style={{
                        border: "none",
                        background: "rgba(7,16,26,0.08)",
                        color: T.textInverse,
                        borderRadius: 999,
                        padding: "11px 16px",
                        cursor: "pointer",
                        fontSize: FS.sm,
                        fontWeight: 700,
                      }}
                    >
                      Open Graph Intel
                    </button>
                    <button
                      type="button"
                      onClick={openWarRoom}
                      className="helios-focus-ring"
                      style={{
                        border: "none",
                        background: T.textInverse,
                        color: T.text,
                        borderRadius: 999,
                        padding: "11px 16px",
                        cursor: "pointer",
                        fontSize: FS.sm,
                        fontWeight: 700,
                        display: "inline-flex",
                        alignItems: "center",
                        gap: SP.xs,
                      }}
                    >
                      Open in War Room
                      <ExternalLink size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {vendorArtifact ? (
              <div
                style={{
                  width: "min(760px, 100%)",
                  borderRadius: 28,
                  background: "linear-gradient(180deg, rgba(246,248,252,0.96) 0%, rgba(231,236,243,0.92) 100%)",
                  color: T.textInverse,
                  padding: PAD.spacious,
                  display: "grid",
                  gap: SP.md,
                  boxShadow: "0 28px 80px rgba(0,0,0,0.28)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: SP.md, alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: FS.lg, fontWeight: 800, letterSpacing: "-0.05em" }}>{vendorArtifact.title}</div>
                    <div style={{ fontSize: FS.base, color: "rgba(7,16,26,0.78)", lineHeight: 1.65, marginTop: SP.xs }}>
                      {vendorArtifact.summary}
                    </div>
                  </div>
                  <Sparkles size={18} color={T.textInverse} />
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                  {vendorArtifact.anchors.map((anchor) => (
                    <span
                      key={anchor}
                      style={{
                        borderRadius: 999,
                        background: "rgba(7,16,26,0.08)",
                        color: "rgba(7,16,26,0.7)",
                        padding: "8px 12px",
                        fontSize: FS.caption,
                        fontWeight: 700,
                      }}
                    >
                      {anchor}
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: SP.md, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ fontSize: FS.caption, color: "rgba(7,16,26,0.56)" }}>{vendorArtifact.note}</div>
                  <div style={{ display: "flex", gap: SP.sm, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      onClick={openWarRoom}
                      className="helios-focus-ring"
                      style={{
                        border: "none",
                        background: "rgba(7,16,26,0.08)",
                        color: T.textInverse,
                        borderRadius: 999,
                        padding: "11px 16px",
                        cursor: "pointer",
                        fontSize: FS.sm,
                        fontWeight: 700,
                      }}
                    >
                      Open in War Room
                    </button>
                    <button
                      type="button"
                      onClick={() => onOpenCase(vendorArtifact.caseId)}
                      className="helios-focus-ring"
                      style={{
                        border: "none",
                        background: T.textInverse,
                        color: T.text,
                        borderRadius: 999,
                        padding: "11px 16px",
                        cursor: "pointer",
                        fontSize: FS.sm,
                        fontWeight: 700,
                      }}
                    >
                      Open dossier
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {errorText ? (
              <div style={{ width: "min(760px, 100%)" }}>
                <InlineMessage tone="danger" title="Front Porch hit a problem" message={errorText} />
              </div>
            ) : null}
          </div>
        </div>

        {workingCaseId ? (
          <div style={{ display: "none" }}>
            <EnrichmentStream caseId={workingCaseId} apiBase={window.location.origin} onComplete={handleEnrichmentComplete} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
