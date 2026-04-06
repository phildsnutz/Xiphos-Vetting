import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChevronDown, ExternalLink, Loader2, MessageSquareText } from "lucide-react";
import {
  createMissionBrief,
  fetchCaseGraph,
  fetchCaseNetworkRisk,
  fetchEnrichment,
  fetchSupplierPassport,
  buildProtectedUrl,
  createCase,
  generateDossier,
  resolveEntity,
  routeIntake,
  runAxiomSearchIngest,
  searchContractVehicle,
  submitResolveFeedback,
  updateMissionBrief,
  type EnrichmentReport,
  type EntityCandidate,
  type EntityResolution,
  type MissionBriefPayload,
  type MissionBriefRoom,
  type MissionBriefRecord,
  type NetworkRiskResult,
  type SupplierPassport,
  type VehicleVendor,
  type VehicleSearchResult,
  type CaseGraphData,
} from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { EnrichmentStream } from "./enrichment-stream";
import { FrontPorchBriefView, type FrontPorchBriefViewModel } from "./front-porch-brief-view";
import { BriefArtifact, InlineMessage, SectionEyebrow, StatusPill } from "./shell-primitives";
import { DEEP_ROOM_NAME, STOA_NAME } from "./room-names";
import { T, FS, SP, PAD, O, MOTION } from "@/lib/tokens";

type RoomMenu = "recent" | "examples" | null;
type ObjectType = "vendor" | "vehicle";
type SupportLayer = "counterparty" | "cyber" | "export";
type VehicleTiming = "current" | "expired" | "pre_solicitation";
type PendingFollowUp =
  | "object_type"
  | "vendor_name"
  | "vehicle_name"
  | "vehicle_timing"
  | "vehicle_follow_on_or_incumbent"
  | "vehicle_incumbent_prime"
  | "vendor_priority_focus";
type PriorityFocus =
  | "full_picture"
  | "ownership"
  | "teammate_network"
  | "competitive_weakness"
  | "export_exposure"
  | "cyber_posture"
  | "capability_fit"
  | "adverse_history"
  | "vehicle_ecosystem"
  | "incumbent_continuity";

type MessageRole = "axiom" | "user" | "status";

interface FrontPorchLandingProps {
  cases?: VettingCase[];
  loginRequired?: boolean;
  onNavigate: (tab: string) => void;
  onOpenCase: (caseId: string) => void;
  onOpenAegisIntent?: (intent: {
    targetEntity: string;
    vehicleName?: string;
    domainFocus?: string;
    seedLabel?: string;
    autoRun?: boolean;
  }) => void;
  onRequestLogin?: () => void;
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
  seedText: string | null;
  priorityFocus: PriorityFocus | null;
  supportLayer: SupportLayer;
  vehicleTiming: VehicleTiming | null;
  followOn: boolean | null;
  incumbentPrime: string | null;
  followUpCount: number;
  pendingFollowUp: PendingFollowUp | null;
}

interface VendorArtifact {
  caseId: string;
  phase: "warming" | "ready";
  title: string;
  eyebrow: string;
  framing: string;
  sections: Array<{
    label: string;
    detail: string;
    tone?: "neutral" | "info" | "success" | "warning" | "danger";
  }>;
  note: string;
  provenance: string[];
}

interface VendorBriefReadiness {
  enrichment: EnrichmentReport | null;
  passport: SupplierPassport | null;
  graph: CaseGraphData | null;
  networkRisk: NetworkRiskResult | null;
  axiomGapClosure: {
    status: "completed" | "skipped" | "failed";
    passes: number;
    entitiesFound: number;
    relationshipsFound: number;
    gapCount: number;
    note: string;
    remainingThinSignals?: number;
    unresolvedReasons?: string[];
    gapHighlights?: string[];
  } | null;
}

type ResumeIntent =
  | { kind: "vendor"; session: IntakeSession }
  | { kind: "vehicle"; session: IntakeSession };
type RoutedIntake = Awaited<ReturnType<typeof routeIntake>>;

const FRONT_PORCH_EXAMPLES = [
  "ILS 2 follow-on. We think Amentum is the incumbent.",
  "Need a quick read on SMX as a potential teammate.",
  "Who matters under LEIA and where is it vulnerable?",
  "Thin-data vendor with a suspicious ownership trail.",
];

const PROGRESS_LINES = [
  "Pulling the first public picture.",
  "Testing what holds and what still stays thin.",
  "Shaping the returned brief.",
];

