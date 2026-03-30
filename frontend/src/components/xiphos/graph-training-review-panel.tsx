import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock3, GitBranchPlus, Loader2, RefreshCw, XCircle } from "lucide-react";
import {
  fetchPredictedLinkReviewQueue,
  fetchPredictedLinkReviewStats,
  queuePredictedLinks,
  reviewPredictedLinksBatch,
  type PredictedLinkQueueItem,
  type PredictedLinkReviewStats,
} from "@/lib/api";
import { T, FS } from "@/lib/tokens";
import { formatRelationshipLabel } from "@/lib/workflow-copy";

interface GraphTrainingReviewPanelProps {
  rootEntityId?: string;
  entityName?: string;
  onGraphRefresh?: () => Promise<void> | void;
}

const DEFAULT_TOP_K = 12;

function pct(value?: number | null) {
  return `${(((value ?? 0) as number) * 100).toFixed(0)}%`;
}

function ageLabel(hours?: number | null) {
  if (!hours || hours <= 0) return "0h";
  if (hours >= 24 * 7) return `${(hours / (24 * 7)).toFixed(1)}w`;
  if (hours >= 24) return `${(hours / 24).toFixed(1)}d`;
  return `${hours.toFixed(1)}h`;
}

function scoreLabel(score?: number | null) {
  return `${(((score ?? 0) as number) * 100).toFixed(1)}%`;
}

function toneForDecision(confirmed?: boolean) {
  if (confirmed === true) {
    return { color: T.green, background: `${T.green}14`, border: `${T.green}33` };
  }
  if (confirmed === false) {
    return { color: T.red, background: `${T.red}14`, border: `${T.red}33` };
  }
  return { color: T.muted, background: T.surface, border: T.border };
}

