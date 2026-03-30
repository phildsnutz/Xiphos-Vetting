import { useState, useEffect } from "react";
import { T, FS } from "@/lib/tokens";
import { Database, ExternalLink, Clock, Shield, Loader2, X, Globe } from "lucide-react";
import { fetchEntityProvenance, fetchRelationshipProvenance } from "@/lib/api";
import type { EntityProvenance, RelationshipProvenance, ProvenanceSource } from "@/lib/api";
import { SkeletonCard } from "./loader";
import { emit } from "@/lib/telemetry";

interface GraphProvenancePanelProps {
  /** Pass entityId to show entity provenance */
  entityId?: string | null;
  /** Pass relationshipId to show relationship provenance */
  relationshipId?: number | null;
  /** Close callback */
  onClose: () => void;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "Unknown";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function authorityColor(level?: string): string {
  switch (level) {
    case "official":
    case "government":
      return T.green;
    case "commercial":
    case "industry":
      return T.accent;
    case "open_source":
    case "community":
      return T.amber;
    default:
      return T.muted;
  }
}

function SourceCard({ source }: { source: ProvenanceSource }) {
  const authColor = authorityColor(source.authority_level);
  return (
    <div className="rounded-lg p-3 card-interactive" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Database size={11} color={T.accent} />
          <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
            {source.connector}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {source.authority_level && (
            <span
              className="rounded-full"
              style={{ padding: "2px 7px", fontSize: 10, fontWeight: 600, color: authColor, background: `${authColor}14` }}
            >
              {source.authority_level.replace(/_/g, " ")}
            </span>
          )}
          <span
            className="rounded-full font-mono"
            style={{ padding: "2px 7px", fontSize: 10, fontWeight: 700, color: T.accent, background: `${T.accent}14` }}
          >
            {Math.round(source.confidence * 100)}%
          </span>
        </div>
      </div>
      {source.raw_snippet && (
        <div style={{ marginTop: 6, fontSize: 12, color: T.dim, lineHeight: 1.5 }}>
          {source.raw_snippet.length > 200 ? source.raw_snippet.slice(0, 200) + "..." : source.raw_snippet}
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap" style={{ marginTop: 6 }}>
        {source.fetched_at && (
          <span style={{ fontSize: 11, color: T.muted }}>
            <Clock size={9} style={{ display: "inline", marginRight: 3, verticalAlign: "middle" }} />
            {relativeTime(source.fetched_at)}
          </span>
        )}
        {source.url && (
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1"
            style={{ fontSize: 11, color: T.accent, textDecoration: "none" }}
          >
            <ExternalLink size={9} /> Source
          </a>
        )}
      </div>
    </div>
  );
}

export function GraphProvenancePanel({ entityId, relationshipId, onClose }: GraphProvenancePanelProps) {
  const [entityProv, setEntityProv] = useState<EntityProvenance | null>(null);
  const [relProv, setRelProv] = useState<RelationshipProvenance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEntityProv(null);
    setRelProv(null);

    const load = async () => {
      try {
        if (entityId) {
          const data = await fetchEntityProvenance(entityId);
          if (!cancelled) {
            setEntityProv(data);
            emit("provenance_entity_viewed", {
              screen: "case_graph",
              metadata: { entity_id: entityId, source_count: data.sources?.length ?? 0, corroboration: data.corroboration_count ?? 0 },
            });
          }
        } else if (relationshipId != null) {
          const data = await fetchRelationshipProvenance(relationshipId);
          if (!cancelled) {
            setRelProv(data);
            emit("provenance_relationship_viewed", {
              screen: "case_graph",
              metadata: { relationship_id: relationshipId, source_count: data.sources?.length ?? 0, corroboration: data.corroboration_count ?? 0 },
            });
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load provenance");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    if (entityId || relationshipId != null) {
      load();
    } else {
      setLoading(false);
    }

    return () => { cancelled = true; };
  }, [entityId, relationshipId]);

  const sources: ProvenanceSource[] = entityProv?.sources ?? relProv?.sources ?? [];
  const corrobCount = entityProv?.corroboration_count ?? relProv?.corroboration_count ?? 0;
  const firstSeen = entityProv?.first_seen ?? relProv?.first_seen;
  const lastSeen = entityProv?.last_seen ?? relProv?.last_seen;
  const title = entityProv
    ? entityProv.entity.canonical_name
    : relProv
      ? `${relProv.relationship.rel_type.replace(/_/g, " ")}`
      : "Provenance";

  return (
    <div className="glass-panel p-4 animate-slide-up" style={{ marginTop: 14 }}>
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <Shield size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted, letterSpacing: "0.06em" }}>
            Provenance
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1 cursor-pointer btn-interactive"
          style={{ background: T.raised, border: `1px solid ${T.border}` }}
        >
          <X size={12} color={T.muted} />
        </button>
      </div>

      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {entityProv && (
        <div className="flex items-center gap-2 flex-wrap" style={{ marginBottom: 10 }}>
          <span className="rounded-full" style={{ padding: "2px 7px", fontSize: 11, fontWeight: 600, color: T.accent, background: `${T.accent}14` }}>
            {entityProv.entity.entity_type.replace(/_/g, " ")}
          </span>
          {entityProv.entity.country && (
            <span className="rounded-full inline-flex items-center gap-1" style={{ padding: "2px 7px", fontSize: 11, fontWeight: 600, color: T.dim, background: T.raised }}>
              <Globe size={9} /> {entityProv.entity.country}
            </span>
          )}
        </div>
      )}

      {/* Summary metrics */}
      <div className="grid gap-2 mb-3 stagger-children" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="rounded-lg p-2 card-interactive" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Sources</div>
          <div style={{ fontSize: FS.base, color: T.accent, fontWeight: 700, marginTop: 2 }}>{sources.length}</div>
        </div>
        <div className="rounded-lg p-2 card-interactive" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Corroborated</div>
          <div style={{ fontSize: FS.base, color: T.amber, fontWeight: 700, marginTop: 2 }}>{corrobCount}</div>
        </div>
        <div className="rounded-lg p-2 card-interactive" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Last seen</div>
          <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600, marginTop: 2 }}>{relativeTime(lastSeen)}</div>
        </div>
      </div>

      {loading && (
        <div className="flex flex-col gap-2">
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
        </div>
      )}

      {error && (
        <div className="rounded-lg p-3" style={{ background: T.redBg, border: `1px solid ${T.red}33` }}>
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      {!loading && !error && sources.length > 0 && (
        <div className="flex flex-col gap-2 stagger-children">
          {sources.map((src, idx) => (
            <SourceCard key={`${src.connector}-${src.claim_id ?? idx}`} source={src} />
          ))}
        </div>
      )}

      {!loading && !error && sources.length === 0 && (
        <div className="flex flex-col items-center justify-center py-6">
          <Database size={24} color={T.muted} style={{ marginBottom: 8, opacity: 0.5 }} />
          <div style={{ fontSize: FS.sm, color: T.dim, fontWeight: 600 }}>No provenance data</div>
          <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>This entity has no tracked source records yet.</div>
        </div>
      )}

      {firstSeen && (
        <div style={{ marginTop: 10, fontSize: 11, color: T.muted, textAlign: "center" }}>
          First observed {relativeTime(firstSeen)}
        </div>
      )}
    </div>
  );
}
