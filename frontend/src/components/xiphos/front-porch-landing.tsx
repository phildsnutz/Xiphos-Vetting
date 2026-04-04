import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChevronDown, ExternalLink, Loader2, MessageSquareText } from "lucide-react";
import {
  fetchCaseGraph,
  fetchCaseNetworkRisk,
  fetchEnrichment,
  fetchSupplierPassport,
  buildProtectedUrl,
  createCase,
  generateDossier,
  resolveEntity,
  runAxiomSearchIngest,
  searchContractVehicle,
  submitResolveFeedback,
  type EnrichmentReport,
  type EntityCandidate,
  type EntityResolution,
  type NetworkRiskResult,
  type SupplierPassport,
  type VehicleSearchResult,
  type CaseGraphData,
} from "@/lib/api";
import type { VettingCase } from "@/lib/types";
import { EnrichmentStream } from "./enrichment-stream";
import { FrontPorchBriefView, type FrontPorchBriefViewModel } from "./front-porch-brief-view";
import { BriefArtifact, InlineMessage, SectionEyebrow, StatusPill } from "./shell-primitives";
import { T, FS, SP, PAD, O, MOTION } from "@/lib/tokens";

type RoomMenu = "recent" | "examples" | null;
type ObjectType = "vendor" | "vehicle";
type SupportLayer = "counterparty" | "cyber" | "export";
type VehicleTiming = "current" | "expired" | "pre_solicitation";
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
  onOpenWarRoomIntent?: (intent: {
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
  priorityFocus: PriorityFocus | null;
  supportLayer: SupportLayer;
  vehicleTiming: VehicleTiming | null;
  followOn: boolean | null;
  incumbentPrime: string | null;
  followUpCount: number;
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
    entitiesFound: number;
    relationshipsFound: number;
    gapCount: number;
    note: string;
  } | null;
}

type ResumeIntent =
  | { kind: "vendor"; session: IntakeSession }
  | { kind: "vehicle"; session: IntakeSession };

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

function cleanEntityFragment(value: string) {
  return compactText(value)
    .replace(/^[,:;\-\s]+/, "")
    .replace(/[?.,]+$/, "")
    .trim();
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
    let score = 0.18;
    if (session.vendorName) score += 0.4;
    if (session.priorityFocus) score += session.priorityFocus === "full_picture" ? 0.1 : 0.24;
    if (session.supportLayer !== "counterparty") score += 0.12;
    return Math.min(1, score);
  }

  return 0;
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
        ? `Spin the right vendor out of ${result.vehicle_name} into assessment, or step into War Room if you need to work the weak points directly.`
        : `Step into War Room if the public picture is still too thin to act on cleanly.`,
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
  const subject = subjectOverride ?? candidate?.legal_name ?? session.vendorName ?? "Vendor assessment";
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
      ? `The first returned brief is ready. AXIOM kept the strongest holds visible and left the real ambiguity explicit.`
      : `AXIOM is warming the first picture around ${subject} without pretending the thin parts are settled.`,
    sections: [
      {
        label: "What I found",
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
        label: "Supporting thread",
        detail: supportLayerDetail(session),
      },
    ],
    note: phase === "ready"
      ? "Read the clean narrative here. Step into War Room when you want to challenge the picture or pull a harder thread."
      : "The working case is open and warming. If you want the trail instead of the summary, step into War Room.",
    provenance: phase === "ready"
      ? ["Resolution-backed", "Initial graph context", "Public record only"]
      : ["Entity resolution", "Warm graph context", "Public record only"],
  };
}

function shouldPressureVendorReadiness(readiness: VendorBriefReadiness) {
  const findingsTotal = readiness.enrichment?.summary?.findings_total ?? readiness.passport?.identity.findings_total ?? 0;
  const connectorsWithData = readiness.enrichment?.summary?.connectors_with_data ?? readiness.passport?.identity.connectors_with_data ?? 0;
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  const thinGraph = Boolean(readiness.passport?.graph.intelligence?.thin_graph);

  const thinSignals = [
    findingsTotal < 2,
    connectorsWithData < 2,
    relationshipCount < 2,
    thinGraph,
    controlPathCount === 0,
  ].filter(Boolean).length;

  return thinSignals >= 2;
}

