import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { T, FS, PAD, SP, O } from "@/lib/tokens";
import { Play, Search, Upload, AlertCircle } from "lucide-react";
import { getToken } from "@/lib/auth";
import { useHotkey } from "@/lib/use-hotkeys";
import { EmptyPanel, InlineMessage, LoadingPanel, PanelHeader, ShortcutBadge, StatusPill } from "./shell-primitives";

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
  seed?: {
    targetEntity: string;
    vehicleName?: string;
    domainFocus?: string;
    seedLabel?: string;
    autoRun?: boolean;
  } | null;
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

export function AxiomSearchPanel({ onResultsChange, seed = null }: AxiomSearchPanelProps) {
  const targetInputRef = useRef<HTMLInputElement | null>(null);
  const resultsScrollRef = useRef<HTMLDivElement | null>(null);
  const autoRunSeedKeyRef = useRef<string>("");
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
  const [showExecutionControls, setShowExecutionControls] = useState(false);
  const [resultsScrollState, setResultsScrollState] = useState({
    canScrollUp: false,
    canScrollDown: false,
  });

  const syncResultsScrollState = useCallback(() => {
    const el = resultsScrollRef.current;
    if (!el) return;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    setResultsScrollState({
      canScrollUp: el.scrollTop > 8,
      canScrollDown: remaining > 8,
    });
  }, []);

  useEffect(() => {
    const el = resultsScrollRef.current;
    if (!el) return;
    el.scrollTop = 0;
    window.requestAnimationFrame(syncResultsScrollState);
  }, [error, isRunning, results, status, syncResultsScrollState]);

  useHotkey("cmd+f", () => {
    targetInputRef.current?.focus();
    targetInputRef.current?.select();
  }, { ignoreInputs: false });

  const runSearch = useCallback(async (
    ingest: boolean,
    overrides?: Partial<{
      targetEntity: string;
      vehicleName: string;
      installation: string;
      domainFocus: string;
      provider: AxiomProvider;
      model: string;
    }>,
  ) => {
    const nextTargetEntity = overrides?.targetEntity ?? targetEntity;
    const nextVehicleName = overrides?.vehicleName ?? vehicleName;
    const nextInstallation = overrides?.installation ?? installation;
    const nextDomainFocus = overrides?.domainFocus ?? domainFocus;
    const nextProvider = overrides?.provider ?? provider;
    const nextModel = overrides?.model ?? model;

    if (!nextTargetEntity.trim()) {
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
        prime_contractor: nextTargetEntity,
        vehicle_name: nextVehicleName || undefined,
        installation: nextInstallation || undefined,
        context: nextDomainFocus || undefined,
        provider: nextProvider,
        model: nextModel,
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
  }, [domainFocus, installation, model, onResultsChange, provider, targetEntity, vehicleName]);

  useEffect(() => {
    if (!seed?.targetEntity) return;
    const nextDomainFocus = seed.domainFocus === "full entity picture" ? "" : seed.domainFocus || "";
    setTargetEntity(seed.targetEntity);
    setVehicleName(seed.vehicleName || "");
    setDomainFocus(nextDomainFocus);
    setInstallation("");
    if (!seed.autoRun) return;

    const seedKey = JSON.stringify({
      targetEntity: seed.targetEntity,
      vehicleName: seed.vehicleName || "",
      domainFocus: nextDomainFocus,
    });
    if (autoRunSeedKeyRef.current === seedKey) return;
    autoRunSeedKeyRef.current = seedKey;

    const runSeed = async () => {
      setError("");
      setIsRunning(true);
      setStatus(`AXIOM picked up ${seed.seedLabel || seed.targetEntity} from Front Porch and is working the thread.`);
      setIteration(0);
      setResults(null);

      try {
        const data = await runSearch(false, {
          targetEntity: seed.targetEntity,
          vehicleName: seed.vehicleName || "",
          domainFocus: nextDomainFocus,
        });
        if (data) {
          setStatus(data.status || "AXIOM finished the first pass.");
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(message);
        setStatus("");
      } finally {
        setIsRunning(false);
      }
    };

    void runSeed();
  }, [runSearch, seed]);

  const handleSearch = async () => {
    setError("");
    setIsRunning(true);
    setStatus(autoIngest ? "AXIOM is working the first public picture and warming the graph." : "AXIOM is working the first public picture.");
    setIteration(0);
    setResults(null);

    try {
      const data = await runSearch(autoIngest);
      if (data) {
        setStatus(
          autoIngest
            ? "AXIOM finished the first pass and promoted the accepted picture into the graph."
            : data.status || "AXIOM finished the first pass.",
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
        setStatus("AXIOM reran the thread and promoted the accepted picture into the graph.");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsIngesting(false);
    }
  };

  const runOnEnter = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || isRunning) {
      return;
    }
    event.preventDefault();
    void handleSearch();
  };

  const collectionBrief = [
    targetEntity.trim() ? `Target ${targetEntity.trim()}` : null,
    vehicleName.trim() ? `Vehicle ${vehicleName.trim()}` : null,
    installation.trim() ? `Installation ${installation.trim()}` : null,
    domainFocus.trim() ? `Context ${domainFocus.trim()}` : null,
  ].filter(Boolean);

  return (
    <div
      className="flex flex-col gap-4 rounded-lg"
      style={{
        background: "rgba(12,16,24,0.82)",
        border: `1px solid rgba(255,255,255,0.06)`,
        padding: PAD.comfortable,
        maxHeight: "min(72vh, 860px)",
      }}
    >
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 3,
          display: "grid",
          gap: SP.md,
          paddingBottom: SP.md,
          background: "linear-gradient(180deg, rgba(12,16,24,0.98) 0%, rgba(12,16,24,0.94) 78%, rgba(12,16,24,0) 100%)",
          backdropFilter: "blur(18px)",
        }}
      >
        <PanelHeader
          eyebrow="AXIOM collection"
          title="What should I work?"
          description="Give me the target, vehicle, or weak point that still feels wrong. Add context only if it changes the trail."
          meta={
            <>
              <StatusPill tone="neutral">
                <ShortcutBadge>⌘F</ShortcutBadge>
                Focus target
              </StatusPill>
              <StatusPill tone="neutral">
                <ShortcutBadge>Enter</ShortcutBadge>
                Run pass
              </StatusPill>
            </>
          }
        />

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
              Who or what is the pressure point? *
            </label>
            <input
              ref={targetInputRef}
              type="text"
              value={targetEntity}
              onChange={(e) => setTargetEntity(e.target.value)}
              onKeyDown={runOnEnter}
              placeholder="Amentum on ILS 2"
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
            <div style={{ fontSize: FS.xs, color: T.textTertiary, marginTop: SP.xs }}>
              Start with the incumbent, teammate, sub, or unresolved player that still carries dark space.
            </div>
          </div>

          {collectionBrief.length > 0 ? (
            <InlineMessage
              tone="info"
              title="Working from"
              message={collectionBrief.join(" • ")}
              icon={Search}
            />
          ) : null}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
                Vehicle
              </label>
              <input
                type="text"
                value={vehicleName}
                onChange={(e) => setVehicleName(e.target.value)}
                onKeyDown={runOnEnter}
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
                onKeyDown={runOnEnter}
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
                Why it matters
            </label>
            <input
              type="text"
              value={domainFocus}
              onChange={(e) => setDomainFocus(e.target.value)}
              onKeyDown={runOnEnter}
              placeholder="Recompete pressure, ownership wall, teammate risk"
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

          <div
            style={{
              borderTop: `1px solid ${T.border}`,
              paddingTop: SP.sm,
              display: "flex",
              flexDirection: "column",
              gap: SP.sm,
            }}
          >
            <button
              type="button"
              onClick={() => setShowExecutionControls((current) => !current)}
              className="helios-focus-ring"
              aria-label={showExecutionControls ? "Hide AXIOM execution controls" : "Show AXIOM execution controls"}
              aria-expanded={showExecutionControls}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SP.xs,
                alignSelf: "flex-start",
                borderRadius: 999,
                border: `1px solid ${T.border}`,
                background: T.surface,
                color: T.textSecondary,
                padding: "8px 12px",
                fontSize: FS.sm,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {showExecutionControls ? "Hide" : "Show"} model and graph controls
            </button>

            {showExecutionControls ? (
              <div
                className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-3"
                style={{ alignItems: "end" }}
              >
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

                <label
                  htmlFor="autoIngestCheckbox"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: SP.sm,
                    fontSize: FS.sm,
                    fontWeight: 500,
                    color: T.text,
                    cursor: isRunning ? "not-allowed" : "pointer",
                    minHeight: 40,
                  }}
                >
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
                  Auto-ingest to graph
                </label>
              </div>
            ) : null}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: SP.md, flexWrap: "wrap" }}>
          <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.6 }}>
            {isRunning
              ? "AXIOM is working this thread. The brief stays pinned while the findings update below."
              : "The brief stays pinned. Scroll the findings below without losing the thread."}
          </div>
          <button
            type="button"
            onClick={handleSearch}
            disabled={isRunning || !targetEntity.trim()}
            aria-label="Run AXIOM collection pass"
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
            {isRunning ? "Working this thread" : "Work this thread"}
          </button>
        </div>
      </div>

      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {resultsScrollState.canScrollUp ? (
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: SP.xs,
              height: 28,
              background: "linear-gradient(180deg, rgba(12,16,24,0.98) 0%, rgba(12,16,24,0) 100%)",
              pointerEvents: "none",
              zIndex: 2,
            }}
          />
        ) : null}

        <div
          ref={resultsScrollRef}
          onScroll={syncResultsScrollState}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: SP.md,
            overflowY: "auto",
            minHeight: 0,
            paddingRight: SP.xs,
            paddingBottom: SP.sm,
          }}
        >
          {isRunning ? (
            <LoadingPanel
              label={status || "AXIOM is working the first pass."}
              detail={iteration > 0 ? `Iteration ${iteration} is in progress.` : "Collecting public evidence, keeping the weak residue separate, and shaping the first picture."}
            />
          ) : null}

          {error ? (
            <InlineMessage
              tone="danger"
              title="AXIOM hit a wall"
              message={error}
              icon={AlertCircle}
            />
          ) : null}

          {!error && !isRunning && status ? (
            <InlineMessage
              tone="success"
              title="AXIOM update"
              message={status}
              icon={Search}
            />
          ) : null}

          {!isRunning && !results && !error ? (
            <EmptyPanel
              title="Nothing active yet"
              description="Bring the entity, vehicle, or weak point that still feels unresolved. AXIOM will work outward from there and keep the thin parts explicit."
              icon={Search}
            />
          ) : null}

          {results ? (
            <div className="space-y-3 border-t pt-3" style={{ borderColor: T.border }}>
          <div
            className="grid grid-cols-2 gap-3 rounded-lg md:grid-cols-4"
            style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
          >
            {[
              { label: "Entities", value: results.entities.length },
              { label: "Leads", value: results.relationships.length },
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

          {results.intelligenceGaps.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                Where the picture is still thin ({results.intelligenceGaps.length})
              </h4>
              <div className="space-y-2">
                {results.intelligenceGaps.slice(0, 4).map((gap, index) => (
                  <div
                    key={`${gap.gap_type}-${index}`}
                    className="rounded"
                    style={{ background: `${T.amber}${O["08"]}`, border: `1px solid ${T.amber}${O["20"]}`, padding: PAD.default }}
                  >
                    <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.amber }}>
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
                Best next threads ({results.advisory.length})
              </h4>
              <div className="space-y-2">
                {results.advisory.map((advisory, index) => (
                  <div
                    key={`${advisory.opportunity_type}-${index}`}
                    className="rounded"
                    style={{ background: `${T.accent}${O["08"]}`, border: `1px solid ${T.accent}${O["20"]}`, padding: PAD.default }}
                  >
                    <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.accent }}>
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

          {results.kgIngestion && (
            <InlineMessage
              tone={(results.kgIngestion.entities_created ?? 0) > 0 || (results.kgIngestion.relationships_created ?? 0) > 0 ? "success" : "info"}
              title="Graph promotion"
              message={
                <>
                  {(results.kgIngestion.entities_created ?? 0)} entities, {(results.kgIngestion.relationships_created ?? 0)} relationships, and{" "}
                  {(results.kgIngestion.claims_created ?? 0)} claims created.
                  {results.neo4jSync ? (
                    <span style={{ display: "block", marginTop: SP.xs, color: T.textSecondary }}>
                      Neo4j sync: <span style={{ color: T.text }}>{results.neo4jSync.status || "unknown"}</span>
                      {results.neo4jSync.error ? ` (${results.neo4jSync.error})` : ""}
                    </span>
                  ) : null}
                </>
              }
            />
          )}

          {results.entities.length > 0 && (
            <div>
              <h4 style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, marginBottom: SP.sm }}>
                What surfaced ({results.entities.length})
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
                Trail hints ({results.relationships.length})
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

          {!autoIngest && (
            <button
              type="button"
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
              {isIngesting ? "Promoting..." : "Promote this picture to the graph"}
            </button>
          )}
            </div>
          ) : null}
        </div>

        {resultsScrollState.canScrollDown ? (
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: SP.xs,
              height: 34,
              background: "linear-gradient(180deg, rgba(12,16,24,0) 0%, rgba(12,16,24,0.98) 100%)",
              pointerEvents: "none",
              zIndex: 2,
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
