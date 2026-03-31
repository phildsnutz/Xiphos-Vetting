import type { ElementDefinition } from "cytoscape";

import { T } from "@/lib/tokens";
import { formatRelationshipLabel } from "@/lib/workflow-copy";

export interface GraphEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  country?: string;
}

export interface GraphEvidenceRecord {
  evidence_id: string;
  source?: string;
  title?: string;
  url?: string;
  artifact_ref?: string;
  snippet?: string;
  source_class?: string;
  authority_level?: string;
  access_model?: string;
  observed_at?: string;
  structured_fields?: Record<string, unknown>;
}

export interface GraphClaimRecord {
  claim_id: string;
  claim_value?: string;
  confidence?: number;
  contradiction_state?: string;
  observed_at?: string;
  first_observed_at?: string;
  last_observed_at?: string;
  data_source?: string;
  structured_fields?: Record<string, unknown>;
  updated_at?: string;
  asserting_agent?: {
    label?: string;
    agent_type?: string;
  };
  source_activity?: {
    source?: string;
    activity_type?: string;
    occurred_at?: string;
  };
  evidence_records?: GraphEvidenceRecord[];
}

export interface GraphRelationship {
  id?: string | number;
  source_entity_id: string;
  target_entity_id: string;
  rel_type: string;
  confidence: number;
  data_source?: string;
  evidence?: string;
  evidence_summary?: string;
  created_at?: string;
  corroboration_count?: number;
  data_sources?: string[];
  evidence_snippets?: string[];
  first_seen_at?: string;
  last_seen_at?: string;
  relationship_ids?: Array<string | number>;
  claim_records?: GraphClaimRecord[];
}

export type LayoutMode = "concentric" | "breadthfirst" | "cose";
export type PriorityFilter = "all" | "decision" | "material_plus" | "relevant_plus";

export interface NormalizedRelationship extends GraphRelationship {
  id: string;
  relLabel: string;
  lineColor: string;
  family: string;
  familyLabel: string;
  lineStyle: "solid" | "dashed" | "dotted";
  dataSource: string;
  evidence: string;
  evidenceSummary: string;
  createdAt: string;
  corroborationCount: number;
  dataSources: string[];
  evidenceSnippets: string[];
  firstSeenAt: string;
  lastSeenAt: string;
  claimRecords: GraphClaimRecord[];
  priorityScore: number;
  priorityLabel: string;
}

interface RenderableEntity extends GraphEntity {
  synthetic?: boolean;
}

