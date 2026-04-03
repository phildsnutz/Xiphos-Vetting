import { useState } from "react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import { Play, Upload, AlertCircle } from "lucide-react";
import { getToken } from "@/lib/auth";
import { EmptyPanel, InlineMessage, LoadingPanel, SectionEyebrow } from "./shell-primitives";

type AxiomProvider = "anthropic" | "openai";

interface RawAxiomSearchResult {
  status?: string;
  error?: string;
  iteration?: number;
  iterations?: unknown[];
  entities?: Array<{
    name: string;
    entity_type?: string;
    type?: string;
    confidence?: number;
  }>;
  relationships?: Array<{
    source_entity?: string;
    source?: string;
    target_entity?: string;
    target?: string;
    rel_type?: string;
    relationship_type?: string;
    confidence?: number;
  }>;
  intelligence_gaps?: Array<{
    gap_type?: string;
    description?: string;
    confidence?: number;
  }>;
  advisory_opportunities?: Array<{
    opportunity_type?: string;
    description?: string;
    priority?: string;
  }>;
  advisory?: Array<{
    opportunity_type?: string;
    description?: string;
    priority?: string;
  }>;
  total_queries?: number;
  total_connector_calls?: number;
  elapsed_ms?: number;
  kg_ingestion?: {
    entities_created?: number;
    relationships_created?: number;
    claims_created?: number;
    evidence_created?: number;
  };
  neo4j_sync?: {
    status?: string;
    job_id?: string;
    status_url?: string | null;
    reused_existing_job?: boolean;
    error?: string;
  };
}

interface AxiomSearchResult {
  status: string;
  iteration: number;
  entities: Array<{
    name: string;
    type: string;
    confidence: number;
  }>;
  relationships: Array<{
    source: string;
    target: string;
    relationship_type: string;
    confidence: number;
  }>;
  intelligenceGaps: Array<{
    gap_type: string;
    description: string;
    confidence: number;
  }>;
  advisory: Array<{
    opportunity_type: string;
    description: string;
    priority: string;
  }>;
  totalQueries: number;
  totalConnectorCalls: number;
  elapsedMs: number;
  kgIngestion?: RawAxiomSearchResult["kg_ingestion"];
  neo4jSync?: RawAxiomSearchResult["neo4j_sync"];
}

interface AxiomSearchPanelProps {
  onResultsChange?: (results: AxiomSearchResult) => void;
}

function normalizeSearchResult(raw: RawAxiomSearchResult): AxiomSearchResult {
  return {
    status: raw.status || "completed",
    iteration: raw.iteration ?? raw.iterations?.length ?? 0,
    entities: (raw.entities || []).map((entity) => ({
      name: entity.name,
      type: entity.entity_type || entity.type || "unknown",
      confidence: entity.confidence ?? 0,
    })),
    relationships: (raw.relationships || []).map((relationship) => ({
      source: relationship.source_entity || relationship.source || "Unknown",
      target: relationship.target_entity || relationship.target || "Unknown",
      relationship_type: relationship.rel_type || relationship.relationship_type || "related_to",
      confidence: relationship.confidence ?? 0,
    })),
    intelligenceGaps: (raw.intelligence_gaps || []).map((gap) => ({
      gap_type: gap.gap_type || "gap",
      description: gap.description || "No description provided",
      confidence: gap.confidence ?? 0,
    })),
    advisory: (raw.advisory_opportunities || raw.advisory || []).map((opportunity) => ({
      opportunity_type: opportunity.opportunity_type || "advisory",
      description: opportunity.description || "No description provided",
      priority: opportunity.priority || "medium",
    })),
    totalQueries: raw.total_queries ?? 0,
    totalConnectorCalls: raw.total_connector_calls ?? 0,
    elapsedMs: raw.elapsed_ms ?? 0,
    kgIngestion: raw.kg_ingestion,
    neo4jSync: raw.neo4j_sync,
  };
}

function formatMillis(elapsedMs: number): string {
  if (!elapsedMs) return "0 ms";
  if (elapsedMs < 1000) return `${elapsedMs} ms`;
  return `${(elapsedMs / 1000).toFixed(1)} s`;
}

