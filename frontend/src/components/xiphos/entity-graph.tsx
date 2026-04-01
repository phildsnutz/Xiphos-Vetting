/**
 * Entity Association Graph
 *
 * Cytoscape-based graph explorer for the Helios case detail page.
 * Replaces the previous hand-rolled canvas renderer with a graph-native
 * navigation surface plus a readable inspector panel.
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import cytoscape, {
  type Core,
  type EdgeSingular,
  type ElementDefinition,
  type NodeSingular,
} from "cytoscape";
import { Search } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import { formatRelationshipLabel } from "@/lib/workflow-copy";

interface GraphEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  country?: string;
}

interface GraphRelationship {
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

interface GraphEvidenceRecord {
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

interface GraphClaimRecord {
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

interface EntityGraphProps {
  entities: GraphEntity[];
  relationships: GraphRelationship[];
  rootEntityId?: string;
  width?: number;
  height?: number;
  onEntityClick?: (entity: GraphEntity) => void;
  onRelationshipClick?: (relationshipId: number) => void;
}

interface SelectedNodeSummary {
  id: string;
  label: string;
  fullLabel: string;
  type: string;
  confidence: number;
  country: string;
  connectionCount: number;
}

interface SelectedEdgeSummary {
  id: string;
  sourceId: string;
  targetId: string;
  sourceLabel: string;
  targetLabel: string;
  relType: string;
  relLabel: string;
  family: string;
  familyLabel: string;
  confidence: number;
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

type LayoutMode = "concentric" | "breadthfirst" | "cose" | "cola";
type ViewMode = "graph" | "table";
type ViewportMode = "neighborhood" | "center" | "pan" | "none";
type EdgeViewportMode = "fit" | "pan" | "none";
type PriorityFilter = "all" | "decision" | "material_plus" | "relevant_plus";

interface NormalizedRelationship extends GraphRelationship {
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

const GOLD = "#C4A052";
const GRAPH_BG = "#07101a";
const GRAPH_BG_GLOW = "radial-gradient(circle at 50% 42%, rgba(196,160,82,0.10), rgba(7,16,26,0.96) 38%, rgba(5,10,16,1) 100%)";

const TYPE_META: Record<string, { fill: string; stroke: string; label: string; shape: string }> = {
  company:           { fill: "#193552", stroke: "#60a5fa", label: "Company", shape: "round-rectangle" },
  government_agency: { fill: "#0d4036", stroke: "#34d399", label: "Government Agency", shape: "rectangle" },
  sanctions_list:    { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions List", shape: "diamond" },
  sanctions_entry:   { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions Entry", shape: "diamond" },
  court_case:        { fill: "#5f4715", stroke: "#fbbf24", label: "Court Case", shape: "hexagon" },
  person:            { fill: "#40205e", stroke: "#a78bfa", label: "Person", shape: "ellipse" },
  product:           { fill: "#1f3a5f", stroke: "#93c5fd", label: "Product", shape: "round-rectangle" },
  cve:               { fill: "#4c1d95", stroke: "#c4b5fd", label: "CVE", shape: "hexagon" },
  kev_entry:         { fill: "#7c2d12", stroke: "#fdba74", label: "KEV Entry", shape: "diamond" },
  component:         { fill: "#1f2937", stroke: "#f59e0b", label: "Component", shape: "round-rectangle" },
  subsystem:         { fill: "#102a43", stroke: "#38bdf8", label: "Subsystem", shape: "hexagon" },
  holding_company:   { fill: "#16324f", stroke: "#2dd4bf", label: "Holding Company", shape: "rectangle" },
  bank:              { fill: "#18324a", stroke: "#22d3ee", label: "Bank", shape: "rectangle" },
  telecom_provider:  { fill: "#0f2844", stroke: "#60a5fa", label: "Telecom Provider", shape: "round-rectangle" },
  distributor:       { fill: "#233544", stroke: "#f59e0b", label: "Distributor", shape: "round-rectangle" },
  facility:          { fill: "#1d3b2a", stroke: "#4ade80", label: "Facility", shape: "rectangle" },
  shipment_route:    { fill: "#3b2f12", stroke: "#fbbf24", label: "Shipment Route", shape: "hexagon" },
  service:           { fill: "#1a2d5a", stroke: "#93c5fd", label: "Service", shape: "round-rectangle" },
  trade_show_event:  { fill: "#3b2a17", stroke: "#f59e0b", label: "Trade Show Event", shape: "round-rectangle" },
  country:           { fill: "#1a3a4a", stroke: "#38bdf8", label: "Country", shape: "round-rectangle" },
  export_control:    { fill: "#4a1520", stroke: "#fb7185", label: "Export Control", shape: "octagon" },
  case:              { fill: "#2d3748", stroke: "#e2e8f0", label: "Case", shape: "round-rectangle" },
  unknown:           { fill: "#243447", stroke: "#94a3b8", label: "Unknown", shape: "ellipse" },
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
  // Person screening relationship types
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

const PRIORITY_META: Record<string, { label: string; color: string; background: string }> = {
  decision: { label: "Decision edge", color: "#fca5a5", background: "rgba(239,68,68,0.14)" },
  material: { label: "Material", color: GOLD, background: "rgba(196,160,82,0.16)" },
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

const EFFORTLESS_PRIORITY_PRESETS: Array<{ value: PriorityFilter; label: string; description: string }> = [
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

function getTypeMeta(type: string) {
  return TYPE_META[type] || TYPE_META.unknown;
}

function getRelationshipLabel(relType: string) {
  return formatRelationshipLabel(relType);
}

function getRelationshipColor(relType: string) {
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

function formatConnectorLabel(source?: string) {
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

function formatFirstSeen(value?: string) {
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

function summarizeCorroboration(count: number, sourceCount: number) {
  if (count <= 1) return sourceCount > 1 ? "Single corroborated edge" : "Single record";
  if (sourceCount > 1) return `${count} corroborating records across ${sourceCount} sources`;
  return `${count} corroborating records`;
}

function inferEntityTypeFromId(id: string) {
  if (id.startsWith("lei:") || id.startsWith("cik:") || id.startsWith("uei:") || id.startsWith("cage:") || id.startsWith("duns:") || id.startsWith("entity:")) {
    return "company";
  }
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

function resolveRootId(entities: GraphEntity[], requested?: string) {
  if (requested && entities.some((entity) => entity.id === requested)) return requested;
  const company = entities.find((entity) => entity.entity_type === "company");
  return company?.id || entities[0]?.id;
}

function normalizeRelationships(relationships: GraphRelationship[]): NormalizedRelationship[] {
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

function filterRelationships(
  relationships: NormalizedRelationship[],
  relationFilter: string,
  minConfidence: number,
) {
  return relationships.filter((relationship) => {
    if (relationFilter !== "all" && relationship.rel_type !== relationFilter) return false;
    return relationship.confidence >= minConfidence;
  });
}

function filterRelationshipsByPriority(
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

function maxDepthForLayout(layoutMode: LayoutMode, showSecondaryLinks: boolean): number | null {
  if (layoutMode === "concentric") return showSecondaryLinks ? 2 : 1;
  if (layoutMode === "breadthfirst") return 2;
  if (layoutMode === "cola") return showSecondaryLinks ? 3 : 2;
  return null;
}

function describeScope(layoutMode: LayoutMode, showSecondaryLinks: boolean) {
  if (layoutMode === "cola") {
    return showSecondaryLinks ? "Force-directed (3-hop)" : "Force-directed (2-hop)";
  }
  if (layoutMode === "concentric") {
    return showSecondaryLinks ? "Focused network · primary + secondary links" : "Focused network · primary links";
  }
  if (layoutMode === "breadthfirst") {
    return "Trace mode · root to second-ring context";
  }
  return "Explore mode · full network";
}

function describePriorityFilter(priorityFilter: PriorityFilter) {
  return PRIORITY_FILTER_META[priorityFilter];
}

function recommendedPriorityFilter(relationshipCount: number): PriorityFilter {
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

function filterRelationshipsByDepth(
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

function getPriorityMeta(label: string) {
  return Object.values(PRIORITY_META).find((meta) => meta.label === label) || PRIORITY_META.context;
}

function prioritizeRelationships(
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

function countVisibleEntities(
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

function buildRenderableEntityMap(
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

function buildElements(
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
        temporalRecency: (() => {
          const last = relationship.lastSeenAt || relationship.createdAt;
          if (!last) return 0.5;
          const age = Date.now() - new Date(last).getTime();
          const days = age / (1000 * 60 * 60 * 24);
          if (days < 7) return 1.0;
          if (days < 30) return 0.85;
          if (days < 90) return 0.65;
          if (days < 365) return 0.4;
          return 0.2;
        })(),
      },
    });
  });

  return elements;
}

function buildStyles(): cytoscape.StylesheetJson {
  const styles = [
    // ── Base nodes ───────────────────────────────────────────────
    {
      selector: "node",
      style: {
        shape: "data(shape)",
        width: (ele: NodeSingular) => {
          const base = ele.data("isRoot") ? 64 : ele.data("type") === "company" ? 40 : 28;
          return base + Math.min(ele.degree() * 0.8, 12);
        },
        height: (ele: NodeSingular) => {
          const base = ele.data("isRoot") ? 64 : ele.data("type") === "company" ? 40 : 28;
          return base + Math.min(ele.degree() * 0.8, 12);
        },
        "background-color": "data(fillColor)",
        "background-opacity": (ele: NodeSingular) => 0.75 + Number(ele.data("confidence") ?? 0.5) * 0.25,
        "border-color": "data(strokeColor)",
        "border-width": (ele: NodeSingular) => (ele.data("isRoot") ? 3 : 1.5),
        "border-opacity": 0.9,
        "overlay-padding": 8,
        "overlay-color": "data(strokeColor)",
        "overlay-opacity": 0,
        label: "data(label)",
        color: "#e2e8f0",
        "font-size": (ele: NodeSingular) => (ele.data("isRoot") ? 13 : 11),
        "font-weight": (ele: NodeSingular) => (ele.data("isRoot") ? 700 : 600),
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 10,
        "text-wrap": "wrap",
        "text-max-width": 120,
        "text-background-color": "#07101a",
        "text-background-opacity": 0.65,
        "text-background-padding": 4,
        "text-background-shape": "roundrectangle",
        "text-outline-color": "#07101a",
        "text-outline-width": 0.5,
        "text-outline-opacity": 0.4,
        "transition-property": "background-color border-color border-width opacity width height background-opacity",
        "transition-duration": "220ms",
      },
    },
    // ── Root node emphasis ────────────────────────────────────────
    {
      selector: "node[?isRoot]",
      style: {
        "border-width": 3,
        "border-color": GOLD,
        "background-color": "#1a1508",
        "overlay-color": GOLD,
        "overlay-opacity": 0.08,
        "overlay-padding": 14,
        "font-size": 14,
        "font-weight": 800,
        "text-background-opacity": 0.8,
        "z-index": 10,
      },
    },
    // ── Sanctions/risk node glow ─────────────────────────────────
    {
      selector: "node[type = 'sanctions_list'], node[type = 'sanctions_entry']",
      style: {
        "overlay-color": "#ef4444",
        "overlay-opacity": 0.06,
        "overlay-padding": 10,
      },
    },
    // ── Base edges ───────────────────────────────────────────────
    {
      selector: "edge",
      style: {
        width: (ele: EdgeSingular) => 0.8 + Number(ele.data("confidence") ?? 0.5) * 2.6,
        "line-color": "data(lineColor)",
        "line-style": "data(lineStyle)",
        "target-arrow-shape": "triangle",
        "target-arrow-color": "data(lineColor)",
        "arrow-scale": (ele: EdgeSingular) => 0.6 + Number(ele.data("confidence") ?? 0.5) * 0.4,
        opacity: (ele: EdgeSingular) => 0.15 + Number(ele.data("confidence") ?? 0.5) * 0.35,
        "curve-style": "bezier",
        "line-cap": "round",
        "overlay-padding": 4,
        "overlay-color": "data(lineColor)",
        "overlay-opacity": 0,
        "transition-property": "opacity line-color width line-style overlay-opacity",
        "transition-duration": "200ms",
      },
    },
    // ── High-corroboration edges ─────────────────────────────────
    {
      selector: "edge[corroborationCount > 1]",
      style: {
        opacity: (ele: EdgeSingular) => 0.3 + Number(ele.data("confidence") ?? 0.5) * 0.4,
        width: (ele: EdgeSingular) => 1.2 + Number(ele.data("confidence") ?? 0.5) * 3,
      },
    },
    // ── Sanctions edges: always prominent ────────────────────────
    {
      selector: "edge[relType = 'sanctioned_on'], edge[relType = 'sanctioned_person']",
      style: { opacity: 0.7, width: 3.5, "line-color": "#ef4444", "target-arrow-color": "#ef4444" },
    },
    // ── Hover states ─────────────────────────────────────────────
    {
      selector: "node.hovered",
      style: {
        "overlay-opacity": 0.08,
        "border-width": (ele: NodeSingular) => (ele.data("isRoot") ? 3.5 : 2.5),
        "border-opacity": 1,
        "z-index": 15,
      },
    },
    {
      selector: "edge.hovered",
      style: {
        opacity: (ele: EdgeSingular) => Math.min(1, 0.4 + Number(ele.data("confidence") ?? 0.5) * 0.5),
        "overlay-opacity": 0.05,
        width: (ele: EdgeSingular) => 1.5 + Number(ele.data("confidence") ?? 0.5) * 3,
        "z-index": 15,
      },
    },
    // ── Dimmed states ────────────────────────────────────────────
    {
      selector: "node.dimmed",
      style: { opacity: 0.12, "text-opacity": 0.06, "overlay-opacity": 0 },
    },
    {
      selector: "edge.dimmed",
      style: { opacity: 0.03, "overlay-opacity": 0 },
    },
    // ── Selected node: bright halo ───────────────────────────────
    {
      selector: "node.selected-node",
      style: {
        "border-color": "#f8fafc",
        "border-width": 4,
        "border-opacity": 1,
        "background-opacity": 1,
        "overlay-color": "#f8fafc",
        "overlay-opacity": 0.1,
        "overlay-padding": 16,
        "text-background-opacity": 0.9,
        "text-outline-width": 1,
        "z-index": 20,
      },
    },
    // ── Neighbor nodes ───────────────────────────────────────────
    {
      selector: "node.neighbor-node",
      style: { opacity: 1, "text-opacity": 1, "background-opacity": 0.9, "overlay-opacity": 0.04 },
    },
    // ── Active edges ─────────────────────────────────────────────
    {
      selector: "edge.active-edge",
      style: { opacity: 0.85, "overlay-opacity": 0.04 },
    },
    // ── Selected edge ────────────────────────────────────────────
    {
      selector: "edge.selected-edge",
      style: {
        opacity: 1,
        width: (ele: EdgeSingular) => 3 + Number(ele.data("confidence") ?? 0.5) * 3,
        "line-color": "#f8fafc",
        "target-arrow-color": "#f8fafc",
        "arrow-scale": 1,
        "overlay-color": "#f8fafc",
        "overlay-opacity": 0.06,
        "overlay-padding": 8,
        "z-index": 20,
      },
    },
    // ── Path highlight ───────────────────────────────────────────
    {
      selector: "node.path-highlight",
      style: {
        "border-color": "#22d3ee",
        "border-width": 4,
        opacity: 1,
        "text-opacity": 1,
        "background-color": "#0e7490",
        "background-opacity": 1,
        "overlay-color": "#22d3ee",
        "overlay-opacity": 0.12,
        "overlay-padding": 14,
        "text-background-opacity": 0.9,
        "z-index": 15,
      },
    },
    {
      selector: "edge.path-highlight",
      style: {
        "line-color": "#22d3ee",
        "target-arrow-color": "#22d3ee",
        width: 4,
        opacity: 1,
        "line-style": "solid",
        "overlay-color": "#22d3ee",
        "overlay-opacity": 0.08,
        "z-index": 15,
      },
    },
    // ── Neo4j expanded ───────────────────────────────────────────
    {
      selector: "node.neo4j-expanded",
      style: {
        "border-color": "#a78bfa",
        "border-width": 2.5,
        "border-style": "dashed",
        "overlay-color": "#a78bfa",
        "overlay-opacity": 0.06,
      },
    },
    // ── Path source ──────────────────────────────────────────────
    {
      selector: "node.path-source",
      style: {
        "border-color": "#f59e0b",
        "border-width": 5,
        opacity: 1,
        "overlay-color": "#f59e0b",
        "overlay-opacity": 0.12,
        "overlay-padding": 14,
      },
    },
  ];
  return styles as unknown as cytoscape.StylesheetJson;
}

function applyLayout(
  cy: Core,
  layoutMode: LayoutMode,
  rootId?: string,
  onComplete?: () => void,
) {
  const largeGraph = cy.nodes().length > 220 || cy.edges().length > 320;
  const animate = cy.nodes().length <= 180 && cy.edges().length <= 260;
  const preserveViewport = !animate;
  const layoutPadding = largeGraph ? 18 : 48;
  const spacingFactor = largeGraph ? 0.62 : 1.05;

  if (layoutMode === "cola") {
    // Force-directed with edge length constraints for cleaner separation
    const layout = cy.layout({
      name: "cose",
      animate,
      animationDuration: animate ? 400 : 0,
      fit: !preserveViewport,
      padding: layoutPadding,
      nodeRepulsion: largeGraph ? 12000 : 32000,
      idealEdgeLength: largeGraph ? 90 : 180,
      edgeElasticity: largeGraph ? 40 : 80,
      gravity: largeGraph ? 0.15 : 0.08,
      componentSpacing: largeGraph ? 50 : 80,
      nestingFactor: 1.2,
      numIter: largeGraph ? 500 : 1000,
      coolingFactor: 0.95,
      minTemp: 1.0,
    });
    if (onComplete) {
      layout.one("layoutstop", onComplete);
    }
    layout.run();
    return;
  }

  if (layoutMode === "breadthfirst") {
    const root = rootId ? cy.getElementById(rootId) : cy.nodes().first();
    const layout = cy.layout({
      name: "breadthfirst",
      directed: false,
      animate,
      animationDuration: animate ? 240 : 0,
      fit: !preserveViewport,
      padding: layoutPadding,
      spacingFactor,
      roots: root.nonempty() ? [root.id()] : undefined,
    });
    if (onComplete) {
      layout.one("layoutstop", onComplete);
    }
    layout.run();
    return;
  }

  if (layoutMode === "concentric") {
    const layout = cy.layout({
      name: "concentric",
      animate,
      animationDuration: animate ? 220 : 0,
      fit: !preserveViewport,
      padding: layoutPadding,
      spacingFactor,
      concentric: (node) => {
        if (node.data("isRoot")) return 100;
        return 10 + Number(node.degree());
      },
      levelWidth: () => (largeGraph ? 28 : 10),
    });
    if (onComplete) {
      layout.one("layoutstop", onComplete);
    }
    layout.run();
    return;
  }

  const layout = cy.layout({
    name: "cose",
    animate,
    animationDuration: animate ? 280 : 0,
    fit: !preserveViewport,
    padding: layoutPadding,
    nodeRepulsion: largeGraph ? 1800 : 9000,
    idealEdgeLength: largeGraph ? 58 : 140,
    edgeElasticity: largeGraph ? 55 : 90,
    gravity: largeGraph ? 0.7 : 0.3,
    componentSpacing: largeGraph ? 22 : 40,
  });
  if (onComplete) {
    layout.one("layoutstop", onComplete);
  }
  layout.run();
}

function overviewZoom(cy: Core) {
  const nodeCount = cy.nodes().length;
  if (nodeCount > 550) return 0.42;
  if (nodeCount > 380) return 0.48;
  if (nodeCount > 220) return 0.58;
  return 0.95;
}

function clearFocus(cy: Core) {
  cy.elements().removeClass("dimmed selected-node neighbor-node active-edge selected-edge");
}

export function EntityGraph({
  entities,
  relationships,
  rootEntityId,
  width = 800,
  height = 560,
  onEntityClick,
  onRelationshipClick,
}: EntityGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const initialLayoutModeRef = useRef<LayoutMode>("concentric");
  const graphReadyRef = useRef(false);
  const selectedNodeRef = useRef<SelectedNodeSummary | null>(null);
  const selectedEdgeRef = useRef<SelectedEdgeSummary | null>(null);

  const [layoutMode, setLayoutMode] = useState<LayoutMode>("concentric");
  const [viewMode, setViewMode] = useState<ViewMode>("graph");
  const [searchQuery, setSearchQuery] = useState("");
  const [relationFilter, setRelationFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>("all");
  const [minConfidence, setMinConfidence] = useState(0.25);
  const [showSecondaryLinks, setShowSecondaryLinks] = useState(false);
  const [selectedNode, setSelectedNode] = useState<SelectedNodeSummary | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SelectedEdgeSummary | null>(null);
  const [pendingEdgeFocusId, setPendingEdgeFocusId] = useState<string | null>(null);
  const [showAllEdgeEvidence, setShowAllEdgeEvidence] = useState(false);
  const [tablePage, setTablePage] = useState(0);
  const [interactiveGraphKey, setInteractiveGraphKey] = useState<string | null>(null);
  const [showAdvancedControls, setShowAdvancedControls] = useState(false);
  const [showTemporalHeat, setShowTemporalHeat] = useState(false);
  const [hasCustomizedDenseView, setHasCustomizedDenseView] = useState(false);

  // Neo4j expand/path state
  const [neo4jAvailable, setNeo4jAvailable] = useState(false);
  const [expandedEntities, setExpandedEntities] = useState<GraphEntity[]>([]);
  const [expandedRelationships, setExpandedRelationships] = useState<GraphRelationship[]>([]);
  const [isExpanding, setIsExpanding] = useState(false);
  const [pathMode, setPathMode] = useState(false);
  const [pathSourceId, setPathSourceId] = useState<string | null>(null);
  const [highlightedPathIds, setHighlightedPathIds] = useState<string[]>([]);
  const [neo4jSyncing, setNeo4jSyncing] = useState(false);
  const [nodeRisk, setNodeRisk] = useState<{ risk_score: number; base_risk: string; connected_count: number } | null>(null);
  const [nodeCentrality, setNodeCentrality] = useState<{ degree: number; bridged: number; influence: number } | null>(null);
  const [loadingIntel, setLoadingIntel] = useState(false);
  const pathModeRef = useRef(false);
  const pathSourceIdRef = useRef<string | null>(null);
  const handleFindPathRef = useRef<((src: string, tgt: string) => void) | null>(null);

  // Check Neo4j availability on mount
  useEffect(() => {
    import("@/lib/api").then(({ fetchNeo4jHealth }) => {
      fetchNeo4jHealth().then((r) => setNeo4jAvailable(r.neo4j_available)).catch(() => {});
    });
  }, []);

  // Merge expanded entities/relationships with base data
  const mergedEntities = useMemo(() => {
    if (!expandedEntities.length) return entities;
    const existingIds = new Set(entities.map((e) => e.id));
    return [...entities, ...expandedEntities.filter((e) => !existingIds.has(e.id))];
  }, [entities, expandedEntities]);

  const mergedRelationships = useMemo(() => {
    if (!expandedRelationships.length) return relationships;
    const existingKeys = new Set(
      relationships.map((r) => `${r.source_entity_id}-${r.target_entity_id}-${r.rel_type}`)
    );
    return [
      ...relationships,
      ...expandedRelationships.filter(
        (r) => !existingKeys.has(`${r.source_entity_id}-${r.target_entity_id}-${r.rel_type}`)
      ),
    ];
  }, [relationships, expandedRelationships]);

  // Neo4j expand handler
  const handleExpandNode = useCallback(async (entityId: string) => {
    setIsExpanding(true);
    try {
      const { fetchNeo4jNeighbors } = await import("@/lib/api");
      const result = await fetchNeo4jNeighbors(entityId);
      const newEntities: GraphEntity[] = result.neighbors.map((n) => ({
        id: n.neighbor_id,
        canonical_name: n.neighbor_name,
        entity_type: n.entity_type,
        confidence: n.rel_confidence ?? 0.5,
      }));
      const newRels: GraphRelationship[] = result.neighbors.map((n) => ({
        source_entity_id: entityId,
        target_entity_id: n.neighbor_id,
        rel_type: n.rel_type,
        confidence: n.rel_confidence ?? 0.5,
        data_source: "neo4j",
      }));
      setExpandedEntities((prev) => [...prev, ...newEntities]);
      setExpandedRelationships((prev) => [...prev, ...newRels]);
    } catch (e) {
      console.error("Neo4j expand failed:", e);
    } finally {
      setIsExpanding(false);
    }
  }, []);

  // Neo4j find path handler
  const handleFindPath = useCallback(async (sourceId: string, targetId: string) => {
    try {
      const { fetchNeo4jPath } = await import("@/lib/api");
      const result = await fetchNeo4jPath(sourceId, targetId);
      if (result.path_found && result.nodes && result.nodes.length > 0) {
        const pathNodeIds = result.nodes.map((n) => n.id);
        setHighlightedPathIds(pathNodeIds);
        // Add path entities that might not be in the graph
        const newEntities: GraphEntity[] = result.nodes.map((n) => ({
          id: n.id,
          canonical_name: n.name,
          entity_type: n.type,
          confidence: 1,
        }));
        setExpandedEntities((prev) => [...prev, ...newEntities]);
        // Highlight the path in Cytoscape
        const cy = cyRef.current;
        if (cy) {
          cy.elements().removeClass("path-highlight");
          pathNodeIds.forEach((nid) => {
            cy.$(`node[id = "${nid}"]`).addClass("path-highlight");
          });
          for (let i = 0; i < pathNodeIds.length - 1; i++) {
            cy.edges().filter((e: EdgeSingular) => {
              const src = e.data("source");
              const tgt = e.data("target");
              return (
                (src === pathNodeIds[i] && tgt === pathNodeIds[i + 1]) ||
                (src === pathNodeIds[i + 1] && tgt === pathNodeIds[i])
              );
            }).addClass("path-highlight");
          }
        }
      }
    } catch (e) {
      console.error("Neo4j path failed:", e);
    } finally {
      setPathMode(false);
      setPathSourceId(null);
    }
  }, []);

  // Neo4j sync handler
  const handleNeo4jSync = useCallback(async () => {
    setNeo4jSyncing(true);
    try {
      const { triggerNeo4jSync } = await import("@/lib/api");
      await triggerNeo4jSync();
    } catch (e) {
      console.error("Neo4j sync failed:", e);
    } finally {
      setNeo4jSyncing(false);
    }
  }, []);

  // Load risk + centrality when a node is selected (Neo4j)
  useEffect(() => {
    if (!selectedNode || !neo4jAvailable) {
      setNodeRisk(null);
      setNodeCentrality(null);
      return;
    }
    setLoadingIntel(true);
    setNodeRisk(null);
    setNodeCentrality(null);
    Promise.all([
      import("@/lib/api").then(({ fetchNeo4jRisk }) => fetchNeo4jRisk(selectedNode.id)).catch(() => null),
      import("@/lib/api").then(({ fetchNeo4jCentrality }) => fetchNeo4jCentrality(selectedNode.id)).catch(() => null),
    ]).then(([risk, centrality]) => {
      if (risk && risk.risk_score !== undefined) {
        setNodeRisk({ risk_score: risk.risk_score, base_risk: risk.base_risk, connected_count: risk.connected_risks?.length ?? 0 });
      }
      if (centrality && centrality.degree_centrality !== undefined) {
        setNodeCentrality({ degree: centrality.degree_centrality, bridged: centrality.bridged_entities, influence: centrality.influence_score });
      }
      setLoadingIntel(false);
    });
  }, [selectedNode, neo4jAvailable]);

  // Keep refs in sync for Cytoscape tap handler closures
  useEffect(() => { pathModeRef.current = pathMode; }, [pathMode]);
  useEffect(() => { pathSourceIdRef.current = pathSourceId; }, [pathSourceId]);
  useEffect(() => { handleFindPathRef.current = handleFindPath; }, [handleFindPath]);

  useEffect(() => {
    initialLayoutModeRef.current = layoutMode;
  }, [layoutMode]);

  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  useEffect(() => {
    selectedEdgeRef.current = selectedEdge;
  }, [selectedEdge]);

  const resolvedRootId = useMemo(() => resolveRootId(mergedEntities, rootEntityId), [mergedEntities, rootEntityId]);
  const normalizedRelationships = useMemo(() => normalizeRelationships(mergedRelationships), [mergedRelationships]);
  const filteredRelationships = useMemo(
    () => filterRelationships(normalizedRelationships, relationFilter, minConfidence),
    [minConfidence, normalizedRelationships, relationFilter],
  );
  const denseNetworkRecommendedPriority = useMemo(
    () => recommendedPriorityFilter(filteredRelationships.length),
    [filteredRelationships.length],
  );
  const denseScopeEntityCount = useMemo(
    () => countVisibleEntities(filteredRelationships, resolvedRootId),
    [filteredRelationships, resolvedRootId],
  );
  const isDenseNetwork = denseScopeEntityCount > 220 || filteredRelationships.length > 320;
  const effortlessModeActive = isDenseNetwork && !hasCustomizedDenseView;
  const effectiveLayoutMode = effortlessModeActive ? "concentric" : layoutMode;
  const effectiveShowSecondaryLinks = effortlessModeActive ? false : showSecondaryLinks;
  const effectivePriorityFilter = effortlessModeActive ? denseNetworkRecommendedPriority : priorityFilter;
  const effectiveViewMode = effortlessModeActive ? "graph" : viewMode;
  const scopedRelationships = useMemo(
    () => filterRelationshipsByDepth(filteredRelationships, resolvedRootId, maxDepthForLayout(effectiveLayoutMode, effectiveShowSecondaryLinks)),
    [effectiveLayoutMode, effectiveShowSecondaryLinks, filteredRelationships, resolvedRootId],
  );
  const prioritizedRelationships = useMemo(
    () => prioritizeRelationships(scopedRelationships, resolvedRootId),
    [resolvedRootId, scopedRelationships],
  );
  const visibleRelationships = useMemo(
    () => filterRelationshipsByPriority(prioritizedRelationships, effectivePriorityFilter),
    [effectivePriorityFilter, prioritizedRelationships],
  );
  const renderableEntityMap = useMemo(
    () => buildRenderableEntityMap(entities, visibleRelationships),
    [entities, visibleRelationships],
  );
  const graphElements = useMemo(
    () => (effectiveViewMode === "graph" ? buildElements(renderableEntityMap, visibleRelationships, resolvedRootId) : []),
    [effectiveViewMode, visibleRelationships, renderableEntityMap, resolvedRootId],
  );
  const stackInspector = width < 720;
  const visibleEntityCount = useMemo(
    () => countVisibleEntities(visibleRelationships, resolvedRootId),
    [visibleRelationships, resolvedRootId],
  );
  const isLargeGraph = visibleEntityCount > 220 || visibleRelationships.length > 320;
  const currentGraphKey = `${resolvedRootId ?? "none"}:${visibleRelationships.length}:${visibleEntityCount}:${effectivePriorityFilter}`;
  const interactiveReady = !isLargeGraph || interactiveGraphKey === currentGraphKey;
  const tablePageSize = isLargeGraph ? 12 : 24;
  const totalTablePages = Math.max(1, Math.ceil(visibleRelationships.length / tablePageSize));
  const effectiveTablePage = Math.min(tablePage, totalTablePages - 1);
  const pagedRelationships = useMemo(() => {
    const start = effectiveTablePage * tablePageSize;
    return visibleRelationships.slice(start, start + tablePageSize);
  }, [effectiveTablePage, visibleRelationships, tablePageSize]);
  const selectedEdgeEvidence = useMemo(() => {
    if (!selectedEdge) return [];
    const snippets = selectedEdge.evidenceSnippets.length > 0 ? selectedEdge.evidenceSnippets : [selectedEdge.evidence];
    return snippets.filter(Boolean);
  }, [selectedEdge]);
  const selectedEdgeClaims = useMemo(
    () => selectedEdge?.claimRecords ?? [],
    [selectedEdge],
  );
  const visibleSelectedEdgeEvidence = useMemo(
    () => (showAllEdgeEvidence ? selectedEdgeEvidence : selectedEdgeEvidence.slice(0, 2)),
    [selectedEdgeEvidence, showAllEdgeEvidence],
  );
  const priorityFilterMeta = useMemo(() => describePriorityFilter(effectivePriorityFilter), [effectivePriorityFilter]);
  const hiddenByPriorityCount = Math.max(0, prioritizedRelationships.length - visibleRelationships.length);
  const useEffortlessControls = isDenseNetwork && !showAdvancedControls;

  const focusNode = useCallback((
    cy: Core,
    node: NodeSingular,
    viewportMode: ViewportMode = "neighborhood",
    animateViewport = true,
  ) => {
    const shouldAnimateViewport = animateViewport && cy.nodes().length <= 180 && cy.edges().length <= 260;
    clearFocus(cy);
    const neighborhood = node.closedNeighborhood();
    cy.elements().addClass("dimmed");
    neighborhood.removeClass("dimmed");
    node.addClass("selected-node");
    neighborhood.nodes().difference(node).addClass("neighbor-node");
    neighborhood.edges().addClass("active-edge");

    setSelectedEdge(null);
    setShowAllEdgeEvidence(false);
    setSelectedNode({
      id: node.id(),
      label: String(node.data("label")),
      fullLabel: String(node.data("fullLabel")),
      type: String(node.data("type")),
      confidence: Number(node.data("confidence") ?? 0),
      country: String(node.data("country") ?? ""),
      connectionCount: node.connectedEdges().length,
    });

    if (viewportMode === "none") {
      return;
    }

    if (viewportMode === "pan") {
      if (shouldAnimateViewport) {
        cy.animate({
          center: { eles: node },
          duration: 160,
        });
      } else {
        cy.center(node);
      }
      return;
    }

    if (viewportMode === "center") {
      const targetZoom = Math.min(cy.maxZoom(), Math.max(cy.minZoom(), overviewZoom(cy)));
      if (shouldAnimateViewport) {
        cy.animate({
          center: { eles: node },
          zoom: targetZoom,
          duration: 160,
        });
      } else {
        cy.center(node);
        cy.zoom(targetZoom);
      }
      return;
    }

    if (shouldAnimateViewport) {
      cy.animate({
        fit: { eles: neighborhood, padding: 84 },
        duration: 200,
      });
    } else {
      cy.fit(neighborhood, 84);
    }
  }, []);

  const focusEdge = useCallback((
    cy: Core,
    edge: EdgeSingular,
    viewportMode: EdgeViewportMode = "fit",
    animateViewport = true,
  ) => {
    const shouldAnimateViewport = animateViewport && cy.nodes().length <= 180 && cy.edges().length <= 260;
    clearFocus(cy);
    const path = edge.connectedNodes().union(edge);
    cy.elements().addClass("dimmed");
    path.removeClass("dimmed");
    edge.connectedNodes().addClass("selected-node");
    edge.addClass("selected-edge");

    setSelectedNode(null);
    setShowAllEdgeEvidence(false);
    setSelectedEdge({
      id: edge.id(),
      sourceId: String(edge.data("source")),
      targetId: String(edge.data("target")),
      sourceLabel: String(edge.source().data("fullLabel") || edge.source().data("label")),
      targetLabel: String(edge.target().data("fullLabel") || edge.target().data("label")),
      relType: String(edge.data("relType")),
      relLabel: String(edge.data("relLabel")),
      family: String(edge.data("family")),
      familyLabel: String(edge.data("familyLabel")),
      confidence: Number(edge.data("confidence") ?? 0),
      dataSource: String(edge.data("dataSource") ?? ""),
      evidence: String(edge.data("evidence") ?? ""),
      evidenceSummary: String(edge.data("evidenceSummary") ?? ""),
      createdAt: String(edge.data("createdAt") ?? ""),
      corroborationCount: Number(edge.data("corroborationCount") ?? 1),
      dataSources: Array.isArray(edge.data("dataSources")) ? edge.data("dataSources") : [],
      evidenceSnippets: Array.isArray(edge.data("evidenceSnippets")) ? edge.data("evidenceSnippets") : [],
      firstSeenAt: String(edge.data("firstSeenAt") ?? ""),
      lastSeenAt: String(edge.data("lastSeenAt") ?? ""),
      claimRecords: Array.isArray(edge.data("claimRecords")) ? edge.data("claimRecords") : [],
      priorityScore: Number(edge.data("priorityScore") ?? 0),
      priorityLabel: String(edge.data("priorityLabel") ?? PRIORITY_META.context.label),
    });

    if (viewportMode === "none") {
      return;
    }

    if (viewportMode === "pan") {
      if (shouldAnimateViewport) {
        cy.animate({
          center: { eles: path },
          duration: 160,
        });
      } else {
        cy.center(path);
      }
      return;
    }

    if (shouldAnimateViewport) {
      cy.animate({
        fit: { eles: path, padding: 110 },
        duration: 180,
      });
    } else {
      cy.fit(path, 110);
    }
  }, []);

  const resetView = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    clearFocus(cy);
    setSelectedNode(null);
    setSelectedEdge(null);
    setShowAllEdgeEvidence(false);
    cy.elements().removeClass("dimmed");
    const root = resolvedRootId ? cy.getElementById(resolvedRootId) : cy.nodes().first();
    if (root.nonempty()) {
      focusNode(cy, root, "center", false);
      return;
    }
    cy.fit(cy.elements(), 48);
  }, [focusNode, resolvedRootId]);

  const centerRoot = useCallback(() => {
    const cy = cyRef.current;
    if (!cy || !resolvedRootId) return;
    const root = cy.getElementById(resolvedRootId);
    if (root.nonempty()) {
      focusNode(cy, root, "center");
    }
  }, [focusNode, resolvedRootId]);

  const runSearch = useCallback(() => {
    const cy = cyRef.current;
    const needle = searchQuery.trim().toLowerCase();
    if (!cy || !needle) return;

    const matches = cy.nodes().filter((node) => {
      const label = String(node.data("fullLabel") ?? node.data("label") ?? "").toLowerCase();
      const country = String(node.data("country") ?? "").toLowerCase();
      return label.includes(needle) || country.includes(needle) || node.id().toLowerCase().includes(needle);
    });

    if (matches.length > 0) {
      focusNode(cy, matches[0]);
    }
  }, [focusNode, searchQuery]);

  useEffect(() => {
    if (effectiveViewMode !== "graph" || !interactiveReady) {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
      graphReadyRef.current = false;
      return;
    }

    if (!containerRef.current || !graphElements.length) return;

    graphReadyRef.current = false;

    const cy = cytoscape({
      container: containerRef.current,
      elements: graphElements,
      style: buildStyles(),
      minZoom: 0.45,
      maxZoom: 2.1,
      boxSelectionEnabled: false,
      autoungrabify: false,
      userPanningEnabled: true,
      userZoomingEnabled: false,
      textureOnViewport: true,
      hideEdgesOnViewport: false,
      motionBlur: false,
      pixelRatio: "auto",
    });

    cyRef.current = cy;

    cy.on("tap", "node", (event) => {
      const node = event.target;
      const nodeId = node.id();

      // Path mode: if active and we have a source, find path to this node
      if (pathModeRef.current && pathSourceIdRef.current && pathSourceIdRef.current !== nodeId) {
        if (handleFindPathRef.current) {
          handleFindPathRef.current(pathSourceIdRef.current, nodeId);
        }
        return;
      }
      // Path mode: if active but no source yet, set this as source
      if (pathModeRef.current && !pathSourceIdRef.current) {
        setPathSourceId(nodeId);
        cy.elements().removeClass("path-source");
        node.addClass("path-source");
        return;
      }

      focusNode(cy, node, isLargeGraph ? "none" : "neighborhood");
      const entity = entities.find((candidate) => candidate.id === nodeId);
      if (entity && onEntityClick) onEntityClick(entity);
    });

    cy.on("tap", "edge", (event) => {
      focusEdge(cy, event.target, isLargeGraph ? "none" : "fit", !isLargeGraph);
      const edgeId = event.target.id();
      const rawId = Number(edgeId);
      if (onRelationshipClick && !isNaN(rawId)) {
        onRelationshipClick(rawId);
      }
    });

    cy.on("tap", (event) => {
      if (event.target === cy) {
        resetView();
      }
    });

    cy.on("mouseover", "node", (event) => { event.target.addClass("hovered"); if (containerRef.current) containerRef.current.style.cursor = "pointer"; });
    cy.on("mouseout", "node", (event) => { event.target.removeClass("hovered"); if (containerRef.current) containerRef.current.style.cursor = "default"; });
    cy.on("mouseover", "edge", (event) => { event.target.addClass("hovered"); if (containerRef.current) containerRef.current.style.cursor = "pointer"; });
    cy.on("mouseout", "edge", (event) => { event.target.removeClass("hovered"); if (containerRef.current) containerRef.current.style.cursor = "default"; });

    requestAnimationFrame(() => {
      applyLayout(cy, initialLayoutModeRef.current, resolvedRootId, () => {
        requestAnimationFrame(() => {
          const root = resolvedRootId ? cy.getElementById(resolvedRootId) : cy.nodes().first();
          if (root.nonempty()) {
            focusNode(cy, root, "center", false);
          } else {
            cy.fit(cy.elements(), 48);
          }
          graphReadyRef.current = true;
        });
      });
    });

    return () => {
      graphReadyRef.current = false;
      cy.destroy();
      cyRef.current = null;
    };
  }, [effectiveViewMode, entities, focusEdge, focusNode, graphElements, interactiveReady, isLargeGraph, onEntityClick, onRelationshipClick, resetView, resolvedRootId]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !graphReadyRef.current) return;

    requestAnimationFrame(() => {
      applyLayout(cy, layoutMode, resolvedRootId, () => {
        requestAnimationFrame(() => {
          const selectedEdgeSnapshot = selectedEdgeRef.current;
          if (selectedEdgeSnapshot) {
            const edge = cy.getElementById(selectedEdgeSnapshot.id);
            if (edge.nonempty() && edge.isEdge()) {
              focusEdge(cy, edge, isLargeGraph ? "pan" : "fit", false);
              return;
            }
          }

          const selectedNodeSnapshot = selectedNodeRef.current;
          if (selectedNodeSnapshot) {
            const node = cy.getElementById(selectedNodeSnapshot.id);
            if (node.nonempty() && node.isNode()) {
              focusNode(cy, node, isLargeGraph ? "pan" : "center", false);
              return;
            }
          }

          const root = resolvedRootId ? cy.getElementById(resolvedRootId) : cy.nodes().first();
          if (root.nonempty()) {
            focusNode(cy, root, "center", false);
          } else {
            cy.fit(cy.elements(), 48);
          }
        });
      });
    });
  }, [focusEdge, focusNode, isLargeGraph, layoutMode, resolvedRootId]);

  // Temporal heat: adjust edge opacity based on recency
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !graphReadyRef.current) return;
    cy.edges().forEach((edge) => {
      const recency = Number(edge.data("temporalRecency") ?? 0.5);
      const conf = Number(edge.data("confidence") ?? 0.5);
      if (showTemporalHeat) {
        edge.style("opacity", Math.max(0.08, recency * 0.7));
        // Warm = recent (gold), cool = old (blue-gray)
        if (recency >= 0.8) edge.style("line-color", "#c4a052");
        else if (recency >= 0.5) edge.style("line-color", "#7a8a5c");
        else edge.style("line-color", "#4a6080");
      } else {
        edge.style("opacity", 0.15 + conf * 0.35);
        edge.style("line-color", edge.data("lineColor"));
      }
    });
  }, [showTemporalHeat]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !pendingEdgeFocusId) return;
    const edge = cy.getElementById(pendingEdgeFocusId);
    if (edge.nonempty() && edge.isEdge()) {
      focusEdge(cy, edge, isLargeGraph ? "pan" : "fit");
      setPendingEdgeFocusId(null);
    }
  }, [focusEdge, isLargeGraph, pendingEdgeFocusId]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    requestAnimationFrame(() => {
      cy.resize();
    });
  }, [height, width]);

  const typesSeen = useMemo(() => {
    return Array.from(new Set(entities.map((entity) => entity.entity_type || "unknown")));
  }, [entities]);

  const relsSeen = useMemo(() => {
    return Array.from(new Set(visibleRelationships.map((relationship) => relationship.rel_type)));
  }, [visibleRelationships]);

  const relationFamiliesSeen = useMemo(() => {
    return Array.from(new Set(visibleRelationships.map((relationship) => relationship.family))).map((family) => ({
      family,
      ...REL_FAMILY_META[family],
    }));
  }, [visibleRelationships]);

  if (!entities.length) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height,
          border: `1px solid ${T.border}`,
          borderRadius: 16,
          background: T.bg,
          color: T.muted,
          fontSize: FS.sm,
        }}
      >
        No graph data available. Run an assessment to populate the knowledge graph.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        className="rounded-xl p-3 glass-card"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 10px",
              borderRadius: 10,
              background: T.raised,
              border: `1px solid ${T.border}`,
              minWidth: 240,
            }}
          >
            <Search size={14} color={T.muted} />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") runSearch();
              }}
              placeholder="Search entities"
              style={{
                flex: 1,
                minWidth: 120,
                background: "transparent",
                border: "none",
                outline: "none",
                color: T.text,
                fontSize: FS.sm,
              }}
            />
            <button
              onClick={runSearch}
              className="cursor-pointer"
              style={{
                border: "none",
                background: "transparent",
                color: T.accent,
                fontSize: FS.sm,
                fontWeight: 700,
              }}
            >
              Find
            </button>
          </div>

          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {([
              ["graph", "Graph"],
              ["table", "Table"],
            ] as const).map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => {
                  setViewMode(mode);
                  if (isDenseNetwork) setHasCustomizedDenseView(true);
                  if (mode === "table") {
                    setTablePage(0);
                    setInteractiveGraphKey(null);
                  }
                }}
                className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: effectiveViewMode === mode ? `${GOLD}18` : T.raised,
                  color: effectiveViewMode === mode ? GOLD : T.dim,
                  borderColor: effectiveViewMode === mode ? `${GOLD}44` : T.border,
                  fontWeight: 600,
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {useEffortlessControls ? (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {EFFORTLESS_PRIORITY_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => {
                    setPriorityFilter(preset.value);
                    setTablePage(0);
                    setHasCustomizedDenseView(true);
                  }}
                  className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                    style={{
                      padding: "7px 10px",
                      fontSize: FS.sm,
                    background: effectivePriorityFilter === preset.value ? `${GOLD}18` : T.raised,
                    color: effectivePriorityFilter === preset.value ? GOLD : T.dim,
                    borderColor: effectivePriorityFilter === preset.value ? `${GOLD}44` : T.border,
                      fontWeight: 600,
                    }}
                >
                  {preset.label}
                </button>
              ))}
              <button
                onClick={() => {
                  setShowAdvancedControls(true);
                  setHasCustomizedDenseView(true);
                }}
                className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: T.raised,
                  color: T.text,
                  borderColor: T.border,
                  fontWeight: 600,
                }}
              >
                More controls
              </button>
            </div>
          ) : (
            <>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {([
                  ["concentric", "Focused"],
                  ["breadthfirst", "Trace"],
                  ["cose", "Explore"],
                  ["cola", "Force"],
                ] as const).map(([mode, label]) => (
                  <button
                    key={mode}
                    onClick={() => {
                      setLayoutMode(mode);
                      setTablePage(0);
                      if (isDenseNetwork) setHasCustomizedDenseView(true);
                    }}
                    className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                    style={{
                      padding: "7px 10px",
                      fontSize: FS.sm,
                      background: effectiveLayoutMode === mode ? `${T.accent}18` : T.raised,
                      color: effectiveLayoutMode === mode ? T.accent : T.dim,
                      borderColor: effectiveLayoutMode === mode ? `${T.accent}44` : T.border,
                      fontWeight: 600,
                    }}
                    >
                      {label}
                    </button>
                ))}
              </div>

              {effectiveLayoutMode === "concentric" && (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {([
                    [false, "Primary only"],
                    [true, "Include secondary"],
                  ] as const).map(([enabled, label]) => (
                    <button
                      key={label}
                      onClick={() => {
                        setShowSecondaryLinks(enabled);
                        setTablePage(0);
                        if (isDenseNetwork) setHasCustomizedDenseView(true);
                      }}
                      className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                      style={{
                        padding: "7px 10px",
                        fontSize: FS.sm,
                        background: effectiveShowSecondaryLinks === enabled ? `${GOLD}18` : T.raised,
                        color: effectiveShowSecondaryLinks === enabled ? GOLD : T.dim,
                        borderColor: effectiveShowSecondaryLinks === enabled ? `${GOLD}44` : T.border,
                        fontWeight: 600,
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}

              <select
                value={effectivePriorityFilter}
                onChange={(event) => {
                  setPriorityFilter(event.target.value as PriorityFilter);
                  setTablePage(0);
                  if (isDenseNetwork) setHasCustomizedDenseView(true);
                }}
                className="rounded-lg outline-none cursor-pointer focus-ring"
                style={{
                  padding: "8px 10px",
                  fontSize: FS.sm,
                  background: T.raised,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              >
                <option value="all">All priorities</option>
                <option value="decision">Decision edges</option>
                <option value="material_plus">Material + decision</option>
                <option value="relevant_plus">Relevant and above</option>
              </select>

              <select
                value={relationFilter}
                onChange={(event) => {
                  setRelationFilter(event.target.value);
                  setTablePage(0);
                  if (isDenseNetwork) setHasCustomizedDenseView(true);
                }}
                className="rounded-lg outline-none cursor-pointer focus-ring"
                style={{
                  padding: "8px 10px",
                  fontSize: FS.sm,
                  background: T.raised,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              >
                <option value="all">All relations</option>
                {relsSeen.map((rel) => (
                  <option key={rel} value={rel}>
                    {getRelationshipLabel(rel)}
                  </option>
                ))}
              </select>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 10px",
                  borderRadius: 10,
                  background: T.raised,
                  border: `1px solid ${T.border}`,
                }}
              >
                <span style={{ fontSize: FS.sm, color: T.muted }}>Min confidence</span>
                <input
                  type="range"
                  min={0}
                  max={0.9}
                  step={0.05}
                  value={minConfidence}
                  onChange={(event) => {
                    setMinConfidence(Number(event.target.value));
                    setTablePage(0);
                    if (isDenseNetwork) setHasCustomizedDenseView(true);
                  }}
                  style={{ width: 120 }}
                />
                <span style={{ fontSize: FS.sm, color: T.text, fontVariantNumeric: "tabular-nums" }}>
                  {Math.round(minConfidence * 100)}%
                </span>
              </div>

              <button
                onClick={() => setShowTemporalHeat(!showTemporalHeat)}
                className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: showTemporalHeat ? `${GOLD}18` : T.raised,
                  color: showTemporalHeat ? GOLD : T.dim,
                  borderColor: showTemporalHeat ? `${GOLD}44` : T.border,
                  fontWeight: 600,
                }}
              >
                Temporal heat
              </button>

              {isDenseNetwork && (
                <button
                  onClick={() => setShowAdvancedControls(false)}
                  className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                  style={{
                    padding: "7px 10px",
                    fontSize: FS.sm,
                    background: T.raised,
                    color: T.text,
                    borderColor: T.border,
                    fontWeight: 600,
                  }}
                >
                  Simplify controls
                </button>
              )}
            </>
          )}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            padding: "8px 10px",
            borderRadius: 10,
            background: priorityFilterMeta.background,
            border: `1px solid ${T.border}`,
          }}
        >
          <span
            style={{
              padding: "4px 8px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 700,
              color: priorityFilterMeta.color,
              background: T.surface,
            }}
          >
            {priorityFilterMeta.label}
          </span>
          <span style={{ fontSize: FS.sm, color: T.dim }}>
            {priorityFilterMeta.description}
          </span>
          {hiddenByPriorityCount > 0 && (
            <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
              Hiding {hiddenByPriorityCount} lower-priority relationships.
            </span>
          )}
          {useEffortlessControls && (
            <span style={{ fontSize: FS.sm, color: T.dim }}>
              Dense-case effortless mode is active: root-first, primary links first, advanced controls tucked away.
            </span>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 999,
              background: `${GOLD}14`,
              color: GOLD,
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {visibleEntityCount} entities
          </div>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 999,
              background: `${T.accent}14`,
              color: T.accent,
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {visibleRelationships.length} relationships
          </div>
          <button
            onClick={centerRoot}
            className="rounded border cursor-pointer"
            style={{
              padding: "7px 10px",
              fontSize: FS.sm,
              background: T.raised,
              color: T.text,
              borderColor: T.border,
              fontWeight: 600,
            }}
          >
            Center root
          </button>
          <button
            onClick={resetView}
            className="rounded border cursor-pointer"
            style={{
              padding: "7px 10px",
              fontSize: FS.sm,
              background: T.raised,
              color: T.text,
              borderColor: T.border,
              fontWeight: 600,
            }}
          >
            Reset view
          </button>

          {neo4jAvailable && (
            <>
              <div style={{ width: 1, height: 18, background: T.border, alignSelf: "center" }} />
              <button
                onClick={handleNeo4jSync}
                disabled={neo4jSyncing}
                className="rounded border cursor-pointer"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: neo4jSyncing ? `#a78bfa18` : T.raised,
                  color: neo4jSyncing ? "#a78bfa" : "#a78bfa",
                  borderColor: "#a78bfa44",
                  fontWeight: 600,
                  opacity: neo4jSyncing ? 0.6 : 1,
                }}
              >
                {neo4jSyncing ? "Syncing..." : "Sync Neo4j"}
              </button>
              <button
                onClick={() => {
                  if (pathMode) {
                    setPathMode(false);
                    setPathSourceId(null);
                    const cy = cyRef.current;
                    if (cy) cy.elements().removeClass("path-source");
                  } else {
                    setPathMode(true);
                  }
                }}
                className="rounded border cursor-pointer"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: pathMode ? `#22d3ee18` : T.raised,
                  color: pathMode ? "#22d3ee" : "#22d3ee",
                  borderColor: pathMode ? "#22d3ee66" : "#22d3ee44",
                  fontWeight: 600,
                }}
              >
                {pathMode ? "Exit Path Mode" : "Path Mode"}
              </button>
              {(expandedEntities.length > 0 || highlightedPathIds.length > 0) && (
                <button
                  onClick={() => {
                    setExpandedEntities([]);
                    setExpandedRelationships([]);
                    setHighlightedPathIds([]);
                    setPathMode(false);
                    setPathSourceId(null);
                    const cy = cyRef.current;
                    if (cy) cy.elements().removeClass("path-highlight path-source neo4j-expanded");
                  }}
                  className="rounded border cursor-pointer"
                  style={{
                    padding: "7px 10px",
                    fontSize: FS.sm,
                    background: T.raised,
                    color: T.dim,
                    borderColor: T.border,
                    fontWeight: 600,
                  }}
                >
                  Clear Neo4j
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {viewMode === "graph" ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: stackInspector ? "1fr" : "minmax(0, 1fr) 300px",
            gap: 12,
            alignItems: "stretch",
          }}
        >
          <div
            className="rounded-xl"
            style={{
              position: "relative",
              overflow: "hidden",
              border: "1px solid rgba(196,160,82,0.12)",
              background: GRAPH_BG,
              backgroundImage: GRAPH_BG_GLOW,
              minHeight: height,
              boxShadow: "0 0 40px 2px rgba(196,160,82,0.04), 0 2px 16px rgba(0,0,0,0.4)",
            }}
          >
            {/* Ambient overlays */}
            <div className="graph-grid-overlay" />
            <div className="graph-vignette" />
            <div className="graph-scanline" />
            <div className="graph-corner-accents" />
            <div className="graph-corner-accents-b" />
            {!interactiveReady ? (
              <div
                style={{
                  width: "100%",
                  height,
                  padding: 28,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  gap: 18,
                }}
              >
                <div style={{ maxWidth: 560 }}>
                  <div style={{ fontSize: FS.lg, fontWeight: 700, color: T.text, marginBottom: 8 }}>
                    Large network ready
                  </div>
                  <div style={{ fontSize: FS.base, color: T.dim, lineHeight: 1.65 }}>
                    This graph is dense enough to freeze the page if we boot the full explorer immediately. Start in table view or launch the interactive graph when you want the visual network.
                  </div>
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <div className="rounded-full px-3 py-2" style={{ background: `${GOLD}14`, color: GOLD, fontSize: FS.sm, fontWeight: 700 }}>
                    {visibleEntityCount} entities
                  </div>
                  <div className="rounded-full px-3 py-2" style={{ background: `${T.accent}14`, color: T.accent, fontSize: FS.sm, fontWeight: 700 }}>
                    {visibleRelationships.length} relationships
                  </div>
                  <div
                    className="rounded-full px-3 py-2"
                    style={{
                      background: priorityFilterMeta.background,
                      color: priorityFilterMeta.color,
                      fontSize: FS.sm,
                      fontWeight: 700,
                    }}
                  >
                    {priorityFilterMeta.label}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button
                    onClick={() => setInteractiveGraphKey(currentGraphKey)}
                    className="rounded-lg border cursor-pointer btn-interactive"
                    style={{
                      padding: "10px 14px",
                      fontSize: FS.sm,
                      background: `${GOLD}18`,
                      color: GOLD,
                      borderColor: `${GOLD}44`,
                      fontWeight: 700,
                      boxShadow: `0 0 16px 2px rgba(196,160,82,0.08)`,
                    }}
                  >
                    Open interactive graph
                  </button>
                  <button
                    onClick={() => setViewMode("table")}
                    className="rounded border cursor-pointer"
                    style={{
                      padding: "10px 14px",
                      fontSize: FS.sm,
                      background: T.raised,
                      color: T.text,
                      borderColor: T.border,
                      fontWeight: 600,
                    }}
                  >
                    Open table view
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div
                  ref={containerRef}
                  style={{
                    position: "relative",
                    zIndex: 5,
                    width: "100%",
                    height,
                  }}
                />
                {/* Floating status bar */}
                <div
                  style={{
                    position: "absolute",
                    bottom: 10,
                    left: "50%",
                    transform: "translateX(-50%)",
                    display: "flex",
                    gap: 12,
                    padding: "5px 14px",
                    borderRadius: 999,
                    background: "rgba(7,17,25,0.8)",
                    backdropFilter: "blur(12px)",
                    border: "1px solid rgba(196,160,82,0.12)",
                    zIndex: 10,
                    pointerEvents: "none",
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: GOLD, letterSpacing: "0.04em" }}>
                    {visibleEntityCount} entities
                  </span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: T.accent, letterSpacing: "0.04em" }}>
                    {visibleRelationships.length} links
                  </span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: T.dim, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {effectiveLayoutMode}
                  </span>
                </div>
                {pathMode && (
                  <div
                    style={{
                      position: "absolute",
                      top: 12,
                      left: "50%",
                      transform: "translateX(-50%)",
                      padding: "8px 16px",
                      borderRadius: 999,
                      background: "#0e7490ee",
                      color: "#e0f2fe",
                      fontSize: FS.sm,
                      fontWeight: 700,
                      zIndex: 20,
                      pointerEvents: "none",
                      boxShadow: "0 4px 24px rgba(0,0,0,0.4)",
                    }}
                  >
                    {pathSourceId
                      ? "Click a target node to find the shortest path"
                      : "Click a source node to begin path finding"}
                  </div>
                )}
                <div
                  style={{
                    position: "absolute",
                    left: 12,
                    top: 12,
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    pointerEvents: "auto",
                  }}
                >
                  <div
                    style={{
                      padding: "6px 10px",
                      borderRadius: 999,
                      background: "rgba(7,17,25,0.8)",
                      border: "1px solid rgba(196,160,82,0.12)",
                      color: T.text,
                      fontSize: 11,
                      fontWeight: 700,
                      backdropFilter: "blur(12px)",
                      letterSpacing: "0.04em",
                      boxShadow: "0 2px 12px rgba(0,0,0,0.3)",
                    }}
                  >
                    {describeScope(layoutMode, showSecondaryLinks)}
                  </div>
                  {resolvedRootId && (
                    <button
                      onClick={centerRoot}
                      style={{
                        padding: "6px 10px",
                        borderRadius: 999,
                        background: "rgba(196,160,82,0.16)",
                        border: `1px solid rgba(196,160,82,0.32)`,
                        color: GOLD,
                        fontSize: 12,
                        fontWeight: 700,
                        backdropFilter: "blur(10px)",
                        cursor: "pointer",
                      }}
                    >
                      Root anchored
                    </button>
                  )}
                </div>
              </>
            )}
          </div>

          <div
            className="rounded-xl p-4 glass-card"
            style={{
              minHeight: height,
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
          <div>
            <div style={{ fontSize: FS.sm, color: GOLD, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Graph Inspector
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 6, lineHeight: 1.6 }}>
              {effectivePriorityFilter === "all"
                ? "Select a node to understand its neighborhood or select an edge to see the relationship clearly without canvas label clutter."
                : `${priorityFilterMeta.label} is active. The inspector is focused on the highest-signal slice of the network.`}
            </div>
          </div>

          {selectedNode && (
            <div
              className="rounded-xl p-4"
              style={{
                background: T.raised,
                border: `1px solid ${T.border}`,
                boxShadow: `inset 0 0 0 1px ${T.border}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 999,
                    background: getTypeMeta(selectedNode.type).fill,
                    border: `1px solid ${getTypeMeta(selectedNode.type).stroke}`,
                    boxShadow: `0 0 16px ${getTypeMeta(selectedNode.type).stroke}44`,
                  }}
                />
                <div style={{ fontSize: FS.sm, color: T.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Node
                </div>
              </div>
              <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, lineHeight: 1.35 }}>
                {selectedNode.fullLabel}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
                <span style={{ padding: "4px 8px", borderRadius: 999, fontSize: 12, color: getTypeMeta(selectedNode.type).stroke, background: `${getTypeMeta(selectedNode.type).stroke}14` }}>
                  {getTypeMeta(selectedNode.type).label}
                </span>
                {selectedNode.country && (
                  <span style={{ padding: "4px 8px", borderRadius: 999, fontSize: 12, color: T.dim, background: T.bg }}>
                    {selectedNode.country}
                  </span>
                )}
              </div>
              <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Confidence</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {Math.round(selectedNode.confidence * 100)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Connections</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {selectedNode.connectionCount}
                  </div>
                </div>
              </div>
              {/* Neo4j Intelligence Panel */}
              {neo4jAvailable && (nodeRisk || nodeCentrality || loadingIntel) && (
                <div
                  style={{
                    marginTop: 14,
                    padding: "10px 12px",
                    borderRadius: 10,
                    background: `${T.bg}`,
                    border: `1px solid ${T.border}`,
                  }}
                >
                  <div style={{ fontSize: 11, color: "#a78bfa", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700, marginBottom: 8 }}>
                    Neo4j Intelligence
                  </div>
                  {loadingIntel && (
                    <div style={{ fontSize: FS.sm, color: T.dim }}>Loading network intelligence...</div>
                  )}
                  {!loadingIntel && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {nodeRisk && (
                        <>
                          <div>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Network Risk</div>
                            <div style={{
                              fontSize: FS.base, fontWeight: 700, marginTop: 2,
                              color: nodeRisk.risk_score > 0.6 ? "#ef4444" : nodeRisk.risk_score > 0.3 ? "#f59e0b" : "#22c55e",
                            }}>
                              {Math.round(nodeRisk.risk_score * 100)}%
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Risk Paths</div>
                            <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                              {nodeRisk.connected_count}
                            </div>
                          </div>
                        </>
                      )}
                      {nodeCentrality && (
                        <>
                          <div>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Degree</div>
                            <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                              {nodeCentrality.degree}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Influence</div>
                            <div style={{
                              fontSize: FS.base, fontWeight: 700, marginTop: 2,
                              color: nodeCentrality.influence > 0.5 ? "#22d3ee" : T.text,
                            }}>
                              {Math.round(nodeCentrality.influence * 100)}%
                            </div>
                          </div>
                          {nodeCentrality.bridged > 0 && (
                            <div style={{ gridColumn: "1 / -1" }}>
                              <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Bridging Power</div>
                              <div style={{ fontSize: FS.sm, color: "#a78bfa", fontWeight: 600, marginTop: 2 }}>
                                Connects to {nodeCentrality.bridged} otherwise unreachable entities
                              </div>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Neo4j actions */}
              {neo4jAvailable && (
                <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>
                    Graph Intelligence
                  </div>
                  <button
                    onClick={() => handleExpandNode(selectedNode.id)}
                    disabled={isExpanding}
                    className="rounded border cursor-pointer"
                    style={{
                      padding: "8px 12px",
                      fontSize: FS.sm,
                      background: `#a78bfa18`,
                      color: "#a78bfa",
                      borderColor: "#a78bfa44",
                      fontWeight: 600,
                      opacity: isExpanding ? 0.5 : 1,
                      textAlign: "left",
                    }}
                  >
                    {isExpanding ? "Expanding..." : "Expand Node (Neo4j)"}
                  </button>
                  <button
                    onClick={() => {
                      if (pathMode && pathSourceId === selectedNode.id) {
                        setPathMode(false);
                        setPathSourceId(null);
                        const cy = cyRef.current;
                        if (cy) cy.elements().removeClass("path-source");
                      } else {
                        setPathMode(true);
                        setPathSourceId(selectedNode.id);
                        const cy = cyRef.current;
                        if (cy) {
                          cy.elements().removeClass("path-source");
                          cy.$(`node[id = "${selectedNode.id}"]`).addClass("path-source");
                        }
                      }
                    }}
                    className="rounded border cursor-pointer"
                    style={{
                      padding: "8px 12px",
                      fontSize: FS.sm,
                      background: pathMode && pathSourceId === selectedNode.id ? `#f59e0b18` : `#22d3ee18`,
                      color: pathMode && pathSourceId === selectedNode.id ? "#f59e0b" : "#22d3ee",
                      borderColor: pathMode && pathSourceId === selectedNode.id ? "#f59e0b44" : "#22d3ee44",
                      fontWeight: 600,
                      textAlign: "left",
                    }}
                  >
                    {pathMode && pathSourceId === selectedNode.id
                      ? "Cancel Path Mode"
                      : pathMode && pathSourceId
                      ? "Find Path From Here Instead"
                      : "Find Path From Here"}
                  </button>
                  {pathMode && pathSourceId && pathSourceId !== selectedNode.id && (
                    <button
                      onClick={() => handleFindPath(pathSourceId, selectedNode.id)}
                      className="rounded border cursor-pointer"
                      style={{
                        padding: "8px 12px",
                        fontSize: FS.sm,
                        background: `#22d3ee24`,
                        color: "#22d3ee",
                        borderColor: "#22d3ee66",
                        fontWeight: 700,
                        textAlign: "left",
                      }}
                    >
                      Find Path To Here
                    </button>
                  )}
                  {highlightedPathIds.length > 0 && (
                    <button
                      onClick={() => {
                        setHighlightedPathIds([]);
                        const cy = cyRef.current;
                        if (cy) cy.elements().removeClass("path-highlight");
                      }}
                      className="rounded border cursor-pointer"
                      style={{
                        padding: "8px 12px",
                        fontSize: FS.sm,
                        background: T.raised,
                        color: T.dim,
                        borderColor: T.border,
                        fontWeight: 600,
                        textAlign: "left",
                      }}
                    >
                      Clear Path Highlight
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {selectedEdge && (
            <div
              className="rounded-xl p-4"
              style={{
                background: T.raised,
                border: `1px solid ${T.border}`,
                boxShadow: `inset 0 0 0 1px ${T.border}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <div
                  style={{
                    width: 18,
                    height: 2,
                    borderRadius: 999,
                    background: getRelationshipColor(selectedEdge.relType),
                    boxShadow: `0 0 12px ${getRelationshipColor(selectedEdge.relType)}66`,
                  }}
                />
                <div style={{ fontSize: FS.sm, color: T.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Relationship
                </div>
              </div>
              <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, lineHeight: 1.35 }}>
                {selectedEdge.relLabel}
              </div>
              <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <span
                    style={{
                      padding: "4px 8px",
                      borderRadius: 999,
                      fontSize: 12,
                      color: REL_FAMILY_META[selectedEdge.family]?.color || T.dim,
                      background: `${REL_FAMILY_META[selectedEdge.family]?.color || T.border}16`,
                      fontWeight: 700,
                    }}
                  >
                    {selectedEdge.familyLabel}
                  </span>
                  <span
                    style={{
                      padding: "4px 8px",
                      borderRadius: 999,
                      fontSize: 12,
                      color: getRelationshipColor(selectedEdge.relType),
                      background: `${getRelationshipColor(selectedEdge.relType)}16`,
                      fontWeight: 700,
                    }}
                  >
                    {selectedEdge.relLabel}
                  </span>
                  <span
                    style={{
                      padding: "4px 8px",
                      borderRadius: 999,
                      fontSize: 12,
                      color: getPriorityMeta(selectedEdge.priorityLabel).color,
                      background: getPriorityMeta(selectedEdge.priorityLabel).background,
                      fontWeight: 700,
                    }}
                  >
                    {selectedEdge.priorityLabel}
                  </span>
                </div>
                <div className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Source</div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600, marginTop: 4 }}>{selectedEdge.sourceLabel}</div>
                </div>
                <div className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Target</div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600, marginTop: 4 }}>{selectedEdge.targetLabel}</div>
                </div>
              </div>
              <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Confidence</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {Math.round(selectedEdge.confidence * 100)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Family</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {selectedEdge.familyLabel}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Priority</div>
                  <div style={{ fontSize: FS.base, color: getPriorityMeta(selectedEdge.priorityLabel).color, fontWeight: 700, marginTop: 2 }}>
                    {selectedEdge.priorityLabel}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Type</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {selectedEdge.relType}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Connector</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {selectedEdge.dataSources.length > 1
                      ? summarizeCorroboration(selectedEdge.corroborationCount, selectedEdge.dataSources.length)
                      : formatConnectorLabel(selectedEdge.dataSource)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>First Seen</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {formatFirstSeen(selectedEdge.firstSeenAt || selectedEdge.createdAt)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Last Seen</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {formatFirstSeen(selectedEdge.lastSeenAt || selectedEdge.createdAt)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Corroboration</div>
                  <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 2 }}>
                    {selectedEdge.corroborationCount}
                  </div>
                </div>
              </div>
              <div
                className="rounded-lg p-3"
                style={{
                  marginTop: 14,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Provenance
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {(selectedEdge.dataSources.length > 0 ? selectedEdge.dataSources : [selectedEdge.dataSource]).filter(Boolean).slice(0, 4).map((source) => (
                    <span
                      key={source}
                      style={{
                        padding: "4px 8px",
                        borderRadius: 999,
                        fontSize: 12,
                        color: T.accent,
                        background: `${T.accent}14`,
                        fontWeight: 700,
                      }}
                    >
                      {formatConnectorLabel(source)}
                    </span>
                  ))}
                  {selectedEdge.dataSources.length > 4 && (
                    <span
                      style={{
                        padding: "4px 8px",
                        borderRadius: 999,
                        fontSize: 12,
                        color: T.dim,
                        background: T.surface,
                        fontWeight: 600,
                      }}
                    >
                      +{selectedEdge.dataSources.length - 4} more
                    </span>
                  )}
                  <span
                    style={{
                      padding: "4px 8px",
                      borderRadius: 999,
                      fontSize: 12,
                      color: T.dim,
                      background: T.surface,
                      fontWeight: 600,
                    }}
                  >
                    First seen {formatFirstSeen(selectedEdge.firstSeenAt || selectedEdge.createdAt)}
                  </span>
                </div>
                {selectedEdge.evidenceSummary && (
                  <div
                    style={{
                      fontSize: FS.sm,
                      color: T.text,
                      lineHeight: 1.65,
                      padding: "10px 12px",
                      borderRadius: 10,
                      background: T.surface,
                      border: `1px solid ${T.border}`,
                    }}
                  >
                    {selectedEdge.evidenceSummary}
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Supporting evidence
                  </div>
                  {selectedEdgeEvidence.length > 2 && (
                    <button
                      onClick={() => setShowAllEdgeEvidence((current) => !current)}
                      className="cursor-pointer"
                      style={{
                        border: "none",
                        background: "transparent",
                        color: GOLD,
                        fontSize: 12,
                        fontWeight: 700,
                        padding: 0,
                      }}
                    >
                      {showAllEdgeEvidence ? "Hide supporting evidence" : `Show all supporting evidence (${selectedEdgeEvidence.length})`}
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {visibleSelectedEdgeEvidence.map((snippet, index) => (
                    <div key={`${selectedEdge.id}-snippet-${index}`} style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.65 }}>
                      {snippet}
                    </div>
                  ))}
                  {!showAllEdgeEvidence && selectedEdgeEvidence.length > visibleSelectedEdgeEvidence.length && (
                    <div style={{ fontSize: 12, color: T.muted }}>
                      Showing {visibleSelectedEdgeEvidence.length} of {selectedEdgeEvidence.length} supporting records.
                    </div>
                  )}
                  {!selectedEdgeEvidence.length && (
                    <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.65 }}>
                      No evidence excerpt was saved for this relationship yet.
                    </div>
                  )}
                </div>
                <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Claim records
                  </div>
                  {selectedEdgeClaims.length > 0 ? selectedEdgeClaims.map((claim) => (
                    <div
                      key={claim.claim_id}
                      className="rounded-lg p-3"
                      style={{ background: T.surface, border: `1px solid ${T.border}`, display: "flex", flexDirection: "column", gap: 8 }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <span
                            style={{
                              padding: "4px 8px",
                              borderRadius: 999,
                              fontSize: 12,
                              color: T.accent,
                              background: `${T.accent}14`,
                              fontWeight: 700,
                            }}
                          >
                            {formatConnectorLabel(claim.data_source || selectedEdge.dataSource)}
                          </span>
                          <span
                            style={{
                              padding: "4px 8px",
                              borderRadius: 999,
                              fontSize: 12,
                              color: T.dim,
                              background: T.bg,
                              fontWeight: 600,
                            }}
                          >
                            {Math.round((claim.confidence ?? 0) * 100)}% claim confidence
                          </span>
                          {claim.contradiction_state && (
                            <span
                              style={{
                                padding: "4px 8px",
                                borderRadius: 999,
                                fontSize: 12,
                                color: claim.contradiction_state === "contradicted" ? T.red : T.amber,
                                background: claim.contradiction_state === "contradicted" ? T.redBg : `${T.amber}14`,
                                fontWeight: 700,
                              }}
                            >
                              {claim.contradiction_state}
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 12, color: T.muted }}>
                          {formatFirstSeen(claim.last_observed_at || claim.observed_at || claim.updated_at)}
                        </div>
                      </div>
                      {claim.claim_value && (
                        <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.6 }}>
                          {claim.claim_value}
                        </div>
                      )}
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", fontSize: 12, color: T.muted }}>
                        <div>
                          Agent: {claim.asserting_agent?.label || "System"}
                          {claim.asserting_agent?.agent_type ? ` · ${claim.asserting_agent.agent_type}` : ""}
                        </div>
                        <div>
                          Activity: {claim.source_activity?.source || "n/a"}
                          {claim.source_activity?.activity_type ? ` · ${claim.source_activity.activity_type}` : ""}
                        </div>
                      </div>
                      {(claim.evidence_records?.length ?? 0) > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          {claim.evidence_records?.map((record) => (
                            <div
                              key={record.evidence_id}
                              className="rounded-lg p-3"
                              style={{ background: T.bg, border: `1px solid ${T.border}`, display: "flex", flexDirection: "column", gap: 6 }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                                <div style={{ fontSize: 12, color: T.text, fontWeight: 700 }}>
                                  {record.title || record.source || "Evidence record"}
                                </div>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  {record.url && (
                                    <a
                                      href={record.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{ fontSize: 12, color: T.accent, fontWeight: 700 }}
                                    >
                                      Open source
                                    </a>
                                  )}
                                  {record.artifact_ref && (
                                    <span style={{ fontSize: 12, color: T.muted }}>
                                      {record.artifact_ref}
                                    </span>
                                  )}
                                </div>
                              </div>
                              {record.snippet && (
                                <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.6 }}>
                                  {record.snippet}
                                </div>
                              )}
                              <div style={{ fontSize: 12, color: T.muted }}>
                                {record.source_class || "source"} · {record.authority_level || "authority"} · {record.access_model || "access"}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )) : (
                    <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.65 }}>
                      No claim-level provenance records were attached to this edge yet.
                    </div>
                  )}
                </div>
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 14, lineHeight: 1.6 }}>
                {REL_FAMILY_META[selectedEdge.family]?.description || "Relationship detail lives here, where it can be read cleanly without canvas clutter."}
              </div>
            </div>
          )}

          {!selectedNode && !selectedEdge && (
            <div
              className="rounded-xl p-4"
              style={{
                background: T.raised,
                border: `1px solid ${T.border}`,
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                Focused exploration starts at the root vendor
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.65 }}>
                Focused keeps the vendor root in command, with an optional secondary ring when you need it. Trace shows the root through the second ring, and Explore opens the full network. Click any node or edge to bring its context into focus.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Node labels</div>
                  <div style={{ fontSize: FS.sm, color: T.text, marginTop: 4 }}>Always visible for key entities</div>
                </div>
                <div className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Edge detail</div>
                  <div style={{ fontSize: FS.sm, color: T.text, marginTop: 4 }}>Readable here, not stacked on canvas</div>
                </div>
              </div>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: FS.sm, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Relationship Families
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {relationFamiliesSeen.map((family) => (
                <div
                  key={family.family}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 8px",
                    borderRadius: 999,
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    fontSize: 12,
                    color: T.dim,
                  }}
                >
                  <div
                    style={{
                      width: 16,
                      height: 0,
                      borderTopWidth: 2,
                      borderTopStyle: family.lineStyle,
                      borderTopColor: family.color,
                    }}
                  />
                  {family.label}
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: FS.sm, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Node Types
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {typesSeen.map((type) => {
                const meta = getTypeMeta(type);
                return (
                  <div
                    key={type}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 8px",
                      borderRadius: 999,
                      background: T.bg,
                      border: `1px solid ${T.border}`,
                      fontSize: 12,
                      color: T.dim,
                    }}
                  >
                    <div
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 999,
                        background: meta.fill,
                        border: `1px solid ${meta.stroke}`,
                      }}
                    />
                    {meta.label}
                  </div>
                );
              })}
            </div>
          </div>

          {relsSeen.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: FS.sm, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                Edge Types In View
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {relsSeen.slice(0, 8).map((rel) => (
                  <div
                    key={rel}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 8px",
                      borderRadius: 999,
                      background: T.bg,
                      border: `1px solid ${T.border}`,
                      fontSize: 12,
                      color: T.dim,
                    }}
                  >
                    <div
                      style={{
                        width: 14,
                        height: 2,
                        borderRadius: 999,
                        background: getRelationshipColor(rel),
                      }}
                    />
                    {getRelationshipLabel(rel)}
                  </div>
                ))}
              </div>
            </div>
          )}
          </div>
        </div>
      ) : (
        <div
          className="rounded-xl glass-panel"
          style={{
            overflow: "hidden",
          }}
        >
          <div
            className="px-4 py-3"
            style={{
              borderBottom: `1px solid ${T.border}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <div>
              <div style={{ fontSize: FS.sm, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                Relationship Table
              </div>
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
                {effectivePriorityFilter === "all"
                  ? "Exact reading mode for dense graph relationships, sorted by decision relevance first."
                  : `${priorityFilterMeta.label} is active. Exact reading mode for the current high-signal slice.`}
              </div>
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim }}>
              {visibleRelationships.length} visible rows
            </div>
          </div>
          <div
            className="px-4 py-3"
            style={{
              borderBottom: `1px solid ${T.border}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              background: T.raised,
            }}
          >
            <div style={{ fontSize: FS.sm, color: T.dim }}>
              Showing {visibleRelationships.length === 0 ? 0 : effectiveTablePage * tablePageSize + 1}
              {" "}to{" "}
              {Math.min((effectiveTablePage + 1) * tablePageSize, visibleRelationships.length)}
              {" "}of {visibleRelationships.length}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                onClick={() => setTablePage((current) => Math.max(0, current - 1))}
                disabled={effectiveTablePage === 0}
                className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: effectiveTablePage === 0 ? T.bg : T.surface,
                  color: effectiveTablePage === 0 ? T.muted : T.text,
                  borderColor: T.border,
                  fontWeight: 600,
                  cursor: effectiveTablePage === 0 ? "not-allowed" : "pointer",
                  opacity: effectiveTablePage === 0 ? 0.6 : 1,
                }}
              >
                Previous
              </button>
              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                Page {effectiveTablePage + 1} of {totalTablePages}
              </div>
              <button
                onClick={() => setTablePage((current) => Math.min(totalTablePages - 1, current + 1))}
                disabled={effectiveTablePage >= totalTablePages - 1}
                className="rounded-lg border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: effectiveTablePage >= totalTablePages - 1 ? T.bg : T.surface,
                  color: effectiveTablePage >= totalTablePages - 1 ? T.muted : T.text,
                  borderColor: T.border,
                  fontWeight: 600,
                  cursor: effectiveTablePage >= totalTablePages - 1 ? "not-allowed" : "pointer",
                  opacity: effectiveTablePage >= totalTablePages - 1 ? 0.6 : 1,
                }}
              >
                Next
              </button>
            </div>
          </div>
          <div style={{ maxHeight: Math.min(height, 440), overflow: "auto" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1.2fr) minmax(160px, 0.8fr) minmax(0, 1.2fr) 96px 128px",
                gap: 0,
                minWidth: 0,
              }}
            >
              {["Source", "Relationship", "Target", "Confidence", "Action"].map((label) => (
                <div
                  key={label}
                  style={{
                    position: "sticky",
                    top: 0,
                    zIndex: 1,
                    padding: "12px 14px",
                    color: T.muted,
                    fontWeight: 700,
                    fontSize: FS.sm,
                    background: T.surface,
                    borderBottom: `1px solid ${T.border}`,
                  }}
                >
                  {label}
                </div>
              ))}

              {pagedRelationships.map((relationship) => {
                const source = renderableEntityMap.get(relationship.source_entity_id);
                const target = renderableEntityMap.get(relationship.target_entity_id);
                return (
                  <Fragment key={relationship.id}>
                    <div
                      title={source?.canonical_name || relationship.source_entity_id}
                      style={{
                        padding: "12px 14px",
                        color: T.text,
                        fontWeight: 600,
                        borderBottom: `1px solid ${T.border}`,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {source?.canonical_name || relationship.source_entity_id}
                    </div>
                    <div
                      style={{
                        padding: "12px 14px",
                        borderBottom: `1px solid ${T.border}`,
                        overflow: "hidden",
                      }}
                    >
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            padding: "4px 8px",
                            borderRadius: 999,
                            background: `${REL_FAMILY_META[relationship.family]?.color || T.border}16`,
                            color: REL_FAMILY_META[relationship.family]?.color || T.dim,
                            fontWeight: 700,
                            fontSize: 11,
                          }}
                        >
                          {relationship.familyLabel}
                        </span>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            padding: "4px 8px",
                            borderRadius: 999,
                            background: getPriorityMeta(relationship.priorityLabel).background,
                            color: getPriorityMeta(relationship.priorityLabel).color,
                            fontWeight: 700,
                            fontSize: 11,
                          }}
                        >
                          {relationship.priorityLabel}
                        </span>
                        {relationship.dataSource && (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              padding: "4px 8px",
                              borderRadius: 999,
                              background: `${T.accent}14`,
                              color: T.accent,
                              fontWeight: 700,
                              fontSize: 11,
                            }}
                          >
                            {formatConnectorLabel(relationship.dataSource)}
                          </span>
                        )}
                        {relationship.corroborationCount > 1 && (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              padding: "4px 8px",
                              borderRadius: 999,
                              background: `${GOLD}14`,
                              color: GOLD,
                              fontWeight: 700,
                              fontSize: 11,
                            }}
                        >
                            {summarizeCorroboration(relationship.corroborationCount, relationship.dataSources.length)}
                          </span>
                        )}
                      </div>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                          maxWidth: "100%",
                          padding: "6px 10px",
                          borderRadius: 999,
                          background: `${relationship.lineColor}14`,
                          color: relationship.lineColor,
                          fontWeight: 700,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        <span
                          style={{
                            width: 14,
                            height: 2,
                            borderRadius: 999,
                            background: relationship.lineColor,
                            flexShrink: 0,
                          }}
                        />
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {relationship.relLabel}
                        </span>
                      </span>
                      {relationship.evidenceSummary && (
                        <div
                          style={{
                            fontSize: 11,
                            color: T.muted,
                            marginTop: 8,
                            lineHeight: 1.5,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={relationship.evidenceSummary}
                        >
                          {relationship.evidenceSummary}
                        </div>
                      )}
                    </div>
                    <div
                      title={target?.canonical_name || relationship.target_entity_id}
                      style={{
                        padding: "12px 14px",
                        color: T.text,
                        fontWeight: 600,
                        borderBottom: `1px solid ${T.border}`,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {target?.canonical_name || relationship.target_entity_id}
                    </div>
                    <div
                      style={{
                        padding: "12px 14px",
                        borderBottom: `1px solid ${T.border}`,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      <div style={{ color: T.text, fontWeight: 700 }}>
                        {Math.round(relationship.confidence * 100)}%
                      </div>
                      <div style={{ fontSize: 11, color: T.muted, marginTop: 4, lineHeight: 1.5 }}>
                        {formatFirstSeen(relationship.firstSeenAt || relationship.createdAt)}
                      </div>
                    </div>
                    <div
                      style={{
                        padding: "12px 14px",
                        borderBottom: `1px solid ${T.border}`,
                      }}
                    >
                      <button
                        onClick={() => {
                          setViewMode("graph");
                          setPendingEdgeFocusId(relationship.id);
                        }}
                        className="rounded border cursor-pointer"
                        style={{
                          padding: "7px 10px",
                          fontSize: FS.sm,
                          background: T.raised,
                          color: T.text,
                          borderColor: T.border,
                          fontWeight: 600,
                          width: "100%",
                        }}
                      >
                        Inspect
                      </button>
                    </div>
                  </Fragment>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