function buildGapClosureContext(
  session: IntakeSession,
  subject: string,
  readiness: VendorBriefReadiness,
) {
  const context: string[] = [
    `Front Porch returned brief warming for ${subject}.`,
    "Work the full entity picture and close the thinnest public-data gap before the brief freezes.",
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
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  if (controlPathCount > 0) {
    context.push(`There are ${controlPathCount} control path${controlPathCount === 1 ? "" : "s"} already visible in the graph.`);
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
  const connectorsRun = readiness.enrichment?.summary?.connectors_run ?? 0;
  const relationshipCount = readiness.graph?.relationship_count ?? readiness.passport?.graph.relationship_count ?? 0;
  const controlPathCount = readiness.passport?.graph.control_paths.length ?? 0;
  const networkRiskLevel = String(readiness.networkRisk?.network_risk_level || "").toUpperCase();
  const graphIntelligence = readiness.passport?.graph.intelligence;
  const dominantEdgeFamily = String(graphIntelligence?.dominant_edge_family || "").replace(/_/g, " ");
  const gapClosure = readiness.axiomGapClosure;

  const whatHolds = connectorsWithData > 0 || findingsTotal > 0
    ? `${connectorsWithData} of ${connectorsRun || connectorsWithData} sources produced data and ${findingsTotal} finding${findingsTotal === 1 ? "" : "s"} survived into the first picture.`
    : "The public record stayed unusually thin, so the brief is carrying the strongest visible holds without pretending the surface picture is complete.";

  const graphDetail = relationshipCount > 0
    ? `${relationshipCount} graph relationship${relationshipCount === 1 ? "" : "s"} and ${controlPathCount} control path${controlPathCount === 1 ? "" : "s"} are now informing the brief${dominantEdgeFamily ? `, with ${dominantEdgeFamily} as the dominant edge family.` : "."}`
    : "The graph is still thin enough that silence should not be treated as comfort.";

  const gapDetail = gapClosure?.status === "completed"
    ? `AXIOM ran a second pass against the weak edge and surfaced ${gapClosure.entitiesFound} entities, ${gapClosure.relationshipsFound} relationships, and ${gapClosure.gapCount} residual gap${gapClosure.gapCount === 1 ? "" : "s"}.`
    : gapClosure?.status === "failed"
      ? gapClosure.note
      : "AXIOM did not need a second pass because the first picture already had enough structure to freeze the brief honestly.";

  return {
    caseId,
    phase: "ready",
    title: subject,
    eyebrow: "Returned brief",
    framing: gapClosure?.status === "completed"
      ? "The returned brief is ready. AXIOM used enrichment, graph relationships, and a second gap-closing pass before freezing the picture."
      : "The returned brief is ready. AXIOM used enrichment and the current graph relationships before freezing the picture.",
    sections: [
      {
        label: "What holds",
        detail: weightedFirst ? `${whatHolds} ${weightedFirst} stayed weighted first without shrinking the scope.` : whatHolds,
        tone: findingsTotal > 0 ? "success" : "warning",
      },
      {
        label: "Graph pressure",
        detail: networkRiskLevel && networkRiskLevel !== "NONE"
          ? `${graphDetail} Network risk is currently ${networkRiskLevel.toLowerCase().replace(/_/g, " ")}.`
          : graphDetail,
        tone: relationshipCount > 0 ? "info" : "warning",
      },
      {
        label: "Gap closure",
        detail: gapDetail,
        tone: gapClosure?.status === "failed" ? "warning" : "neutral",
      },
    ],
    note: gapClosure?.status === "completed"
      ? "Read the clean narrative here. Step into War Room when you want to challenge what still stayed thin after the second pass."
      : "Read the clean narrative here. Step into War Room when you want to challenge the weak edge directly.",
    provenance: [
      `${connectorsWithData} sources with data`,
      relationshipCount > 0 ? `${relationshipCount} graph relationships` : "Graph still thin",
      gapClosure?.status === "completed" ? "AXIOM second pass" : "Single-pass public picture",
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
    note: "Stay in this room for the clean public picture. Step into War Room or Graph when you want to press the weak edge instead of just reading it.",
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
  onOpenWarRoomIntent,
  onRequestLogin,
}: FrontPorchLandingProps) {
  const [menu, setMenu] = useState<RoomMenu>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>(INITIAL_MESSAGES);
  const [session, setSession] = useState<IntakeSession>({
    objectType: null,
    vendorName: null,
    vehicleName: null,
    priorityFocus: null,
    supportLayer: "counterparty",
    vehicleTiming: null,
    followOn: null,
    incumbentPrime: null,
    followUpCount: 0,
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

  const askFollowUp = useCallback((nextSession: IntakeSession, message: string) => {
    setSession({ ...nextSession, followUpCount: nextSession.followUpCount + 1 });
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

  const buildWarRoomIntent = useCallback(() => {
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

  const openWarRoom = useCallback(() => {
    if (loginRequired) {
      onRequestLogin?.();
      return;
    }
    const intent = buildWarRoomIntent();
    if (intent) {
      onOpenWarRoomIntent?.(intent);
    }
    onNavigate("axiom");
  }, [buildWarRoomIntent, loginRequired, onNavigate, onOpenWarRoomIntent, onRequestLogin]);

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
    setPressureThreadDismissed(true);
    setPressureThreadVisible(false);
    if (vendorArtifact?.phase === "warming") {
      setVendorArtifact(buildVendorArtifact(null, nextSession, "warming", vendorArtifact.caseId, vendorArtifact.title));
    }
    const lead = humanizePriorityFocus(focus) || "that thread";
    appendMessage("axiom", `Understood. I’ll weight ${lead} first while I work the full picture.`);
  }, [appendMessage, session, vendorArtifact]);

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
  ) => {
    try {
      const response = await runAxiomSearchIngest({
        prime_contractor: subject,
        vehicle_name: nextSession.vehicleName || undefined,
        context: buildGapClosureContext(nextSession, subject, readiness),
        vendor_id: caseId,
      });
      return {
        status: "completed" as const,
        entitiesFound: response.entities?.length ?? 0,
        relationshipsFound: response.relationships?.length ?? 0,
        gapCount: response.intelligence_gaps?.length ?? 0,
        note: "AXIOM pressured the thinnest thread before the brief froze.",
      };
    } catch (error) {
      const message = humanizeApiError(error, "The second AXIOM pass did not close the weak edge cleanly.");
      return {
        status: "failed" as const,
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
    const subject = subjectOverride || nextSession.vendorName || "Vendor assessment";
    let readiness = await loadVendorReadiness(caseId);
    let gapClosureMessageSent = false;

    if (shouldPressureVendorReadiness(readiness)) {
      gapClosureMessageSent = true;
      appendMessage("axiom", "The first pass is still thin. I’m using the graph and a second AXIOM pass to close the weakest gap before I freeze the brief.");
      const gapClosure = await runVendorGapClosure(caseId, subject, nextSession, readiness);
      readiness = {
        ...(await loadVendorReadiness(caseId)),
        axiomGapClosure: gapClosure,
      };
      if (gapClosure.status === "failed") {
        appendMessage("axiom", "The second pass did not close the weak edge cleanly. I’m freezing the brief with the ambiguity explicit instead of bluffing past it.");
      }
    }

    setIsWorking(false);
    setVendorArtifact(buildReturnedVendorArtifact(nextSession, caseId, subject, readiness));
    appendMessage(
      "axiom",
      gapClosureMessageSent && readiness.axiomGapClosure?.status === "completed"
        ? "The returned brief is ready. I used the graph and a second AXIOM pass to tighten the weak edge before freezing it."
        : "The returned brief is ready. Open it here, or step into War Room if you want to challenge the weak edge.",
    );
  }, [appendMessage, loadVendorReadiness, runVendorGapClosure]);

  const handleEnrichmentComplete = useCallback(() => {
    if (!workingCaseId) return;
    void hydrateReturnedVendorBrief(
      workingCaseId,
      vendorArtifact?.title ? { ...session, vendorName: vendorArtifact.title } : session,
      vendorArtifact?.title,
    );
  }, [hydrateReturnedVendorBrief, session, vendorArtifact, workingCaseId]);

  const startCaseCreation = useCallback(async (candidate: EntityCandidate | null) => {
    const payload = buildCasePayload(candidate, session);
    setIsWorking(true);
    setProgressIndex(0);
    setErrorText(null);

    try {
      const created = await createCase(payload);
      setWorkingCaseId(created.case_id);
      setVendorArtifact(buildVendorArtifact(candidate, session, "warming", created.case_id));
    } catch (error) {
      setIsWorking(false);
      const message = humanizeApiError(error, "Unable to open the vendor assessment.");
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
    appendMessage("axiom", `Good. I’m taking ${candidate.legal_name} as the working entity unless you redirect me.`);
    await startCaseCreation(candidate);
  }, [appendMessage, resolution, startCaseCreation]);

  const startVendorFlow = useCallback(async (nextSession: IntakeSession) => {
    const name = compactText(nextSession.vendorName || "");
    if (!name) {
      appendMessage("axiom", "Which vendor are we looking at?");
      return;
    }

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
        await startCaseCreation(recommendedCandidate);
        return;
      }

      if (result.candidates.length > 1) {
        setCandidateChoices(result.candidates.slice(0, 4));
        appendMessage("axiom", "I found a few plausible matches. Pick the one you want me to work and I’ll take it from there.");
        return;
      }

      if (result.candidates.length === 1) {
        appendMessage("axiom", `I found a clean entity match on ${result.candidates[0].legal_name}. I’m opening the assessment from there.`);
        await startCaseCreation(result.candidates[0]);
        return;
      }

      appendMessage("axiom", "The entity resolution is still thin, but that is not a blocker. I’m opening the assessment from the provided name and keeping the ambiguity explicit.");
      await startCaseCreation(null);
    } catch (error) {
      setIsWorking(false);
      const message = humanizeApiError(error, "Unable to resolve the vendor cleanly.");
      setErrorText(message);
      appendMessage("axiom", "The clean entity match did not hold. If you still want me to proceed, give me the vendor name again or add one more fact.");
    }
  }, [appendMessage, handoffToLogin, loginRequired, startCaseCreation]);

  const startVehicleFlow = useCallback(async (nextSession: IntakeSession) => {
    const vehicleName = compactText(nextSession.vehicleName || "");
    if (!vehicleName) {
      appendMessage("axiom", "Which vehicle are we looking at?");
      return;
    }

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
      appendMessage("axiom", `The first vehicle picture is in hand. ${summarizeVehicle(result, nextSession)}`);
    } catch (error) {
      setIsWorking(false);
      const message = humanizeApiError(error, "Unable to search the vehicle right now.");
      setErrorText(message);
      appendMessage("axiom", "The vehicle search did not come back cleanly. Stay here and either refine the vehicle name or send me one more identifying detail.");
    }
  }, [appendMessage, handoffToLogin, loginRequired]);

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
      if (/\bprime\b/.test(lower) || nextSession.followOn === true) {
        nextSession.incumbentPrime = extractPrimeName(input);
      }
    }

    setSession(nextSession);

    const confidence = computeIntakeConfidence(nextSession);

    if (!nextSession.vehicleName) {
      askFollowUp(nextSession, "Which contract vehicle are we looking at?");
      return;
    }
    if (!nextSession.vehicleTiming) {
      askFollowUp(nextSession, "Is this current, expired, or still in pre-solicitation?");
      return;
    }
    if (
      nextSession.followUpCount < FRONT_PORCH_MAX_FOLLOW_UPS &&
      confidence < FRONT_PORCH_START_CONFIDENCE &&
      nextSession.vehicleTiming === "pre_solicitation" &&
      (nextSession.followOn === null || !nextSession.incumbentPrime)
    ) {
      askFollowUp(
        nextSession,
        "Good. If this is a follow-on, do you know the incumbent prime? If not, I can still start from the vehicle.",
      );
      return;
    }
    if (
      nextSession.followUpCount < FRONT_PORCH_MAX_FOLLOW_UPS &&
      confidence < FRONT_PORCH_SECOND_FOLLOW_UP_CONFIDENCE &&
      nextSession.followOn === true &&
      !nextSession.incumbentPrime
    ) {
      askFollowUp(nextSession, "If you know who holds the prime position now, tell me. If not, I’ll keep the incumbent path open while I work.");
      return;
    }

    await startVehicleFlow(nextSession);
  }, [askFollowUp, startVehicleFlow]);

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
      askFollowUp(nextSession, "Which vendor are we looking at?");
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
      );
      return;
    }

    await startVendorFlow(nextSession);
  }, [askFollowUp, startVendorFlow]);

  const handleUserTurn = useCallback(async (raw: string) => {
    const text = compactText(raw);
    if (!text || isWorking) return;

    appendMessage("user", text);
    resetArtifacts();

    const nextSession = { ...session };

    if (!nextSession.objectType) {
      const inferredObject = inferObjectType(text);
      if (!inferredObject) {
        askFollowUp(nextSession, "Are we looking at a contract vehicle or a specific vendor?");
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
  }, [askFollowUp, decideVehicleNext, decideVendorNext, isWorking, resetArtifacts, session]);

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
            <StatusPill tone="info">Front Porch</StatusPill>
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
                onOpenWarRoom={openWarRoom}
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
                <div style={{ fontSize: FS.sm, color: isWorking ? T.accent : T.textSecondary }}>
                  {isWorking ? PROGRESS_LINES[progressIndex] : "AXIOM will ask only what it needs to start."}
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
                      {isWorking
                        ? "AXIOM is working this pass. When it returns, you can redirect or press deeper."
                        : "You can be messy. AXIOM will narrow it from there and ask only what changes the work."}
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
              <div style={{ width: "min(760px, 100%)" }}>
                <BriefArtifact
                  surface="light"
                  eyebrow="Vehicle brief"
                  title={vehicleArtifact.vehicle_name}
                  framing="The first public picture is ready. Open the brief room for the clean narrative, or move straight into War Room if you want to pressure the weak edge."
                  sections={[
                    {
                      label: "Current read",
                      detail: summarizeVehicle(vehicleArtifact, session),
                    },
                  ]}
                  provenance={["Separate brief room", "Public vehicle picture", "War Room one move away"]}
                  note="The vehicle brief now has its own room so the conversation can stay clean."
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
                        Take into War Room
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
                    ? "The first returned brief is ready. Open the brief room for the clean narrative, or step into War Room if you want to challenge the weak edge."
                    : "The working brief is open in its own room while AXIOM warms the dossier and keeps the thin parts explicit."}
                  sections={[
                    {
                      label: "Current posture",
                      detail: vendorArtifact.sections[0]?.detail ?? vendorArtifact.framing,
                    },
                  ]}
                  provenance={vendorArtifact.phase === "ready"
                    ? ["Returned brief ready", "Separate brief room", "War Room one move away"]
                    : ["Working brief warming", "Conversation stays primary", "Dossier still under pressure"]}
                  note="The brief now has its own room so the thread and the artifact stop competing with each other."
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
                        Take into War Room
                        <ExternalLink size={14} />
                      </button>
                    </>
                  }
                />
              </div>
            ) : null}

            {errorText ? (
              <div style={{ width: "min(760px, 100%)" }}>
                <InlineMessage tone="danger" title="Front Porch hit a problem" message={errorText} />
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