const FRONT_PORCH_START_CONFIDENCE = 0.72;
const FRONT_PORCH_SECOND_FOLLOW_UP_CONFIDENCE = 0.42;
const FRONT_PORCH_MAX_FOLLOW_UPS = 2;
const FRONT_PORCH_PRESSURE_THREAD_DELAY_MS = 3400;
const STRONG_ROUTING_CORRECTION_CONFIDENCE = 0.84;

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
  if (/\bunder\s+[A-Z]{3,}\b/.test(value)) {
    return "vehicle";
  }
  if (/\b[A-Z]{2,}[ -]?\d{1,3}[A-Z0-9-]*\b/.test(value)) {
    return "vehicle";
  }
  if (/\b(read on|assessment on|screen|trust read|trust|partner with|team with|teammate|competitive read|compete against|vendor assessment)\b/.test(lower)) {
    return "vendor";
  }
  if (/\b(vendor|supplier|teammate|partner|prime|subcontractor|company)\b/.test(lower)) {
    return "vendor";
  }
  const compact = compactText(value).replace(/[?!.]+$/g, "");
  const tokens = compact.split(/\s+/).filter(Boolean);
  const opener = tokens[0]?.toLowerCase() ?? "";
  const ambiguousCompactAcronym = tokens.length === 1 && /^[A-Z0-9-]{2,8}$/.test(compact);
  if (ambiguousCompactAcronym) {
    return null;
  }
  if (
    compact &&
    tokens.length <= 6 &&
    /[A-Za-z]/.test(compact) &&
    !["who", "what", "when", "where", "why", "how", "is", "are", "can", "do", "does", "should"].includes(opener)
  ) {
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

function inferPriorityFocus(value: string): PriorityFocus | null {
  const lower = value.toLowerCase();
  if (/\b(full picture|whole picture|overall read|everything|broad read)\b/.test(lower)) return "full_picture";
  if (/\b(owner|ownership|control|behind them|parent company|ultimate parent|beneficial)\b/.test(lower)) return "ownership";
  if (/\b(teammate|team with|partner with|partner|sub network|likely team|who matters under)\b/.test(lower)) return "teammate_network";
  if (/\b(compete|competitor|weak point|pressure point|vulnerable|attack)\b/.test(lower)) return "competitive_weakness";
  if (/\b(export|itar|ear|ddtc|bis|deemed export)\b/.test(lower)) return "export_exposure";
  if (/\b(cyber|cmmc|sprs|ssp|poam|sbom|vex|software assurance|rmf)\b/.test(lower)) return "cyber_posture";
  if (/\b(capability fit|fit|belongs in|actually belong|relevant to the vehicle)\b/.test(lower)) return "capability_fit";
  if (/\b(adverse|litigation|sanction|media|foreign exposure|pep|debar)\b/.test(lower)) return "adverse_history";
  if (/\b(vehicle ecosystem|ecosystem|incumbent team|team beneath|customer map)\b/.test(lower)) return "vehicle_ecosystem";
  if (/\b(incumbent continuity|follow-on path|transition path|recompete posture)\b/.test(lower)) return "incumbent_continuity";
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

const ENTITY_NOISE_WORDS = new Set([
  "inc",
  "incorporated",
  "corp",
  "corporation",
  "company",
  "co",
  "llc",
  "ltd",
  "limited",
  "plc",
  "lp",
  "llp",
  "gmbh",
  "ag",
  "sa",
  "srl",
  "bv",
  "nv",
  "public",
]);

function cleanEntityFragment(value: string) {
  return compactText(value)
    .replace(/^[,:;\-\s]+/, "")
    .replace(/[?.,]+$/, "")
    .trim();
}

function normalizeCandidateName(value: string) {
  return compactText(value)
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((token) => token && !ENTITY_NOISE_WORDS.has(token))
    .join(" ");
}

function candidateHasSource(candidate: EntityCandidate, source: string) {
  return String(candidate.source || "")
    .split(",")
    .map((item) => item.trim())
    .includes(source);
}

function candidateChoiceIndexWord(index: number) {
  return ["first", "second", "third", "fourth"][index] || `${index + 1}th`;
}

function describeCandidateForDisambiguation(candidate: EntityCandidate) {
  const details: string[] = [];
  if (candidate.ticker) {
    details.push(`public company with ticker ${candidate.ticker}`);
  }
  if (candidate.uei) {
    details.push(`registered entity with UEI ${candidate.uei}`);
  }
  if (candidate.cage) {
    details.push(`CAGE ${candidate.cage}`);
  }
  if (candidate.country) {
    details.push(candidate.country === "US" || candidate.country === "USA" ? "US entity" : `${candidate.country} entity`);
  }
  if (candidateHasSource(candidate, "local_vendor_memory")) {
    details.push("already in Helios vendor memory");
  }
  if (candidateHasSource(candidate, "knowledge_graph") || (candidate.graph_relationship_count ?? 0) > 0) {
    details.push(
      candidate.graph_relationship_count
        ? `anchored in the graph with ${candidate.graph_relationship_count} relationship${candidate.graph_relationship_count === 1 ? "" : "s"}`
        : "already anchored in the graph",
    );
  }
  if (candidate.graph_related_candidates?.[0]?.summary) {
    details.push(candidate.graph_related_candidates[0].summary);
  }
  return details.slice(0, 2).join(", ");
}

function inferCandidateRelationshipAnswer(candidates: EntityCandidate[]) {
  if (candidates.length < 2) {
    return "I only have one plausible entity in frame, so there is no disambiguation problem left.";
  }

  const groups = new Map<string, EntityCandidate[]>();
  for (const candidate of candidates) {
    const key = normalizeCandidateName(candidate.legal_name || "");
    if (!key) continue;
    const existing = groups.get(key) || [];
    existing.push(candidate);
    groups.set(key, existing);
  }

  const duplicateGroups = [...groups.values()].filter((group) => group.length > 1);
  const duplicateLine = duplicateGroups.length > 0
    ? `Two of these look like the same entity written in slightly different forms: ${duplicateGroups[0].map((candidate) => candidate.legal_name).join(" and ")}.`
    : "";

  const publicCandidate = candidates.find((candidate) => Boolean(candidate.ticker));
  const servicesCandidate = candidates.find((candidate) => /services|consulting|tech|systems|solutions/i.test(candidate.legal_name || ""));
  const localMemoryCandidate = candidates.find((candidate) => candidateHasSource(candidate, "local_vendor_memory"));
  const graphCandidate = candidates.find((candidate) => candidateHasSource(candidate, "knowledge_graph") || (candidate.graph_relationship_count ?? 0) > 0);

  const directGraphRelation = candidates
    .flatMap((candidate) =>
      (candidate.graph_related_candidates || []).map((related) => ({
        source: candidate.legal_name,
        ...related,
      })),
    )
    .find((related) => related.relationship_kind === "direct");

  if (directGraphRelation) {
    return `${duplicateLine ? `${duplicateLine} ` : ""}${directGraphRelation.summary}`;
  }

  const sharedGraphRelation = candidates
    .flatMap((candidate) =>
      (candidate.graph_related_candidates || []).map((related) => ({
        source: candidate.legal_name,
        ...related,
      })),
    )
    .find((related) => related.relationship_kind === "shared_neighbor");

  if (sharedGraphRelation) {
    return `${duplicateLine ? `${duplicateLine} ` : ""}${sharedGraphRelation.summary}`;
  }

  if (localMemoryCandidate) {
    return `${duplicateLine ? `${duplicateLine} ` : ""}${localMemoryCandidate.legal_name} is the one already anchored in Helios memory, so that is the strongest working candidate unless you meant a different entity.`;
  }

  if (graphCandidate) {
    const graphLead = graphCandidate.graph_relationship_count
      ? `${graphCandidate.legal_name} is already anchored in the Helios graph with ${graphCandidate.graph_relationship_count} relationship${graphCandidate.graph_relationship_count === 1 ? "" : "s"}, so that is the strongest working candidate unless you meant a different entity.`
      : `${graphCandidate.legal_name} is already anchored in the Helios graph, so that is the strongest working candidate unless you meant a different entity.`;
    if (graphCandidate.graph_signal_summary) {
      return `${duplicateLine ? `${duplicateLine} ` : ""}${graphLead} ${graphCandidate.graph_signal_summary}`;
    }
    return `${duplicateLine ? `${duplicateLine} ` : ""}${graphLead}`;
  }

  if (publicCandidate && servicesCandidate && publicCandidate.legal_name !== servicesCandidate.legal_name) {
    return `${duplicateLine ? `${duplicateLine} ` : ""}I do not have evidence that ${publicCandidate.legal_name} and ${servicesCandidate.legal_name} are the same company. The ticker-based public company looks separate from the services contractor naming.`;
  }

  if (duplicateLine) {
    return `${duplicateLine} I do not have evidence yet that the remaining names are part of the same ownership chain.`;
  }

  return "Not from what I can support yet. These look like distinct plausible entities, not one clean company family.";
}

function recommendCandidateFromChoices(
  candidates: EntityCandidate[],
  session: IntakeSession,
): { candidate: EntityCandidate | null; rationale: string | null } {
  const localMemoryCandidate = candidates.find((candidate) => candidateHasSource(candidate, "local_vendor_memory"));
  if (localMemoryCandidate) {
    return {
      candidate: localMemoryCandidate,
      rationale: `${localMemoryCandidate.legal_name} is already in Helios vendor memory, so it is the strongest working candidate.`,
    };
  }

  const graphCandidate = candidates.find((candidate) => candidateHasSource(candidate, "knowledge_graph") || (candidate.graph_relationship_count ?? 0) > 0);
  if (graphCandidate) {
    return {
      candidate: graphCandidate,
      rationale: graphCandidate.graph_relationship_count
        ? `${graphCandidate.legal_name} is already anchored in the Helios graph with ${graphCandidate.graph_relationship_count} relationship${graphCandidate.graph_relationship_count === 1 ? "" : "s"}, so it is the strongest working candidate.`
        : `${graphCandidate.legal_name} is already anchored in the Helios graph, so it is the strongest working candidate.`,
    };
  }

  const contractorCandidate = candidates.find((candidate) =>
    Boolean(candidate.uei || candidate.cage) ||
    /services|consulting|systems|solutions|defense|federal|technology|tech/i.test(candidate.legal_name || ""),
  );
  if (contractorCandidate) {
    return {
      candidate: contractorCandidate,
      rationale: `${contractorCandidate.legal_name} looks most like the operating contractor rather than a public-market or registry-adjacent name.`,
    };
  }

  const priorityCandidate = candidates.find((candidate) => {
    const name = candidate.legal_name || "";
    if (session.priorityFocus === "ownership") return Boolean(candidate.ticker || candidate.cik || candidate.lei);
    if (session.priorityFocus === "teammate_network") return /services|consulting|systems|solutions/i.test(name);
    return false;
  });
  if (priorityCandidate) {
    return {
      candidate: priorityCandidate,
      rationale: `${priorityCandidate.legal_name} is the cleanest fit for the edge you asked me to weight first.`,
    };
  }

  return { candidate: candidates[0] || null, rationale: null };
}

function matchCandidateChoiceFromText(text: string, candidates: EntityCandidate[]) {
  const lower = text.toLowerCase();
  const ordinalMap = ["first", "second", "third", "fourth"];
  for (let index = 0; index < Math.min(candidates.length, ordinalMap.length); index += 1) {
    if (lower.includes(ordinalMap[index]) || lower === String(index + 1) || lower.includes(`option ${index + 1}`)) {
      return candidates[index];
    }
  }

  for (const candidate of candidates) {
    const legalName = candidate.legal_name || "";
    if (!legalName) continue;
    if (lower.includes(legalName.toLowerCase())) {
      return candidate;
    }
    if (candidate.ticker && lower.includes(candidate.ticker.toLowerCase())) {
      return candidate;
    }
    if (candidate.uei && lower.includes(candidate.uei.toLowerCase())) {
      return candidate;
    }
    const normalized = normalizeCandidateName(legalName);
    if (normalized && lower.includes(normalized)) {
      return candidate;
    }
  }

  return null;
}

function isCandidateRelationshipQuestion(text: string) {
  return /\b(related|same company|same entity|same organization|connected|duplicates?|the same)\b/i.test(text);
}

function isCandidateRecommendationQuestion(text: string) {
  return /\b(which one|which of these|what should i pick|what should i choose|which is the right one|which looks like|which seems like|best match)\b/i.test(text);
}

function cutBeforeCue(value: string, cues: RegExp[]) {
  let end = value.length;
  for (const cue of cues) {
    const match = cue.exec(value);
    if (match && typeof match.index === "number" && match.index < end) {
      end = match.index;
    }
  }
  return value.slice(0, end);
}

function extractVehicleName(value: string): string | null {
  const source = compactText(value);
  const underMatch = source.match(/\bunder\s+([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,80})/i);
  if (underMatch?.[1]) {
    return cleanEntityFragment(underMatch[1]);
  }

  let candidate = source
    .replace(/^we(?:'re| are)?\s+looking\s+at\s+/i, "")
    .replace(/^looking\s+at\s+/i, "")
    .replace(/^it(?:'s| is)\s+/i, "")
    .replace(/^the\s+follow[- ]on\s+to\s+/i, "")
    .replace(/^follow[- ]on\s+to\s+/i, "");

  candidate = cutBeforeCue(candidate, [
    /\b(?:follow[- ]on|pre[- ]solicitation|incumbent|current prime|prime is|we think|current vehicle|expired vehicle|net new)\b/i,
    /[?.!]/,
    /,\s/,
  ]);

  const cleaned = cleanEntityFragment(candidate);
  return cleaned && cleaned.length > 1 ? cleaned : null;
}

function extractVendorName(value: string): string | null {
  const source = compactText(value);
  const directMatch = source.match(/\b(?:read on|assessment on|look at|screen|trust|partner with|team with|compete against|attack|on)\s+([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,80})/i);
  const candidate = directMatch?.[1]
    ? directMatch[1]
    : source
      .replace(/^need\s+(?:a\s+)?quick\s+read\s+on\s+/i, "")
      .replace(/^need\s+(?:an?\s+)?assessment\s+on\s+/i, "")
      .replace(/^open\s+(?:a\s+)?vendor\s+assessment\s+on\s+/i, "")
      .replace(/^vendor\s+/i, "")
      .replace(/^supplier\s+/i, "")
      .replace(/^teammate\s+/i, "");

  const trimmed = cutBeforeCue(candidate, [
    /\b(?:as a potential teammate|as a teammate|as a potential partner|as teammate|as partner|potential teammate|potential partner)\b/i,
    /[?.!]/,
    /,\s/,
  ]);

  const cleaned = cleanEntityFragment(trimmed);
  return cleaned && cleaned.length > 1 ? cleaned : null;
}

function extractPrimeName(value: string): string | null {
  const source = compactText(value);
  const thinkIncumbent = source.match(/\bwe\s+think\s+([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,80})\s+is\s+the\s+incumbent\b/i);
  if (thinkIncumbent?.[1]) {
    return cleanEntityFragment(thinkIncumbent[1]);
  }
  const explicit = source.match(/\b(?:prime(?:\s+is|\s+position)?|incumbent(?:\s+is)?)\b[:\s-]*([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,80})/i);
  if (explicit?.[1]) {
    return cleanEntityFragment(explicit[1]);
  }
  const reverse = source.match(/([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,80})\s+is\s+the\s+incumbent\b/i);
  if (reverse?.[1]) {
    return cleanEntityFragment(reverse[1]);
  }
  if (!/[?.!,]/.test(source)) {
    const cleaned = cleanEntityFragment(source);
    if (cleaned && cleaned.split(/\s+/).length <= 6) {
      return cleaned;
    }
  }
  return null;
}

function humanizeApiError(value: unknown, fallback: string) {
  if (!(value instanceof Error)) return fallback;
  const cleaned = value.message.replace(/^API\s+\d+:\s*/i, "").trim();
  return cleaned || fallback;
}

function humanizePriorityFocus(focus: PriorityFocus | null): string | null {
  if (!focus || focus === "full_picture") return null;
  const labels: Record<Exclude<PriorityFocus, "full_picture">, string> = {
    ownership: "ownership and control",
    teammate_network: "the teammate network",
    competitive_weakness: "competitive weak points",
    export_exposure: "export exposure",
    cyber_posture: "cyber posture",
    capability_fit: "capability fit",
    adverse_history: "adverse history",
    vehicle_ecosystem: "the vehicle ecosystem",
    incumbent_continuity: "incumbent continuity",
  };
  return labels[focus];
}

function vendorSeedStrength(name: string | null): number {
  const cleaned = compactText(name || "").replace(/[?!.]+$/g, "");
  if (!cleaned) return 0;
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  const hasCorporateSuffix = /\b(inc|corp|corporation|llc|ltd|plc|lp|llp|co|company|gmbh|ag|sa|srl|bv|nv)\b/i.test(cleaned);
  const isCompactAcronym = tokens.length === 1 && /^[A-Z0-9&-]{2,8}$/.test(cleaned);
  const looksLikeNamedEntity = tokens.length <= 5 && /[A-Za-z]/.test(cleaned);

  if (isCompactAcronym || hasCorporateSuffix) return 0.58;
  if (looksLikeNamedEntity) return 0.52;
  return 0.4;
}

function computeIntakeConfidence(session: IntakeSession): number {
  if (session.objectType === "vehicle") {
    let score = 0.18;
    if (session.vehicleName) score += 0.34;
    if (session.vehicleTiming) score += 0.15;
    if (session.followOn !== null) score += 0.15;
    if (session.incumbentPrime) score += 0.18;
    return Math.min(1, score);
  }

  if (session.objectType === "vendor") {
    let score = 0.22;
    if (session.vendorName) score += vendorSeedStrength(session.vendorName);
    if (session.priorityFocus) score += session.priorityFocus === "full_picture" ? 0.06 : 0.14;
    if (session.supportLayer !== "counterparty") score += 0.08;
    if (session.vehicleName) score += 0.06;
    return Math.min(1, score);
  }

  return 0;
}

function shouldPivotToVehicle(routed: RoutedIntake) {
  return routed.winning_mode === "vehicle"
    && !routed.clarifier_needed
    && (routed.override_applied || routed.confidence >= STRONG_ROUTING_CORRECTION_CONFIDENCE);
}

function shouldPivotToVendor(routed: RoutedIntake, pendingFollowUp: PendingFollowUp | null) {
  if (pendingFollowUp === "vehicle_follow_on_or_incumbent" || pendingFollowUp === "vehicle_incumbent_prime") {
    return false;
  }
  return routed.winning_mode === "vendor" && !routed.clarifier_needed && routed.override_applied;
}

function hypothesisForKind(routed: RoutedIntake, kind: "vendor" | "vehicle") {
  return routed.hypotheses.find((hypothesis) => hypothesis.kind === kind) || null;
}

function routeReasonMentionsMemory(reasons: string[]) {
  return reasons.some((reason) => /\b(memory|graph)\b/i.test(reason));
}

function buildObjectTypeClarifier(input: string, routed: RoutedIntake) {
  const seed = compactText(routed.raw_input || input).replace(/[?!.]+$/g, "");
  const vehicle = hypothesisForKind(routed, "vehicle");
  const vendor = hypothesisForKind(routed, "vendor");
  const strongVehicle = (vehicle?.score || 0) >= 0.84;
  const strongVendor = (vendor?.score || 0) >= 0.72;

  if (seed && strongVehicle && strongVendor) {
    if (routeReasonMentionsMemory(vendor?.reasons || [])) {
      return `I can take ${seed} as either the contract vehicle or an entity already in Helios memory. Which one do you mean?`;
    }
    return `I can take ${seed} as either a contract vehicle or a specific entity. Which one do you mean?`;
  }

  return "Are we looking at a contract vehicle or a specific vendor?";
}

function buildVehicleCorrectionSession(session: IntakeSession, value: string, routed: RoutedIntake): IntakeSession {
  const correctedVehicleName = compactText(
    routed.anchor_text
    || extractVehicleName(value)
    || compactText(stripObjectLabel(value))
    || session.vehicleName
    || session.vendorName
    || "",
  );
  const inferredTiming = inferVehicleTiming(value);
  const correctedPrime = extractPrimeName(value);
  const inferredFollowOn = inferBoolean(value);

  return {
    ...session,
    objectType: "vehicle",
    vendorName: null,
    vehicleName: correctedVehicleName || null,
    seedText: correctedVehicleName || session.seedText,
    vehicleTiming: inferredTiming ?? session.vehicleTiming,
    followOn: correctedPrime ? true : inferredFollowOn ?? session.followOn,
    incumbentPrime: correctedPrime ?? session.incumbentPrime,
    pendingFollowUp: null,
    followUpCount: 0,
  };
}

function buildVendorCorrectionSession(session: IntakeSession, value: string, routed: RoutedIntake): IntakeSession {
  const correctedVendorName = compactText(
    routed.anchor_text
    || extractVendorName(value)
    || compactText(stripObjectLabel(value))
    || session.vendorName
    || session.vehicleName
    || "",
  );

  return {
    ...session,
    objectType: "vendor",
    vendorName: correctedVendorName || null,
    vehicleName: null,
    seedText: correctedVendorName || session.seedText,
    vehicleTiming: null,
    followOn: null,
    incumbentPrime: null,
    supportLayer: inferSupportLayer(value) || session.supportLayer,
    priorityFocus: inferPriorityFocus(value) || session.priorityFocus,
    pendingFollowUp: null,
    followUpCount: 0,
  };
}

function applyPendingFollowUpAnswer(session: IntakeSession, value: string): IntakeSession {
  const nextSession = { ...session, pendingFollowUp: null };
  const stripped = compactText(stripObjectLabel(value));
  const lower = value.toLowerCase();
  const preservedSeed = compactText(session.seedText || "");

  switch (session.pendingFollowUp) {
    case "object_type": {
      const inferredObject = inferObjectType(value);
      if (inferredObject) {
        nextSession.objectType = inferredObject;
        if (inferredObject === "vehicle" && !nextSession.vehicleName && preservedSeed) {
          nextSession.vehicleName = extractVehicleName(preservedSeed) || preservedSeed;
        }
        if (inferredObject === "vendor" && !nextSession.vendorName && preservedSeed) {
          nextSession.vendorName = extractVendorName(preservedSeed) || preservedSeed;
        }
      }
      break;
    }
    case "vehicle_name":
      if (stripped && !looksLikeObjectOnlyAnswer(value)) {
        nextSession.objectType = "vehicle";
        nextSession.vehicleName = extractVehicleName(value) || stripped;
      }
      break;
    case "vendor_name":
      if (stripped && !looksLikeObjectOnlyAnswer(value)) {
        nextSession.objectType = "vendor";
        nextSession.vendorName = extractVendorName(value) || stripped;
      }
      break;
    case "vehicle_timing": {
      const inferredTiming = inferVehicleTiming(value);
      if (inferredTiming) {
        nextSession.vehicleTiming = inferredTiming;
      }
      break;
    }
    case "vehicle_follow_on_or_incumbent": {
      const followOnAnswer = inferBoolean(value);
      if (followOnAnswer !== null) {
        nextSession.followOn = followOnAnswer;
      }
      if (!/\b(no|nope|not sure|unsure|don't know|do not know)\b/i.test(lower)) {
        const primeName = extractPrimeName(value);
        if (primeName) {
          nextSession.incumbentPrime = primeName;
          nextSession.followOn = true;
        }
      }
      break;
    }
    case "vehicle_incumbent_prime":
      if (!/\b(no|nope|not sure|unsure|don't know|do not know)\b/i.test(lower)) {
        const primeName = extractPrimeName(value);
        if (primeName) {
          nextSession.incumbentPrime = primeName;
          nextSession.followOn ??= true;
        }
      }
      break;
    case "vendor_priority_focus": {
      const inferredFocus = inferPriorityFocus(value);
      if (inferredFocus) {
        nextSession.priorityFocus = inferredFocus;
      } else if (/\b(full picture|whole picture|overall read|broad read|everything|all of it|all of them|no preference|you decide|work it all)\b/i.test(lower)) {
        nextSession.priorityFocus = "full_picture";
      }
      break;
    }
    default:
      break;
  }

  return nextSession;
}

function missionBriefSummary(session: IntakeSession): string {
  if (session.objectType === "vehicle") {
    const details = [
      session.vehicleName,
      session.vehicleTiming ? session.vehicleTiming.replace(/_/g, " ") : null,
      session.followOn === true ? "follow-on" : session.followOn === false ? "net-new" : null,
      session.incumbentPrime ? `${session.incumbentPrime} incumbent` : null,
    ].filter(Boolean).join(", ");
    return details
      ? `Vehicle brief on ${details}.`
      : "Vehicle brief scoped from the briefing room.";
  }

  const weightedFirst = humanizePriorityFocus(session.priorityFocus) || "the full picture";
  return session.vendorName
    ? `Entity brief on ${session.vendorName}. Weight ${weightedFirst} first without shrinking the scope.`
    : "Entity brief scoped from the briefing room.";
}

function clarifyingFollowUpLabel(pendingFollowUp: PendingFollowUp | null): string | null {
  switch (pendingFollowUp) {
    case "object_type":
      return "Clarifying object";
    case "vendor_name":
      return "Clarifying vendor";
    case "vehicle_name":
      return "Clarifying vehicle";
    case "vehicle_timing":
      return "Clarifying timing";
    case "vehicle_follow_on_or_incumbent":
      return "Clarifying incumbent";
    case "vehicle_incumbent_prime":
      return "Confirming prime";
    case "vendor_priority_focus":
      return "Weighting one edge";
    default:
      return null;
  }
}

function missionBriefPriorityRequirements(session: IntakeSession): string[] {
  const requirements = ["Work the full picture first."];
  const weightedFirst = humanizePriorityFocus(session.priorityFocus);
  if (weightedFirst) {
    requirements.push(`Weight ${weightedFirst} first.`);
  }
  if (session.objectType === "vehicle" && session.vehicleTiming === "pre_solicitation") {
    requirements.push("Treat timing as pre-solicitation and pressure continuity.");
  }
  if (session.objectType === "vehicle" && session.followOn === true && session.incumbentPrime) {
    requirements.push(`Start from incumbent continuity through ${session.incumbentPrime}.`);
  }
  if (session.supportLayer !== "counterparty") {
    requirements.push(`${session.supportLayer} stays folded in as a supporting layer, not a separate product lane.`);
  }
  return requirements;
}

function missionBriefNotesFromReadiness(readiness: VendorBriefReadiness): string[] {
  const findingsTotal = readiness.enrichment?.summary?.findings_total ?? readiness.passport?.identity.findings_total ?? 0;
  const connectorsWithData = readiness.enrichment?.summary?.connectors_with_data ?? readiness.passport?.identity.connectors_with_data ?? 0;
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  const notes: string[] = [];

  notes.push(
    connectorsWithData > 0 || findingsTotal > 0
      ? `${connectorsWithData} sources with data produced ${findingsTotal} surviving findings in the returned brief.`
      : "The public record stayed thin enough that the returned brief is explicitly carrying ambiguity.",
  );

  if (relationshipCount > 0 || controlPathCount > 0) {
    notes.push(`The graph changed the read with ${relationshipCount} relationships and ${controlPathCount} visible control paths.`);
  } else {
    notes.push("The graph remained thin and could not carry the brief on its own.");
  }

  if (readiness.axiomGapClosure?.status === "completed") {
    notes.push(
      `AXIOM ran ${readiness.axiomGapClosure.passes > 1 ? `${readiness.axiomGapClosure.passes} pressure passes` : "a pressure pass"} and surfaced ${readiness.axiomGapClosure.entitiesFound} entities, ${readiness.axiomGapClosure.relationshipsFound} relationships, and ${readiness.axiomGapClosure.gapCount} residual gaps.`,
    );
    if (readiness.axiomGapClosure.unresolvedReasons?.length) {
      notes.push(`What stayed thin after pressure: ${readiness.axiomGapClosure.unresolvedReasons.join(" ")}`);
    }
  } else if (readiness.axiomGapClosure?.status === "failed") {
    notes.push(readiness.axiomGapClosure.note);
  } else {
    notes.push("AXIOM did not need a pressure pass before the returned brief froze.");
  }

  return notes;
}

function buildMissionBriefPayload(
  session: IntakeSession,
  inputSeed: string,
  options: {
    caseId?: string | null;
    status?: string;
    room?: MissionBriefRoom;
    readiness?: VendorBriefReadiness | null;
  } = {},
): MissionBriefPayload {
  const weightedFirst = humanizePriorityFocus(session.priorityFocus);
  const isVehicle = session.objectType === "vehicle";
  const primaryTargets: Record<string, unknown> = isVehicle
    ? {
      vehicle_name: session.vehicleName,
      incumbent_prime: session.incumbentPrime,
      vendor_name: session.vendorName,
    }
    : {
      vendor_name: session.vendorName,
      vehicle_name: session.vehicleName,
    };

  const knownContext: Record<string, unknown> = {
    opening_input: inputSeed,
    weighted_first: weightedFirst || "full picture",
    support_layer: session.supportLayer,
  };
  if (session.vehicleTiming) knownContext.vehicle_timing = session.vehicleTiming.replace(/_/g, " ");
  if (session.followOn !== null) knownContext.follow_on = session.followOn;
  if (session.incumbentPrime) knownContext.incumbent_prime = session.incumbentPrime;
  if (options.readiness?.networkRisk?.network_risk_level) {
    knownContext.network_risk_level = options.readiness.networkRisk.network_risk_level;
  }

  return {
    room: options.room || "stoa",
    case_id: options.caseId || null,
    object_type: session.objectType,
    engagement_type: isVehicle ? "contract_vehicle_intelligence" : "vendor_assessment",
    collection_depth: "full_picture",
    timeline: isVehicle ? (session.vehicleTiming || "current") : "preliminary_returned_brief",
    status: options.status || "scoped",
    question_count: session.followUpCount,
    confidence_score: computeIntakeConfidence(session),
    primary_targets: primaryTargets,
    known_context: knownContext,
    priority_requirements: missionBriefPriorityRequirements(session),
    authorized_tiers: ["public_record", "graph_context", "axiom_gap_closure"],
    summary: missionBriefSummary(session),
    notes: options.readiness ? missionBriefNotesFromReadiness(options.readiness) : [],
  };
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

function buildVehicleSearchFallback(session: IntakeSession, errorMessage?: string): VehicleSearchResult {
  const vehicleName = compactText(session.vehicleName || "") || "Vehicle brief";
  const primeVendors: VehicleVendor[] = session.incumbentPrime
    ? [{
        vendor_name: session.incumbentPrime,
        role: "prime",
      }]
    : [];
  const uniqueVendorMap = new Map<string, VehicleVendor>();
  for (const vendor of primeVendors) {
    uniqueVendorMap.set(vendor.vendor_name.toLowerCase(), vendor);
  }

  return {
    vehicle_name: vehicleName,
    search_terms: [vehicleName],
    timestamp: new Date().toISOString(),
    primes: primeVendors,
    subs: [],
    unique_vendors: Array.from(uniqueVendorMap.values()),
    total_primes: primeVendors.length,
    total_subs: 0,
    total_unique: uniqueVendorMap.size,
    idv_awards_checked: 0,
    errors: errorMessage ? [{ source: "vehicle_search_fallback", message: errorMessage }] : [],
  };
}

function supportLayerDetail(session: IntakeSession) {
  if (session.supportLayer === "export") {
    return "Export exposure stays folded into the full entity picture unless the record forces it into its own issue.";
  }
  if (session.supportLayer === "cyber") {
    return "Cyber posture stays in scope as supporting evidence instead of taking over the brief.";
  }
  return "AXIOM is building the full entity picture first and only weights one edge ahead of the rest when the brief calls for it.";
}

function vehiclePressureDetail(result: VehicleSearchResult, session: IntakeSession) {
  if (session.vehicleTiming === "pre_solicitation" && session.followOn === true && session.incumbentPrime) {
    return `${session.incumbentPrime} gives AXIOM a concrete incumbent spine to test for continuity, brittleness, and likely teammate carryover.`;
  }
  if (session.vehicleTiming === "pre_solicitation") {
    return "Because this is still ahead of release, the real value is continuity and lineage, not surface-level award noise.";
  }
  if (result.total_subs === 0) {
    return "Subcontractor visibility is still thin, so the first picture should be treated as a disciplined public read, not a complete team map.";
  }
  return "The public ecosystem is warm enough to start separating what holds from what still needs pressure.";
}

function buildVehicleArtifactSections(result: VehicleSearchResult, session: IntakeSession) {
  const weightedFirst = humanizePriorityFocus(session.priorityFocus);
  const sections: VendorArtifact["sections"] = [
    {
      label: "What I found",
      detail: summarizeVehicle(result, session),
    },
    {
      label: "Where it stays thin",
      detail: vehiclePressureDetail(result, session),
      tone: result.total_subs === 0 ? "warning" : "neutral",
    },
    {
      label: "Best next question",
      detail: result.unique_vendors.length > 0
        ? `Spin the right vendor out of ${result.vehicle_name} into assessment, or step into ${DEEP_ROOM_NAME} if you need to work the weak points directly.`
        : `Step into ${DEEP_ROOM_NAME} if the public picture is still too thin to act on cleanly.`,
    },
  ];
  if (weightedFirst) {
    sections.splice(1, 0, {
      label: "Weighted first",
      detail: `AXIOM is keeping the full vehicle picture in scope while weighting ${weightedFirst} first.`,
      tone: "info",
    });
  }
  return sections;
}

function buildVendorArtifact(
  candidate: EntityCandidate | null,
  session: IntakeSession,
  phase: "warming" | "ready",
  caseId: string,
  subjectOverride?: string,
): VendorArtifact {
  const subject = subjectOverride ?? candidate?.legal_name ?? session.vendorName ?? "Entity brief";
  const ownershipDetail = candidate?.highest_owner && candidate.highest_owner !== candidate.legal_name
    ? `Public control signals already run beyond the surface entity toward ${candidate.highest_owner}.`
    : "The visible public record is still surface-level, so the control story will stay under pressure until it holds.";
  const focusDetail = humanizePriorityFocus(session.priorityFocus);

  return {
    caseId,
    phase,
    title: subject,
    eyebrow: phase === "ready" ? "Returned brief" : "Working brief",
    framing: phase === "ready"
      ? "AXIOM's first memo is ready. It keeps the strongest holds visible and leaves the real ambiguity explicit."
      : `AXIOM is building the first judgment around ${subject} without pretending the thin edge is settled.`,
    sections: [
      {
        label: "Initial judgment",
        detail: focusDetail
          ? `This is being worked as a full entity picture, with ${focusDetail} weighted first instead of shrinking the scope.`
          : "This is being worked as a full entity picture, with the public record forced to answer the real decision before AXIOM narrows anything.",
      },
      {
        label: "Where it stays thin",
        detail: ownershipDetail,
        tone: candidate?.highest_owner && candidate.highest_owner !== candidate.legal_name ? "info" : "warning",
      },
      {
        label: "What changes the call",
        detail: supportLayerDetail(session),
      },
    ],
    note: phase === "ready"
      ? `Read the memo here. Step into ${DEEP_ROOM_NAME} when you want to challenge the picture or pull a harder thread.`
      : `The working case is open and warming. Step into ${DEEP_ROOM_NAME} when you want the trail instead of the summary.`,
    provenance: phase === "ready"
      ? ["Resolution-backed", "Initial graph context", "Public record only"]
      : ["Entity resolution", "Warm graph context", "Public record only"],
  };
}

function assessVendorThinness(readiness: VendorBriefReadiness) {
  const findingsTotal = readiness.enrichment?.summary?.findings_total ?? readiness.passport?.identity.findings_total ?? 0;
  const connectorsWithData = readiness.enrichment?.summary?.connectors_with_data ?? readiness.passport?.identity.connectors_with_data ?? 0;
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  const graphIntelligence = readiness.passport?.graph.intelligence;
  const thinGraph = Boolean(graphIntelligence?.thin_graph);
  const missingRequiredEdgeFamilies = (graphIntelligence?.missing_required_edge_families ?? []).filter(Boolean);
  const dominantEdgeFamily = String(graphIntelligence?.dominant_edge_family || "").replace(/_/g, " ").trim();
  const networkRiskLevel = String(readiness.networkRisk?.network_risk_level || "").toLowerCase();
  const topControlPath = readiness.passport?.graph.control_paths[0];
  const reasons: string[] = [];

  if (findingsTotal < 2) reasons.push("The visible public record is still thin.");
  if (connectorsWithData < 2) reasons.push("Too few connectors returned usable data.");
  if (relationshipCount < 2) reasons.push("Relationship depth is still shallow.");
  if (thinGraph) reasons.push("The graph is still thin.");
  if (controlPathCount === 0) reasons.push("No control path has held cleanly yet.");
  if (missingRequiredEdgeFamilies.length > 0) {
    reasons.push(
      `Required graph edge families are still missing: ${missingRequiredEdgeFamilies
        .slice(0, 3)
        .map((item) => item.replace(/_/g, " "))
        .join(", ")}.`,
    );
  }
  if (networkRiskLevel === "high" || networkRiskLevel === "critical") {
    reasons.push(`Network risk is already reading ${networkRiskLevel}.`);
  }

  const severe =
    findingsTotal === 0 ||
    connectorsWithData === 0 ||
    thinGraph ||
    controlPathCount === 0 ||
    missingRequiredEdgeFamilies.length > 0;

  return {
    findingsTotal,
    connectorsWithData,
    relationshipCount,
    controlPathCount,
    thinGraph,
    thinSignals: reasons.length,
    severe,
    reasons,
    missingRequiredEdgeFamilies,
    dominantEdgeFamily,
    networkRiskLevel,
    topControlPath,
  };
}

function shouldPressureVendorReadiness(readiness: VendorBriefReadiness) {
  const assessment = assessVendorThinness(readiness);
  return assessment.severe || assessment.thinSignals >= 2;
}

function shouldEscalateVendorGapClosure(
  readiness: VendorBriefReadiness,
  gapClosure: VendorBriefReadiness["axiomGapClosure"],
) {
  if (!gapClosure || gapClosure.status !== "completed" || gapClosure.passes >= 2) {
    return false;
  }
  const assessment = assessVendorThinness(readiness);
  return (
    assessment.severe ||
    assessment.thinSignals >= 2 ||
    gapClosure.gapCount > 0 ||
    gapClosure.relationshipsFound === 0
  );
}

function mergeVendorGapClosures(
  existing: VendorBriefReadiness["axiomGapClosure"],
  next: VendorBriefReadiness["axiomGapClosure"],
  readiness: VendorBriefReadiness,
): VendorBriefReadiness["axiomGapClosure"] {
  if (!existing) return next;
  if (!next) return existing;

  const assessment = assessVendorThinness(readiness);
  const gapHighlights = Array.from(
    new Set([...(existing.gapHighlights ?? []), ...(next.gapHighlights ?? [])].filter(Boolean)),
  ).slice(0, 3);

  return {
    status: next.status === "failed" && existing.status === "failed" ? "failed" : "completed",
    passes: Math.max(existing.passes, next.passes),
    entitiesFound: existing.entitiesFound + next.entitiesFound,
    relationshipsFound: existing.relationshipsFound + next.relationshipsFound,
    gapCount: next.gapCount,
    note:
      next.status === "failed"
        ? next.note
        : next.passes > 1
          ? "AXIOM pressured the weak edge twice before the brief froze."
          : next.note,
    remainingThinSignals: assessment.thinSignals,
    unresolvedReasons: assessment.reasons.slice(0, 3),
    gapHighlights,
  };
}

function buildGapClosureContext(
  session: IntakeSession,
  subject: string,
  readiness: VendorBriefReadiness,
  options: {
    passIndex?: number;
    escalated?: boolean;
  } = {},
) {
  const assessment = assessVendorThinness(readiness);
  const context: string[] = [
    `Brief view warming for ${subject}.`,
    options.escalated
      ? "The first AXIOM pressure pass still left the picture thin. Push harder against the unresolved edge before the brief freezes."
      : "Work the full entity picture and close the thinnest public-data gap before the brief freezes.",
  ];
  const weightedFirst = humanizePriorityFocus(session.priorityFocus);
  if (weightedFirst) {
    context.push(`Weight ${weightedFirst} first.`);
  }
  if (session.vehicleName) {
    context.push(`Vehicle context already in frame: ${session.vehicleName}.`);
  }
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  if (relationshipCount > 0) {
    context.push(`Current graph already holds ${relationshipCount} relationship${relationshipCount === 1 ? "" : "s"}. Use those relationships to guide the next thread, not just the surface record.`);
  }
  if (assessment.controlPathCount > 0) {
    context.push(`There are ${assessment.controlPathCount} control path${assessment.controlPathCount === 1 ? "" : "s"} already visible in the graph.`);
  } else {
    context.push("No clean control path is holding yet. Pressure ownership and control until the graph stops being surface-level.");
  }
  if (assessment.missingRequiredEdgeFamilies.length > 0) {
    context.push(
      `Missing edge families: ${assessment.missingRequiredEdgeFamilies
        .slice(0, 3)
        .map((item) => item.replace(/_/g, " "))
        .join(", ")}.`,
    );
  }
  if (assessment.dominantEdgeFamily) {
    context.push(`The dominant graph edge family so far is ${assessment.dominantEdgeFamily}. Use it, but do not let it trap the next move.`);
  }
  if (assessment.networkRiskLevel === "high" || assessment.networkRiskLevel === "critical") {
    context.push(`Network risk is already ${assessment.networkRiskLevel}. Use the graph to explain that propagation instead of treating it as a detached score.`);
  }
  if (assessment.topControlPath?.source_name && assessment.topControlPath?.target_name) {
    context.push(
      `One visible control path already runs from ${assessment.topControlPath.source_name} to ${assessment.topControlPath.target_name}. Confirm whether that path is stable or misleading.`,
    );
  }
  if (assessment.reasons.length > 0) {
    context.push(`Residual thinness after pass ${options.passIndex ?? 1}: ${assessment.reasons.slice(0, 3).join(" ")}`);
  }
  return context.join(" ");
}

function buildReturnedVendorArtifact(
  session: IntakeSession,
  caseId: string,
  subject: string,
  readiness: VendorBriefReadiness,
): VendorArtifact {
  const weightedFirst = humanizePriorityFocus(session.priorityFocus);
  const findingsTotal = readiness.enrichment?.summary?.findings_total ?? readiness.passport?.identity.findings_total ?? 0;
  const connectorsWithData = readiness.enrichment?.summary?.connectors_with_data ?? readiness.passport?.identity.connectors_with_data ?? 0;
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  const networkRiskLevel = String(readiness.networkRisk?.network_risk_level || "").toUpperCase();
  const graphIntelligence = readiness.passport?.graph.intelligence;
  const dominantEdgeFamily = String(graphIntelligence?.dominant_edge_family || "").replace(/_/g, " ");
  const missingEdgeFamilies = (graphIntelligence?.missing_required_edge_families ?? []).filter(Boolean);
  const gapClosure = readiness.axiomGapClosure;
  const pressurePasses = gapClosure?.passes ?? 0;

  const whatHolds = connectorsWithData > 0 || findingsTotal > 0
    ? `The first judgment is resting on ${connectorsWithData} live source${connectorsWithData === 1 ? "" : "s"} with data, and ${findingsTotal} finding${findingsTotal === 1 ? "" : "s"} survived the first cut. That is enough to brief from without pretending the surface story is complete.`
    : "The public record stayed unusually thin, so this memo is holding only the parts that actually stand up instead of bluffing past the gaps.";

  const graphDetail = relationshipCount > 0
    ? `The graph changed the call, not just the picture. It is carrying ${relationshipCount} relationship${relationshipCount === 1 ? "" : "s"} and ${controlPathCount} control path${controlPathCount === 1 ? "" : "s"}${dominantEdgeFamily ? `, with ${dominantEdgeFamily} holding the strongest edge family.` : "."}`
    : "The graph stayed too thin to soften the call, which means silence still should not be treated as comfort.";

  const thinDetails: string[] = [];
  if (connectorsWithData < 2) {
    thinDetails.push("Connector coverage is still thin.");
  }
  if (relationshipCount < 2) {
    thinDetails.push("Relationship depth is still shallow.");
  }
  if (controlPathCount === 0) {
    thinDetails.push("No control path has held cleanly yet.");
  }
  if (missingEdgeFamilies.length > 0) {
    thinDetails.push(
      `The graph is still missing ${missingEdgeFamilies
        .slice(0, 2)
        .map((item) => item.replace(/_/g, " "))
        .join(" and ")}.`,
    );
  }
  if (gapClosure?.gapCount && gapClosure.gapCount > 0) {
    thinDetails.push(`${gapClosure.gapCount} gap${gapClosure.gapCount === 1 ? "" : "s"} remain open after ${pressurePasses > 1 ? `${pressurePasses} pressure passes` : "the pressure pass"}.`);
  }
  if (gapClosure?.unresolvedReasons?.length) {
    thinDetails.push(gapClosure.unresolvedReasons.join(" "));
  }
  const thinDetail = thinDetails.length > 0
    ? thinDetails.join(" ")
    : "The weak edge is now explicit, but no material thin spot is being hidden under surface calm.";

  const gapDetail = gapClosure?.status === "completed"
    ? `AXIOM reopened the weak edge ${pressurePasses > 1 ? `${pressurePasses} times` : "once"} and surfaced ${gapClosure.entitiesFound} additional entit${gapClosure.entitiesFound === 1 ? "y" : "ies"}, ${gapClosure.relationshipsFound} relationship${gapClosure.relationshipsFound === 1 ? "" : "s"}, and ${gapClosure.gapCount} residual gap${gapClosure.gapCount === 1 ? "" : "s"}.${gapClosure.gapHighlights?.length ? ` It kept pressure on ${gapClosure.gapHighlights.join("; ")}.` : ""}`
    : gapClosure?.status === "failed"
      ? gapClosure.note
      : "AXIOM did not need a second pressure pass because the first picture already had enough structure to freeze honestly.";

  return {
    caseId,
    phase: "ready",
    title: subject,
    eyebrow: "Returned brief",
    framing: gapClosure?.status === "completed"
      ? `AXIOM's first judgment is ready. It uses enrichment, the visible relationship fabric, and ${pressurePasses > 1 ? `${pressurePasses} pressure passes` : "one pressure pass"} before the picture was allowed to freeze.`
      : "AXIOM's first judgment is ready. It uses enrichment and the current relationship fabric before the picture was allowed to freeze.",
    sections: [
      {
        label: "What holds",
        detail: weightedFirst ? `${whatHolds} ${weightedFirst} stayed weighted first without shrinking the scope.` : whatHolds,
        tone: findingsTotal > 0 ? "success" : "warning",
      },
      {
        label: "What stayed thin",
        detail: thinDetail,
        tone: thinDetails.length > 0 ? "warning" : "neutral",
      },
      {
        label: "What AXIOM did",
        detail: gapDetail,
        tone: gapClosure?.status === "failed" ? "warning" : "neutral",
      },
      {
        label: "What the graph changed",
        detail: networkRiskLevel && networkRiskLevel !== "NONE"
          ? `${graphDetail} Network risk is currently ${networkRiskLevel.toLowerCase().replace(/_/g, " ")}.`
          : graphDetail,
        tone: relationshipCount > 0 ? "info" : "warning",
      },
    ],
    note: gapClosure?.status === "completed"
      ? `Read the judgment here. Step into ${DEEP_ROOM_NAME} when you want to challenge what still stayed thin after AXIOM pressed the weak edge.`
      : `Read the judgment here. Step into ${DEEP_ROOM_NAME} when you want to challenge the weak edge directly.`,
    provenance: [
      `${connectorsWithData} sources with data`,
      relationshipCount > 0 ? `${relationshipCount} graph relationships` : "Graph still thin",
      gapClosure?.status === "completed" ? `AXIOM ${pressurePasses > 1 ? `${pressurePasses}-pass pressure loop` : "pressure pass"}` : "Single-pass public picture",
    ],
  };
}

function pressureOptionsForSession(session: IntakeSession): PriorityFocus[] {
  if (session.objectType === "vehicle") {
    return [
      "incumbent_continuity",
      "vehicle_ecosystem",
      "teammate_network",
      "competitive_weakness",
    ];
  }

  const options: PriorityFocus[] = ["ownership", "adverse_history", "teammate_network"];
  if (session.supportLayer === "cyber") {
    options.push("cyber_posture");
  } else if (session.supportLayer === "export") {
    options.push("export_exposure");
  } else {
    options.push("capability_fit");
  }
  return options;
}

function buildVehicleBriefViewModel(result: VehicleSearchResult, session: IntakeSession): FrontPorchBriefViewModel {
  return {
    kind: "vehicle",
    eyebrow: "Preliminary picture",
    statusLine: session.vehicleTiming === "pre_solicitation" ? "Pre-solicitation picture" : "Vehicle picture",
    title: result.vehicle_name,
    framing: summarizeVehicle(result, session),
    sections: buildVehicleArtifactSections(result, session),
    provenance: [
      `${result.total_primes} primes`,
      `${result.total_subs} subcontractor traces`,
      `${result.total_unique} unique vendors`,
    ],
    note: `Stay in this room for the clean public picture. Step into ${DEEP_ROOM_NAME} or Graph when you want to press the weak edge instead of just reading it.`,
  };
}

function buildVendorBriefViewModel(artifact: VendorArtifact): FrontPorchBriefViewModel {
  return {
    kind: "vendor",
    eyebrow: artifact.eyebrow,
    statusLine: artifact.phase === "ready" ? "Returned brief ready" : "Working brief warming",
    title: artifact.title,
    framing: artifact.framing,
    sections: artifact.sections,
    provenance: artifact.provenance,
    note: artifact.note,
  };
}

function buildVehicleWorkingLead(session: IntakeSession) {
  const frame = [
    session.vehicleName,
    session.vehicleTiming ? session.vehicleTiming.replace(/_/g, " ") : null,
    session.followOn === true ? "follow-on" : session.followOn === false ? "net-new" : null,
    session.incumbentPrime ? `${session.incumbentPrime} incumbent` : null,
  ].filter(Boolean).join(", ");
  return frame ? `I have enough: ${frame}.` : "";
}

function buildVendorWorkingLead(session: IntakeSession) {
  const frame = [
    session.vendorName,
    humanizePriorityFocus(session.priorityFocus)
      ? `${humanizePriorityFocus(session.priorityFocus)} first`
      : null,
    session.supportLayer !== "counterparty" ? `${session.supportLayer} in support` : null,
  ].filter(Boolean).join(", ");
  return frame ? `I have enough: ${frame}.` : "";
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
    content: "Start anywhere. A vehicle, a vendor, or the knot you cannot quite name yet.",
  },
];

export function FrontPorchLanding({
  cases = [],
  loginRequired = false,
  onNavigate,
  onOpenCase,
  onOpenAegisIntent,
  onRequestLogin,
}: FrontPorchLandingProps) {
  const [menu, setMenu] = useState<RoomMenu>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>(INITIAL_MESSAGES);
  const [session, setSession] = useState<IntakeSession>({
    objectType: null,
    vendorName: null,
    vehicleName: null,
    seedText: null,
    priorityFocus: null,
    supportLayer: "counterparty",
    vehicleTiming: null,
    followOn: null,
    incumbentPrime: null,
    followUpCount: 0,
    pendingFollowUp: null,
  });
  const [isWorking, setIsWorking] = useState(false);
  const [workingCaseId, setWorkingCaseId] = useState<string | null>(null);
  const [progressIndex, setProgressIndex] = useState(0);
  const [resolution, setResolution] = useState<EntityResolution | null>(null);
  const [candidateChoices, setCandidateChoices] = useState<EntityCandidate[]>([]);
  const [vehicleArtifact, setVehicleArtifact] = useState<VehicleSearchResult | null>(null);
  const [vendorArtifact, setVendorArtifact] = useState<VendorArtifact | null>(null);
  const [activeBriefKind, setActiveBriefKind] = useState<"vendor" | "vehicle" | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [openingDossierFor, setOpeningDossierFor] = useState<string | null>(null);
  const [resumeIntent, setResumeIntent] = useState<ResumeIntent | null>(null);
  const [missionBrief, setMissionBrief] = useState<MissionBriefRecord | null>(null);
  const [lastUserInput, setLastUserInput] = useState("");
  const [pressureThreadVisible, setPressureThreadVisible] = useState(false);
  const [pressureThreadDismissed, setPressureThreadDismissed] = useState(false);
  const [threadScrollState, setThreadScrollState] = useState({
    canScrollUp: false,
    canScrollDown: false,
    atBottom: true,
  });
  const [isCompactViewport, setIsCompactViewport] = useState(() => window.innerWidth < 768);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const recentCases = useMemo(() => sortRecentCases(cases).slice(0, 6), [cases]);
  const hasThreadDepth = messages.length > INITIAL_MESSAGES.length || candidateChoices.length > 0 || Boolean(vehicleArtifact || vendorArtifact || errorText);
  const hasArtifactStage = Boolean(vehicleArtifact || vendorArtifact);
  const isDisambiguatingEntity = candidateChoices.length > 0;
  const isClarifyingIntake = !isDisambiguatingEntity && Boolean(session.pendingFollowUp);
  const pressureThreadOptions = useMemo(() => pressureOptionsForSession(session), [session]);
  const activeBriefView = useMemo<FrontPorchBriefViewModel | null>(() => {
    if (activeBriefKind === "vendor" && vendorArtifact) {
      return buildVendorBriefViewModel(vendorArtifact);
    }
    if (activeBriefKind === "vehicle" && vehicleArtifact) {
      return buildVehicleBriefViewModel(vehicleArtifact, session);
    }
    return null;
  }, [activeBriefKind, session, vendorArtifact, vehicleArtifact]);
  const roomStatusText = isDisambiguatingEntity
    ? "AXIOM is narrowing the entity in frame."
    : isClarifyingIntake
      ? "AXIOM is tightening the brief before it starts."
    : isWorking
      ? PROGRESS_LINES[progressIndex]
      : "AXIOM will ask only what it needs to start.";
  const composerSupportText = isDisambiguatingEntity
    ? "Pick the right entity or ask one separating question. AXIOM will stay on the same thread."
    : isClarifyingIntake
      ? "Answer the question in plain language. AXIOM will treat the next turn as part of the same brief."
    : isWorking
      ? "AXIOM is working this pass. When it returns, you can redirect or press deeper."
      : "You can be messy. AXIOM will narrow it from there and ask only what changes the work.";
  const clarifyingLabel = clarifyingFollowUpLabel(session.pendingFollowUp);

  const appendMessage = useCallback((role: MessageRole, content: string) => {
    setMessages((current) => [...current, { id: nextId(role), role, content }]);
  }, []);

  const resetArtifacts = useCallback(() => {
    setCandidateChoices([]);
    setResolution(null);
    setVehicleArtifact(null);
    setVendorArtifact(null);
    setActiveBriefKind(null);
    setErrorText(null);
  }, []);

  const askFollowUp = useCallback((nextSession: IntakeSession, message: string, pendingFollowUp: PendingFollowUp) => {
    setSession({
      ...nextSession,
      followUpCount: nextSession.followUpCount + 1,
      pendingFollowUp,
    });
    appendMessage("axiom", message);
  }, [appendMessage]);

  useEffect(() => {
    composerRef.current?.focus();
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const handleChange = (event: MediaQueryListEvent) => setIsCompactViewport(event.matches);
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  const syncThreadScrollState = useCallback(() => {
    const el = messageListRef.current;
    if (!el) return;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    setThreadScrollState({
      canScrollUp: el.scrollTop > 8,
      canScrollDown: remaining > 8,
      atBottom: remaining <= 8,
    });
  }, []);

  useEffect(() => {
    const el = messageListRef.current;
    if (!el) return;
    if (isWorking || threadScrollState.atBottom) {
      el.scrollTop = el.scrollHeight;
    }
    window.requestAnimationFrame(syncThreadScrollState);
  }, [isWorking, messages, syncThreadScrollState, threadScrollState.atBottom]);

  useEffect(() => {
    if (!isWorking) return undefined;
    const timer = window.setInterval(() => {
      setProgressIndex((current) => (current + 1) % PROGRESS_LINES.length);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [isWorking]);

  useEffect(() => {
    if (!isWorking) {
      setPressureThreadVisible(false);
      setPressureThreadDismissed(false);
      return undefined;
    }
    if (pressureThreadDismissed || (session.priorityFocus && session.priorityFocus !== "full_picture")) {
      setPressureThreadVisible(false);
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setPressureThreadVisible(true);
    }, FRONT_PORCH_PRESSURE_THREAD_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [isWorking, pressureThreadDismissed, session.priorityFocus]);

  useEffect(() => {
    if (activeBriefKind === "vendor" && !vendorArtifact) {
      setActiveBriefKind(null);
    }
    if (activeBriefKind === "vehicle" && !vehicleArtifact) {
      setActiveBriefKind(null);
    }
  }, [activeBriefKind, vendorArtifact, vehicleArtifact]);

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

  const buildAegisIntent = useCallback(() => {
    if (session.objectType === "vehicle") {
      const targetEntity = session.incumbentPrime || session.vehicleName || "";
      const domainFocus = humanizePriorityFocus(session.priorityFocus) || "vehicle pressure";
      if (!targetEntity) return null;
      return {
        targetEntity,
        vehicleName: session.vehicleName || undefined,
        domainFocus,
        seedLabel: session.vehicleName || targetEntity,
        autoRun: true,
      };
    }
    if (session.objectType === "vendor") {
      const targetEntity = vendorArtifact?.title || session.vendorName || "";
      if (!targetEntity) return null;
      return {
        targetEntity,
        domainFocus: humanizePriorityFocus(session.priorityFocus) || undefined,
        seedLabel: targetEntity,
        autoRun: Boolean(isWorking || vendorArtifact || workingCaseId),
      };
    }
    return null;
  }, [isWorking, session, vendorArtifact, workingCaseId]);

  const persistMissionBrief = useCallback(async (
    nextSession: IntakeSession,
    options: {
      caseId?: string | null;
      status?: string;
      readiness?: VendorBriefReadiness | null;
      room?: MissionBriefRoom;
    } = {},
  ) => {
    if (loginRequired) {
      return missionBrief ?? null;
    }
    const payload = buildMissionBriefPayload(nextSession, lastUserInput, options);
    try {
      const saved = missionBrief?.id
        ? await updateMissionBrief(missionBrief.id, payload)
        : await createMissionBrief(payload);
      setMissionBrief(saved);
      return saved;
    } catch {
      return null;
    }
  }, [lastUserInput, loginRequired, missionBrief]);

  const openAegis = useCallback(() => {
    if (loginRequired) {
      onRequestLogin?.();
      return;
    }
    const intent = buildAegisIntent();
    if (intent) {
      onOpenAegisIntent?.(intent);
    }
    if (missionBrief) {
      void persistMissionBrief(session, { room: "aegis", status: missionBrief.case_id ? "working" : "scoped" });
    }
    onNavigate("axiom");
  }, [buildAegisIntent, loginRequired, missionBrief, onNavigate, onOpenAegisIntent, onRequestLogin, persistMissionBrief, session]);

  const handoffToLogin = useCallback((kind: ResumeIntent["kind"], nextSession: IntakeSession, message: string) => {
    setResumeIntent({ kind, session: nextSession });
    setIsWorking(false);
    setErrorText(null);
    appendMessage("axiom", message);
    onRequestLogin?.();
  }, [appendMessage, onRequestLogin]);

  const handlePressureThread = useCallback((focus: PriorityFocus) => {
    const nextSession = { ...session, priorityFocus: focus };
    setSession(nextSession);
    void persistMissionBrief(nextSession, { status: isWorking ? "working" : "scoped" });
    setPressureThreadDismissed(true);
    setPressureThreadVisible(false);
    if (vendorArtifact?.phase === "warming") {
      setVendorArtifact(buildVendorArtifact(null, nextSession, "warming", vendorArtifact.caseId, vendorArtifact.title));
    }
    const lead = humanizePriorityFocus(focus) || "that thread";
    appendMessage("axiom", `Understood. I’ll weight ${lead} first while I work the full picture.`);
  }, [appendMessage, isWorking, persistMissionBrief, session, vendorArtifact]);

  const loadVendorReadiness = useCallback(async (caseId: string): Promise<VendorBriefReadiness> => {
    const [enrichmentResult, passportResult, graphResult, networkRiskResult] = await Promise.allSettled([
      fetchEnrichment(caseId),
      fetchSupplierPassport(caseId),
      fetchCaseGraph(caseId, 2),
      fetchCaseNetworkRisk(caseId),
    ]);

    return {
      enrichment: enrichmentResult.status === "fulfilled" ? enrichmentResult.value : null,
      passport: passportResult.status === "fulfilled" ? passportResult.value : null,
      graph: graphResult.status === "fulfilled" ? graphResult.value : null,
      networkRisk: networkRiskResult.status === "fulfilled" ? networkRiskResult.value : null,
      axiomGapClosure: null,
    };
  }, []);

  const runVendorGapClosure = useCallback(async (
    caseId: string,
    subject: string,
    nextSession: IntakeSession,
    readiness: VendorBriefReadiness,
    options: {
      passIndex?: number;
      escalated?: boolean;
    } = {},
  ) => {
    try {
      const response = await runAxiomSearchIngest({
        prime_contractor: subject,
        vehicle_name: nextSession.vehicleName || undefined,
        context: buildGapClosureContext(nextSession, subject, readiness, options),
        vendor_id: caseId,
      });
      return {
        status: "completed" as const,
        passes: options.passIndex ?? 1,
        entitiesFound: response.entities?.length ?? 0,
        relationshipsFound: response.relationships?.length ?? 0,
        gapCount: response.intelligence_gaps?.length ?? 0,
        note: options.escalated
          ? "AXIOM escalated the weak edge after the first pressure pass stayed thin."
          : "AXIOM pressured the thinnest thread before the brief froze.",
        gapHighlights: (response.intelligence_gaps ?? [])
          .map((gap) => gap.description || gap.gap_type || "")
          .filter(Boolean)
          .slice(0, 3),
      };
    } catch (error) {
  const message = humanizeApiError(error, "The AXIOM pressure pass did not close the weak edge cleanly.");
      return {
        status: "failed" as const,
        passes: options.passIndex ?? 1,
        entitiesFound: 0,
        relationshipsFound: 0,
        gapCount: 0,
        note: message,
      };
    }
  }, []);

  const hydrateReturnedVendorBrief = useCallback(async (
    caseId: string,
    nextSession: IntakeSession,
    subjectOverride?: string,
  ) => {
  const subject = subjectOverride || nextSession.vendorName || "Entity brief";
    let readiness = await loadVendorReadiness(caseId);
    let gapClosureMessageSent = false;
    let gapClosure: VendorBriefReadiness["axiomGapClosure"] = null;

    if (shouldPressureVendorReadiness(readiness)) {
      gapClosureMessageSent = true;
      appendMessage("axiom", "The first pass is still thin. I’m using the graph and an AXIOM pressure pass to close the weakest gap before I freeze the brief.");
      gapClosure = await runVendorGapClosure(caseId, subject, nextSession, readiness, { passIndex: 1 });
      readiness = {
        ...(await loadVendorReadiness(caseId)),
        axiomGapClosure: gapClosure,
      };
      if (shouldEscalateVendorGapClosure(readiness, gapClosure)) {
        appendMessage("axiom", "One weak edge still is not holding. I’m going back through it once more with the graph in hand before I freeze the brief.");
        const escalatedClosure = await runVendorGapClosure(caseId, subject, nextSession, readiness, {
          passIndex: 2,
          escalated: true,
        });
        const refreshedReadiness = await loadVendorReadiness(caseId);
        gapClosure = mergeVendorGapClosures(gapClosure, escalatedClosure, refreshedReadiness);
        readiness = {
          ...refreshedReadiness,
          axiomGapClosure: gapClosure,
        };
      }
      if (gapClosure?.status === "failed") {
        appendMessage("axiom", "The pressure pass did not close the weak edge cleanly. I’m freezing the brief with the ambiguity explicit instead of bluffing past it.");
      }
    }

    setIsWorking(false);
    setVendorArtifact(buildReturnedVendorArtifact(nextSession, caseId, subject, readiness));
    void persistMissionBrief(nextSession, {
      caseId,
      status: "brief_ready",
      readiness,
    });
    appendMessage(
      "axiom",
      gapClosureMessageSent && readiness.axiomGapClosure?.status === "completed"
        ? `The returned brief is ready. I used the graph and ${readiness.axiomGapClosure.passes > 1 ? `${readiness.axiomGapClosure.passes} AXIOM pressure passes` : "an AXIOM pressure pass"} to tighten the weak edge before freezing it.`
        : `The returned brief is ready. Open it here, or step into ${DEEP_ROOM_NAME} if you want to challenge the weak edge.`,
    );
  }, [appendMessage, loadVendorReadiness, persistMissionBrief, runVendorGapClosure]);

  const handleEnrichmentComplete = useCallback(() => {
    if (!workingCaseId) return;
    void hydrateReturnedVendorBrief(
      workingCaseId,
      vendorArtifact?.title ? { ...session, vendorName: vendorArtifact.title } : session,
      vendorArtifact?.title,
    );
  }, [hydrateReturnedVendorBrief, session, vendorArtifact, workingCaseId]);

  const startCaseCreation = useCallback(async (candidate: EntityCandidate | null, nextSession: IntakeSession) => {
    const payload = buildCasePayload(candidate, nextSession);
    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);

    try {
      const created = await createCase(payload);
      setWorkingCaseId(created.case_id);
      setVendorArtifact(buildVendorArtifact(candidate, nextSession, "warming", created.case_id));
      void persistMissionBrief(nextSession, {
        caseId: created.case_id,
        status: "working",
      });
    } catch (error) {
      setIsWorking(false);
      const message = humanizeApiError(error, "Unable to open the vendor assessment.");
      setErrorText(message);
      appendMessage("axiom", "I could not open the assessment cleanly. Stay here and I will let you retry without losing the thread.");
    }
  }, [appendMessage, persistMissionBrief]);

  const handleCandidateChoice = useCallback(async (candidate: EntityCandidate) => {
    setCandidateChoices([]);
    if (resolution?.request_id && candidate.candidate_id) {
      void submitResolveFeedback(
        resolution.request_id,
        candidate.candidate_id,
        resolution.recommended_candidate_id === candidate.candidate_id,
      ).catch(() => undefined);
    }
    appendMessage("axiom", `Good. I’m taking ${candidate.legal_name} as the working entity unless you redirect me.`);
    await startCaseCreation(candidate, session);
  }, [appendMessage, resolution, session, startCaseCreation]);

  const startVendorFlow = useCallback(async (nextSession: IntakeSession) => {
    const name = compactText(nextSession.vendorName || "");
    if (!name) {
      appendMessage("axiom", "Which vendor are we looking at?");
      return;
    }

    void persistMissionBrief(nextSession, { status: "scoped" });

    if (loginRequired) {
      handoffToLogin(
        "vendor",
        nextSession,
        `${buildVendorWorkingLead(nextSession)} Sign in and I’ll start the first picture without making you restate the brief.`.trim(),
      );
      return;
    }

    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);
    appendMessage(
      "axiom",
      humanizePriorityFocus(nextSession.priorityFocus)
        ? `${buildVendorWorkingLead(nextSession)} That is enough to start. I’ll work the full picture and weight ${humanizePriorityFocus(nextSession.priorityFocus)} first.`
        : `${buildVendorWorkingLead(nextSession)} That is enough to start. I’ll work the full picture and keep the thin parts explicit instead of narrowing too early.`.trim(),
    );

    try {
      const result = await resolveEntity(name, {
        use_ai: true,
        max_candidates: 6,
        context: nextSession.priorityFocus ? `Weight first: ${humanizePriorityFocus(nextSession.priorityFocus) || "full picture"}` : undefined,
      });
      setIsWorking(false);
      setResolution(result.resolution || null);

      const recommendedCandidate =
        result.resolution?.status === "recommended"
          ? result.candidates.find((candidate) => candidate.candidate_id === result.resolution?.recommended_candidate_id) ?? null
          : null;

      if (recommendedCandidate) {
        appendMessage("axiom", `I believe you mean ${recommendedCandidate.legal_name}. I’m going to use that entity unless you redirect me.`);
        await startCaseCreation(recommendedCandidate, nextSession);
        return;
      }

      if (result.candidates.length > 1) {
        setCandidateChoices(result.candidates.slice(0, 4));
        appendMessage("axiom", "I found a few plausible matches. Pick the one you want me to work and I’ll take it from there.");
        return;
      }

      if (result.candidates.length === 1) {
        appendMessage("axiom", `I found a clean entity match on ${result.candidates[0].legal_name}. I’m opening the assessment from there.`);
        await startCaseCreation(result.candidates[0], nextSession);
        return;
      }

      appendMessage("axiom", "The entity resolution is still thin, but that is not a blocker. I’m opening the assessment from the provided name and keeping the ambiguity explicit.");
      await startCaseCreation(null, nextSession);
    } catch (error) {
      setIsWorking(false);
      const message = humanizeApiError(error, "Unable to resolve the vendor cleanly.");
      setErrorText(message);
      appendMessage("axiom", "The clean entity match did not hold. If you still want me to proceed, give me the vendor name again or add one more fact.");
    }
  }, [appendMessage, handoffToLogin, loginRequired, persistMissionBrief, startCaseCreation]);

  const startVehicleFlow = useCallback(async (nextSession: IntakeSession) => {
    const vehicleName = compactText(nextSession.vehicleName || "");
    if (!vehicleName) {
      appendMessage("axiom", "Which vehicle are we looking at?");
      return;
    }

    void persistMissionBrief(nextSession, { status: "scoped" });

    if (loginRequired) {
      handoffToLogin(
        "vehicle",
        nextSession,
        `${buildVehicleWorkingLead(nextSession)} Sign in and I’ll work the incumbent path and public ecosystem from there.`.trim(),
      );
      return;
    }

    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);
    appendMessage(
      "axiom",
      nextSession.incumbentPrime
        ? `${buildVehicleWorkingLead(nextSession)} That is enough to start. I’m going to work from ${vehicleName}, ${nextSession.incumbentPrime}'s incumbent position, and the likely transition path.`
        : `${buildVehicleWorkingLead(nextSession)} That is enough to start. I’m going to work from ${vehicleName} and build the public ecosystem picture from there.`,
    );

    try {
      const result = await searchContractVehicle(vehicleName);
      setIsWorking(false);
      setVehicleArtifact(result);
      void persistMissionBrief(nextSession, {
        status: "brief_ready",
      });
      appendMessage("axiom", `The first vehicle picture is in hand. ${summarizeVehicle(result, nextSession)}`);
    } catch (error) {
      const message = humanizeApiError(error, "Unable to search the vehicle right now.");
      const fallback = buildVehicleSearchFallback(nextSession, message);
      setIsWorking(false);
      setErrorText(null);
      setVehicleArtifact(fallback);
      void persistMissionBrief(nextSession, {
        status: "brief_ready",
      });
      appendMessage(
        "axiom",
        `The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand. ${summarizeVehicle(fallback, nextSession)}`,
      );
    }
  }, [appendMessage, handoffToLogin, loginRequired, persistMissionBrief]);

  const routeIntakeTurn = useCallback(async (
    text: string,
    options?: {
      current_object_type?: ObjectType | null;
      in_entity_narrowing?: boolean;
    },
  ) => {
    try {
      return await routeIntake(text, options);
    } catch {
      const fallback = inferObjectType(text);
      return {
        raw_input: text,
        winning_mode: fallback,
        confidence: fallback ? 0.5 : 0,
        clarifier_needed: !fallback,
        override_applied: false,
        anchor_text: compactText(text),
        hypotheses: [],
      };
    }
  }, []);

  useEffect(() => {
    if (loginRequired || !resumeIntent) return;
    const pending = resumeIntent;
    setResumeIntent(null);
    if (pending.kind === "vehicle") {
      void startVehicleFlow(pending.session);
      return;
    }
    void startVendorFlow(pending.session);
  }, [loginRequired, resumeIntent, startVendorFlow, startVehicleFlow]);

  const continueVehicleIntake = useCallback(async (nextSession: IntakeSession) => {
    const preparedSession = { ...nextSession, pendingFollowUp: null };
    setSession(preparedSession);

    const confidence = computeIntakeConfidence(preparedSession);

    if (!preparedSession.vehicleName) {
      askFollowUp(preparedSession, "Which contract vehicle are we looking at?", "vehicle_name");
      return;
    }
    if (!preparedSession.vehicleTiming) {
      askFollowUp(preparedSession, "Is this current, expired, or still in pre-solicitation?", "vehicle_timing");
      return;
    }
    if (
      preparedSession.followUpCount < FRONT_PORCH_MAX_FOLLOW_UPS &&
      confidence < FRONT_PORCH_START_CONFIDENCE &&
      preparedSession.vehicleTiming === "pre_solicitation" &&
      (preparedSession.followOn === null || !preparedSession.incumbentPrime)
    ) {
      askFollowUp(
        preparedSession,
        "Good. If this is a follow-on, do you know the incumbent prime? If not, I can still start from the vehicle.",
        "vehicle_follow_on_or_incumbent",
      );
      return;
    }
    if (
      preparedSession.followUpCount < FRONT_PORCH_MAX_FOLLOW_UPS &&
      confidence < FRONT_PORCH_SECOND_FOLLOW_UP_CONFIDENCE &&
      preparedSession.followOn === true &&
      !preparedSession.incumbentPrime
    ) {
      askFollowUp(
        preparedSession,
        "If you know who holds the prime position now, tell me. If not, I’ll keep the incumbent path open while I work.",
        "vehicle_incumbent_prime",
      );
      return;
    }

    await startVehicleFlow(preparedSession);
  }, [askFollowUp, startVehicleFlow]);

  const decideVehicleNext = useCallback(async (input: string, current: IntakeSession) => {
    const nextSession = { ...current };
    const stripped = compactText(stripObjectLabel(input));
    const lower = input.toLowerCase();

    if (!nextSession.vehicleName && stripped && !looksLikeObjectOnlyAnswer(input)) {
      nextSession.vehicleName = extractVehicleName(input) || stripped;
    }
    if (!nextSession.vehicleTiming) {
      const inferredTiming = inferVehicleTiming(input);
      if (inferredTiming) nextSession.vehicleTiming = inferredTiming;
    }
    if (nextSession.followOn === null && /\bfollow-on|follow on|net-new|net new\b/.test(lower)) {
      nextSession.followOn = inferBoolean(input);
    }
    if (!nextSession.incumbentPrime && stripped) {
      if (/\bprime\b/.test(lower) || nextSession.followOn === true || current.pendingFollowUp === "vehicle_follow_on_or_incumbent" || current.pendingFollowUp === "vehicle_incumbent_prime") {
        nextSession.incumbentPrime = extractPrimeName(input);
      }
    }
    if (nextSession.vehicleTiming === "pre_solicitation" && nextSession.incumbentPrime && nextSession.followOn === null) {
      nextSession.followOn = true;
    }
    await continueVehicleIntake(nextSession);
  }, [continueVehicleIntake]);

  const decideVendorNext = useCallback(async (input: string, current: IntakeSession) => {
    const nextSession = { ...current };
    const stripped = compactText(stripObjectLabel(input));

    if (!nextSession.vendorName && stripped && !looksLikeObjectOnlyAnswer(input)) {
      nextSession.vendorName = extractVendorName(input) || stripped;
    }
    if (!nextSession.priorityFocus) {
      const inferredFocus = inferPriorityFocus(input);
      if (inferredFocus) nextSession.priorityFocus = inferredFocus;
    }
    if (nextSession.supportLayer === "counterparty") {
      const inferredLayer = inferSupportLayer(input);
      if (inferredLayer) nextSession.supportLayer = inferredLayer;
    }

    setSession(nextSession);

    const confidence = computeIntakeConfidence(nextSession);

    if (!nextSession.vendorName) {
      askFollowUp(nextSession, "Which vendor are we looking at?", "vendor_name");
      return;
    }

    if (
      nextSession.followUpCount < FRONT_PORCH_MAX_FOLLOW_UPS &&
      confidence < FRONT_PORCH_START_CONFIDENCE &&
      !nextSession.priorityFocus
    ) {
      askFollowUp(
        nextSession,
        "If there’s one edge you want me to weight first, tell me now. Otherwise I’ll work the full picture.",
        "vendor_priority_focus",
      );
      return;
    }

    await startVendorFlow(nextSession);
  }, [askFollowUp, startVendorFlow]);

  const handleCandidateDisambiguationTurn = useCallback(async (text: string) => {
    if (candidateChoices.length === 0) return false;

    const routed = await routeIntakeTurn(text, {
      current_object_type: session.objectType,
      in_entity_narrowing: true,
    });
    if (shouldPivotToVehicle(routed)) {
      const correctedSession = buildVehicleCorrectionSession(session, text, routed);
      setCandidateChoices([]);
      setResolution(null);
      appendMessage("axiom", "Understood. That is a contract vehicle, not the entity set I was narrowing. I’m switching the frame.");
      await continueVehicleIntake(correctedSession);
      return true;
    }

    const matchedCandidate = matchCandidateChoiceFromText(text, candidateChoices);
    if (matchedCandidate) {
      await handleCandidateChoice(matchedCandidate);
      return true;
    }

    if (isCandidateRelationshipQuestion(text)) {
      const relationshipAnswer = inferCandidateRelationshipAnswer(candidateChoices);
      const recommendation = recommendCandidateFromChoices(candidateChoices, session);
      appendMessage(
        "axiom",
        recommendation.candidate
          ? `${relationshipAnswer} If you want me to keep moving, the strongest working candidate is ${recommendation.candidate.legal_name}.`
          : relationshipAnswer,
      );
      return true;
    }

    if (isCandidateRecommendationQuestion(text)) {
      const recommendation = recommendCandidateFromChoices(candidateChoices, session);
      if (recommendation.candidate) {
        const rationale = recommendation.rationale
          ? `${recommendation.rationale} `
          : "";
        const descriptor = describeCandidateForDisambiguation(recommendation.candidate);
        appendMessage(
          "axiom",
          `${rationale}${descriptor ? `That one reads as ${descriptor}. ` : ""}If that is the one you mean, say its name or pick the ${candidateChoiceIndexWord(
            candidateChoices.indexOf(recommendation.candidate),
          )} option.`,
        );
      } else {
        appendMessage("axiom", "I do not have a clean recommendation yet. Give me one fact that separates the entity you mean from the others.");
      }
      return true;
    }

    appendMessage(
      "axiom",
      "I still need the right entity in frame. Pick one of the candidates or give me one fact that separates the one you mean from the others.",
    );
    return true;
  }, [appendMessage, candidateChoices, continueVehicleIntake, handleCandidateChoice, routeIntakeTurn, session]);

  const handleUserTurn = useCallback(async (raw: string) => {
    const text = compactText(raw);
    if (!text || isWorking) return;

    setLastUserInput(text);
    appendMessage("user", text);

    if (candidateChoices.length > 0) {
      await handleCandidateDisambiguationTurn(text);
      return;
    }

    resetArtifacts();

    const routed = await routeIntakeTurn(text, {
      current_object_type: session.objectType,
      in_entity_narrowing: false,
    });
    const nextSession = applyPendingFollowUpAnswer(session, text);

    if ((session.objectType === "vendor" || nextSession.objectType === "vendor") && shouldPivotToVehicle(routed)) {
      const correctedSession = buildVehicleCorrectionSession(nextSession, text, routed);
      setCandidateChoices([]);
      setResolution(null);
      appendMessage("axiom", "Understood. That is a contract vehicle, not the vendor branch I had in frame. I’m switching the frame.");
      await continueVehicleIntake(correctedSession);
      return;
    }

    if ((session.objectType === "vehicle" || nextSession.objectType === "vehicle") && shouldPivotToVendor(routed, session.pendingFollowUp)) {
      const correctedSession = buildVendorCorrectionSession(nextSession, text, routed);
      appendMessage("axiom", "Understood. That is a specific vendor, not the contract-vehicle branch I had in frame. I’m switching the frame.");
      await decideVendorNext(text, correctedSession);
      return;
    }

    if (!nextSession.objectType || session.pendingFollowUp === "object_type") {
      const inferredObject = routed.clarifier_needed ? nextSession.objectType : routed.winning_mode || nextSession.objectType || inferObjectType(text);
      if (!inferredObject) {
        const seededSession = {
          ...nextSession,
          seedText: nextSession.seedText || compactText(routed.anchor_text || stripObjectLabel(text) || text) || null,
        };
        askFollowUp(seededSession, buildObjectTypeClarifier(text, routed), "object_type");
        return;
      }
      nextSession.objectType = inferredObject;
      if (inferredObject === "vendor") {
        nextSession.supportLayer = inferSupportLayer(text) || nextSession.supportLayer;
        nextSession.priorityFocus = inferPriorityFocus(text) || nextSession.priorityFocus;
      }
      setSession(nextSession);
    }

    if (nextSession.objectType === "vehicle") {
      await decideVehicleNext(text, nextSession);
      return;
    }

    await decideVendorNext(text, nextSession);
  }, [appendMessage, askFollowUp, candidateChoices.length, continueVehicleIntake, decideVehicleNext, decideVendorNext, handleCandidateDisambiguationTurn, isWorking, resetArtifacts, routeIntakeTurn, session]);

  const submitDraft = useCallback(async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await handleUserTurn(text);
  }, [draft, handleUserTurn]);

  const handleExample = useCallback(async (example: string) => {
    setMenu(null);
    setDraft("");
    void handleUserTurn(example);
  }, [handleUserTurn]);

  const shellBackground = `radial-gradient(circle at 18% 20%, ${T.accent}${O["12"]}, transparent 28%), radial-gradient(circle at 82% 18%, ${T.statusQualified}${O["12"]}, transparent 22%), linear-gradient(180deg, ${T.bg} 0%, #06080c 100%)`;

  const openArtifactDossier = useCallback(async (caseId: string) => {
    if (vendorArtifact?.phase !== "ready" || vendorArtifact.caseId !== caseId) {
      appendMessage("axiom", "The dossier is still warming. Let me finish the returned brief before I hand you the full artifact.");
      return;
    }
    if (loginRequired) {
      appendMessage("axiom", "Sign in and I’ll open the returned dossier in the same thread.");
      onRequestLogin?.();
      return;
    }
    setOpeningDossierFor(caseId);
    setErrorText(null);
    try {
      const data = await generateDossier(caseId);
      const url = data.download_url || `/api/dossiers/dossier-${caseId}.html`;
      const protectedUrl = await buildProtectedUrl(url);
      window.open(protectedUrl, "_blank");
    } catch (error) {
      const message = humanizeApiError(error, "The dossier is not ready to open yet.");
      setErrorText(message);
      appendMessage("axiom", "The dossier render hit a snag. The thread is still warm, and you can retry without losing the work.");
    } finally {
      setOpeningDossierFor(null);
    }
  }, [appendMessage, loginRequired, onRequestLogin, vendorArtifact]);

  return (
    <div
      style={{
        minHeight: "100%",
        height: "100%",
        background: shellBackground,
        color: T.text,
        padding: `${isCompactViewport ? SP.lg : SP.xl}px ${isCompactViewport ? SP.lg : PAD.spacious}px ${PAD.spacious}px`,
        overflowY: "auto",
        overflowX: "hidden",
      }}
    >
      <div
        style={{
          width: "min(1180px, 100%)",
          margin: "0 auto",
          minHeight: "100%",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          ref={menuRef}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: SP.lg,
            padding: `${SP.sm}px 0 ${isCompactViewport ? SP.xl : SP.xxxl}px`,
            position: "relative",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: SP.sm }}>
            <div style={{ fontSize: FS.md, fontWeight: 800, letterSpacing: "-0.04em" }}>Helios</div>
            <StatusPill tone="info">{STOA_NAME}</StatusPill>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: SP.sm, position: "relative", flexWrap: "wrap", justifyContent: isCompactViewport ? "flex-start" : "flex-end" }}>
            {!loginRequired ? (
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
            ) : null}
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
              onClick={openAegis}
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
              {DEEP_ROOM_NAME}
              <ArrowUpRight size={14} />
            </button>
            {loginRequired ? (
              <button
                type="button"
                onClick={() => onRequestLogin?.()}
                className="helios-focus-ring"
                style={{
                  border: `1px solid ${T.border}`,
                  background: "transparent",
                  color: T.textSecondary,
                  fontSize: FS.sm,
                  fontWeight: 700,
                  padding: PAD.default,
                  borderRadius: 999,
                  cursor: "pointer",
                }}
              >
                Sign in
              </button>
            ) : null}

            {menu === "recent" && !loginRequired ? (
              <div
                style={{
                  position: "absolute",
                  top: "calc(100% + 10px)",
                  right: 0,
                  width: isCompactViewport ? "min(calc(100vw - 32px), 380px)" : 320,
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
                  right: 0,
                  width: isCompactViewport ? "min(calc(100vw - 32px), 420px)" : 380,
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
            justifyContent: hasThreadDepth ? "flex-start" : "center",
            padding: `${SP.lg}px 0 ${SP.xxxl}px`,
            gap: SP.xl,
          }}
        >
          <div style={{ width: "min(860px, 100%)", display: "flex", flexDirection: "column", alignItems: "center", gap: SP.xl }}>
            <div style={{ display: "grid", justifyItems: "center", gap: SP.xs, textAlign: "center" }}>
              <SectionEyebrow>Brief AXIOM</SectionEyebrow>
              <p
                style={{
                  margin: 0,
                  fontSize: FS.md,
                  color: T.textSecondary,
                  lineHeight: 1.6,
                  maxWidth: 620,
                }}
              >
                Start with whatever you know. AXIOM will narrow the problem and ask only what changes the work.
              </p>
            </div>
            {activeBriefView ? (
              <FrontPorchBriefView
                artifact={activeBriefView}
                isCompactViewport={isCompactViewport}
                dossierLabel={
                  activeBriefView.kind === "vendor"
                    ? vendorArtifact?.phase === "ready"
                      ? "Read dossier"
                      : "Warming dossier"
                    : undefined
                }
                dossierDisabled={
                  activeBriefView.kind === "vendor"
                    ? vendorArtifact?.phase !== "ready" || openingDossierFor === vendorArtifact?.caseId
                    : true
                }
                dossierLoading={activeBriefView.kind === "vendor" ? openingDossierFor === vendorArtifact?.caseId : false}
                onBack={() => setActiveBriefKind(null)}
                onOpenAegis={openAegis}
                onOpenGraph={activeBriefView.kind === "vehicle" ? () => onNavigate("graph") : undefined}
                onOpenDossier={activeBriefView.kind === "vendor" && vendorArtifact
                  ? () => { void openArtifactDossier(vendorArtifact.caseId); }
                  : undefined}
              >
                {activeBriefView.kind === "vehicle" && vehicleArtifact && vehicleArtifact.unique_vendors.length > 0 ? (
                  <div style={{ display: "grid", gap: SP.sm }}>
                    <SectionEyebrow>Spin into assessment</SectionEyebrow>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                      {vehicleArtifact.unique_vendors.slice(0, 4).map((vendor) => (
                        <button
                          key={`${vendor.vendor_name}-${vendor.role}`}
                          type="button"
                          onClick={async () => {
                            setActiveBriefKind(null);
                            setVehicleArtifact(null);
                            const nextSession = {
                              ...session,
                              objectType: "vendor" as const,
                              vendorName: vendor.vendor_name,
                              priorityFocus: session.priorityFocus || "teammate_network",
                            };
                            setSession(nextSession);
                            appendMessage("user", `Open a vendor assessment on ${vendor.vendor_name}.`);
                            await startVendorFlow(nextSession);
                          }}
                          className="helios-focus-ring"
                          style={{
                            border: `1px solid rgba(255,255,255,0.08)`,
                            background: "rgba(255,255,255,0.04)",
                            color: T.text,
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
                  </div>
                ) : null}
              </FrontPorchBriefView>
            ) : (
              <>
            <div
              style={{
                width: "100%",
                borderRadius: 28,
                border: `1px solid rgba(255,255,255,0.08)`,
                background: "linear-gradient(180deg, rgba(10,13,20,0.88) 0%, rgba(8,10,16,0.9) 100%)",
                boxShadow: "0 28px 80px rgba(0,0,0,0.28)",
                padding: isCompactViewport ? PAD.comfortable : PAD.spacious,
                display: "grid",
                gap: SP.lg,
                position: hasThreadDepth && !isCompactViewport && !hasArtifactStage ? "sticky" : "relative",
                top: hasThreadDepth && !isCompactViewport && !hasArtifactStage ? SP.lg : undefined,
                zIndex: hasThreadDepth && !isCompactViewport && !hasArtifactStage ? 6 : undefined,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.md, flexWrap: "wrap" }}>
                <div style={{ fontSize: FS.caption, color: T.textTertiary, letterSpacing: "0.12em", textTransform: "uppercase" }}>
                  AXIOM
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {clarifyingLabel ? <StatusPill tone="info">{clarifyingLabel}</StatusPill> : null}
                  <div style={{ fontSize: FS.sm, color: isWorking || isDisambiguatingEntity || isClarifyingIntake ? T.accent : T.textSecondary }}>
                    {roomStatusText}
                  </div>
                </div>
              </div>

              {pressureThreadVisible && pressureThreadOptions.length > 0 ? (
                <div
                  style={{
                    borderRadius: 22,
                    border: `1px solid rgba(255,255,255,0.06)`,
                    background: "rgba(255,255,255,0.025)",
                    padding: PAD.comfortable,
                    display: "grid",
                    gap: SP.sm,
                  }}
                >
                  <div style={{ display: "grid", gap: 6 }}>
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                      While I work the full picture, is there one thread you want me to weight first?
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>
                      You can skip this. AXIOM is already working the full picture.
                    </div>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
                    {pressureThreadOptions.map((focus) => (
                      <button
                        key={`pressure-thread-${focus}`}
                        type="button"
                        onClick={() => handlePressureThread(focus)}
                        className="helios-focus-ring"
                        style={{
                          border: `1px solid rgba(255,255,255,0.08)`,
                          background: "rgba(255,255,255,0.04)",
                          color: T.text,
                          borderRadius: 999,
                          padding: "10px 14px",
                          cursor: "pointer",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                      >
                        {humanizePriorityFocus(focus) || "Full picture"}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        setPressureThreadDismissed(true);
                        setPressureThreadVisible(false);
                      }}
                      className="helios-focus-ring"
                      style={{
                        border: "none",
                        background: "transparent",
                        color: T.textSecondary,
                        borderRadius: 999,
                        padding: "10px 14px",
                        cursor: "pointer",
                        fontSize: FS.sm,
                        fontWeight: 700,
                      }}
                    >
                      Keep working
                    </button>
                  </div>
                </div>
              ) : null}

              <div style={{ position: "relative" }}>
                {threadScrollState.canScrollUp ? (
                  <div
                    aria-hidden="true"
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      right: SP.xs,
                      height: 28,
                      background: "linear-gradient(180deg, rgba(8,10,16,0.96) 0%, rgba(8,10,16,0) 100%)",
                      pointerEvents: "none",
                      zIndex: 2,
                    }}
                  />
                ) : null}

                <div
                  ref={messageListRef}
                  aria-live="polite"
                  onScroll={syncThreadScrollState}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: SP.md,
                    maxHeight: isCompactViewport ? "min(44vh, 400px)" : "min(46vh, 520px)",
                    overflowY: "auto",
                    paddingRight: SP.xs,
                    paddingBottom: SP.sm,
                    scrollPaddingBottom: SP.xxxl,
                  }}
                >
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      style={{
                        alignSelf: message.role === "user" ? "flex-end" : "stretch",
                        maxWidth: message.role === "user" ? (isCompactViewport ? "92%" : "82%") : "100%",
                        marginLeft: message.role === "user" ? (isCompactViewport ? 20 : 72) : 0,
                        borderRadius: 24,
                        border: message.role === "status" ? "none" : `1px solid ${message.role === "user" ? `${T.accent}${O["20"]}` : "rgba(255,255,255,0.06)"}`,
                        background: message.role === "status"
                          ? "transparent"
                          : message.role === "user"
                            ? `${T.accent}${O["08"]}`
                            : "rgba(255,255,255,0.02)",
                        padding: message.role === "status" ? "2px 0" : `${SP.lg}px ${PAD.comfortable}`,
                        color: message.role === "status" ? T.accent : T.text,
                        fontSize: message.role === "status" ? FS.sm : FS.base,
                        lineHeight: 1.7,
                      }}
                    >
                      {message.content}
                    </div>
                  ))}
                </div>

                {threadScrollState.canScrollDown ? (
                  <div
                    aria-hidden="true"
                    style={{
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: SP.xs,
                      height: 34,
                      background: "linear-gradient(180deg, rgba(8,10,16,0) 0%, rgba(8,10,16,0.98) 100%)",
                      pointerEvents: "none",
                      zIndex: 2,
                    }}
                  />
                ) : null}
              </div>

              <div
                style={{
                  borderTop: `1px solid rgba(255,255,255,0.06)`,
                  paddingTop: SP.lg,
                  display: "grid",
                  gap: SP.md,
                  background: "linear-gradient(180deg, rgba(8,10,16,0.78) 0%, rgba(8,10,16,0.98) 32%)",
                  backdropFilter: "blur(16px)",
                }}
              >
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
                  placeholder="ILS 2. Pre-solicitation follow-on. Amentum is the incumbent."
                  aria-label="Brief AXIOM"
                  disabled={isWorking}
                  className="helios-focus-ring"
                  style={{
                    width: "100%",
                    minHeight: 72,
                    resize: "none",
                    border: "none",
                    outline: "none",
                    background: "transparent",
                    color: T.text,
                    fontSize: FS.md,
                    lineHeight: 1.55,
                    fontFamily: "inherit",
                    opacity: isWorking ? 0.75 : 1,
                    cursor: isWorking ? "not-allowed" : "text",
                  }}
                />
                <div style={{ display: "flex", flexDirection: isCompactViewport ? "column" : "row", alignItems: isCompactViewport ? "stretch" : "center", justifyContent: "space-between", gap: SP.md, flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexWrap: "wrap" }}>
                    <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>
                      {composerSupportText}
                    </div>
                    {threadScrollState.canScrollDown ? (
                      <button
                        type="button"
                        onClick={() => {
                          messageListRef.current?.scrollTo({ top: messageListRef.current.scrollHeight, behavior: "smooth" });
                        }}
                        className="helios-focus-ring"
                        style={{
                          border: `1px solid rgba(255,255,255,0.08)`,
                          background: "rgba(255,255,255,0.04)",
                          color: T.textSecondary,
                          borderRadius: 999,
                          padding: "8px 12px",
                          cursor: "pointer",
                          fontSize: FS.xs,
                          fontWeight: 700,
                        }}
                      >
                        Jump to latest
                      </button>
                    ) : null}
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
                      justifyContent: "center",
                      gap: SP.xs,
                      fontSize: FS.sm,
                      fontWeight: 800,
                      transition: `all ${MOTION.fast} ${MOTION.easing}`,
                      width: isCompactViewport ? "100%" : undefined,
                    }}
                  >
                    {isWorking ? <Loader2 size={14} className="animate-spin" /> : <MessageSquareText size={14} />}
                    {isWorking ? "Working this pass" : "Start the brief"}
                  </button>
                </div>
              </div>
            </div>

            {candidateChoices.length > 0 ? (
              <div style={{ width: "min(760px, 100%)", display: "grid", gap: SP.sm }}>
                <div
                  style={{
                    borderRadius: 18,
                    border: `1px solid ${T.border}`,
                    background: `${T.surface}`,
                    padding: PAD.comfortable,
                    display: "grid",
                    gap: SP.xs,
                  }}
                >
                  <SectionEyebrow>Entity narrowing</SectionEyebrow>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700 }}>
                    AXIOM has a few plausible entities in frame.
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.65 }}>
                    Pick one, or ask a separating question like “are any of these related?” or “which one looks most like the contractor?”
                  </div>
                </div>
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
                        {candidate.graph_signal_summary || candidate.graph_related_candidates?.[0]?.summary ? (
                          <div style={{ fontSize: FS.sm, color: T.accent, marginTop: SP.sm, lineHeight: 1.6 }}>
                            {candidate.graph_signal_summary || candidate.graph_related_candidates?.[0]?.summary}
                          </div>
                        ) : null}
                      </div>
                      <ChevronDown size={14} color={T.textTertiary} style={{ transform: "rotate(-90deg)" }} />
                    </div>
                  </button>
                ))}
              </div>
            ) : null}

            {vehicleArtifact ? (
              <div style={{ width: "min(760px, 100%)" }}>
                <BriefArtifact
                  surface="light"
                  eyebrow="Vehicle brief"
                  title={vehicleArtifact.vehicle_name}
                  framing={`The first public picture is ready. Open the brief view for the clean narrative, or move straight into ${DEEP_ROOM_NAME} if you want to pressure the weak edge.`}
                  sections={[
                    {
                      label: "Current read",
                      detail: summarizeVehicle(vehicleArtifact, session),
                    },
                  ]}
                  provenance={["Separate brief view", "Public vehicle picture", `${DEEP_ROOM_NAME} one move away`]}
                  note="The vehicle brief now has its own view so the conversation can stay clean."
                  actions={
                    <>
                      <button
                        type="button"
                        onClick={() => setActiveBriefKind("vehicle")}
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
                        Open brief
                      </button>
                      <button
                        type="button"
                        onClick={openAegis}
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
                        Enter {DEEP_ROOM_NAME}
                        <ExternalLink size={14} />
                      </button>
                    </>
                  }
                />
              </div>
            ) : null}

            {vendorArtifact ? (
              <div style={{ width: "min(760px, 100%)" }}>
                <BriefArtifact
                  surface="light"
                  eyebrow={vendorArtifact.phase === "ready" ? "Returned brief" : "Working brief"}
                  title={vendorArtifact.title}
                  framing={vendorArtifact.phase === "ready"
                    ? `The first returned brief is ready. Open the brief view for the clean narrative, or step into ${DEEP_ROOM_NAME} if you want to challenge the weak edge.`
                    : "The working brief is open in its own view while AXIOM warms the dossier and keeps the thin parts explicit."}
                  sections={[
                    {
                      label: "Current posture",
                      detail: vendorArtifact.sections[0]?.detail ?? vendorArtifact.framing,
                    },
                  ]}
                  provenance={vendorArtifact.phase === "ready"
                    ? ["Returned brief ready", "Separate brief view", `${DEEP_ROOM_NAME} one move away`]
                    : ["Working brief warming", "Conversation stays primary", "Dossier still under pressure"]}
                  note="The brief now has its own view so the thread and the artifact stop competing with each other."
                  actions={
                    <>
                      <button
                        type="button"
                        onClick={() => setActiveBriefKind("vendor")}
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
                        {vendorArtifact.phase === "ready" ? "Open returned brief" : "Open working brief"}
                      </button>
                      <button
                        type="button"
                        onClick={openAegis}
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
                        Enter {DEEP_ROOM_NAME}
                        <ExternalLink size={14} />
                      </button>
                    </>
                  }
                />
              </div>
            ) : null}

            {errorText ? (
              <div style={{ width: "min(760px, 100%)" }}>
                <InlineMessage tone="danger" title={`${STOA_NAME} hit a problem`} message={errorText} />
              </div>
            ) : null}
              </>
            )}
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