export function AxiomSearchPanel({ onResultsChange }: AxiomSearchPanelProps) {
  const [targetEntity, setTargetEntity] = useState("");
  const [vehicleName, setVehicleName] = useState("");
  const [installation, setInstallation] = useState("");
  const [domainFocus, setDomainFocus] = useState("");
  const [provider, setProvider] = useState<AxiomProvider>("anthropic");
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [iteration, setIteration] = useState(0);
  const [results, setResults] = useState<AxiomSearchResult | null>(null);
  const [error, setError] = useState<string>("");
  const [isIngesting, setIsIngesting] = useState(false);
  const [autoIngest, setAutoIngest] = useState(true);

  const runSearch = async (ingest: boolean) => {
    if (!targetEntity.trim()) {
      setError("Target entity is required");
      return null;
    }

    const endpoint = ingest ? "/api/axiom/search/ingest" : "/api/axiom/search";
    const token = getToken();
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: JSON.stringify({
        prime_contractor: targetEntity,
        vehicle_name: vehicleName || undefined,
        installation: installation || undefined,
        context: domainFocus || undefined,
        provider,
        model,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `Search failed: ${response.status}`);
    }

    const raw = (await response.json()) as RawAxiomSearchResult;
    if (raw.error) {
      throw new Error(raw.error);
    }

    const data = normalizeSearchResult(raw);
    setResults(data);
    setIteration(data.iteration);
    onResultsChange?.(data);
    return data;
  };

  const handleSearch = async () => {
    setError("");
    setIsRunning(true);
    setStatus(autoIngest ? "Initializing search and ingesting to Knowledge Graph..." : "Initializing search...");
    setIteration(0);
    setResults(null);

    try {
      const data = await runSearch(autoIngest);
      if (data) {
        setStatus(
          autoIngest
            ? "Search completed and results ingested to Knowledge Graph"
            : data.status || "Search completed",
        );
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
      setStatus("");
    } finally {
      setIsRunning(false);
    }
  };

  const handleIngestToKG = async () => {
    setIsIngesting(true);
    setError("");

    try {
      const data = await runSearch(true);
      if (data) {
        setStatus("Search rerun and results ingested to Knowledge Graph");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsIngesting(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}`, padding: PAD.default }}
    >
      <div>
        <SectionEyebrow>Search</SectionEyebrow>
        <h2 style={{ fontSize: FS.base, fontWeight: 700, color: T.text, margin: `${SP.xs}px 0 0` }}>Run a focused collection pass</h2>
      </div>

      <div className="space-y-3">
        <div>
          <label
            style={{
              display: "block",
              fontSize: FS.sm,
              fontWeight: 500,
              color: T.muted,
              marginBottom: SP.sm,
            }}
          >
            Target Entity Name *
          </label>
          <input
            type="text"
            value={targetEntity}
            onChange={(e) => setTargetEntity(e.target.value)}
            placeholder="e.g., Acme Corp, SMX Technologies"
            disabled={isRunning}
            aria-label="AXIOM target entity"
            className="w-full rounded border outline-none"
            style={{
              padding: PAD.default,
              fontSize: FS.sm,
              background: T.bg,
              border: `1px solid ${T.border}`,
              color: T.text,
            }}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              style={{
                display: "block",
                fontSize: FS.sm,
                fontWeight: 500,
                color: T.muted,
                marginBottom: SP.sm,
              }}
            >
              Vehicle Name
            </label>
            <input
              type="text"
              value={vehicleName}
              onChange={(e) => setVehicleName(e.target.value)}
              placeholder="Optional"
              disabled={isRunning}
              aria-label="AXIOM vehicle name"
              className="w-full rounded border outline-none"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
              }}
            />
          </div>
          <div>
            <label
              style={{
                display: "block",
                fontSize: FS.sm,
                fontWeight: 500,
                color: T.muted,
                marginBottom: SP.sm,
              }}
            >
              Installation
            </label>
            <input
              type="text"
              value={installation}
              onChange={(e) => setInstallation(e.target.value)}
              placeholder="Optional"
              disabled={isRunning}
              aria-label="AXIOM installation"
              className="w-full rounded border outline-none"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
              }}
            />
          </div>
        </div>

        <div>
          <label
            style={{
              display: "block",
              fontSize: FS.sm,
              fontWeight: 500,
              color: T.muted,
              marginBottom: SP.sm,
            }}
          >
            Context / Mission Focus
          </label>
          <input
            type="text"
            value={domainFocus}
            onChange={(e) => setDomainFocus(e.target.value)}
            placeholder="e.g., INDOPACOM C5ISR support"
            disabled={isRunning}
            aria-label="AXIOM mission context"
            className="w-full rounded border outline-none"
            style={{
              padding: PAD.default,
              fontSize: FS.sm,
              background: T.bg,
              border: `1px solid ${T.border}`,
              color: T.text,
            }}
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="autoIngestCheckbox"
            checked={autoIngest}
            onChange={(e) => setAutoIngest(e.target.checked)}
            disabled={isRunning}
            aria-label="Auto-ingest AXIOM results to knowledge graph"
            style={{
              cursor: isRunning ? "not-allowed" : "pointer",
              width: SP.lg,
              height: SP.lg,
            }}
          />
          <label
            htmlFor="autoIngestCheckbox"
            style={{
              fontSize: FS.sm,
              fontWeight: 500,
              color: T.text,
              cursor: isRunning ? "not-allowed" : "pointer",
            }}
          >
            Auto-ingest to Knowledge Graph
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              style={{
                display: "block",
                fontSize: FS.sm,
                fontWeight: 500,
                color: T.muted,
                marginBottom: SP.sm,
              }}
            >
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => {
                const nextProvider = e.target.value as AxiomProvider;
                setProvider(nextProvider);
                setModel(nextProvider === "anthropic" ? "claude-sonnet-4-6" : "gpt-4.1");
              }}
              disabled={isRunning}
              aria-label="AXIOM provider"
              className="w-full rounded border outline-none"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
              }}
            >
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div>
            <label
              style={{
                display: "block",
                fontSize: FS.sm,
                fontWeight: 500,
                color: T.muted,
                marginBottom: SP.sm,
              }}
            >
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={isRunning}
              aria-label="AXIOM model"
              className="w-full rounded border outline-none"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
              }}
            >
              {provider === "anthropic" && (
                <>
                  <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                  <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
                  <option value="claude-3-opus">Claude 3 Opus</option>
                </>
              )}
              {provider === "openai" && (
                <>
                  <option value="gpt-4.1">GPT-4.1</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4">GPT-4</option>
                </>
              )}
            </select>
          </div>
        </div>
      </div>

      {isRunning ? (
        <LoadingPanel
          label={status || "Running AXIOM search"}
          detail={iteration > 0 ? `Iteration ${iteration} in progress.` : "Collecting structured evidence and evaluating knowledge graph ingest."}
        />
      ) : null}

      {error ? (
        <InlineMessage
          tone="danger"
          title="AXIOM search failed"
          message={error}
          icon={AlertCircle}
        />
      ) : null}

      <button
        onClick={handleSearch}
        disabled={isRunning || !targetEntity.trim()}
        aria-label="Run AXIOM search"
        className="flex items-center justify-center gap-2 rounded cursor-pointer font-medium"
        style={{
          padding: PAD.default,
          background: isRunning ? `${T.accent}60` : T.accent,
          color: T.textInverse,
          fontSize: FS.sm,
          opacity: isRunning || !targetEntity.trim() ? 0.6 : 1,
          cursor: isRunning || !targetEntity.trim() ? "not-allowed" : "pointer",
        }}
      >
        <Play size={SP.md + SP.xs} />
        {isRunning ? "Searching..." : "Run AXIOM Search"}
      </button>

      {!isRunning && !results && !error ? (
        <EmptyPanel
          title="No search run yet"
          description="Start with a prime, suspected sub, or target entity. Add vehicle and mission context only when it helps constrain the hunt."
          icon={Upload}
        />
      ) : null}

      {results && (
        <div className="space-y-3 border-t pt-3" style={{ borderColor: T.border }}>
          <div
            className="grid grid-cols-2 gap-3 rounded-lg md:grid-cols-4"
            style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
          >
            {[
              { label: "Entities", value: results.entities.length },
              { label: "Relationships", value: results.relationships.length },
              { label: "Queries", value: results.totalQueries },
              { label: "Elapsed", value: formatMillis(results.elapsedMs) },
            ].map((item) => (
              <div key={item.label}>
                <div style={{ fontSize: FS.sm, color: T.muted }}>{item.label}</div>
                <div style={{ fontSize: FS.base, fontWeight: 600, color: T.text, marginTop: SP.xs / 2 }}>
                  {item.value}
                </div>
              </div>
            ))}
          </div>

          {results.kgIngestion && (
            <div className="rounded-lg" style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}>
              <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Knowledge Graph Ingestion
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted }}>
                {results.kgIngestion.entities_created ?? 0} entities, {results.kgIngestion.relationships_created ?? 0} relationships, {results.kgIngestion.claims_created ?? 0} claims
              </div>
              {results.neo4jSync && (
                <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.sm }}>
                  Neo4j sync: <span style={{ color: T.text }}>{results.neo4jSync.status || "unknown"}</span>
                  {results.neo4jSync.error ? ` (${results.neo4jSync.error})` : ""}
                </div>
              )}
            </div>
          )}

          {results.entities.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Discovered Entities ({results.entities.length})
              </h4>
              <div className="space-y-2">
                {results.entities.slice(0, 5).map((entity, index) => (
                  <div
                    key={`${entity.name}-${index}`}
                    className="flex items-start justify-between gap-2 rounded"
                    style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
                  >
                    <div>
                      <div style={{ fontSize: FS.sm, fontWeight: 500, color: T.text }}>{entity.name}</div>
                      <div style={{ fontSize: FS.sm, color: T.muted }}>{entity.type}</div>
                    </div>
                    <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.accent, flexShrink: 0 }}>
                      {(entity.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.relationships.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Relationships ({results.relationships.length})
              </h4>
              <div className="space-y-2">
                {results.relationships.slice(0, 3).map((relationship, index) => (
                  <div
                    key={`${relationship.source}-${relationship.relationship_type}-${relationship.target}-${index}`}
                    className="rounded text-center"
                    style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
                  >
                    <div style={{ fontSize: FS.sm, color: T.muted }}>
                      {relationship.source} <span style={{ color: T.accent }}>→</span> {relationship.target}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs / 2 }}>
                      {relationship.relationship_type}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.intelligenceGaps.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Intelligence Gaps ({results.intelligenceGaps.length})
              </h4>
              <div className="space-y-2">
                {results.intelligenceGaps.slice(0, 4).map((gap, index) => (
                  <div
                    key={`${gap.gap_type}-${index}`}
                    className="rounded"
                    style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
                  >
                    <div style={{ fontSize: FS.sm, fontWeight: 500, color: T.accent }}>
                      {gap.gap_type}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs / 2 }}>
                      {gap.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.advisory.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Advisory Opportunities ({results.advisory.length})
              </h4>
              <div className="space-y-2">
                {results.advisory.map((advisory, index) => (
                  <div
                    key={`${advisory.opportunity_type}-${index}`}
                    className="rounded"
                    style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
                  >
                    <div style={{ fontSize: FS.sm, fontWeight: 500, color: T.accent }}>
                      {advisory.opportunity_type}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs / 2 }}>
                      {advisory.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!autoIngest && (
            <button
              onClick={handleIngestToKG}
              disabled={isIngesting}
              aria-label="Rerun AXIOM search and ingest to knowledge graph"
              className="mt-4 flex w-full items-center justify-center gap-2 rounded cursor-pointer font-medium"
              style={{
                padding: PAD.default,
                background: `${T.accent}20`,
                border: `1px solid ${T.accent}`,
                color: T.accent,
                fontSize: FS.sm,
                opacity: isIngesting ? 0.6 : 1,
                cursor: isIngesting ? "not-allowed" : "pointer",
              }}
            >
              <Upload size={SP.md + SP.xs} />
              {isIngesting ? "Ingesting..." : "Rerun and Ingest to Knowledge Graph"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