export function GraphTrainingReviewPanel({
  rootEntityId,
  entityName,
  onGraphRefresh,
}: GraphTrainingReviewPanelProps) {
  const [stats, setStats] = useState<PredictedLinkReviewStats | null>(null);
  const [queue, setQueue] = useState<PredictedLinkQueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [edgeFamilyFilter, setEdgeFamilyFilter] = useState<string>("all");
  const [decisions, setDecisions] = useState<Record<number, { confirmed?: boolean; notes: string }>>({});

  const loadPanel = useCallback(async () => {
    if (!rootEntityId) return;
    setLoading(true);
    setError(null);
    try {
      const [statsPayload, queuePayload] = await Promise.all([
        fetchPredictedLinkReviewStats(rootEntityId),
        fetchPredictedLinkReviewQueue({
          reviewed: false,
          sourceEntityId: rootEntityId,
          edgeFamily: edgeFamilyFilter === "all" ? undefined : edgeFamilyFilter,
          limit: DEFAULT_TOP_K,
        }),
      ]);
      setStats(statsPayload);
      setQueue(queuePayload.predictions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load graph training review panel");
    } finally {
      setLoading(false);
    }
  }, [edgeFamilyFilter, rootEntityId]);

  useEffect(() => {
    void loadPanel();
  }, [loadPanel]);

  const pendingDecisions = useMemo(
    () =>
      Object.entries(decisions)
        .filter(([, value]) => value.confirmed !== undefined)
        .map(([id, value]) => ({
          id: Number(id),
          confirmed: Boolean(value.confirmed),
          notes: value.notes.trim(),
        })),
    [decisions],
  );

  const setDecision = useCallback((item: PredictedLinkQueueItem, confirmed: boolean) => {
    setDecisions((current) => ({
      ...current,
      [item.id]: {
        confirmed,
        notes: current[item.id]?.notes ?? "",
      },
    }));
  }, []);

  const setNotes = useCallback((item: PredictedLinkQueueItem, notes: string) => {
    setDecisions((current) => ({
      ...current,
      [item.id]: {
        confirmed: current[item.id]?.confirmed,
        notes,
      },
    }));
  }, []);

  const handleSeedQueue = useCallback(async () => {
    if (!rootEntityId) return;
    setQueueing(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await queuePredictedLinks(rootEntityId, DEFAULT_TOP_K);
      setSuccess(
        `Queued ${result.queued_count} new candidates for ${result.entity_name}. Reused ${result.existing_count} existing predictions.`,
      );
      await loadPanel();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to seed predicted-link queue");
    } finally {
      setQueueing(false);
    }
  }, [loadPanel, rootEntityId]);

  const handleSubmitBatch = useCallback(async () => {
    if (!pendingDecisions.length) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await reviewPredictedLinksBatch(pendingDecisions);
      setSuccess(
        `Reviewed ${result.reviewed_count} candidates. Confirmed ${result.confirmed_count} and rejected ${result.rejected_count}.`,
      );
      setDecisions({});
      await loadPanel();
      await onGraphRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to submit predicted-link review batch");
    } finally {
      setSubmitting(false);
    }
  }, [loadPanel, onGraphRefresh, pendingDecisions]);

  if (!rootEntityId) {
    return (
      <div className="rounded-lg p-4" style={{ marginBottom: 14, background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
          Graph Training Review
        </div>
        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8 }}>
          Root graph entity is missing. Open the graph after enrichment or refresh the case to seed the analyst review queue.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg p-4" style={{ marginBottom: 14, background: T.surface, border: `1px solid ${T.border}` }}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
            Graph Training Review
          </div>
          <div style={{ fontSize: FS.sm, color: T.text, marginTop: 4, fontWeight: 600 }}>
            Analyst loop for missing-edge recovery on {entityName || rootEntityId}
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
            Review predicted ownership, intermediary, route, and dependency edges before they become graph facts.
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => void loadPanel()}
            disabled={loading}
            className="rounded border cursor-pointer"
            style={{ padding: "7px 10px", fontSize: FS.sm, color: T.text, background: T.raised, borderColor: T.border, opacity: loading ? 0.7 : 1 }}
          >
            <span className="inline-flex items-center gap-2">
              <RefreshCw size={14} />
              Refresh
            </span>
          </button>
          <button
            onClick={() => void handleSeedQueue()}
            disabled={queueing}
            className="rounded border cursor-pointer"
            style={{ padding: "7px 10px", fontSize: FS.sm, color: T.accent, background: `${T.accent}12`, borderColor: `${T.accent}33`, opacity: queueing ? 0.7 : 1 }}
          >
            <span className="inline-flex items-center gap-2">
              {queueing ? <Loader2 size={14} className="animate-spin" /> : <GitBranchPlus size={14} />}
              Seed {DEFAULT_TOP_K} candidates
            </span>
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg p-3" style={{ marginTop: 12, background: T.redBg, border: `1px solid ${T.red}33`, color: T.red, fontSize: FS.sm }}>
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg p-3" style={{ marginTop: 12, background: `${T.green}14`, border: `1px solid ${T.green}33`, color: T.green, fontSize: FS.sm }}>
          {success}
        </div>
      )}

      <div className="grid gap-3" style={{ marginTop: 12, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        {[
          { label: "Pending", value: stats?.pending_links ?? 0, tone: T.amber },
          { label: "Reviewed", value: stats?.reviewed_links ?? 0, tone: T.text },
          { label: "Confirmed", value: stats?.confirmed_links ?? 0, tone: T.green },
          { label: "Promoted", value: stats?.promoted_relationships ?? 0, tone: T.accent },
          { label: "Coverage", value: pct(stats?.review_coverage_pct), tone: T.text },
          { label: "Confirm rate", value: pct(stats?.confirmation_rate), tone: T.green },
          { label: "Median age", value: ageLabel(stats?.missing_edge_recovery?.median_pending_age_hours), tone: T.amber },
          { label: "Unsupported", value: pct(stats?.unsupported_promoted_edge_rate), tone: (stats?.unsupported_promoted_edge_rate ?? 0) > 0 ? T.red : T.green },
        ].map((item) => (
          <div key={item.label} className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{item.label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: item.tone, marginTop: 4, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
              {item.value}
            </div>
          </div>
        ))}
      </div>

      {stats && (
        <div className="rounded-lg p-3" style={{ marginTop: 12, background: T.bg, border: `1px solid ${T.border}` }}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Tranche B Metrics
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6 }}>
                Novel edge yield {pct(stats.missing_edge_recovery.novel_edge_yield)} · Mean review latency {ageLabel(stats.missing_edge_recovery.mean_review_latency_hours)} · P95 pending age {ageLabel(stats.missing_edge_recovery.p95_pending_age_hours)}
              </div>
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>
              Stale pending &gt;24h: {stats.missing_edge_recovery.stale_pending_24h} · &gt;7d: {stats.missing_edge_recovery.stale_pending_7d}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap" style={{ marginTop: 10 }}>
            <label style={{ fontSize: FS.sm, color: T.muted }}>Edge family</label>
            <select
              value={edgeFamilyFilter}
              onChange={(event) => setEdgeFamilyFilter(event.target.value)}
              className="rounded border"
              style={{ padding: "6px 10px", fontSize: FS.sm, color: T.text, background: T.surface, borderColor: T.border }}
            >
              <option value="all">All families</option>
              {stats.by_edge_family.map((family) => (
                <option key={family.edge_family} value={family.edge_family}>
                  {family.edge_family} · pending {family.pending_links}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginTop: 12 }}>
        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
          Review Queue
        </div>
        <button
          onClick={() => void handleSubmitBatch()}
          disabled={!pendingDecisions.length || submitting}
          className="rounded border cursor-pointer"
          style={{
            padding: "7px 10px",
            fontSize: FS.sm,
            color: pendingDecisions.length ? T.text : T.muted,
            background: pendingDecisions.length ? `${T.green}12` : T.surface,
            borderColor: pendingDecisions.length ? `${T.green}33` : T.border,
            opacity: submitting ? 0.7 : 1,
          }}
        >
          <span className="inline-flex items-center gap-2">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            Submit {pendingDecisions.length} review{pendingDecisions.length === 1 ? "" : "s"}
          </span>
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2" style={{ marginTop: 14, fontSize: FS.sm, color: T.muted }}>
          <Loader2 size={16} className="animate-spin" />
          Loading graph training queue...
        </div>
      ) : queue.length > 0 ? (
        <div className="grid gap-3" style={{ marginTop: 12 }}>
          {queue.map((item) => {
            const selection = decisions[item.id];
            const tone = toneForDecision(selection?.confirmed);
            return (
              <div key={item.id} className="rounded-lg p-3" style={{ background: T.bg, border: `1px solid ${tone.border}` }}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                      {item.source_entity_name} <span style={{ color: T.muted, fontWeight: 500 }}>→</span> {item.target_entity_name}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                      {formatRelationshipLabel(item.predicted_relation)} · {item.predicted_edge_family} · rank {item.candidate_rank ?? "n/a"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.accent, background: `${T.accent}14` }}>
                      {scoreLabel(item.score)}
                    </span>
                    <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.muted, background: T.surface, border: `1px solid ${T.border}` }}>
                      <span className="inline-flex items-center gap-1">
                        <Clock3 size={12} />
                        {item.created_at ? new Date(item.created_at).toLocaleString() : "queued"}
                      </span>
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap" style={{ marginTop: 10 }}>
                  <button
                    onClick={() => setDecision(item, true)}
                    className="rounded border cursor-pointer"
                    style={{ padding: "6px 10px", fontSize: FS.sm, color: T.green, background: selection?.confirmed === true ? `${T.green}16` : T.surface, borderColor: selection?.confirmed === true ? `${T.green}33` : T.border }}
                  >
                    <span className="inline-flex items-center gap-2">
                      <CheckCircle2 size={14} />
                      Confirm
                    </span>
                  </button>
                  <button
                    onClick={() => setDecision(item, false)}
                    className="rounded border cursor-pointer"
                    style={{ padding: "6px 10px", fontSize: FS.sm, color: T.red, background: selection?.confirmed === false ? `${T.red}16` : T.surface, borderColor: selection?.confirmed === false ? `${T.red}33` : T.border }}
                  >
                    <span className="inline-flex items-center gap-2">
                      <XCircle size={14} />
                      Reject
                    </span>
                  </button>
                </div>
                <textarea
                  value={selection?.notes ?? ""}
                  onChange={(event) => setNotes(item, event.target.value)}
                  placeholder="Analyst rationale, provenance caveat, or rejection reason"
                  rows={2}
                  className="w-full rounded border"
                  style={{ marginTop: 10, padding: 10, fontSize: FS.sm, color: T.text, background: T.surface, borderColor: T.border, resize: "vertical" }}
                />
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg p-3" style={{ marginTop: 12, background: T.bg, border: `1px solid ${T.border}`, fontSize: FS.sm, color: T.muted }}>
          No pending predicted links for this entity and edge-family filter. Seed the queue or change the family filter.
        </div>
      )}
    </div>
  );
}
