/**
 * Graph Intelligence Dashboard
 *
 * Production-quality, full-screen graph analytics dashboard for Helios.
 * Features: risk-based node coloring, layout switching, advanced filters,
 * analytics panels, minimap, and performance optimization for 500+ node graphs.
 *
 * The differentiator: Risk-based node coloring with pulsing animations for CRITICAL nodes,
 * combined with centrality scaling and community detection visualization.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type EventObject, type NodeSingular } from "cytoscape";
import { Search, Grid3X3, Download, Eye, EyeOff, Globe, Pin, PinOff, MessageSquare, Save, FolderOpen, Trash2, FileText, PanelLeft, PanelRight, ArrowLeft } from "lucide-react";
import { T, FS, PAD, SP, O } from "@/lib/tokens";
import { fetchFullGraphIntelligence, fetchGraphTopology, listWorkspaces, createWorkspace, deleteWorkspace, findShortestPath, simulateRiskPropagation, generateGraphBriefing } from "@/lib/api";
import type { GraphEdge as ApiGraphEdge, GraphWorkspace } from "@/lib/api";
import { useHotkey } from "@/lib/use-hotkeys";
import { InlineMessage, LoadingPanel, PanelHeader, ShortcutBadge, StatusPill } from "./shell-primitives";

// ============================================================================
// Type Definitions
// ============================================================================

interface EnrichedGraphNode {
  id: string;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  country?: string;
  centrality_composite: number;
  centrality_structural?: number;
  centrality_decision?: number;
  centrality_degree?: number;
  centrality_betweenness?: number;
  centrality_pagerank?: number;
  sanctions_exposure: number;
  risk_level: "CLEAR" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  community_id?: number | null;
  created_at?: string;
}

interface GraphEdge {
  id?: string;
  source: string;
  target: string;
  rel_type: string;
  confidence: number;
  data_source?: string;
  created_at?: string;
}

interface TemporalProfile {
  timeline: Array<{ month: string; relationships_added: number }>;
  bursts: Array<{ month: string; count: number; multiplier: number }>;
  total_edges: number;
  date_range: { earliest: string; latest: string };
  growth_rate_pct: number;
}

interface FullGraphIntelligence {
  nodes: EnrichedGraphNode[];
  edges: GraphEdge[];
  summary: {
    total_nodes: number;
    total_edges: number;
    risk_distribution: Record<string, number>;
    type_distribution: Record<string, number>;
    community_count: number;
    modularity: number;
  };
  top_by_importance: EnrichedGraphNode[];
  top_by_structural_importance?: EnrichedGraphNode[];
  top_by_risk: EnrichedGraphNode[];
  communities: Array<{ community_id: number; size: number; members: string[]; dominant_type: string }>;
  temporal: TemporalProfile | null;
}

interface FilterState {
  entityTypes: Set<string>;
  riskLevels: Set<string>;
  confidenceThreshold: number;
  relationshipTypes: Set<string>;
  edgeConfidenceThreshold: number;
}

type LayoutMode = "cose" | "breadthfirst" | "concentric" | "geo";
type ShortestPathResult = Awaited<ReturnType<typeof findShortestPath>>;
type ShortestPathStep = NonNullable<ShortestPathResult["path"]>[number];
type PropagationResult = Awaited<ReturnType<typeof simulateRiskPropagation>>;
type PropagationEntity = PropagationResult["waves"][number]["entities"][number];
type SidebarTab = "importance" | "risk" | "detail" | "analytics";

interface WorkspaceFilterState {
  entityTypes?: string[];
  riskLevels?: string[];
  confidenceThreshold?: number;
  edgeConfidenceThreshold?: number;
}

// ============================================================================
// Constants
// ============================================================================

const GRAPH_BG = "#07101a";
const RISK_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  CLEAR: { bg: "#22c55e", border: "#16a34a", text: "#022c0d" },
  LOW: { bg: "#38bdf8", border: "#0284c7", text: "#001f3f" },
  MEDIUM: { bg: "#f59e0b", border: "#d97706", text: "#451a03" },
  HIGH: { bg: "#ef4444", border: "#dc2626", text: "#3f0a0a" },
  CRITICAL: { bg: "#dc2626", border: "#7f1d1d", text: "#3f0a0a" },
};

const TYPE_META: Record<string, { fill: string; stroke: string; label: string; shape: string }> = {
  company: { fill: "#193552", stroke: "#60a5fa", label: "Company", shape: "round-rectangle" },
  government_agency: { fill: "#0d4036", stroke: "#34d399", label: "Govt Agency", shape: "rectangle" },
  sanctions_list: { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions List", shape: "diamond" },
  sanctions_entry: { fill: "#5a1d22", stroke: "#f87171", label: "Sanctions Entry", shape: "diamond" },
  court_case: { fill: "#5f4715", stroke: "#fbbf24", label: "Court Case", shape: "hexagon" },
  person: { fill: "#40205e", stroke: "#a78bfa", label: "Person", shape: "ellipse" },
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
};

const COMMUNITY_PALETTE = [
  "#6366f1", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6",
  "#06b6d4", "#84cc16", "#f43f5e", "#eab308", "#22d3ee",
];

const SIDEBAR_TABS: Array<{ id: SidebarTab; label: string }> = [
  { id: "importance", label: "What matters" },
  { id: "risk", label: "Pressure" },
  { id: "detail", label: "Selected" },
  { id: "analytics", label: "Path lab" },
];

const COUNTRY_CENTROIDS: Record<string, [number, number]> = {
  US: [-98.5, 39.8], GB: [-1.2, 52.2], CN: [104.2, 35.9], RU: [105.3, 61.5],
  DE: [10.5, 51.2], FR: [2.2, 46.2], JP: [138.3, 36.2], KR: [127.8, 35.9],
  IN: [78.9, 20.6], AU: [133.8, -25.3], BR: [-51.9, -14.2], CA: [-106.3, 56.1],
  IL: [34.9, 31.0], IR: [53.7, 32.4], KP: [127.5, 40.3], SA: [45.1, 23.9],
  AE: [53.8, 23.4], PK: [69.3, 30.4], TW: [120.9, 23.7], SG: [103.8, 1.4],
  HK: [114.2, 22.3], NL: [5.3, 52.1], SE: [18.6, 60.1], CH: [8.2, 46.8],
  IT: [12.6, 41.9], ES: [-3.7, 40.5], PL: [19.1, 51.9], TR: [35.2, 38.9],
  MX: [-102.6, 23.6], ZA: [22.9, -30.6], NG: [8.7, 9.1], EG: [30.8, 26.8],
  UA: [31.2, 48.4], BE: [4.5, 50.5], AT: [14.6, 47.5], NO: [8.5, 60.5],
  DK: [9.5, 56.3], FI: [25.7, 61.9], CU: [-77.8, 21.5], VE: [-66.6, 6.4],
  SY: [38.0, 34.8], IQ: [43.7, 33.2], AF: [67.7, 33.9], LY: [17.2, 26.3],
  MM: [96.0, 21.9], TH: [100.5, 15.9], VN: [108.3, 14.1], PH: [121.8, 12.9],
  ID: [113.9, -0.8], MY: [101.7, 4.2], NZ: [174.9, -40.9], CL: [-71.5, -35.7],
  CO: [-74.3, 4.6], AR: [-63.6, -38.4], PE: [-75.0, -9.2],
};

function getDecisionImportance(node: EnrichedGraphNode): number {
  return node.centrality_decision ?? node.centrality_composite ?? 0;
}

function getStructuralImportance(node: EnrichedGraphNode): number {
  return node.centrality_structural ?? node.centrality_composite ?? 0;
}

// ============================================================================
// Main Component
// ============================================================================

interface GraphIntelligenceDashboardProps {
  onExit?: () => void;
  exitLabel?: string;
  contextLabel?: string;
}

export function GraphIntelligenceDashboard({ onExit, exitLabel = "Return", contextLabel }: GraphIntelligenceDashboardProps) {
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const minimapRef = useRef<HTMLCanvasElement>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  // State
  const [graphData, setGraphData] = useState<FullGraphIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backgroundStatus, setBackgroundStatus] = useState<string | null>(null);
  const [isHydratingAnalytics, setIsHydratingAnalytics] = useState(false);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("cose");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<EnrichedGraphNode | null>(null);
  const [filters, setFilters] = useState<FilterState>({
    entityTypes: new Set(),
    riskLevels: new Set(),
    confidenceThreshold: 0.5,
    relationshipTypes: new Set(),
    edgeConfidenceThreshold: 0,
  });
  const [showLabels, setShowLabels] = useState(true);
  const [communityColorEnabled, setCommunityColorEnabled] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: EnrichedGraphNode } | null>(null);
  const [searchMatchCount, setSearchMatchCount] = useState(0);
  const [temporalRange, setTemporalRange] = useState<[number, number]>([0, 100]);
  const [temporalEnabled, setTemporalEnabled] = useState(false);
  const [pinnedNodes, setPinnedNodes] = useState<Set<string>>(new Set());
  const [annotations, setAnnotations] = useState<Record<string, string>>({});
  const [annotatingNodeId, setAnnotatingNodeId] = useState<string | null>(null);
  const [annotationText, setAnnotationText] = useState("");
  const [workspaces, setWorkspaces] = useState<GraphWorkspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [showWorkspacePanel, setShowWorkspacePanel] = useState(false);
  const [showFilterPanel, setShowFilterPanel] = useState(false);
  const [showContextPanel, setShowContextPanel] = useState(false);

  // Shortest Path
  const [pathSource, setPathSource] = useState<string | null>(null);
  const [pathTarget, setPathTarget] = useState<string | null>(null);
  const [pathResult, setPathResult] = useState<ShortestPathResult | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  // Influence Propagation
  const [propagationSource, setPropagationSource] = useState<string | null>(null);
  const [propagationResult, setPropagationResult] = useState<PropagationResult | null>(null);
  const [propagationLoading, setPropagationLoading] = useState(false);
  const [propagationWaveIndex, setPropagationWaveIndex] = useState(0);

  // Load graph data on mount with timeout and retry
  const [retryCount, setRetryCount] = useState(0);
  const MAX_RETRIES = 3;
  const LOAD_TIMEOUT_MS = 75000;
  const TOPOLOGY_TIMEOUT_MS = 20000;
  const requestSequenceRef = useRef(0);

  const normalizeGraphPayload = useCallback((raw: {
    nodes: EnrichedGraphNode[];
    edges: ApiGraphEdge[];
    summary: FullGraphIntelligence["summary"];
    top_by_importance: EnrichedGraphNode[];
    top_by_structural_importance?: EnrichedGraphNode[];
    top_by_risk: EnrichedGraphNode[];
    communities: FullGraphIntelligence["communities"];
    temporal: unknown;
  }): FullGraphIntelligence => ({
    ...raw,
    temporal: (raw.temporal as TemporalProfile | null) ?? null,
    nodes: (raw.nodes || []).map((node) => ({
      ...node,
      created_at: node.created_at,
    })),
    edges: (raw.edges || []).map((edge) => ({
      source: edge.source_entity_id,
      target: edge.target_entity_id,
      rel_type: edge.rel_type,
      confidence: edge.confidence,
      data_source: edge.data_source,
      created_at: edge.created_at,
    })),
    top_by_structural_importance: raw.top_by_structural_importance || [],
  }), []);

  const hydrateAnalytics = useCallback(async (requestId: number) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), LOAD_TIMEOUT_MS);
    try {
      const raw = await fetchFullGraphIntelligence({ signal: controller.signal });
      if (requestId !== requestSequenceRef.current) return;
      setGraphData(normalizeGraphPayload(raw));
      setBackgroundStatus(null);
    } catch (err) {
      if (requestId !== requestSequenceRef.current) return;
      const message = err instanceof DOMException && err.name === "AbortError"
        ? "Topology is live. Full analytics are still warming in the background."
        : "Topology is live. Deep analytics are delayed, but the room is usable.";
      setBackgroundStatus(message);
    } finally {
      clearTimeout(timeoutId);
      if (requestId === requestSequenceRef.current) {
        setIsHydratingAnalytics(false);
      }
    }
  }, [normalizeGraphPayload]);

  const loadGraphData = useCallback(async () => {
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TOPOLOGY_TIMEOUT_MS);
    try {
      setLoading(true);
      setError(null);
      setBackgroundStatus(null);
      setIsHydratingAnalytics(false);

      const topology = await fetchGraphTopology({ signal: controller.signal });
      if (requestId !== requestSequenceRef.current) return;

      clearTimeout(timeoutId);
      setGraphData(normalizeGraphPayload(topology));
      setRetryCount(0);
      setIsHydratingAnalytics(true);
      setBackgroundStatus("Topology is live. Hydrating graph pressure, centrality, and community signals.");
      setLoading(false);
      void hydrateAnalytics(requestId);
    } catch (err) {
      clearTimeout(timeoutId);
      const fallbackController = new AbortController();
      const fallbackTimeoutId = setTimeout(() => fallbackController.abort(), LOAD_TIMEOUT_MS);
      try {
        const raw = await fetchFullGraphIntelligence({ signal: fallbackController.signal });
        if (requestId !== requestSequenceRef.current) return;
        setGraphData(normalizeGraphPayload(raw));
        setRetryCount(0);
      } catch (fallbackErr) {
        if (requestId !== requestSequenceRef.current) return;
        if (fallbackErr instanceof DOMException && fallbackErr.name === "AbortError") {
          setError("The Graph Room is still warming the live graph cache. Give it a moment and retry.");
        } else {
          setError(fallbackErr instanceof Error ? fallbackErr.message : "Failed to load graph intelligence");
        }
      } finally {
        clearTimeout(fallbackTimeoutId);
      }
    } finally {
      if (requestId === requestSequenceRef.current) {
        setLoading(false);
      }
    }
  }, [LOAD_TIMEOUT_MS, TOPOLOGY_TIMEOUT_MS, hydrateAnalytics, normalizeGraphPayload]);

  useEffect(() => {
    loadGraphData();
  }, [loadGraphData]);

  useEffect(() => {
    if (selectedNode || pathResult || propagationResult) {
      setShowContextPanel(true);
    }
  }, [pathResult, propagationResult, selectedNode]);

  // Compute temporal bounds from graph data
  const temporalBounds = useMemo(() => {
    if (!graphData) return { min: 0, max: 0, minDate: "", maxDate: "" };
    const allDates: number[] = [];
    graphData.nodes.forEach((n) => { if (n.created_at) allDates.push(new Date(n.created_at).getTime()); });
    graphData.edges.forEach((e) => { if (e.created_at) allDates.push(new Date(e.created_at).getTime()); });
    if (allDates.length === 0) return { min: 0, max: 0, minDate: "", maxDate: "" };
    const min = Math.min(...allDates);
    const max = Math.max(...allDates);
    return { min, max, minDate: new Date(min).toISOString().slice(0, 10), maxDate: new Date(max).toISOString().slice(0, 10) };
  }, [graphData]);

  // Build filtered nodes/edges
  const filteredData = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };

    let nodes = graphData.nodes;
    let edges = graphData.edges;

    // Apply entity type filter
    if (filters.entityTypes.size > 0) {
      nodes = nodes.filter((n) => filters.entityTypes.has(n.entity_type));
    }

    // Apply risk level filter
    if (filters.riskLevels.size > 0) {
      nodes = nodes.filter((n) => filters.riskLevels.has(n.risk_level));
    }

    // Apply confidence threshold
    nodes = nodes.filter((n) => n.confidence >= filters.confidenceThreshold);

    // Filter edges to only include nodes that passed filters
    const nodeIds = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

    // Apply relationship type filter
    if (filters.relationshipTypes.size > 0) {
      edges = edges.filter((e) => filters.relationshipTypes.has(e.rel_type));
    }

    // Apply edge confidence threshold filter
    edges = edges.filter((e) => e.confidence >= filters.edgeConfidenceThreshold);

    // Apply temporal filter
    if (temporalEnabled && temporalBounds.max > temporalBounds.min) {
      const rangeMs = temporalBounds.max - temporalBounds.min;
      const cutoffMin = temporalBounds.min + (temporalRange[0] / 100) * rangeMs;
      const cutoffMax = temporalBounds.min + (temporalRange[1] / 100) * rangeMs;
      nodes = nodes.filter((n) => {
        if (!n.created_at) return true;
        const t = new Date(n.created_at).getTime();
        return t >= cutoffMin && t <= cutoffMax;
      });
      edges = edges.filter((e) => {
        if (!e.created_at) return true;
        const t = new Date(e.created_at).getTime();
        return t >= cutoffMin && t <= cutoffMax;
      });
    }

    // Performance: LOD with community collapsing for large graphs
    if (nodes.length > 1000) {
      // Collapse small communities into super-nodes
      const communityMap = new Map<number, EnrichedGraphNode[]>();
      const noCommunity: EnrichedGraphNode[] = [];
      nodes.forEach((n) => {
        if (n.community_id != null) {
          const list = communityMap.get(n.community_id) || [];
          list.push(n);
          communityMap.set(n.community_id, list);
        } else {
          noCommunity.push(n);
        }
      });

      const expandedNodes: EnrichedGraphNode[] = [...noCommunity];
      const collapsedCommunities: EnrichedGraphNode[] = [];

      communityMap.forEach((members, communityId) => {
        if (members.length <= 5 || nodes.length <= 2000) {
          // Small community or manageable total: keep individual nodes
          expandedNodes.push(...members);
        } else {
          // Large community: collapse into a single super-node
          const topMember = members.sort((a, b) => getDecisionImportance(b) - getDecisionImportance(a))[0];
          const superNode: EnrichedGraphNode = {
            ...topMember,
            id: `community_${communityId}`,
            canonical_name: `${topMember.canonical_name} +${members.length - 1}`,
            centrality_composite: members.reduce((s, m) => s + (m.centrality_composite || 0), 0) / members.length,
            centrality_decision: members.reduce((s, m) => s + getDecisionImportance(m), 0) / members.length,
            centrality_structural: members.reduce((s, m) => s + getStructuralImportance(m), 0) / members.length,
            sanctions_exposure: Math.max(...members.map((m) => m.sanctions_exposure)),
            risk_level: members.some((m) => m.risk_level === "CRITICAL") ? "CRITICAL" :
                        members.some((m) => m.risk_level === "HIGH") ? "HIGH" :
                        members.some((m) => m.risk_level === "MEDIUM") ? "MEDIUM" : topMember.risk_level,
          };
          collapsedCommunities.push(superNode);
        }
      });

      nodes = [...expandedNodes, ...collapsedCommunities];

      // Rebuild edge set for collapsed nodes
      const finalNodeIds = new Set(nodes.map((n) => n.id));
      // Map old member IDs to super-node IDs
      const memberToSuper = new Map<string, string>();
      communityMap.forEach((members, communityId) => {
        if (members.length > 5 && nodes.length > 2000) {
          members.forEach((m) => memberToSuper.set(m.id, `community_${communityId}`));
        }
      });

      edges = edges.map((e) => ({
        ...e,
        source: memberToSuper.get(e.source) || e.source,
        target: memberToSuper.get(e.target) || e.target,
      })).filter((e) => finalNodeIds.has(e.source) && finalNodeIds.has(e.target) && e.source !== e.target);

      // Deduplicate edges between same super-nodes
      const edgeKey = (e: GraphEdge) => `${e.source}|${e.target}|${e.rel_type}`;
      const seen = new Set<string>();
      edges = edges.filter((e) => {
        const k = edgeKey(e);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });

      // Hard cap at 2000 after collapsing
      if (nodes.length > 2000) {
        const sorted = [...nodes].sort((a, b) => getDecisionImportance(b) - getDecisionImportance(a));
        nodes = sorted.slice(0, 2000);
        const topNodeIds = new Set(nodes.map((n) => n.id));
        edges = edges.filter((e) => topNodeIds.has(e.source) && topNodeIds.has(e.target));
      }
    }

    return { nodes, edges };
  }, [graphData, filters, temporalEnabled, temporalRange, temporalBounds]);

  // Initialize Cytoscape
  useEffect(() => {
    if (!cyContainerRef.current || !filteredData.nodes.length) return;

    const elements = buildCytoscapeElements(filteredData.nodes, filteredData.edges);
    let cy: Core | null = null;

    try {
      const layoutConfig = layoutMode === "geo"
        ? {
            name: "preset",
            positions: (node: NodeSingular) => {
              const nodeData = filteredData.nodes.find((n) => n.id === node.id());
              const country = nodeData?.country;
              const centroid = country ? COUNTRY_CENTROIDS[country] : null;
              if (centroid) {
                const jitter = (Math.random() - 0.5) * 30;
                return { x: centroid[0] * 8 + jitter, y: -centroid[1] * 8 + jitter };
              }
              return { x: (Math.random() - 0.5) * 200, y: (Math.random() - 0.5) * 200 };
            },
            animate: true,
            animationDuration: 400,
          }
        : { name: layoutMode, animate: true, animationDuration: 400 };

      cy = cytoscape({
        container: cyContainerRef.current,
        elements,
        style: buildCytoscapeStyle(),
        layout: layoutConfig,
        pixelRatio: "auto",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Graph render failed");
      return;
    }

    cyRef.current = cy;

    // Event listeners
    const onNodeSelect = (evt: EventObject) => {
      const node = evt.target;
      if (!("isNode" in node) || !node.isNode()) return;
      const nodeData = filteredData.nodes.find((n) => n.id === node.id());
      if (nodeData) setSelectedNode(nodeData);
    };

    const onZoom = () => {
      // Auto-hide labels when zoomed out
      if (cy.zoom() < 1.5) {
        cy.elements("node").style("content", "");
      } else {
        cy.elements("node").style("content", (ele: NodeSingular) => String(ele.data("label") ?? ""));
      }
    };

    // Tooltip handlers
    const onMouseover = (evt: EventObject) => {
      const cyNode = evt.target;
      if (!("isNode" in cyNode) || !cyNode.isNode()) return;
      const nodeData = filteredData.nodes.find((n) => n.id === cyNode.id());
      if (!nodeData) return;
      const pos = cyNode.renderedPosition();
      setTooltip({ x: pos.x, y: pos.y, node: nodeData });
    };

    const onMouseout = () => setTooltip(null);

    // Minimap rendering
    const renderMinimap = () => {
      const canvas = minimapRef.current;
      if (!canvas || !cy) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      canvas.width = 200 * (window.devicePixelRatio || 1);
      canvas.height = 150 * (window.devicePixelRatio || 1);
      ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

      ctx.fillStyle = GRAPH_BG;
      ctx.fillRect(0, 0, 200, 150);

      const bb = cy.elements().boundingBox();
      if (!bb || bb.w === 0 || bb.h === 0) return;

      const scale = Math.min(190 / bb.w, 140 / bb.h);
      const offsetX = (200 - bb.w * scale) / 2;
      const offsetY = (150 - bb.h * scale) / 2;

      cy.nodes().forEach((n: NodeSingular) => {
        const pos = n.position();
        const x = (pos.x - bb.x1) * scale + offsetX;
        const y = (pos.y - bb.y1) * scale + offsetY;
        const fillColor = n.data("fillColor") || "#94a3b8";
        ctx.fillStyle = fillColor;
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      });

      // Draw viewport rectangle
      const ext = cy.extent();
      const vx = (ext.x1 - bb.x1) * scale + offsetX;
      const vy = (ext.y1 - bb.y1) * scale + offsetY;
      const vw = ext.w * scale;
      const vh = ext.h * scale;
      ctx.strokeStyle = "rgba(14, 165, 233, 0.6)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(vx, vy, vw, vh);
    };

    // Risk pulse interval for CRITICAL nodes
    const pulseInterval = setInterval(() => {
      cy.nodes('[riskLevel="CRITICAL"]').toggleClass("risk-pulse");
    }, 1200);

    // Apply community coloring if enabled
    if (communityColorEnabled) {
      cy.nodes().addClass("community-colored");
    } else {
      cy.nodes().removeClass("community-colored");
    }

    // Apply pinned/annotated classes
    pinnedNodes.forEach((id) => {
      const n = cy.getElementById(id);
      if (n.length) n.addClass("pinned");
    });
    Object.keys(annotations).forEach((id) => {
      const n = cy.getElementById(id);
      if (n.length) n.addClass("annotated");
    });

    cy.on("select", "node", onNodeSelect);
    cy.on("zoom", onZoom);
    cy.on("mouseover", "node", onMouseover);
    cy.on("mouseout", "node", onMouseout);
    cy.on("render", renderMinimap);
    cy.on("pan zoom", renderMinimap);

    const resizeAndFit = () => {
      if (!cy || cy.destroyed()) return;
      cy.resize();
      if (cy.elements().length > 0) {
        cy.fit(cy.elements(), 40);
      }
      renderMinimap();
    };

    const frameId = window.requestAnimationFrame(resizeAndFit);
    const resizeObserver = new ResizeObserver(() => {
      resizeAndFit();
    });
    resizeObserver.observe(cyContainerRef.current);
    window.setTimeout(renderMinimap, 500);

    return () => {
      window.cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      cy.off("select", "node", onNodeSelect);
      cy.off("zoom", onZoom);
      cy.off("mouseover", "node", onMouseover);
      cy.off("mouseout", "node", onMouseout);
      cy.off("render", renderMinimap);
      cy.off("pan zoom", renderMinimap);
      clearInterval(pulseInterval);
      cy.destroy();
    };
  }, [filteredData, layoutMode, communityColorEnabled, pinnedNodes, annotations]);

  // Handle batch search
  useEffect(() => {
    if (!cyRef.current || !searchQuery) {
      cyRef.current?.elements("node").removeClass("highlight");
      setSearchMatchCount(0);
      return;
    }

    const query = searchQuery.toLowerCase();
    const matchedNodes = filteredData.nodes.filter((n) =>
      n.canonical_name.toLowerCase().includes(query)
    );

    cyRef.current.elements("node").removeClass("highlight");
    setSearchMatchCount(matchedNodes.length);

    if (matchedNodes.length > 0) {
      matchedNodes.forEach((n) => {
        cyRef.current!.getElementById(n.id).addClass("highlight");
      });

      if (matchedNodes.length === 1) {
        cyRef.current.center(cyRef.current.getElementById(matchedNodes[0].id));
      } else {
        const matchedElements = matchedNodes.map((n) => cyRef.current!.getElementById(n.id)).reduce((acc, el) => acc.union(el), cyRef.current.collection());
        cyRef.current.fit(matchedElements, 80);
      }
    }
  }, [searchQuery, filteredData.nodes]);

  // Handlers
  const handleResetFilters = () => {
    setFilters({
      entityTypes: new Set(),
      riskLevels: new Set(),
      confidenceThreshold: 0.5,
      relationshipTypes: new Set(),
      edgeConfidenceThreshold: 0,
    });
  };

  const handleExportPNG = useCallback(() => {
    if (!cyRef.current) return;
    const png = cyRef.current.png({ output: "blob", bg: GRAPH_BG, scale: 2, full: true });
    const url = URL.createObjectURL(png as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `helios-graph-${new Date().toISOString().slice(0, 10)}.png`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  // Load workspaces on mount
  useEffect(() => {
    listWorkspaces().then((data) => setWorkspaces(data.workspaces || [])).catch(() => {});
  }, []);

  const handlePinNode = useCallback((nodeId: string) => {
    setPinnedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const handleAnnotate = useCallback((nodeId: string, text: string) => {
    setAnnotations((prev) => {
      const next = { ...prev };
      if (text.trim()) next[nodeId] = text.trim();
      else delete next[nodeId];
      return next;
    });
    setAnnotatingNodeId(null);
    setAnnotationText("");
  }, []);

  const handleSaveWorkspace = useCallback(async () => {
    if (!workspaceName.trim()) return;
    const cy = cyRef.current;
    const viewport = cy ? { x: cy.pan().x, y: cy.pan().y, zoom: cy.zoom() } : {};
    const nodePositions: Record<string, { x: number; y: number }> = {};
    if (cy) {
      cy.nodes().forEach((n) => {
        const pos = n.position();
        nodePositions[n.id()] = { x: pos.x, y: pos.y };
      });
    }
    try {
      const ws = await createWorkspace({
        name: workspaceName.trim(),
        pinned_nodes: [...pinnedNodes],
        annotations,
        filter_state: {
          entityTypes: [...filters.entityTypes],
          riskLevels: [...filters.riskLevels],
          confidenceThreshold: filters.confidenceThreshold,
          edgeConfidenceThreshold: filters.edgeConfidenceThreshold,
        },
        layout_mode: layoutMode,
        viewport,
        node_positions: nodePositions,
      });
      setWorkspaces((prev) => [ws, ...prev]);
      setActiveWorkspaceId(ws.id);
      setWorkspaceName("");
    } catch (err) {
      console.error("Failed to save workspace:", err);
    }
  }, [workspaceName, pinnedNodes, annotations, filters, layoutMode]);

  const handleLoadWorkspace = useCallback(async (ws: GraphWorkspace) => {
    setActiveWorkspaceId(ws.id);
    setPinnedNodes(new Set(ws.pinned_nodes || []));
    setAnnotations(ws.annotations || {});

    // Restore filters
    const workspaceFilters = ws.filter_state as Partial<WorkspaceFilterState>;
    if (workspaceFilters) {
      setFilters({
        entityTypes: new Set(workspaceFilters.entityTypes || []),
        riskLevels: new Set(workspaceFilters.riskLevels || []),
        confidenceThreshold: workspaceFilters.confidenceThreshold ?? 0.5,
        relationshipTypes: new Set(),
        edgeConfidenceThreshold: workspaceFilters.edgeConfidenceThreshold ?? 0,
      });
    }

    // Restore layout
    if (ws.layout_mode) setLayoutMode(ws.layout_mode as LayoutMode);

    // Restore positions after layout settles
    setTimeout(() => {
      const cy = cyRef.current;
      if (!cy || !ws.node_positions) return;
      const positions = ws.node_positions;
      cy.nodes().forEach((n) => {
        const p = positions[n.id()];
        if (p) n.position(p);
      });
      if (ws.viewport) {
        const vp = ws.viewport;
        if (vp.zoom) cy.zoom(vp.zoom);
        if (vp.x != null && vp.y != null) cy.pan({ x: vp.x, y: vp.y });
      }
    }, 600);

    setShowWorkspacePanel(false);
  }, []);

  const handleDeleteWorkspace = useCallback(async (wsId: string) => {
    try {
      await deleteWorkspace(wsId);
      setWorkspaces((prev) => prev.filter((w) => w.id !== wsId));
      if (activeWorkspaceId === wsId) setActiveWorkspaceId(null);
    } catch (err) {
      console.error("Failed to delete workspace:", err);
    }
  }, [activeWorkspaceId]);

  const handleFindPath = useCallback(async () => {
    if (!pathSource || !pathTarget) return;
    setPathLoading(true);
    setPathResult(null);
    try {
      const result = await findShortestPath(pathSource, pathTarget);
      setPathResult(result);
      // Highlight path in graph
      if (result.found && result.path && cyRef.current) {
        const cy = cyRef.current;
        cy.elements().removeClass("path-node path-edge");
        const nodeIds = new Set<string>();
        result.path.forEach((step: ShortestPathStep) => {
          nodeIds.add(step.from_id);
          nodeIds.add(step.to_id);
        });
        nodeIds.forEach((id) => {
          const n = cy.getElementById(id);
          if (n.length) n.addClass("path-node");
        });
        // Highlight edges along the path
        result.path.forEach((step: ShortestPathStep) => {
          const edgeId = `${step.from_id}-${step.to_id}`;
          const reverseId = `${step.to_id}-${step.from_id}`;
          const e = cy.getElementById(edgeId);
          const eRev = cy.getElementById(reverseId);
          if (e.length) e.addClass("path-edge");
          if (eRev.length) eRev.addClass("path-edge");
        });
        // Fit to path nodes
        const pathNodes = cy.nodes(".path-node");
        if (pathNodes.length > 0) cy.fit(pathNodes, 80);
      }
    } catch (err) {
      console.error("Shortest path failed:", err);
    } finally {
      setPathLoading(false);
    }
  }, [pathSource, pathTarget]);

  const handlePropagate = useCallback(async () => {
    if (!propagationSource) return;
    setPropagationLoading(true);
    setPropagationResult(null);
    setPropagationWaveIndex(0);
    try {
      const result = await simulateRiskPropagation(propagationSource, 4, 0.6);
      setPropagationResult(result);
      // Highlight source
      if (cyRef.current) {
        cyRef.current.elements().removeClass("propagation-source propagation-wave");
        const src = cyRef.current.getElementById(propagationSource);
        if (src.length) src.addClass("propagation-source");
      }
    } catch (err) {
      console.error("Propagation failed:", err);
    } finally {
      setPropagationLoading(false);
    }
  }, [propagationSource]);

  // Animate propagation waves
  const handleShowWave = useCallback((waveIdx: number) => {
    setPropagationWaveIndex(waveIdx);
    if (!cyRef.current || !propagationResult) return;
    const cy = cyRef.current;
    cy.elements().removeClass("propagation-wave");
    // Show all entities up to this wave
    for (let i = 0; i <= waveIdx; i++) {
      const wave = propagationResult.waves[i];
      if (!wave) continue;
      wave.entities.forEach((entity: PropagationEntity) => {
        const n = cy.getElementById(entity.id);
        if (n.length) n.addClass("propagation-wave");
      });
    }
  }, [propagationResult]);

  const handleClearAnalytics = useCallback(() => {
    setPathSource(null);
    setPathTarget(null);
    setPathResult(null);
    setPropagationSource(null);
    setPropagationResult(null);
    if (cyRef.current) {
      cyRef.current.elements().removeClass("path-node path-edge propagation-source propagation-wave");
    }
  }, []);

  const handleGenerateBriefing = useCallback(async () => {
    try {
      const blob = await generateGraphBriefing({
        title: activeWorkspaceId ? workspaces.find(w => w.id === activeWorkspaceId)?.name || "Graph Analysis" : "Graph Analysis",
        analyst: "tye.gonzalez@gmail.com",
        pinned_nodes: [...pinnedNodes],
        annotations,
        path_result: pathResult,
        propagation_result: propagationResult,
        filter_summary: [
          filters.riskLevels.size > 0 ? `Risk: ${[...filters.riskLevels].join(", ")}` : "",
          filters.entityTypes.size > 0 ? `Types: ${[...filters.entityTypes].join(", ")}` : "",
          `Confidence > ${filters.confidenceThreshold}`,
        ].filter(Boolean).join(" | "),
        layout_mode: layoutMode,
        node_count: filteredData.nodes.length,
        edge_count: filteredData.edges.length,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `helios-briefing-${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Briefing generation failed:", err);
    }
  }, [pinnedNodes, annotations, pathResult, propagationResult, filters, layoutMode, filteredData, activeWorkspaceId, workspaces]);

  const toggleEntityType = (type: string) => {
    const newTypes = new Set(filters.entityTypes);
    if (newTypes.has(type)) {
      newTypes.delete(type);
    } else {
      newTypes.add(type);
    }
    setFilters({ ...filters, entityTypes: newTypes });
  };

  const toggleRiskLevel = (level: string) => {
    const newLevels = new Set(filters.riskLevels);
    if (newLevels.has(level)) {
      newLevels.delete(level);
    } else {
      newLevels.add(level);
    }
    setFilters({ ...filters, riskLevels: newLevels });
  };

  const changeLayout = (mode: LayoutMode) => {
    setLayoutMode(mode);
  };

  useHotkey("cmd+f", () => {
    searchInputRef.current?.focus();
    searchInputRef.current?.select();
  }, { ignoreInputs: false });
  useHotkey("/", () => {
    searchInputRef.current?.focus();
    searchInputRef.current?.select();
  });
  useHotkey("escape", () => {
    if (annotatingNodeId) {
      setAnnotatingNodeId(null);
      setAnnotationText("");
      return;
    }
    if (showWorkspacePanel) {
      setShowWorkspacePanel(false);
      return;
    }
    if (searchQuery) {
      setSearchQuery("");
      return;
    }
    searchInputRef.current?.blur();
  }, { ignoreInputs: false });

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", background: GRAPH_BG, padding: 24 }}>
        <div style={{ width: "100%", maxWidth: 520 }}>
          <LoadingPanel
            label="Opening Graph Room"
            detail="Rebuilding the paths, bridges, and provenance behind the brief. The first load after a deploy can take longer while the graph cache warms."
          />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", background: GRAPH_BG, padding: 24 }}>
        <div style={{ width: "100%", maxWidth: 520, display: "flex", flexDirection: "column", gap: 12 }}>
          <InlineMessage tone="danger" title="Graph Room unavailable" message={error} />
          {retryCount < MAX_RETRIES ? (
            <button
              type="button"
              aria-label="Retry graph intelligence load"
              onClick={() => {
                setRetryCount((count) => count + 1);
                loadGraphData();
              }}
              className="helios-focus-ring"
              style={{
                padding: "10px 16px",
                borderRadius: 12,
                background: T.accent,
                color: "#fff",
                border: "none",
                fontSize: `${FS.base}px`,
                fontWeight: 700,
                cursor: "pointer",
                alignSelf: "flex-start",
              }}
            >
              Retry ({MAX_RETRIES - retryCount} attempts remaining)
            </button>
          ) : (
            <InlineMessage tone="warning" message="Max retries reached. Check the graph service and refresh the page." />
          )}
        </div>
      </div>
    );
  }

  const riskDistribution = graphData?.summary.risk_distribution || {};
  const entityTypes = [...new Set(filteredData.nodes.map((n) => n.entity_type))];
  const relationshipTypes = [...new Set(filteredData.edges.map((e) => e.rel_type))];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        width: "100%",
        background: GRAPH_BG,
        fontFamily: "'Inter', -apple-system, sans-serif",
        color: T.text,
        fontSize: `${FS.base}px`,
      }}
    >
      {/* Center: Graph Canvas */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minHeight: 0 }}>
        {/* Top Toolbar */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: SP.md,
            padding: PAD.comfortable,
            background: T.surface,
            borderBottom: `1px solid ${T.border}`,
            zIndex: 10,
          }}
        >
          {onExit ? (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                className="helios-focus-ring"
                aria-label={exitLabel}
                onClick={onExit}
                style={{
                  padding: PAD.default,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.textSecondary,
                  borderRadius: 999,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
              >
                <ArrowLeft size={14} />
                {exitLabel}
              </button>
            </div>
          ) : null}

          <PanelHeader
            eyebrow="Graph room"
            title={
              <span style={{ fontSize: FS.md, fontWeight: 800, letterSpacing: "-0.03em", color: T.text }}>
                Trace the structure behind the brief
              </span>
            }
            description="Follow the bridges, pressure points, and provenance without falling out of the live thread."
            meta={
              <>
                {contextLabel ? <StatusPill tone="warning">Case context: {contextLabel}</StatusPill> : null}
                <StatusPill tone="info">{filteredData.nodes.length} nodes</StatusPill>
                <StatusPill tone="neutral">{filteredData.edges.length} edges</StatusPill>
                {isHydratingAnalytics ? <StatusPill tone="warning">Analytics warming</StatusPill> : null}
                <StatusPill tone="neutral">Paths beat pictures</StatusPill>
                <StatusPill tone="neutral">
                  <ShortcutBadge>⌘F</ShortcutBadge>
                  Search
                </StatusPill>
                <StatusPill tone="neutral">
                  <ShortcutBadge>/</ShortcutBadge>
                  Focus graph query
                </StatusPill>
              </>
            }
          />

          {backgroundStatus ? (
            <InlineMessage tone="warning" title="Graph status" message={backgroundStatus} />
          ) : null}

          <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm, alignItems: "center" }}>
            <div
              style={{
                flex: "1 1 320px",
                minWidth: 0,
                display: "flex",
                alignItems: "center",
                gap: SP.sm,
                padding: PAD.default,
                borderRadius: 14,
                border: `1px solid ${T.border}`,
                background: T.bg,
              }}
            >
              <Search size={16} color={T.textSecondary} />
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Find an entity, bridge, or vehicle thread"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Search graph entities"
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  color: T.text,
                  fontSize: `${FS.sm}px`,
                  outline: "none",
                }}
              />
              {searchMatchCount > 0 ? (
                <StatusPill tone="neutral">
                  {searchMatchCount} match{searchMatchCount !== 1 ? "es" : ""}
                </StatusPill>
              ) : null}
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: SP.sm }}>
              <LayoutButton active={layoutMode === "cose"} label="Free layout" onClick={() => changeLayout("cose")}>
              Free
              </LayoutButton>
              <LayoutButton active={layoutMode === "breadthfirst"} label="Tree layout" onClick={() => changeLayout("breadthfirst")}>
              Tree
              </LayoutButton>
              <LayoutButton active={layoutMode === "concentric"} label="Orbit layout" onClick={() => changeLayout("concentric")}>
              Orbit
              </LayoutButton>
              <LayoutButton active={layoutMode === "geo"} label="Map layout" onClick={() => changeLayout("geo")}>
              <Globe size={14} style={{ display: "inline", marginRight: "4px" }} />
              Map
              </LayoutButton>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label={showFilterPanel ? "Hide graph framing tools" : "Show graph framing tools"}
                onClick={() => setShowFilterPanel(!showFilterPanel)}
                style={{
                  padding: PAD.default,
                  background: showFilterPanel ? `${T.accent}${O["15"]}` : T.bg,
                  border: `1px solid ${showFilterPanel ? `${T.accent}${O["30"]}` : T.border}`,
                  color: showFilterPanel ? T.accent : T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Frame the graph picture"
              >
                <PanelLeft size={14} />
                Frame
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label="Toggle community coloring"
                onClick={() => setCommunityColorEnabled(!communityColorEnabled)}
                style={{
                  padding: PAD.default,
                  background: communityColorEnabled ? `${T.accent}${O["15"]}` : T.bg,
                  border: `1px solid ${communityColorEnabled ? `${T.accent}${O["30"]}` : T.border}`,
                  color: communityColorEnabled ? T.accent : T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Toggle community coloring"
              >
                <Grid3X3 size={14} />
                Communities
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label={showLabels ? "Hide graph labels" : "Show graph labels"}
                onClick={() => setShowLabels(!showLabels)}
                style={{
                  padding: PAD.default,
                  background: showLabels ? `${T.accent}${O["15"]}` : T.bg,
                  border: `1px solid ${showLabels ? `${T.accent}${O["30"]}` : T.border}`,
                  color: showLabels ? T.accent : T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Toggle labels"
              >
                {showLabels ? <Eye size={14} /> : <EyeOff size={14} />}
                Labels
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label="Export graph as PNG"
                onClick={handleExportPNG}
                style={{
                  padding: PAD.default,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Export graph as PNG"
              >
                <Download size={14} />
                Export
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label="Generate graph briefing"
                onClick={handleGenerateBriefing}
                style={{
                  padding: PAD.default,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Generate briefing PDF"
              >
                <FileText size={14} />
                Pull brief
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label={showWorkspacePanel ? "Hide saved graph workspaces" : "Show saved graph workspaces"}
                onClick={() => setShowWorkspacePanel(!showWorkspacePanel)}
                style={{
                  padding: PAD.default,
                  background: showWorkspacePanel ? `${T.accent}${O["15"]}` : T.bg,
                  border: `1px solid ${showWorkspacePanel ? `${T.accent}${O["30"]}` : T.border}`,
                  color: showWorkspacePanel ? T.accent : T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Workspaces"
              >
                <FolderOpen size={14} />
                Saved views
              </button>

              <button
                type="button"
                className="helios-focus-ring"
                aria-label={showContextPanel ? "Hide graph context" : "Show graph context"}
                onClick={() => setShowContextPanel(!showContextPanel)}
                style={{
                  padding: PAD.default,
                  background: showContextPanel ? `${T.accent}${O["15"]}` : T.bg,
                  border: `1px solid ${showContextPanel ? `${T.accent}${O["30"]}` : T.border}`,
                  color: showContextPanel ? T.accent : T.text,
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: `${FS.sm}px`,
                  display: "flex",
                  alignItems: "center",
                  gap: SP.xs,
                }}
                title="Show graph context"
              >
                <PanelRight size={14} />
                Context
              </button>
            </div>

            {filteredData.nodes.length > 2000 ? (
              <StatusPill tone="warning">Large graph mode</StatusPill>
            ) : null}
          </div>
        </div>

        {/* Graph Canvas */}
        <div
          ref={cyContainerRef}
          style={{
            flex: 1,
            background: GRAPH_BG,
            position: "relative",
            overflow: "hidden",
            display: "flex",
          }}
        >
          {showFilterPanel ? (
            <div style={{ position: "absolute", top: 14, left: 14, zIndex: 35, maxHeight: "calc(100% - 28px)" }}>
              <LeftSidebar
                entityTypes={entityTypes}
                relationshipTypes={relationshipTypes}
                filters={filters}
                riskDistribution={riskDistribution}
                onToggleEntityType={toggleEntityType}
                onToggleRiskLevel={toggleRiskLevel}
                onConfidenceChange={(val) => setFilters({ ...filters, confidenceThreshold: val })}
                onEdgeConfidenceChange={(val) => setFilters({ ...filters, edgeConfidenceThreshold: val })}
                onResetFilters={handleResetFilters}
                temporalEnabled={temporalEnabled}
                onToggleTemporal={() => setTemporalEnabled(!temporalEnabled)}
                temporalRange={temporalRange}
                onTemporalRangeChange={setTemporalRange}
                temporalBounds={temporalBounds}
              />
            </div>
          ) : null}

          {/* Tooltip */}
          {tooltip && (
            <div
              style={{
                position: "absolute",
                left: tooltip.x + 15,
                top: tooltip.y - 10,
                background: "rgba(15, 23, 42, 0.95)",
                border: `1px solid ${T.border}`,
                borderRadius: "6px",
                padding: "8px 12px",
                pointerEvents: "none",
                zIndex: 50,
                maxWidth: "280px",
                backdropFilter: "blur(8px)",
                fontSize: `${FS.sm}px`,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "4px", color: T.text }}>
                {tooltip.node.canonical_name}
              </div>
              <div style={{ display: "flex", gap: "8px", fontSize: `${FS.caption}px`, color: T.textSecondary }}>
                <span>{TYPE_META[tooltip.node.entity_type]?.label || tooltip.node.entity_type}</span>
                <span style={{ color: RISK_COLORS[tooltip.node.risk_level].bg }}>
                  {tooltip.node.risk_level}
                </span>
              </div>
              {tooltip.node.country && (
                <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, marginTop: "2px" }}>
                  {tooltip.node.country}
                </div>
              )}
              <div
                style={{
                  display: "flex",
                  gap: "12px",
                  marginTop: "4px",
                  fontSize: `${FS.caption}px`,
                  color: T.textSecondary,
                }}
              >
                <span>Decision: {getDecisionImportance(tooltip.node).toFixed(2)}</span>
                <span>Structural: {getStructuralImportance(tooltip.node).toFixed(2)}</span>
                <span>Exposure: {(tooltip.node.sanctions_exposure * 100).toFixed(0)}%</span>
              </div>
            </div>
          )}

          {/* Minimap */}
          <canvas
            ref={minimapRef}
            onClick={(e) => {
              if (!cyRef.current) return;
              const canvas = minimapRef.current;
              if (!canvas) return;
              const rect = canvas.getBoundingClientRect();
              const clickX = e.clientX - rect.left;
              const clickY = e.clientY - rect.top;
              const cy = cyRef.current;
              const bb = cy.elements().boundingBox();
              if (!bb || bb.w === 0) return;
              const scale = Math.min(190 / bb.w, 140 / bb.h);
              const offsetX = (200 - bb.w * scale) / 2;
              const offsetY = (150 - bb.h * scale) / 2;
              const graphX = (clickX - offsetX) / scale + bb.x1;
              const graphY = (clickY - offsetY) / scale + bb.y1;
              cy.pan({ x: cy.width() / 2 - graphX * cy.zoom(), y: cy.height() / 2 - graphY * cy.zoom() });
            }}
            style={{
              position: "absolute",
              bottom: "12px",
              right: "12px",
              width: "200px",
              height: "150px",
              background: T.surface,
              border: `1px solid ${T.border}`,
              borderRadius: "4px",
              opacity: 0.8,
              cursor: "pointer",
            }}
          />

          {/* Workspace Panel */}
          {showWorkspacePanel && (
            <div
              style={{
                position: "absolute",
                top: "60px",
                right: "12px",
                width: "320px",
                maxHeight: "calc(100% - 96px)",
                background: "rgba(15, 23, 42, 0.97)",
                border: `1px solid ${T.border}`,
                borderRadius: "8px",
                padding: "16px",
                zIndex: 40,
                display: "flex",
                flexDirection: "column",
                gap: "12px",
                overflow: "auto",
                backdropFilter: "blur(12px)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ fontSize: `${FS.md}px`, fontWeight: 600, color: T.text }}>Workspaces</div>
                <button
                  type="button"
                  className="helios-focus-ring"
                  aria-label="Close workspace panel"
                  onClick={() => setShowWorkspacePanel(false)}
                  style={{ background: "none", border: "none", color: T.textSecondary, cursor: "pointer", fontSize: `${FS.md}px` }}
                >
                  x
                </button>
              </div>

              {/* Save New */}
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="text"
                  placeholder="Workspace name..."
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSaveWorkspace()}
                  style={{
                    flex: 1,
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                    padding: "6px 8px",
                    borderRadius: "4px",
                    fontSize: `${FS.sm}px`,
                    outline: "none",
                  }}
                />
                <button
                  type="button"
                  className="helios-focus-ring"
                  aria-label="Save current graph workspace"
                  onClick={handleSaveWorkspace}
                  style={{
                    padding: "6px 10px",
                    background: T.accent,
                    border: "none",
                    color: "#000",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: `${FS.sm}px`,
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  <Save size={14} />
                </button>
              </div>

              {/* Pinned Summary */}
              {pinnedNodes.size > 0 && (
                <div style={{ fontSize: `${FS.caption}px`, color: "#f59e0b", padding: "4px 0" }}>
                  {pinnedNodes.size} pinned node{pinnedNodes.size !== 1 ? "s" : ""} ·{" "}
                  {Object.keys(annotations).length} annotation{Object.keys(annotations).length !== 1 ? "s" : ""}
                </div>
              )}

              {/* Workspace List */}
              {workspaces.length === 0 ? (
                <div style={{ color: T.textSecondary, fontSize: `${FS.sm}px`, textAlign: "center", padding: "20px 0" }}>
                  No saved workspaces
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {workspaces.map((ws) => (
                    <div
                      key={ws.id}
                      style={{
                        padding: "10px",
                        background: activeWorkspaceId === ws.id ? "rgba(14, 165, 233, 0.15)" : T.bg,
                        border: `1px solid ${activeWorkspaceId === ws.id ? "#0ea5e9" : T.border}`,
                        borderRadius: "6px",
                        cursor: "pointer",
                      }}
                      onClick={() => handleLoadWorkspace(ws)}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ fontWeight: 600, fontSize: `${FS.sm}px`, color: T.text }}>{ws.name}</div>
                        <button
                          type="button"
                          className="helios-focus-ring"
                          aria-label={`Delete workspace ${ws.name}`}
                          onClick={(e) => { e.stopPropagation(); handleDeleteWorkspace(ws.id); }}
                          style={{ background: "none", border: "none", color: T.textSecondary, cursor: "pointer", padding: "2px" }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                      <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, marginTop: "4px" }}>
                        {(ws.pinned_nodes || []).length} pinned · {ws.layout_mode} · {new Date(ws.updated_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Annotation Input Modal */}
          {annotatingNodeId && (
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                width: "360px",
                background: "rgba(15, 23, 42, 0.97)",
                border: `1px solid ${T.border}`,
                borderRadius: "8px",
                padding: "16px",
                zIndex: 50,
                backdropFilter: "blur(12px)",
              }}
            >
              <div style={{ fontSize: `${FS.sm}px`, fontWeight: 600, color: T.text, marginBottom: "8px" }}>
                Annotate: {filteredData.nodes.find((n) => n.id === annotatingNodeId)?.canonical_name || annotatingNodeId}
              </div>
              <textarea
                value={annotationText}
                onChange={(e) => setAnnotationText(e.target.value)}
                placeholder="Add analyst note..."
                style={{
                  width: "100%",
                  minHeight: "80px",
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                  padding: "8px",
                  borderRadius: "4px",
                  fontSize: `${FS.sm}px`,
                  outline: "none",
                  resize: "vertical",
                  fontFamily: "inherit",
                }}
                autoFocus
              />
              <div style={{ display: "flex", gap: "8px", marginTop: "8px", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  className="helios-focus-ring"
                  aria-label="Cancel node annotation"
                  onClick={() => { setAnnotatingNodeId(null); setAnnotationText(""); }}
                  style={{
                    padding: "6px 12px",
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: `${FS.sm}px`,
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="helios-focus-ring"
                  aria-label="Save node annotation"
                  onClick={() => handleAnnotate(annotatingNodeId, annotationText)}
                  style={{
                    padding: "6px 12px",
                    background: T.accent,
                    border: "none",
                    color: "#000",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: `${FS.sm}px`,
                  }}
                >
                  Save
                </button>
              </div>
            </div>
          )}

          {showContextPanel ? (
            <div style={{ position: "absolute", top: 14, right: 14, zIndex: 35, maxHeight: "calc(100% - 28px)" }}>
              <RightSidebar
                selectedNode={selectedNode}
                topByImportance={graphData?.top_by_importance || []}
                topByStructuralImportance={graphData?.top_by_structural_importance || []}
                topByRisk={graphData?.top_by_risk || []}
                communities={graphData?.communities || []}
                riskDistribution={riskDistribution}
                pinnedNodes={pinnedNodes}
                annotations={annotations}
                onPinNode={handlePinNode}
                onAnnotate={(id) => { setAnnotatingNodeId(id); setAnnotationText(annotations[id] || ""); }}
                pathSource={pathSource}
                pathTarget={pathTarget}
                pathResult={pathResult}
                pathLoading={pathLoading}
                propagationSource={propagationSource}
                propagationResult={propagationResult}
                propagationLoading={propagationLoading}
                propagationWaveIndex={propagationWaveIndex}
                onSetPathSource={setPathSource}
                onSetPathTarget={setPathTarget}
                onFindPath={handleFindPath}
                onSetPropagationSource={setPropagationSource}
                onPropagate={handlePropagate}
                onShowWave={handleShowWave}
                onClearAnalytics={handleClearAnalytics}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Sidebar Components
// ============================================================================

function LeftSidebar(props: {
  entityTypes: string[];
  relationshipTypes: string[];
  filters: FilterState;
  riskDistribution: Record<string, number>;
  onToggleEntityType: (type: string) => void;
  onToggleRiskLevel: (level: string) => void;
  onConfidenceChange: (val: number) => void;
  onEdgeConfidenceChange: (val: number) => void;
  onResetFilters: () => void;
  temporalEnabled: boolean;
  onToggleTemporal: () => void;
  temporalRange: [number, number];
  onTemporalRangeChange: (range: [number, number]) => void;
  temporalBounds: { min: number; max: number; minDate: string; maxDate: string };
}) {
  return (
    <div
      style={{
        width: "272px",
        maxHeight: "100%",
        background: "rgba(12, 18, 28, 0.94)",
        border: `1px solid rgba(255,255,255,0.08)`,
        borderRadius: 22,
        backdropFilter: "blur(20px)",
        display: "flex",
        flexDirection: "column",
        overflow: "auto",
        padding: `${PAD.comfortable}px`,
        gap: `${SP.md}px`,
        boxShadow: "0 24px 60px rgba(0,0,0,0.28)",
      }}
    >
      {/* Reset Button */}
      <button
        type="button"
        className="helios-focus-ring"
        aria-label="Reset graph filters"
        onClick={props.onResetFilters}
        style={{
          padding: "8px 12px",
          background: "rgba(255,255,255,0.04)",
          border: `1px solid rgba(255,255,255,0.08)`,
          color: T.text,
          borderRadius: "999px",
          cursor: "pointer",
          fontSize: `${FS.sm}px`,
          fontWeight: 700,
        }}
      >
        Reset the picture
      </button>

      {/* Entity Types */}
      <div>
        <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
          ENTITY CLASSES
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {props.entityTypes.map((type) => (
            <label
              key={type}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                cursor: "pointer",
                fontSize: `${FS.sm}px`,
              }}
            >
              <input
                type="checkbox"
                checked={props.filters.entityTypes.has(type)}
                onChange={() => props.onToggleEntityType(type)}
                style={{ cursor: "pointer" }}
              />
              {TYPE_META[type]?.label || type}
            </label>
          ))}
        </div>
      </div>

      {/* Risk Levels */}
      <div>
        <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
          PRESSURE LEVEL
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {["CLEAR", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => (
            <label
              key={level}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                cursor: "pointer",
                fontSize: `${FS.sm}px`,
              }}
            >
              <input
                type="checkbox"
                checked={props.filters.riskLevels.has(level)}
                onChange={() => props.onToggleRiskLevel(level)}
                style={{ cursor: "pointer" }}
              />
              <div
                style={{
                  width: "12px",
                  height: "12px",
                  background: RISK_COLORS[level].bg,
                  borderRadius: "2px",
                }}
              />
              {level}
            </label>
          ))}
        </div>
      </div>

      {/* Confidence Threshold */}
      <div>
        <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
          THIN-DATA FLOOR
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={props.filters.confidenceThreshold}
            onChange={(e) => props.onConfidenceChange(parseFloat(e.target.value))}
            style={{ flex: 1 }}
          />
          <div style={{ fontSize: `${FS.caption}px`, minWidth: "32px" }}>
            {props.filters.confidenceThreshold.toFixed(1)}
          </div>
        </div>
      </div>

      {/* Edge Confidence Threshold */}
      <div>
        <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
          RELATIONSHIP FLOOR
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={props.filters.edgeConfidenceThreshold}
            onChange={(e) => props.onEdgeConfidenceChange(parseFloat(e.target.value))}
            style={{ flex: 1 }}
          />
          <div style={{ fontSize: `${FS.caption}px`, minWidth: "32px" }}>
            {props.filters.edgeConfidenceThreshold.toFixed(1)}
          </div>
        </div>
      </div>

      {/* Temporal Filter */}
      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
          <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>
            TIMELINE WINDOW
          </div>
          <button
            type="button"
            className="helios-focus-ring"
            aria-label={props.temporalEnabled ? "Disable timeline filter" : "Enable timeline filter"}
            aria-pressed={props.temporalEnabled}
            onClick={props.onToggleTemporal}
            style={{
              padding: "2px 6px",
              background: props.temporalEnabled ? T.accent : "transparent",
              border: `1px solid ${props.temporalEnabled ? T.accent : T.border}`,
              color: props.temporalEnabled ? "#000" : T.textSecondary,
              borderRadius: "3px",
              cursor: "pointer",
              fontSize: `${FS.caption}px`,
            }}
          >
            {props.temporalEnabled ? "ON" : "OFF"}
          </button>
        </div>
        {props.temporalEnabled && props.temporalBounds.minDate && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: `${FS.caption}px`, color: T.textSecondary, marginBottom: "4px" }}>
              <span>{props.temporalBounds.minDate}</span>
              <span>{props.temporalBounds.maxDate}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, minWidth: "32px" }}>From</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={props.temporalRange[0]}
                  onChange={(e) => {
                    const val = parseInt(e.target.value);
                    props.onTemporalRangeChange([Math.min(val, props.temporalRange[1]), props.temporalRange[1]]);
                  }}
                  style={{ flex: 1 }}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, minWidth: "32px" }}>To</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={props.temporalRange[1]}
                  onChange={(e) => {
                    const val = parseInt(e.target.value);
                    props.onTemporalRangeChange([props.temporalRange[0], Math.max(val, props.temporalRange[0])]);
                  }}
                  style={{ flex: 1 }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Risk Distribution Chart */}
      <div>
        <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
          PRESSURE MIX
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          {["CLEAR", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => {
            const count = props.riskDistribution[level] || 0;
            const total = Object.values(props.riskDistribution).reduce((a, b) => a + b, 0);
            const percent = total > 0 ? (count / total) * 100 : 0;
            return (
              <div key={level} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <div style={{ fontSize: `${FS.caption}px`, minWidth: "40px", color: T.textSecondary }}>
                  {level}
                </div>
                <div
                  style={{
                    flex: 1,
                    height: "6px",
                    background: T.bg,
                    borderRadius: "2px",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${percent}%`,
                      background: RISK_COLORS[level].bg,
                      transition: "width 0.2s",
                    }}
                  />
                </div>
                <div style={{ fontSize: `${FS.caption}px`, minWidth: "24px", textAlign: "right" }}>
                  {count}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function RightSidebar(props: {
  selectedNode: EnrichedGraphNode | null;
  topByImportance: EnrichedGraphNode[];
  topByStructuralImportance: EnrichedGraphNode[];
  topByRisk: EnrichedGraphNode[];
  communities: Array<{ community_id: number; size: number; members: string[]; dominant_type: string }>;
  riskDistribution: Record<string, number>;
  pinnedNodes: Set<string>;
  annotations: Record<string, string>;
  onPinNode: (id: string) => void;
  onAnnotate: (id: string) => void;
  pathSource: string | null;
  pathTarget: string | null;
  pathResult: ShortestPathResult | null;
  pathLoading: boolean;
  propagationSource: string | null;
  propagationResult: PropagationResult | null;
  propagationLoading: boolean;
  propagationWaveIndex: number;
  onSetPathSource: (id: string | null) => void;
  onSetPathTarget: (id: string | null) => void;
  onFindPath: () => void;
  onSetPropagationSource: (id: string | null) => void;
  onPropagate: () => void;
  onShowWave: (idx: number) => void;
  onClearAnalytics: () => void;
}) {
  const [activeTab, setActiveTab] = useState<SidebarTab>("importance");

  return (
    <div
      style={{
        width: "320px",
        maxHeight: "100%",
        background: "rgba(12, 18, 28, 0.94)",
        border: `1px solid rgba(255,255,255,0.08)`,
        borderRadius: 22,
        backdropFilter: "blur(20px)",
        display: "flex",
        flexDirection: "column",
        overflow: "auto",
        padding: `${PAD.comfortable}px`,
        gap: `${SP.md}px`,
        boxShadow: "0 24px 60px rgba(0,0,0,0.28)",
      }}
    >
      {/* Tabs */}
      <div style={{ display: "flex", gap: "4px", borderBottom: `1px solid rgba(255,255,255,0.08)`, paddingBottom: "8px" }}>
        {SIDEBAR_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className="helios-focus-ring"
            aria-label={`Show ${tab.label.toLowerCase()} graph sidebar`}
            aria-pressed={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              flex: 1,
              padding: "6px",
              background: activeTab === tab.id ? "rgba(255,255,255,0.05)" : "transparent",
              border: "none",
              color: T.text,
              cursor: "pointer",
              fontSize: `${FS.sm}px`,
              borderBottom: activeTab === tab.id ? `2px solid ${T.accent}` : "none",
              borderRadius: 10,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "importance" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div
            style={{
              padding: "8px",
              background: "rgba(14, 165, 233, 0.08)",
              border: "1px solid rgba(14, 165, 233, 0.25)",
              borderRadius: "6px",
              fontSize: `${FS.caption}px`,
              color: T.textSecondary,
            }}
          >
            These are the nodes most likely to change the working judgment if they move.
          </div>
          {props.topByImportance.slice(0, 10).map((node) => (
            <div
              key={node.id}
              style={{
                padding: "8px",
                background: "rgba(255,255,255,0.03)",
                borderRadius: "10px",
                borderLeft: `3px solid ${RISK_COLORS[node.risk_level].bg}`,
                fontSize: `${FS.sm}px`,
                cursor: "pointer",
                transition: "background 0.2s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(255,255,255,0.07)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "rgba(255,255,255,0.03)";
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "4px" }}>{node.canonical_name}</div>
              <div style={{ color: T.textSecondary, fontSize: `${FS.caption}px`, display: "flex", justifyContent: "space-between", gap: "8px" }}>
                <span>Decision: {getDecisionImportance(node).toFixed(2)}</span>
                <span>Structural: {getStructuralImportance(node).toFixed(2)}</span>
              </div>
            </div>
          ))}

          {props.topByStructuralImportance.length > 0 && (
            <div style={{ marginTop: "12px" }}>
              <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
                BRIDGE NODES
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {props.topByStructuralImportance.slice(0, 5).map((node) => (
                  <div
                    key={`structural-${node.id}`}
                    style={{
                      padding: "8px",
                      background: "rgba(255,255,255,0.03)",
                      borderRadius: "10px",
                      borderLeft: `3px solid ${TYPE_META[node.entity_type]?.stroke || T.accent}`,
                      fontSize: `${FS.sm}px`,
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>{node.canonical_name}</div>
                    <div style={{ color: T.textSecondary, fontSize: `${FS.caption}px`, display: "flex", justifyContent: "space-between", gap: "8px" }}>
                      <span>Structural: {getStructuralImportance(node).toFixed(2)}</span>
                      <span>Decision: {getDecisionImportance(node).toFixed(2)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "risk" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {props.topByRisk.slice(0, 10).map((node) => (
            <div
              key={node.id}
              style={{
                padding: "8px",
                background: "rgba(255,255,255,0.03)",
                borderRadius: "10px",
                borderLeft: `3px solid ${RISK_COLORS[node.risk_level].bg}`,
                fontSize: `${FS.sm}px`,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "4px" }}>{node.canonical_name}</div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: `${FS.caption}px` }}>
                <span style={{ color: T.textSecondary }}>{node.risk_level}</span>
                <span style={{ color: RISK_COLORS[node.risk_level].bg }}>
                  {(node.sanctions_exposure * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === "detail" && props.selectedNode && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div
              style={{
                padding: "8px",
                background: "rgba(255,255,255,0.03)",
                border: `1px solid rgba(255,255,255,0.08)`,
                borderRadius: "10px",
                fontSize: `${FS.caption}px`,
                color: T.textSecondary,
              }}
            >
              Read the selected node as a role in the picture, not as isolated metadata.
            </div>
            <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>NAME</div>
            <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>{props.selectedNode.canonical_name}</div>
          </div>

          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>TYPE</div>
            <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>
              {TYPE_META[props.selectedNode.entity_type]?.label || props.selectedNode.entity_type}
            </div>
          </div>

          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>RISK LEVEL</div>
            <div
              style={{
                fontSize: `${FS.sm}px`,
                marginTop: "4px",
                padding: "4px 8px",
                background: RISK_COLORS[props.selectedNode.risk_level].bg,
                color: RISK_COLORS[props.selectedNode.risk_level].text,
                borderRadius: "4px",
                display: "inline-block",
              }}
            >
              {props.selectedNode.risk_level}
            </div>
          </div>

          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>DECISION IMPORTANCE</div>
            <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>
              {getDecisionImportance(props.selectedNode).toFixed(3)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>STRUCTURAL IMPORTANCE</div>
            <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>
              {getStructuralImportance(props.selectedNode).toFixed(3)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>EXPOSURE</div>
            <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>
              {(props.selectedNode.sanctions_exposure * 100).toFixed(1)}%
            </div>
          </div>

          {props.selectedNode.country && (
            <div>
              <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600 }}>COUNTRY</div>
              <div style={{ fontSize: `${FS.sm}px`, marginTop: "4px" }}>{props.selectedNode.country}</div>
            </div>
          )}

          {/* Pin & Annotate Actions */}
          <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
            <button
              type="button"
              className="helios-focus-ring"
              aria-label={props.pinnedNodes.has(props.selectedNode!.id) ? `Unpin ${props.selectedNode.canonical_name}` : `Pin ${props.selectedNode.canonical_name}`}
              onClick={() => props.onPinNode(props.selectedNode!.id)}
              style={{
                flex: 1,
                padding: "6px",
                background: props.pinnedNodes.has(props.selectedNode!.id) ? "#f59e0b" : T.bg,
                border: `1px solid ${props.pinnedNodes.has(props.selectedNode!.id) ? "#f59e0b" : T.border}`,
                color: props.pinnedNodes.has(props.selectedNode!.id) ? "#000" : T.text,
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: `${FS.caption}px`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "4px",
              }}
            >
              {props.pinnedNodes.has(props.selectedNode!.id) ? <PinOff size={12} /> : <Pin size={12} />}
              {props.pinnedNodes.has(props.selectedNode!.id) ? "Unpin" : "Pin"}
            </button>
            <button
              type="button"
              className="helios-focus-ring"
              aria-label={`Annotate ${props.selectedNode.canonical_name}`}
              onClick={() => props.onAnnotate(props.selectedNode!.id)}
              style={{
                flex: 1,
                padding: "6px",
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: `${FS.caption}px`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "4px",
              }}
            >
              <MessageSquare size={12} />
              Annotate
            </button>
          </div>
          {props.annotations[props.selectedNode.id] && (
            <div style={{ marginTop: "8px", padding: "8px", background: "rgba(124, 58, 237, 0.1)", borderRadius: "4px", borderLeft: `3px solid #7c3aed` }}>
              <div style={{ fontSize: `${FS.caption}px`, color: "#a78bfa", fontWeight: 600, marginBottom: "4px" }}>NOTE</div>
              <div style={{ fontSize: `${FS.sm}px`, color: T.text }}>{props.annotations[props.selectedNode.id]}</div>
            </div>
          )}
        </div>
      )}

      {activeTab === "detail" && !props.selectedNode && (
        <div style={{ color: T.textSecondary, fontSize: `${FS.sm}px`, textAlign: "center", padding: "20px 0" }}>
          Select a node to read its role in the picture.
        </div>
      )}

      {activeTab === "analytics" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Shortest Path */}
          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
              TRACE A PATH
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, minWidth: "36px" }}>From</div>
                <div style={{
                  flex: 1, padding: "4px 8px", background: T.bg, border: `1px solid ${props.pathSource ? "#0ea5e9" : T.border}`,
                  borderRadius: "4px", fontSize: `${FS.sm}px`, color: props.pathSource ? T.text : T.textSecondary,
                  cursor: "pointer", minHeight: "28px", display: "flex", alignItems: "center",
                }}
                  onClick={() => { if (props.selectedNode) props.onSetPathSource(props.selectedNode.id); }}
                >
                  {props.pathSource ? (props.topByImportance.find((n) => n.id === props.pathSource)?.canonical_name || props.pathSource) : "Select a node, then set it here"}
                </div>
              </div>
              <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, minWidth: "36px" }}>To</div>
                <div style={{
                  flex: 1, padding: "4px 8px", background: T.bg, border: `1px solid ${props.pathTarget ? "#0ea5e9" : T.border}`,
                  borderRadius: "4px", fontSize: `${FS.sm}px`, color: props.pathTarget ? T.text : T.textSecondary,
                  cursor: "pointer", minHeight: "28px", display: "flex", alignItems: "center",
                }}
                  onClick={() => { if (props.selectedNode) props.onSetPathTarget(props.selectedNode.id); }}
                >
                  {props.pathTarget ? (props.topByImportance.find((n) => n.id === props.pathTarget)?.canonical_name || props.pathTarget) : "Select a node, then set it here"}
                </div>
              </div>
              <button
                type="button"
                className="helios-focus-ring"
                aria-label="Find shortest path"
                onClick={props.onFindPath}
                disabled={!props.pathSource || !props.pathTarget || props.pathLoading}
                style={{
                  padding: "6px", background: props.pathSource && props.pathTarget ? "#0ea5e9" : T.bg,
                  border: `1px solid ${props.pathSource && props.pathTarget ? "#0ea5e9" : T.border}`,
                  color: props.pathSource && props.pathTarget ? "#000" : T.textSecondary,
                  borderRadius: "4px", cursor: props.pathSource && props.pathTarget ? "pointer" : "default",
                  fontSize: `${FS.sm}px`, fontWeight: 600,
                }}
              >
                {props.pathLoading ? "Tracing..." : "Trace path"}
              </button>
            </div>
            {props.pathResult && (
              <div style={{ marginTop: "8px" }}>
                {props.pathResult.found ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <div style={{ fontSize: `${FS.caption}px`, color: "#0ea5e9", fontWeight: 600 }}>
                      {props.pathResult.hops} hop{props.pathResult.hops !== 1 ? "s" : ""} found
                    </div>
                    {(props.pathResult.path ?? []).map((step: ShortestPathStep, i: number) => (
                      <div key={i} style={{
                        padding: "6px", background: T.bg, borderRadius: "4px",
                        borderLeft: `3px solid #0ea5e9`, fontSize: `${FS.caption}px`,
                      }}>
                        <div style={{ color: T.text, fontWeight: 500 }}>{step.from_name}</div>
                        <div style={{ color: "#0ea5e9", margin: "2px 0" }}>
                          {step.rel_type} ({(step.confidence * 100).toFixed(0)}%)
                        </div>
                        <div style={{ color: T.text, fontWeight: 500 }}>{step.to_name}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: `${FS.sm}px`, color: T.textSecondary }}>No path found</div>
                )}
              </div>
            )}
          </div>

          {/* Divider */}
          <div style={{ height: "1px", background: T.border }} />

          {/* Influence Propagation */}
          <div>
            <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, fontWeight: 600, marginBottom: "8px" }}>
              TEST PROPAGATION
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                <div style={{ fontSize: `${FS.caption}px`, color: T.textSecondary, minWidth: "36px" }}>From</div>
                <div style={{
                  flex: 1, padding: "4px 8px", background: T.bg, border: `1px solid ${props.propagationSource ? "#f43f5e" : T.border}`,
                  borderRadius: "4px", fontSize: `${FS.sm}px`, color: props.propagationSource ? T.text : T.textSecondary,
                  cursor: "pointer", minHeight: "28px", display: "flex", alignItems: "center",
                }}
                  onClick={() => { if (props.selectedNode) props.onSetPropagationSource(props.selectedNode.id); }}
                >
                  {props.propagationSource ? (props.topByImportance.find((n) => n.id === props.propagationSource)?.canonical_name || props.propagationSource) : "Select a node, then set it here"}
                </div>
              </div>
              <button
                type="button"
                className="helios-focus-ring"
                aria-label="Propagate risk from selected source"
                onClick={props.onPropagate}
                disabled={!props.propagationSource || props.propagationLoading}
                style={{
                  padding: "6px", background: props.propagationSource ? "#f43f5e" : T.bg,
                  border: `1px solid ${props.propagationSource ? "#f43f5e" : T.border}`,
                  color: props.propagationSource ? "#fff" : T.textSecondary,
                  borderRadius: "4px", cursor: props.propagationSource ? "pointer" : "default",
                  fontSize: `${FS.sm}px`, fontWeight: 600,
                }}
              >
                {props.propagationLoading ? "Testing..." : "Test propagation"}
              </button>
            </div>
            {props.propagationResult && (
              <div style={{ marginTop: "8px" }}>
                <div style={{ fontSize: `${FS.caption}px`, color: "#f43f5e", fontWeight: 600, marginBottom: "6px" }}>
                  {props.propagationResult.total_affected} entities affected across {props.propagationResult.waves.length} wave{props.propagationResult.waves.length !== 1 ? "s" : ""}
                </div>
                {/* Wave selector */}
                <div style={{ display: "flex", gap: "4px", marginBottom: "8px", flexWrap: "wrap" }}>
                  {props.propagationResult.waves.map((wave, i: number) => (
                    <button
                      key={i}
                      type="button"
                      className="helios-focus-ring"
                      aria-label={`Show propagation wave ${wave.hop}`}
                      onClick={() => props.onShowWave(i)}
                      style={{
                        padding: "3px 8px",
                        background: i <= props.propagationWaveIndex ? `rgba(251, 146, 60, ${0.3 + (i / (props.propagationResult?.waves.length ?? 1)) * 0.7})` : T.bg,
                        border: `1px solid ${i <= props.propagationWaveIndex ? "#fb923c" : T.border}`,
                        color: i <= props.propagationWaveIndex ? "#fff" : T.textSecondary,
                        borderRadius: "4px", cursor: "pointer", fontSize: `${FS.caption}px`,
                      }}
                    >
                      Hop {wave.hop} ({wave.entities.length})
                    </button>
                  ))}
                </div>
                {/* Wave entities */}
                {props.propagationResult.waves[props.propagationWaveIndex] && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "200px", overflow: "auto" }}>
                    {props.propagationResult.waves[props.propagationWaveIndex].entities.slice(0, 10).map((entity: PropagationEntity) => (
                      <div key={entity.id} style={{
                        padding: "6px", background: T.bg, borderRadius: "4px",
                        borderLeft: `3px solid ${RISK_COLORS[entity.existing_risk_level]?.bg || "#94a3b8"}`,
                        fontSize: `${FS.caption}px`,
                      }}>
                        <div style={{ color: T.text, fontWeight: 500 }}>{entity.name}</div>
                        <div style={{ display: "flex", justifyContent: "space-between", color: T.textSecondary, marginTop: "2px" }}>
                          <span>{entity.rel_type}</span>
                          <span style={{ color: "#fb923c" }}>Risk: {(entity.received_risk * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Clear button */}
          <button
            type="button"
            className="helios-focus-ring"
            aria-label="Clear graph analytics selections"
            onClick={props.onClearAnalytics}
            style={{
              padding: "6px", background: T.bg, border: `1px solid ${T.border}`,
              color: T.textSecondary, borderRadius: "4px", cursor: "pointer",
              fontSize: `${FS.sm}px`,
            }}
          >
            Clear path lab
          </button>
        </div>
      )}
    </div>
  );
}

function LayoutButton(props: { active: boolean; label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      className="helios-focus-ring"
      aria-label={props.label}
      aria-pressed={props.active}
      onClick={props.onClick}
      style={{
        padding: PAD.default,
        background: props.active ? `${T.accent}${O["15"]}` : T.bg,
        border: `1px solid ${props.active ? `${T.accent}${O["30"]}` : T.border}`,
        color: props.active ? T.accent : T.text,
        borderRadius: 10,
        cursor: "pointer",
        fontSize: `${FS.sm}px`,
        fontWeight: 500,
        transition: "all 0.2s",
      }}
    >
      {props.children}
    </button>
  );
}

// ============================================================================
// Cytoscape Helpers
// ============================================================================

function buildCytoscapeElements(nodes: EnrichedGraphNode[], edges: GraphEdge[]): ElementDefinition[] {
  const elements: ElementDefinition[] = nodes.map((node) => {
    const riskColor = RISK_COLORS[node.risk_level];
    const size = Math.max(20, Math.min(60, 20 + getDecisionImportance(node) * 40));
    const communityColor =
      node.community_id != null
        ? COMMUNITY_PALETTE[node.community_id % COMMUNITY_PALETTE.length]
        : riskColor.border;

    return {
      data: {
        id: node.id,
        label: node.canonical_name,
        fillColor: riskColor.bg,
        strokeColor: riskColor.border,
        communityColor,
        riskLevel: node.risk_level,
        size,
        shape: TYPE_META[node.entity_type]?.shape || "ellipse",
      },
    };
  });

  edges.forEach((edge, index) => {
    const relColor = REL_COLORS[edge.rel_type] || "#94a3b8";
    elements.push({
      data: {
        id: `${edge.source}-${edge.target}-${edge.rel_type}-${index}`,
        source: edge.source,
        target: edge.target,
        color: relColor,
        width: Math.max(1, edge.confidence * 3),
        opacity: 0.6 + edge.confidence * 0.4,
      },
    });
  });

  return elements;
}

function buildCytoscapeStyle(): cytoscape.StylesheetJsonBlock[] {
  return ([
    {
      selector: "node",
      style: {
        "background-color": "data(fillColor)",
        "border-color": "data(strokeColor)",
        "border-width": 2,
        content: (ele: NodeSingular) => String(ele.data("label") ?? ""),
        width: "data(size)",
        height: "data(size)",
        shape: "data(shape)",
        color: "#e2e8f0",
        "font-size": 10,
        "text-valign": "bottom",
        "text-margin-y": 6,
        "text-outline-width": 2,
        "text-outline-color": GRAPH_BG,
      },
    },
    {
      selector: 'node[riskLevel="HIGH"]',
      style: {
        "border-width": 3,
      },
    },
    {
      selector: 'node[riskLevel="CRITICAL"]',
      style: {
        "border-width": 3,
      },
    },
    {
      selector: "node.risk-pulse",
      style: {
        "border-width": 4,
      },
    },
    {
      selector: "node.community-colored",
      style: {
        "border-color": "data(communityColor)",
      },
    },
    {
      selector: "edge",
      style: {
        "line-color": "data(color)",
        width: "data(width)",
        opacity: "data(opacity)",
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "target-arrow-color": "data(color)",
        "arrow-scale": 0.6,
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#0ea5e9",
      },
    },
    {
      selector: "node.highlight",
      style: {
        "border-width": 3,
        "border-color": "#fbbf24",
        "background-color": "data(fillColor)",
      },
    },
    {
      selector: "node.pinned",
      style: {
        "border-width": 3,
        "border-color": "#f59e0b",
        "border-style": "double",
      },
    },
    {
      selector: "node.annotated",
      style: {
        "text-outline-color": "#7c3aed",
        "text-outline-width": 3,
      },
    },
    {
      selector: "node.path-node",
      style: {
        "border-width": 4,
        "border-color": "#0ea5e9",
      },
    },
    {
      selector: "edge.path-edge",
      style: {
        "line-color": "#0ea5e9",
        width: 4,
        opacity: 1,
        "target-arrow-color": "#0ea5e9",
        "z-index": 999,
      },
    },
    {
      selector: "node.propagation-source",
      style: {
        "border-width": 5,
        "border-color": "#f43f5e",
      },
    },
    {
      selector: "node.propagation-wave",
      style: {
        "border-width": 3,
        "border-color": "#fb923c",
      },
    },
  ] as unknown) as cytoscape.StylesheetJsonBlock[];
}