const TYPE_META: Record<string, { fill: string; stroke: string; label: string; shape: string }> = {
  company: { fill: "#193552", stroke: "#60a5fa", label: "Company", shape: "round-rectangle" },
  government_agency: { fill: "#0d4036", stroke: "#34d399", label: "Government Agency", shape: "rectangle" },
  sanctions_list: { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions List", shape: "diamond" },
  sanctions_entry: { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions Entry", shape: "diamond" },
  court_case: { fill: "#5f4715", stroke: "#fbbf24", label: "Court Case", shape: "hexagon" },
  person: { fill: "#40205e", stroke: "#a78bfa", label: "Person", shape: "ellipse" },
  product: { fill: "#1f3a5f", stroke: "#93c5fd", label: "Product", shape: "round-rectangle" },
  cve: { fill: "#4c1d95", stroke: "#c4b5fd", label: "CVE", shape: "hexagon" },
  kev_entry: { fill: "#7c2d12", stroke: "#fdba74", label: "KEV Entry", shape: "diamond" },
  component: { fill: "#1f2937", stroke: "#f59e0b", label: "Component", shape: "round-rectangle" },
  subsystem: { fill: "#102a43", stroke: "#38bdf8", label: "Subsystem", shape: "hexagon" },
  holding_company: { fill: "#16324f", stroke: "#2dd4bf", label: "Holding Company", shape: "rectangle" },
  bank: { fill: "#18324a", stroke: "#22d3ee", label: "Bank", shape: "rectangle" },
  telecom_provider: { fill: "#0f2844", stroke: "#60a5fa", label: "Telecom Provider", shape: "round-rectangle" },
  distributor: { fill: "#233544", stroke: "#f59e0b", label: "Distributor", shape: "round-rectangle" },
  facility: { fill: "#1d3b2a", stroke: "#4ade80", label: "Facility", shape: "rectangle" },
  shipment_route: { fill: "#3b2f12", stroke: "#fbbf24", label: "Shipment Route", shape: "hexagon" },
  service: { fill: "#1a2d5a", stroke: "#93c5fd", label: "Service", shape: "round-rectangle" },
  trade_show_event: { fill: "#3b2a17", stroke: "#f59e0b", label: "Trade Show Event", shape: "round-rectangle" },
  country: { fill: "#1a3a4a", stroke: "#38bdf8", label: "Country", shape: "round-rectangle" },
  export_control: { fill: "#4a1520", stroke: "#fb7185", label: "Export Control", shape: "octagon" },
  case: { fill: "#2d3748", stroke: "#e2e8f0", label: "Case", shape: "round-rectangle" },
  unknown: { fill: "#243447", stroke: "#94a3b8", label: "Unknown", shape: "ellipse" },
};

const REL_COLORS: Record<string, string> = {
  subsidiary_of: "#14b8a6",
  subcontractor_of: "#06b6d4",
  prime_contractor_of: "#06b6d4",
  contracts_with: "#60a5fa",
  litigant_in: "#f59e0b",
  sanctioned_on: "#ef4444",
  sanctioned_person: "#ef4444",
  officer_of: "#a78bfa",
  alias_of: "#94a3b8",
  former_name: "#64748b",
  mentioned_with: "#64748b",
  related_entity: "#64748b",
  filed_with: "#f59e0b",
  regulated_by: "#34d399",
  employed_by: "#818cf8",
  screened_for: "#94a3b8",
  deemed_export_subject: "#fb923c",
  co_national: "#64748b",
  national_of: "#38bdf8",
  has_vulnerability: "#f97316",
  uses_product: "#60a5fa",
  supplies_component: "#f59e0b",
  supplies_component_to: "#f59e0b",
  integrated_into: "#38bdf8",
  owned_by: "#2dd4bf",
  beneficially_owned_by: "#14b8a6",
  depends_on_network: "#60a5fa",
  routes_payment_through: "#22d3ee",
  distributed_by: "#f59e0b",
  operates_facility: "#4ade80",
  ships_via: "#fbbf24",
  depends_on_service: "#93c5fd",
};

const REL_FAMILY_META: Record<string, { label: string; color: string; lineStyle: "solid" | "dashed" | "dotted"; description: string }> = {
  supply_chain: {
    label: "Prime / Sub",
    color: "#38bdf8",
    lineStyle: "solid",
    description: "Prime, subcontractor, and award-chain relationships tied to work execution.",
  },
  ownership: {
    label: "Ownership / Governance",
    color: "#2dd4bf",
    lineStyle: "dashed",
    description: "Parent, subsidiary, officer, and governance relationships that shape control.",
  },
  sanctions_regulatory: {
    label: "Sanctions / Regulatory",
    color: "#fb7185",
    lineStyle: "dotted",
    description: "Sanctions, filings, and regulators connected to this entity.",
  },
  cyber_components: {
    label: "Cyber / Components",
    color: "#f59e0b",
    lineStyle: "solid",
    description: "Products, vulnerabilities, components, and subsystems tied to the entity.",
  },
  control_path: {
    label: "Control Path",
    color: "#22d3ee",
    lineStyle: "solid",
    description: "Telecom, banking, distribution, facility, service, and route dependencies that shape hidden control paths.",
  },
  litigation_contracts: {
    label: "Litigation / Contracts",
    color: "#f59e0b",
    lineStyle: "solid",
    description: "Courts, disputes, and contract-linked relationships that drive exposure.",
  },
  context: {
    label: "Context / Identity",
    color: "#94a3b8",
    lineStyle: "dashed",
    description: "Alias, former-name, and contextual links that help explain the network.",
  },
};

const REL_FAMILY_PRIORITY: Record<string, number> = {
  sanctions_regulatory: 260,
  cyber_components: 240,
  control_path: 220,
  litigation_contracts: 230,
  supply_chain: 210,
  ownership: 170,
  context: 90,
};

const REL_TYPE_PRIORITY: Record<string, number> = {
  sanctioned_on: 160,
  sanctioned_person: 155,
  deemed_export_subject: 145,
  beneficially_owned_by: 142,
  owned_by: 138,
  depends_on_network: 122,
  routes_payment_through: 121,
  depends_on_service: 119,
  regulated_by: 130,
  litigant_in: 120,
  distributed_by: 111,
  operates_facility: 109,
  ships_via: 107,
  prime_contractor_of: 115,
  subcontractor_of: 115,
  supplies_component_to: 112,
  integrated_into: 110,
  has_vulnerability: 108,
  contracts_with: 105,
  uses_product: 102,
  supplies_component: 100,
  employed_by: 95,
  subsidiary_of: 85,
  parent_of: 85,
  officer_of: 70,
  filed_with: 55,
  screened_for: 40,
  former_name: 30,
  alias_of: 25,
  national_of: 20,
  mentioned_with: 15,
  co_national: 12,
  related_entity: 10,
};

export const PRIORITY_META: Record<string, { label: string; color: string; background: string }> = {
  decision: { label: "Decision edge", color: "#fca5a5", background: "rgba(239,68,68,0.14)" },
  material: { label: "Material", color: "#C4A052", background: "rgba(196,160,82,0.16)" },
  relevant: { label: "Relevant", color: T.accent, background: `${T.accent}14` },
  context: { label: "Context", color: T.dim, background: T.bg },
};

const PRIORITY_FILTER_META: Record<PriorityFilter, { label: string; description: string; color: string; background: string }> = {
  all: {
    label: "Full ranked network",
    description: "Showing the full relationship set, ordered by decision relevance.",
    color: T.dim,
    background: T.bg,
  },
  decision: {
    label: "Decision edge view",
    description: "Showing only the highest-value relationships most likely to affect procurement or diligence.",
    color: PRIORITY_META.decision.color,
    background: PRIORITY_META.decision.background,
  },
  material_plus: {
    label: "Material view",
    description: "Showing material and decision-grade relationships while hiding lower-signal context.",
    color: PRIORITY_META.material.color,
    background: PRIORITY_META.material.background,
  },
  relevant_plus: {
    label: "Relevant view",
    description: "Showing relevant, material, and decision-grade relationships while dropping context-only links.",
    color: PRIORITY_META.relevant.color,
    background: PRIORITY_META.relevant.background,
  },
};

export const EFFORTLESS_PRIORITY_PRESETS: Array<{ value: PriorityFilter; label: string; description: string }> = [
  {
    value: "material_plus",
    label: "What matters",
    description: "Decision-grade relationships first",
  },
  {
    value: "relevant_plus",
    label: "Balanced",
    description: "Keeps relevant context in view",
  },
  {
    value: "all",
    label: "Everything",
    description: "Show the full ranked network",
  },
];

export function getTypeMeta(type: string) {
  return TYPE_META[type] || TYPE_META.unknown;
}

export function getRelationshipLabel(relType: string) {
  return formatRelationshipLabel(relType);
}

export function getRelationshipColor(relType: string) {
  return REL_COLORS[relType] || "#94a3b8";
}

function getRelationshipFamily(relType: string) {
  if (["subcontractor_of", "prime_contractor_of", "supplies_component_to"].includes(relType)) return "supply_chain";
  if (["subsidiary_of", "parent_of", "officer_of", "employed_by", "owned_by", "beneficially_owned_by"].includes(relType)) return "ownership";
  if (["sanctioned_on", "sanctioned_person", "regulated_by", "filed_with", "deemed_export_subject"].includes(relType)) return "sanctions_regulatory";
  if (["has_vulnerability", "uses_product", "supplies_component", "integrated_into"].includes(relType)) return "cyber_components";
  if (["depends_on_network", "depends_on_service", "distributed_by", "operates_facility", "ships_via", "routes_payment_through"].includes(relType)) return "control_path";
  if (["litigant_in", "contracts_with"].includes(relType)) return "litigation_contracts";
  if (["screened_for", "national_of", "co_national"].includes(relType)) return "context";
  return "context";
}

function getRelationshipFamilyMeta(relType: string) {
  const family = getRelationshipFamily(relType);
  return {
    family,
    ...REL_FAMILY_META[family],
  };
}

function truncateLabel(label: string, max = 34) {
  return label.length > max ? `${label.slice(0, max - 3)}...` : label;
}

function titleCaseWords(value: string) {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}

export function formatConnectorLabel(source?: string) {
  if (!source) return "Connector not recorded";
  return titleCaseWords(
    source
      .replace(/[_-]+/g, " ")
      .replace(/\bus\b/g, "US")
      .replace(/\bsec\b/gi, "SEC")
      .replace(/\bofac\b/gi, "OFAC")
      .replace(/\bfpds\b/gi, "FPDS")
      .replace(/\bgdelt\b/gi, "GDELT")
      .replace(/\bsam\b/gi, "SAM")
      .replace(/\bdoi\b/gi, "DOI")
      .replace(/\bdoj\b/gi, "DOJ")
      .trim(),
  );
}

export function formatFirstSeen(value?: string) {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function summarizeCorroboration(count: number, sourceCount: number) {
  if (count <= 1) return sourceCount > 1 ? "Single corroborated edge" : "Single record";
  if (sourceCount > 1) return `${count} corroborating records across ${sourceCount} sources`;
  return `${count} corroborating records`;
}

function inferEntityTypeFromId(id: string) {
  if (id.startsWith("lei:") || id.startsWith("cik:") || id.startsWith("uei:") || id.startsWith("cage:") || id.startsWith("duns:") || id.startsWith("entity:")) return "company";
  if (id.startsWith("person:")) return "person";
  if (id.startsWith("product:")) return "product";
  if (id.startsWith("cve:")) return "cve";
  if (id.startsWith("kev:")) return "kev_entry";
  if (id.startsWith("component:")) return "component";
  if (id.startsWith("subsystem:")) return "subsystem";
  if (id.startsWith("holding_company:")) return "holding_company";
  if (id.startsWith("bank:")) return "bank";
  if (id.startsWith("telecom_provider:")) return "telecom_provider";
  if (id.startsWith("distributor:")) return "distributor";
  if (id.startsWith("facility:")) return "facility";
  if (id.startsWith("shipment_route:")) return "shipment_route";
  if (id.startsWith("service:")) return "service";
  if (id.startsWith("court:") || id.startsWith("docket:")) return "court_case";
  if (id.startsWith("case:")) return "case";
  if (id.startsWith("ofac:") || id.startsWith("sdn:") || id.startsWith("sanction:") || id.startsWith("sanctions:")) return "sanctions_list";
  if (id.startsWith("agency:")) return "government_agency";
  if (id.startsWith("country:")) return "country";
  if (id.startsWith("export_class:")) return "export_control";
  return "unknown";
}

function fallbackEntityLabel(id: string) {
  const [prefix, raw = ""] = id.split(":", 2);
  if (!raw) return id;
  const cleaned = raw.replace(/[_-]+/g, " ").trim();
  const clipped = cleaned.length > 18 ? `${cleaned.slice(0, 15)}...` : cleaned;

  switch (prefix) {
    case "lei":
      return `LEI ${clipped.toUpperCase()}`;
    case "cik":
      return `CIK ${clipped}`;
    case "uei":
      return `UEI ${clipped.toUpperCase()}`;
    case "cage":
      return `CAGE ${clipped.toUpperCase()}`;
    case "duns":
      return `DUNS ${clipped}`;
    case "person":
      return cleaned || "Person";
    case "entity":
      return `Entity ${clipped}`;
    case "product":
      return cleaned || "Product";
    case "cve":
      return raw.toUpperCase();
    case "kev":
      return `KEV ${clipped.toUpperCase()}`;
    case "component":
      return cleaned || "Component";
    case "subsystem":
      return cleaned || "Subsystem";
    case "holding_company":
      return cleaned || "Holding company";
    case "bank":
      return cleaned || "Bank";
    case "telecom_provider":
      return cleaned || "Telecom provider";
    case "distributor":
      return cleaned || "Distributor";
    case "facility":
      return cleaned || "Facility";
    case "shipment_route":
      return cleaned || "Shipment route";
    case "service":
      return cleaned || "Service";
    default:
      return `${prefix.toUpperCase()} ${clipped}`;
  }
}

export function resolveRootId(entities: GraphEntity[], requested?: string) {
  if (requested && entities.some((entity) => entity.id === requested)) return requested;
  const company = entities.find((entity) => entity.entity_type === "company");
  return company?.id || entities[0]?.id;
}

export function normalizeRelationships(relationships: GraphRelationship[]): NormalizedRelationship[] {
  return relationships.map((relationship, index) => ({
    ...relationship,
    id: relationship.id != null
      ? String(relationship.id)
      : `${relationship.source_entity_id}::${relationship.rel_type}::${relationship.target_entity_id}::${index}`,
    relLabel: getRelationshipLabel(relationship.rel_type),
    lineColor: getRelationshipColor(relationship.rel_type),
    family: getRelationshipFamilyMeta(relationship.rel_type).family,
    familyLabel: getRelationshipFamilyMeta(relationship.rel_type).label,
    lineStyle: getRelationshipFamilyMeta(relationship.rel_type).lineStyle,
    dataSource: relationship.data_source || "",
    evidence: relationship.evidence || "",
    evidenceSummary: relationship.evidence_summary || "",
    createdAt: relationship.created_at || "",
    corroborationCount: relationship.corroboration_count || (relationship.data_sources?.length ?? 0) || 1,
    dataSources: relationship.data_sources || (relationship.data_source ? [relationship.data_source] : []),
    evidenceSnippets: relationship.evidence_snippets || (relationship.evidence ? [relationship.evidence] : []),
    firstSeenAt: relationship.first_seen_at || relationship.created_at || "",
    lastSeenAt: relationship.last_seen_at || relationship.created_at || "",
    claimRecords: relationship.claim_records || [],
    priorityScore: 0,
    priorityLabel: PRIORITY_META.context.label,
  }));
}

export function filterRelationships(
  relationships: NormalizedRelationship[],
  relationFilter: string,
  minConfidence: number,
) {
  return relationships.filter((relationship) => {
    if (relationFilter !== "all" && relationship.rel_type !== relationFilter) return false;
    return relationship.confidence >= minConfidence;
  });
}

export function filterRelationshipsByPriority(
  relationships: NormalizedRelationship[],
  priorityFilter: PriorityFilter,
) {
  if (priorityFilter === "all") return relationships;

  return relationships.filter((relationship) => {
    const label = relationship.priorityLabel;
    if (priorityFilter === "decision") return label === PRIORITY_META.decision.label;
    if (priorityFilter === "material_plus") {
      return label === PRIORITY_META.decision.label || label === PRIORITY_META.material.label;
    }
    if (priorityFilter === "relevant_plus") return label !== PRIORITY_META.context.label;
    return true;
  });
}

export function maxDepthForLayout(layoutMode: LayoutMode, showSecondaryLinks: boolean): number | null {
  if (layoutMode === "concentric") return showSecondaryLinks ? 2 : 1;
  if (layoutMode === "breadthfirst") return 2;
  return null;
}

export function describeScope(layoutMode: LayoutMode, showSecondaryLinks: boolean) {
  if (layoutMode === "concentric") {
    return showSecondaryLinks ? "Focused network · primary + secondary links" : "Focused network · primary links";
  }
  if (layoutMode === "breadthfirst") {
    return "Trace mode · root to second-ring context";
  }
  return "Explore mode · full network";
}

export function describePriorityFilter(priorityFilter: PriorityFilter) {
  return PRIORITY_FILTER_META[priorityFilter];
}

export function recommendedPriorityFilter(relationshipCount: number): PriorityFilter {
  if (relationshipCount > 900) return "decision";
  if (relationshipCount > 420) return "material_plus";
  if (relationshipCount > 240) return "relevant_plus";
  return "all";
}

function buildNodeDepthMap(
  rootId: string | undefined,
  relationships: NormalizedRelationship[],
) {
  const depths = new Map<string, number>();
  if (!rootId) return depths;

  const adjacency = new Map<string, Set<string>>();
  for (const relationship of relationships) {
    if (!adjacency.has(relationship.source_entity_id)) adjacency.set(relationship.source_entity_id, new Set());
    if (!adjacency.has(relationship.target_entity_id)) adjacency.set(relationship.target_entity_id, new Set());
    adjacency.get(relationship.source_entity_id)?.add(relationship.target_entity_id);
    adjacency.get(relationship.target_entity_id)?.add(relationship.source_entity_id);
  }

  if (!adjacency.has(rootId)) {
    depths.set(rootId, 0);
    return depths;
  }

  const queue: string[] = [rootId];
  depths.set(rootId, 0);
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    const currentDepth = depths.get(current) ?? 0;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (depths.has(neighbor)) continue;
      depths.set(neighbor, currentDepth + 1);
      queue.push(neighbor);
    }
  }

  return depths;
}

export function filterRelationshipsByDepth(
  relationships: NormalizedRelationship[],
  rootId: string | undefined,
  maxDepth: number | null,
) {
  if (maxDepth == null || !rootId) return relationships;
  const depths = buildNodeDepthMap(rootId, relationships);

  return relationships.filter((relationship) => {
    const sourceDepth = depths.get(relationship.source_entity_id);
    const targetDepth = depths.get(relationship.target_entity_id);
    if (sourceDepth == null || targetDepth == null) return false;
    return Math.max(sourceDepth, targetDepth) <= maxDepth && Math.min(sourceDepth, targetDepth) < maxDepth;
  });
}

function getPriorityLabel(score: number) {
  if (score >= 700) return PRIORITY_META.decision.label;
  if (score >= 560) return PRIORITY_META.material.label;
  if (score >= 430) return PRIORITY_META.relevant.label;
  return PRIORITY_META.context.label;
}

export function getPriorityMeta(label: string) {
  return Object.values(PRIORITY_META).find((meta) => meta.label === label) || PRIORITY_META.context;
}

export function prioritizeRelationships(
  relationships: NormalizedRelationship[],
  rootId: string | undefined,
) {
  const depths = buildNodeDepthMap(rootId, relationships);

  return [...relationships]
    .map((relationship) => {
      const sourceDepth = depths.get(relationship.source_entity_id) ?? 99;
      const targetDepth = depths.get(relationship.target_entity_id) ?? 99;
      const directRootLink = relationship.source_entity_id === rootId || relationship.target_entity_id === rootId;
      const nearestDepth = Math.min(sourceDepth, targetDepth);
      const furthestDepth = Math.max(sourceDepth, targetDepth);

      let score =
        (REL_FAMILY_PRIORITY[relationship.family] ?? 0) +
        (REL_TYPE_PRIORITY[relationship.rel_type] ?? 0) +
        Math.round(relationship.confidence * 100) +
        Math.min(relationship.corroborationCount * 16, 96);

      if (directRootLink) score += 220;
      else if (nearestDepth <= 1) score += 130;
      else if (nearestDepth <= 2) score += 70;

      score += Math.max(0, 90 - Math.min(furthestDepth, 6) * 18);

      return {
        ...relationship,
        priorityScore: score,
        priorityLabel: getPriorityLabel(score),
      };
    })
    .sort((left, right) => {
      if (right.priorityScore !== left.priorityScore) return right.priorityScore - left.priorityScore;
      if (right.confidence !== left.confidence) return right.confidence - left.confidence;
      if (right.corroborationCount !== left.corroborationCount) return right.corroborationCount - left.corroborationCount;
      return left.relLabel.localeCompare(right.relLabel);
    });
}

export function countVisibleEntities(
  relationships: NormalizedRelationship[],
  rootId?: string,
) {
  const ids = new Set<string>();
  if (rootId) ids.add(rootId);
  for (const relationship of relationships) {
    ids.add(relationship.source_entity_id);
    ids.add(relationship.target_entity_id);
  }
  return ids.size;
}

export function buildRenderableEntityMap(
  entities: GraphEntity[],
  relationships: NormalizedRelationship[],
) {
  const entityMap = new Map<string, RenderableEntity>(
    entities.map((entity) => [entity.id, entity]),
  );

  relationships.forEach((relationship) => {
    if (!entityMap.has(relationship.source_entity_id)) {
      entityMap.set(relationship.source_entity_id, {
        id: relationship.source_entity_id,
        canonical_name: fallbackEntityLabel(relationship.source_entity_id),
        entity_type: inferEntityTypeFromId(relationship.source_entity_id),
        confidence: Math.max(relationship.confidence ?? 0.35, 0.35),
        synthetic: true,
      });
    }
    if (!entityMap.has(relationship.target_entity_id)) {
      entityMap.set(relationship.target_entity_id, {
        id: relationship.target_entity_id,
        canonical_name: fallbackEntityLabel(relationship.target_entity_id),
        entity_type: inferEntityTypeFromId(relationship.target_entity_id),
        confidence: Math.max(relationship.confidence ?? 0.35, 0.35),
        synthetic: true,
      });
    }
  });

  return entityMap;
}

export function buildElements(
  entityMap: Map<string, RenderableEntity>,
  relationships: NormalizedRelationship[],
  rootId?: string,
): ElementDefinition[] {
  const visibleIds = new Set<string>();
  const elements: ElementDefinition[] = [];
  relationships.forEach((relationship) => {
    visibleIds.add(relationship.source_entity_id);
    visibleIds.add(relationship.target_entity_id);
  });
  if (rootId) visibleIds.add(rootId);

  for (const entity of entityMap.values()) {
    if (!visibleIds.has(entity.id)) continue;
    const meta = getTypeMeta(entity.entity_type);
    elements.push({
      group: "nodes",
      data: {
        id: entity.id,
        label: truncateLabel(entity.canonical_name),
        fullLabel: entity.canonical_name,
        type: entity.entity_type || "unknown",
        confidence: entity.confidence ?? 0.5,
        country: entity.country || "",
        isRoot: entity.id === rootId,
        isSynthetic: Boolean(entity.synthetic),
        fillColor: meta.fill,
        strokeColor: meta.stroke,
        shape: meta.shape,
      },
    });
  }

  relationships.forEach((relationship) => {
    elements.push({
      group: "edges",
      data: {
        id: relationship.id,
        source: relationship.source_entity_id,
        target: relationship.target_entity_id,
        relType: relationship.rel_type,
        relLabel: relationship.relLabel,
        family: relationship.family,
        familyLabel: relationship.familyLabel,
        confidence: relationship.confidence ?? 0.5,
        lineColor: relationship.lineColor,
        lineStyle: relationship.lineStyle,
        dataSource: relationship.dataSource,
        evidence: relationship.evidence,
        evidenceSummary: relationship.evidenceSummary,
        createdAt: relationship.createdAt,
        corroborationCount: relationship.corroborationCount,
        dataSources: relationship.dataSources,
        evidenceSnippets: relationship.evidenceSnippets,
        firstSeenAt: relationship.firstSeenAt,
        lastSeenAt: relationship.lastSeenAt,
        claimRecords: relationship.claimRecords,
        priorityScore: relationship.priorityScore,
        priorityLabel: relationship.priorityLabel,
      },
    });
  });

  return elements;
}
