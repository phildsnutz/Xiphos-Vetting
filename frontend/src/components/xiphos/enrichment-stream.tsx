import { useState, useEffect, useRef } from "react";
import { T, FS, tierBand, type TierKey } from "@/lib/tokens";
import { CONNECTOR_META } from "@/lib/connectors";
import { buildProtectedUrl } from "@/lib/api";
import { Radar, CheckCircle, XCircle, Loader, Zap } from "lucide-react";

type ConnectorState = "pending" | "running" | "done" | "error";

interface ConnectorProgress {
  name: string;
  state: ConnectorState;
  hasData?: boolean;
  findingsCount?: number;
  elapsedMs?: number;
  error?: string;
}

interface ScoringResult {
  calibrated_tier: string;
  calibrated_probability: number;
  is_hard_stop: boolean;
  composite_score: number;
}

interface EnrichmentStreamProps {
  caseId: string;
  apiBase: string;
  onComplete?: () => void;
}

function parseStreamEvent<T>(event: Event, label: string): T | null {
  try {
    return JSON.parse((event as MessageEvent).data) as T;
  } catch (error) {
    console.warn(`Failed to parse enrichment stream event: ${label}`, error);
    return null;
  }
}

export function EnrichmentStream({ caseId, apiBase, onComplete }: EnrichmentStreamProps) {
  const [connectors, setConnectors] = useState<ConnectorProgress[]>([]);
  const [totalConnectors, setTotalConnectors] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalFindings, setTotalFindings] = useState(0);
  const [phase, setPhase] = useState<"connecting" | "enriching" | "scoring" | "done" | "error">("connecting");
  const [scoring, setScoring] = useState<ScoringResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<number>(0);
  const startTimeRef = useRef<number>(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectFailureTimerRef = useRef<number | null>(null);

  // Elapsed timer
  useEffect(() => {
    startTimeRef.current = Date.now();
    timerRef.current = window.setInterval(() => {
      setElapsed(Date.now() - startTimeRef.current);
    }, 100);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // SSE connection
  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;

    const clearReconnectFailureTimer = () => {
      if (reconnectFailureTimerRef.current) {
        window.clearTimeout(reconnectFailureTimerRef.current);
        reconnectFailureTimerRef.current = null;
      }
    };

    const failStream = (message: string = "Live collection disconnected before the returned brief closed.") => {
      clearReconnectFailureTimer();
      setErrorMessage(message);
      setPhase("error");
      if (timerRef.current) clearInterval(timerRef.current);
      eventSourceRef.current?.close();
    };

    const markStreamHealthy = () => {
      clearReconnectFailureTimer();
      setErrorMessage("");
    };

    const scheduleReconnectFailure = (message: string) => {
      clearReconnectFailureTimer();
      reconnectFailureTimerRef.current = window.setTimeout(() => {
        if (cancelled) return;
        if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.OPEN) {
          failStream(message);
        }
      }, 4000);
    };

    const handleOpen = () => {
      markStreamHealthy();
    };

    const handleStart = (e: Event) => {
      const data = parseStreamEvent<{ total_connectors: number; connector_names: string[] }>(e, "start");
      if (!data) return failStream();
      markStreamHealthy();
      setTotalConnectors(data.total_connectors);
      setPhase("enriching");
      setConnectors(
        data.connector_names.map((name: string) => ({
          name,
          state: "running" as ConnectorState,
        }))
      );
    };

    const handleConnectorDone = (e: Event) => {
      const data = parseStreamEvent<{ name: string; has_data: boolean; findings_count: number; elapsed_ms: number; index: number }>(e, "connector_done");
      if (!data) return failStream();
      markStreamHealthy();
      setConnectors((prev) =>
        prev.map((c) =>
          c.name === data.name
            ? { ...c, state: "done", hasData: data.has_data, findingsCount: data.findings_count, elapsedMs: data.elapsed_ms }
            : c
        )
      );
      setCompletedCount(data.index);
      setTotalFindings((prev) => prev + (data.findings_count || 0));
    };

    const handleConnectorError = (e: Event) => {
      const data = parseStreamEvent<{ name: string; error: string; index: number }>(e, "connector_error");
      if (!data) return failStream();
      markStreamHealthy();
      setConnectors((prev) =>
        prev.map((c) =>
          c.name === data.name
            ? { ...c, state: "error", error: data.error }
            : c
        )
      );
      setCompletedCount(data.index);
    };

    const handleComplete = () => {
      markStreamHealthy();
      setPhase("scoring");
    };

    const handleScored = (e: Event) => {
      const data = parseStreamEvent<ScoringResult>(e, "scored");
      if (!data) return failStream();
      markStreamHealthy();
      setScoring(data);
    };

    const handleDone = () => {
      markStreamHealthy();
      setPhase("done");
      if (timerRef.current) clearInterval(timerRef.current);
      eventSourceRef.current?.close();
      onComplete?.();
    };

    const handleError = (e: Event) => {
      const rawData = "data" in e ? String((e as MessageEvent).data || "").trim() : "";
      if (rawData) {
        const data = parseStreamEvent<{ error?: string }>(e, "error");
        if (data?.error) {
          failStream(data.error);
          return;
        }
      }
      scheduleReconnectFailure("Live collection disconnected before the returned brief closed.");
    };

    (async () => {
      try {
        const protectedPath = await buildProtectedUrl(`/api/cases/${caseId}/enrich-stream`);
        if (cancelled) return;
        es = new EventSource(`${apiBase}${protectedPath}`);
        const currentEs = es;
        eventSourceRef.current = currentEs;
        currentEs.addEventListener("open", handleOpen);
        currentEs.addEventListener("start", handleStart);
        currentEs.addEventListener("connector_done", handleConnectorDone);
        currentEs.addEventListener("connector_error", handleConnectorError);
        currentEs.addEventListener("complete", handleComplete);
        currentEs.addEventListener("scored", handleScored);
        currentEs.addEventListener("done", handleDone);
        currentEs.addEventListener("error", handleError);
      } catch {
        setErrorMessage("Could not open the live collection stream.");
        setPhase("error");
        if (timerRef.current) clearInterval(timerRef.current);
      }
    })();

    return () => {
      cancelled = true;
      clearReconnectFailureTimer();
      es?.removeEventListener("open", handleOpen);
      es?.removeEventListener("start", handleStart);
      es?.removeEventListener("connector_done", handleConnectorDone);
      es?.removeEventListener("connector_error", handleConnectorError);
      es?.removeEventListener("complete", handleComplete);
      es?.removeEventListener("scored", handleScored);
      es?.removeEventListener("done", handleDone);
      es?.removeEventListener("error", handleError);
      es?.close();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [caseId, apiBase, onComplete]);

  const pct = totalConnectors > 0 ? Math.round((completedCount / totalConnectors) * 100) : 0;

  // Group connectors by category
  const grouped = connectors.reduce<Record<string, ConnectorProgress[]>>((acc, c) => {
    const group = CONNECTOR_META[c.name as keyof typeof CONNECTOR_META]?.category || "Other";
    if (!acc[group]) acc[group] = [];
    acc[group].push(c);
    return acc;
  }, {});

  const dataConnectors = connectors.filter((c) => c.state === "done" && c.hasData).length;

  return (
    <div className="flex flex-col gap-3">
      {/* Header with live stats */}
      <div
        className="rounded-lg"
        style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Radar size={14} color={T.accent} className={phase === "enriching" ? "animate-pulse" : ""} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            {phase === "connecting" && "Connecting to OSINT pipeline..."}
            {phase === "enriching" && "Live Intelligence Collection"}
            {phase === "scoring" && "Computing risk score..."}
            {phase === "done" && "Enrichment Complete"}
            {phase === "error" && "Connection Error"}
          </span>
          <span className="ml-auto font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
            {(elapsed / 1000).toFixed(1)}s
          </span>
        </div>

        {/* Progress bar */}
        <div className="rounded-full overflow-hidden" style={{ height: 6, background: T.raised }}>
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${phase === "done" ? 100 : pct}%`,
              background: phase === "error"
                ? T.red
                : phase === "done"
                ? T.green
                : `linear-gradient(90deg, ${T.accent}, ${T.accentHover})`,
            }}
          />
        </div>

        {/* Live counters */}
        <div className="grid grid-cols-4 gap-3 mt-3">
          <div className="text-center">
            <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {completedCount}/{totalConnectors}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>Sources</div>
          </div>
          <div className="text-center">
            <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {totalFindings}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>Findings</div>
          </div>
          <div className="text-center">
            <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {dataConnectors}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>With Data</div>
          </div>
          <div className="text-center">
            <div className="font-mono font-bold" style={{ fontSize: FS.lg, color: T.text }}>
              {scoring ? `${Math.round(scoring.calibrated_probability * 100)}%` : "--"}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>Risk Score</div>
          </div>
        </div>

        {/* Final tier badge */}
        {scoring && (
          <div
            className="flex items-center justify-center gap-2 mt-3 pt-3 rounded"
            style={{ borderTop: `1px solid ${T.border}`, padding: "10px" }}
          >
            <Zap size={14} color={scoring.is_hard_stop ? T.red : T.green} />
            <span
              className="font-mono font-bold uppercase"
              style={{
                fontSize: FS.sm,
                color: scoring.is_hard_stop ? T.red : tierBand(scoring.calibrated_tier as TierKey) === "elevated" ? T.amber : T.green,
              }}
            >
              {scoring.calibrated_tier.replace("_", " ")}
            </span>
            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
              ({Math.round(scoring.calibrated_probability * 100)}% risk probability)
            </span>
          </div>
        )}

        {phase === "error" && errorMessage ? (
          <div
            className="mt-3 rounded"
            style={{ border: `1px solid ${T.red}33`, background: `${T.red}12`, padding: "10px 12px", color: T.text }}
          >
            <div className="font-semibold" style={{ fontSize: FS.sm }}>
              Live collection failed
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4, lineHeight: 1.55 }}>
              {errorMessage}
            </div>
          </div>
        ) : null}
      </div>

      {/* Connector grid by group */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
        {Object.entries(grouped).map(([group, conns]) => (
          <div
            key={group}
            className="rounded-lg"
            style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 10 }}
          >
            <div
              className="font-semibold uppercase tracking-wider mb-1.5"
              style={{ fontSize: "9px", color: T.muted, letterSpacing: "0.08em" }}
            >
              {group}
            </div>
            {conns.map((c) => (
              <ConnectorPill key={c.name} connector={c} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- Individual connector pill ---- */
function ConnectorPill({ connector }: { connector: ConnectorProgress }) {
  const { name, state, hasData, findingsCount, elapsedMs, error } = connector;
  const label = CONNECTOR_META[name as keyof typeof CONNECTOR_META]?.label || name;

  let iconEl: React.ReactNode;
  let statusColor: string;

  switch (state) {
    case "running":
      iconEl = <Loader size={10} color={T.accent} className="animate-spin" />;
      statusColor = T.accent;
      break;
    case "done":
      iconEl = <CheckCircle size={10} color={hasData ? T.green : T.muted} />;
      statusColor = hasData ? T.green : T.muted;
      break;
    case "error":
      iconEl = <XCircle size={10} color={T.red} />;
      statusColor = T.red;
      break;
    default:
      iconEl = <div className="w-2.5 h-2.5 rounded-full" style={{ background: T.border }} />;
      statusColor = T.muted;
  }

  return (
    <div
      className="flex items-center gap-1.5"
      style={{ padding: "3px 0", borderBottom: `1px solid ${T.border}22` }}
      title={error || `${findingsCount ?? 0} findings, ${elapsedMs ?? 0}ms`}
    >
      {iconEl}
      <span
        className="flex-1 truncate"
        style={{ fontSize: FS.sm, color: state === "running" ? T.text : T.dim }}
      >
        {label}
      </span>
      {state === "done" && (
        <>
          <span className="font-mono" style={{ fontSize: "9px", color: statusColor }}>
            {findingsCount || 0}
          </span>
          <span className="font-mono" style={{ fontSize: "9px", color: T.muted }}>
            {elapsedMs ? `${(elapsedMs / 1000).toFixed(1)}s` : ""}
          </span>
        </>
      )}
      {state === "running" && (
        <span className="font-mono" style={{ fontSize: "9px", color: T.accent }}>
          ...
        </span>
      )}
    </div>
  );
}
