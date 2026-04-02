import { useState } from "react";
import { T, FS } from "@/lib/tokens";
import { Search, Play, Upload, AlertCircle } from "lucide-react";
import { getToken } from "@/lib/auth";

interface AxiomSearchResult {
  status: string;
  iteration?: number;
  entities?: Array<{
    name: string;
    type: string;
    confidence: number;
  }>;
  relationships?: Array<{
    source: string;
    target: string;
    relationship_type: string;
  }>;
  signals?: Array<{
    type: string;
    value: string;
    confidence: number;
  }>;
  advisory?: Array<{
    opportunity_type: string;
    description: string;
    priority: string;
  }>;
}

interface AxiomSearchPanelProps {
  onResultsChange?: (results: AxiomSearchResult) => void;
}

export function AxiomSearchPanel({ onResultsChange }: AxiomSearchPanelProps) {
  const [targetEntity, setTargetEntity] = useState("");
  const [vehicleName, setVehicleName] = useState("");
  const [installation, setInstallation] = useState("");
  const [domainFocus, setDomainFocus] = useState("");
  const [provider, setProvider] = useState<"anthropic" | "openai">("anthropic");
  const [model, setModel] = useState("claude-3-5-sonnet");
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [iteration, setIteration] = useState(0);
  const [results, setResults] = useState<AxiomSearchResult | null>(null);
  const [error, setError] = useState<string>("");
  const [isIngesting, setIsIngesting] = useState(false);

  const handleSearch = async () => {
    if (!targetEntity.trim()) {
      setError("Target entity is required");
      return;
    }

    setError("");
    setIsRunning(true);
    setStatus("Initializing search...");
    setIteration(0);
    setResults(null);

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
        body: JSON.stringify({
          target_entity: targetEntity,
          vehicle_name: vehicleName || undefined,
          installation: installation || undefined,
          domain_focus: domainFocus || undefined,
          provider,
          model,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Search failed: ${response.status}`);
      }

      const data = (await response.json()) as AxiomSearchResult;
      setResults(data);
      setStatus(data.status || "Search completed");
      setIteration(data.iteration || 0);
      onResultsChange?.(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
      setStatus("");
    } finally {
      setIsRunning(false);
    }
  };

  const handleIngestToKG = async () => {
    if (!results) return;

    setIsIngesting(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/search/ingest", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
        body: JSON.stringify({
          search_results: results,
          target_entity: targetEntity,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Ingest failed: ${response.status}`);
      }

      setStatus("Results ingested to knowledge graph");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsIngesting(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-4 p-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}` }}
    >
      <h3 style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>AXIOM Search</h3>

      {/* Search inputs */}
      <div className="space-y-3">
        <div>
          <label
            style={{
              display: "block",
              fontSize: FS.sm,
              fontWeight: 500,
              color: T.muted,
              marginBottom: 6,
            }}
          >
            Target Entity Name *
          </label>
          <input
            type="text"
            value={targetEntity}
            onChange={(e) => setTargetEntity(e.target.value)}
            placeholder="e.g., Acme Corp, John Smith"
            disabled={isRunning}
            className="w-full rounded border outline-none"
            style={{
              padding: "8px 10px",
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
                marginBottom: 6,
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
              className="w-full rounded border outline-none"
              style={{
                padding: "8px 10px",
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
                marginBottom: 6,
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
              className="w-full rounded border outline-none"
              style={{
                padding: "8px 10px",
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
              marginBottom: 6,
            }}
          >
            Domain Focus
          </label>
          <input
            type="text"
            value={domainFocus}
            onChange={(e) => setDomainFocus(e.target.value)}
            placeholder="e.g., defense, tech, finance"
            disabled={isRunning}
            className="w-full rounded border outline-none"
            style={{
              padding: "8px 10px",
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
                marginBottom: 6,
              }}
            >
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as "anthropic" | "openai")}
              disabled={isRunning}
              className="w-full rounded border outline-none"
              style={{
                padding: "8px 10px",
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
                marginBottom: 6,
              }}
            >
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={isRunning}
              className="w-full rounded border outline-none"
              style={{
                padding: "8px 10px",
                fontSize: FS.sm,
                background: T.bg,
                border: `1px solid ${T.border}`,
                color: T.text,
              }}
            >
              {provider === "anthropic" && (
                <>
                  <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
                  <option value="claude-3-opus">Claude 3 Opus</option>
                  <option value="claude-3-haiku">Claude 3 Haiku</option>
                </>
              )}
              {provider === "openai" && (
                <>
                  <option value="gpt-4">GPT-4</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                </>
              )}
            </select>
          </div>
        </div>
      </div>

      {/* Status display */}
      {isRunning && (
        <div className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.borderActive}` }}>
          <div style={{ fontSize: FS.sm, color: T.accent, marginBottom: 4 }}>
            {status}
          </div>
          {iteration > 0 && (
            <div style={{ fontSize: FS.sm, color: T.muted }}>
              Iteration {iteration}...
            </div>
          )}
          <div className="mt-2" style={{ height: 2, background: T.border, borderRadius: 1, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                background: T.accent,
                animation: "pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
              }}
            />
          </div>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="rounded-lg p-3 flex gap-2" style={{ background: T.red + "15", border: `1px solid ${T.red}` }}>
          <AlertCircle size={16} color={T.red} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: FS.sm, color: T.red }}>{error}</div>
        </div>
      )}

      {/* Search button */}
      <button
        onClick={handleSearch}
        disabled={isRunning || !targetEntity.trim()}
        className="flex items-center justify-center gap-2 rounded px-4 py-2 cursor-pointer font-medium"
        style={{
          background: isRunning ? T.accent + "60" : T.accent,
          color: "#000",
          fontSize: FS.sm,
          opacity: isRunning || !targetEntity.trim() ? 0.6 : 1,
          cursor: isRunning || !targetEntity.trim() ? "not-allowed" : "pointer",
        }}
      >
        <Play size={14} />
        {isRunning ? "Searching..." : "Run AXIOM Search"}
      </button>

      {/* Results section */}
      {results && (
        <div className="space-y-3 pt-3 border-t" style={{ borderColor: T.border }}>
          {results.entities && results.entities.length > 0 && (
            <div>
              <h4
                style={{
                  fontSize: FS.sm,
                  fontWeight: 600,
                  color: T.text,
                  marginBottom: 8,
                }}
              >
                Discovered Entities ({results.entities.length})
              </h4>
              <div className="space-y-2">
                {results.entities.slice(0, 5).map((entity, idx) => (
                  <div
                    key={idx}
                    className="flex items-start justify-between gap-2 p-2 rounded"
                    style={{ background: T.bg, border: `1px solid ${T.border}` }}
                  >
                    <div>
                      <div style={{ fontSize: FS.sm, fontWeight: 500, color: T.text }}>
                        {entity.name}
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.muted }}>
                        {entity.type}
                      </div>
                    </div>
                    <div
                      style={{
                        fontSize: FS.sm,
                        fontWeight: 600,
                        color: T.accent,
                        flexShrink: 0,
                      }}
                    >
                      {(entity.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.relationships && results.relationships.length > 0 && (
            <div>
              <h4
                style={{
                  fontSize: FS.sm,
                  fontWeight: 600,
                  color: T.text,
                  marginBottom: 8,
                }}
              >
                Relationships ({results.relationships.length})
              </h4>
              <div className="space-y-2">
                {results.relationships.slice(0, 3).map((rel, idx) => (
                  <div
                    key={idx}
                    className="p-2 rounded text-center"
                    style={{ background: T.bg, border: `1px solid ${T.border}` }}
                  >
                    <div style={{ fontSize: FS.sm, color: T.muted }}>
                      {rel.source} <span style={{ color: T.accent }}>→</span> {rel.target}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
                      {rel.relationship_type}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.signals && results.signals.length > 0 && (
            <div>
              <h4
                style={{
                  fontSize: FS.sm,
                  fontWeight: 600,
                  color: T.text,
                  marginBottom: 8,
                }}
              >
                Signals ({results.signals.length})
              </h4>
              <div className="space-y-1">
                {results.signals.slice(0, 4).map((signal, idx) => (
                  <div
                    key={idx}
                    style={{
                      fontSize: FS.sm,
                      color: T.dim,
                      padding: "6px 0",
                      borderBottom: `1px solid ${T.border}`,
                    }}
                  >
                    <span style={{ color: T.text, fontWeight: 500 }}>
                      {signal.type}
                    </span>
                    : {signal.value}
                  </div>
                ))}
              </div>
            </div>
          )}

          {results.advisory && results.advisory.length > 0 && (
            <div>
              <h4
                style={{
                  fontSize: FS.sm,
                  fontWeight: 600,
                  color: T.text,
                  marginBottom: 8,
                }}
              >
                Advisory Opportunities
              </h4>
              <div className="space-y-2">
                {results.advisory.map((adv, idx) => (
                  <div
                    key={idx}
                    className="p-2 rounded"
                    style={{ background: T.bg, border: `1px solid ${T.border}` }}
                  >
                    <div
                      style={{
                        fontSize: FS.sm,
                        fontWeight: 500,
                        color: T.accent,
                      }}
                    >
                      {adv.opportunity_type}
                    </div>
                    <div
                      style={{
                        fontSize: FS.sm,
                        color: T.dim,
                        marginTop: 4,
                      }}
                    >
                      {adv.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Ingest button */}
          <button
            onClick={handleIngestToKG}
            disabled={isIngesting}
            className="w-full flex items-center justify-center gap-2 rounded px-4 py-2 cursor-pointer font-medium mt-4"
            style={{
              background: T.accent + "20",
              border: `1px solid ${T.accent}`,
              color: T.accent,
              fontSize: FS.sm,
              opacity: isIngesting ? 0.6 : 1,
              cursor: isIngesting ? "not-allowed" : "pointer",
            }}
          >
            <Upload size={14} />
            {isIngesting ? "Ingesting..." : "Ingest to Knowledge Graph"}
          </button>
        </div>
      )}
    </div>
  );
}
