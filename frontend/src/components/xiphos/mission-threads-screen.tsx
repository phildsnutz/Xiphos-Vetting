import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Grid3X3, Network, Plus, Shield } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import {
  createMissionThread,
  fetchMissionThreadBriefing,
  fetchMissionThreadMemberPassport,
  fetchMissionThreadSummary,
  fetchMissionThreads,
} from "@/lib/api";
import type {
  MissionThreadBriefing,
  MissionThreadBriefingExposure,
  MissionThreadHeader,
  MissionThreadMemberPassport,
  MissionThreadMemberScore,
  MissionThreadSummary,
} from "@/lib/api";

interface MissionThreadsScreenProps {
  onNavigate?: (tab: string) => void;
}

function laneLabel(value: string): string {
  const normalized = String(value || "").trim();
  if (!normalized) return "Unassigned";
  return normalized.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function pct(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "0%";
  return `${Math.round(value * 100)}%`;
}

function memberTone(score: MissionThreadMemberScore) {
  if (score.brittle_node_score >= 0.65) {
    return { color: "#f87171", bg: "rgba(248,113,113,0.12)", border: "rgba(248,113,113,0.28)" };
  }
  if (score.brittle_node_score >= 0.45) {
    return { color: "#fbbf24", bg: "rgba(251,191,36,0.12)", border: "rgba(251,191,36,0.24)" };
  }
  return { color: "#34d399", bg: "rgba(52,211,153,0.12)", border: "rgba(52,211,153,0.22)" };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? value as Record<string, unknown> : null;
}

export function MissionThreadsScreen({ onNavigate }: MissionThreadsScreenProps) {
  const [threads, setThreads] = useState<MissionThreadHeader[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [selectedMemberId, setSelectedMemberId] = useState<string>("");
  const [summary, setSummary] = useState<MissionThreadSummary | null>(null);
  const [briefing, setBriefing] = useState<MissionThreadBriefing | null>(null);
  const [memberPassport, setMemberPassport] = useState<MissionThreadMemberPassport | null>(null);
  const [loading, setLoading] = useState(false);
  const [passportLoading, setPassportLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newTheater, setNewTheater] = useState("INDOPACOM");
  const [newProgram, setNewProgram] = useState("contested_sustainment");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoading(true);
    fetchMissionThreads(100)
      .then((payload) => {
        if (cancelled) return;
        setThreads(payload.mission_threads || []);
        const first = payload.mission_threads?.[0]?.id || "";
        setSelectedId((current) => current || first);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSummary(null);
      setBriefing(null);
      return;
    }
    let cancelled = false;
    setError(null);
    setLoading(true);
    Promise.all([
      fetchMissionThreadSummary(selectedId, 2),
      fetchMissionThreadBriefing(selectedId, 2, "control"),
    ])
      .then(([summaryPayload, briefingPayload]) => {
        if (!cancelled) {
          setSummary(summaryPayload);
          setBriefing(briefingPayload);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectedThread = useMemo(
    () => threads.find((thread) => thread.id === selectedId) || null,
    [selectedId, threads],
  );
  const resilience = summary?.resilience?.summary;
  const brittleMembers = useMemo(
    () => resilience?.top_brittle_members || [],
    [resilience?.top_brittle_members],
  );
  const briefingMembers = useMemo(
    () => briefing?.top_brittle_members || [],
    [briefing?.top_brittle_members],
  );
  const missionNodes = useMemo(
    () => briefing?.mission_important_nodes || summary?.graph?.top_nodes_by_mission_importance || [],
    [briefing?.mission_important_nodes, summary?.graph?.top_nodes_by_mission_importance],
  );
  const controlPathExposures = useMemo(
    () => briefing?.top_control_path_exposures || [],
    [briefing?.top_control_path_exposures],
  );
  const evidenceGaps = useMemo(
    () => briefing?.unresolved_evidence_gaps || [],
    [briefing?.unresolved_evidence_gaps],
  );
  const mitigations = useMemo(
    () => briefing?.recommended_mitigations || [],
    [briefing?.recommended_mitigations],
  );
  const memberRecord = asRecord(memberPassport?.member);
  const memberVendor = asRecord(memberRecord?.vendor);
  const supplierPassport = asRecord(memberPassport?.supplier_passport);
  const supplierVendor = asRecord(supplierPassport?.vendor);
  const supplierScore = asRecord(supplierPassport?.score);
  const supplierGraph = asRecord(supplierPassport?.graph);
  const controlPathSummary = asRecord(supplierGraph?.control_path_summary);

  useEffect(() => {
    setSelectedMemberId("");
    setMemberPassport(null);
  }, [selectedId]);

  useEffect(() => {
    const sourceMembers = briefingMembers.length ? briefingMembers : brittleMembers;
    if (!sourceMembers.length) {
      setSelectedMemberId("");
      setMemberPassport(null);
      return;
    }
    if (!sourceMembers.some((member) => member.member_id === selectedMemberId)) {
      setSelectedMemberId(sourceMembers[0].member_id);
    }
  }, [briefingMembers, brittleMembers, selectedMemberId]);

  useEffect(() => {
    if (!selectedId || !selectedMemberId || Number.isNaN(Number(selectedMemberId))) {
      setMemberPassport(null);
      return;
    }
    let cancelled = false;
    setError(null);
    setPassportLoading(true);
    fetchMissionThreadMemberPassport(selectedId, Number(selectedMemberId), 2)
      .then((payload) => {
        if (!cancelled) {
          setMemberPassport(payload);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setPassportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedMemberId]);

  async function handleCreateThread() {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    try {
      const created = await createMissionThread({
        name,
        lane: "counterparty",
        theater: newTheater,
        program: newProgram,
        mission_type: "contested_logistics",
        description: "Mission-thread operator context for contested sustainment analysis.",
      });
      const payload = await fetchMissionThreads(100);
      setThreads(payload.mission_threads || []);
      setSelectedId(created.id);
      setNewName("");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create mission thread");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-[1480px] mx-auto flex flex-col gap-5">
        <div className="glass-panel animate-slide-up" style={{ padding: 24 }}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div style={{ fontSize: 11, color: T.accent, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: 8 }}>
                Mission threads
              </div>
              <h1 className="text-3xl font-bold text-slate-50" style={{ letterSpacing: "-0.04em", marginBottom: 10 }}>
                Model contested sustainment as a real operating problem.
              </h1>
              <p className="text-sm leading-7 text-slate-300" style={{ maxWidth: 760 }}>
                Mission threads let Helios move from single-vendor diligence into mission-scoped brittle-node analysis. The first view here is simple on purpose: create the thread, see what is brittle, and push the next investigation into the workbench or graph.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 lg:min-w-[340px]">
              <div className="glass-card" style={{ padding: 14 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Threads</div>
                <div className="text-2xl font-bold text-slate-100">{threads.length}</div>
              </div>
              <div className="glass-card" style={{ padding: 14 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Members</div>
                <div className="text-2xl font-bold text-sky-300">{summary?.member_count || 0}</div>
              </div>
              <div className="glass-card" style={{ padding: 14 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Avg resilience</div>
                <div className="text-2xl font-bold text-emerald-300">{pct(resilience?.average_resilience_score)}</div>
              </div>
              <div className="glass-card" style={{ padding: 14 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Critical brittle</div>
                <div className="text-2xl font-bold text-rose-300">{resilience?.critical_brittle_member_count || 0}</div>
              </div>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 lg:grid-cols-[1.3fr_0.9fr_0.9fr] gap-3">
            <div className="glass-card" style={{ padding: 16 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Create thread</div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Mission thread name"
                  className="rounded-2xl outline-none helios-focus-ring"
                  style={{ padding: "12px 14px", background: T.surface, border: `1px solid ${T.borderStrong}`, color: T.text, fontSize: FS.sm }}
                />
                <input
                  value={newTheater}
                  onChange={(e) => setNewTheater(e.target.value)}
                  placeholder="Theater"
                  className="rounded-2xl outline-none helios-focus-ring"
                  style={{ padding: "12px 14px", background: T.surface, border: `1px solid ${T.borderStrong}`, color: T.text, fontSize: FS.sm }}
                />
                <input
                  value={newProgram}
                  onChange={(e) => setNewProgram(e.target.value)}
                  placeholder="Program"
                  className="rounded-2xl outline-none helios-focus-ring"
                  style={{ padding: "12px 14px", background: T.surface, border: `1px solid ${T.borderStrong}`, color: T.text, fontSize: FS.sm }}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-3">
                <button
                  onClick={handleCreateThread}
                  disabled={creating || !newName.trim()}
                  className="btn-interactive"
                  style={{
                    padding: "11px 14px",
                    borderRadius: 14,
                    border: "none",
                    background: creating || !newName.trim() ? T.border : T.accent,
                    color: creating || !newName.trim() ? T.muted : "#04101f",
                    cursor: creating || !newName.trim() ? "default" : "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    fontWeight: 700,
                  }}
                >
                  <Plus size={14} />
                  Create thread
                </button>
                <button
                  onClick={() => onNavigate?.("portfolio")}
                  className="btn-interactive"
                  style={{ padding: "11px 14px", borderRadius: 14, border: `1px solid ${T.border}`, background: T.surface, color: T.text, display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 700 }}
                >
                  <Shield size={14} />
                  Open workbench
                </button>
                <button
                  onClick={() => onNavigate?.("graph")}
                  className="btn-interactive"
                  style={{ padding: "11px 14px", borderRadius: 14, border: `1px solid ${T.border}`, background: T.surface, color: T.text, display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 700 }}
                >
                  <Grid3X3 size={14} />
                  Graph intel
                </button>
              </div>
            </div>
            <div className="glass-card" style={{ padding: 16 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Selected thread</div>
              {selectedThread ? (
                <div className="flex flex-col gap-2">
                  <div className="text-lg font-semibold text-slate-100">{selectedThread.name}</div>
                  <div className="text-sm text-slate-400">{laneLabel(selectedThread.theater)} · {laneLabel(selectedThread.program)}</div>
                  <div className="text-sm text-slate-300">{laneLabel(selectedThread.lane)} · {selectedThread.member_count} members</div>
                </div>
              ) : (
                <div className="text-sm text-slate-400">Create a thread to start mission-scoped analysis.</div>
              )}
            </div>
            <div className="glass-card" style={{ padding: 16 }}>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Graph footprint</div>
              <div className="flex flex-col gap-2">
                <div className="text-lg font-semibold text-slate-100">{summary?.graph.entity_count || 0} entities</div>
                <div className="text-sm text-slate-400">{summary?.graph.relationship_count || 0} relationships</div>
                <div className="text-sm text-slate-300">{pct(Number(summary?.graph.intelligence?.avg_edge_intelligence_score || 0))} avg edge quality</div>
              </div>
            </div>
          </div>

          {briefing && (
            <div className="mt-5 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-3">
              <div className="glass-card" style={{ padding: 16 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Operator brief</div>
                <div className="text-lg font-semibold text-slate-100 leading-8">{briefing.operator_readout}</div>
                <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                    <div className="text-[11px] uppercase tracking-wider text-slate-500">Alternates</div>
                    <div className="text-sm font-semibold text-slate-100">{briefing.overview.alternate_member_count}</div>
                  </div>
                  <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                    <div className="text-[11px] uppercase tracking-wider text-slate-500">Gaps</div>
                    <div className="text-sm font-semibold text-amber-300">{evidenceGaps.length}</div>
                  </div>
                  <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                    <div className="text-[11px] uppercase tracking-wider text-slate-500">Exposures</div>
                    <div className="text-sm font-semibold text-rose-300">{controlPathExposures.length}</div>
                  </div>
                  <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                    <div className="text-[11px] uppercase tracking-wider text-slate-500">Mitigations</div>
                    <div className="text-sm font-semibold text-emerald-300">{mitigations.length}</div>
                  </div>
                </div>
              </div>
              <div className="glass-card" style={{ padding: 16 }}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Immediate moves</div>
                <div className="flex flex-col gap-2">
                  {mitigations.length === 0 ? (
                    <div className="text-sm text-slate-300">No mitigations generated yet.</div>
                  ) : mitigations.slice(0, 4).map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded-2xl" style={{ padding: "12px 14px", background: T.surface, border: `1px solid ${T.border}` }}>
                      <div className="text-sm text-slate-100">{item}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-2xl flex items-center justify-between" style={{ padding: "12px 14px", background: "rgba(248,113,113,0.12)", border: "1px solid rgba(248,113,113,0.24)", color: "#fda4af" }}>
              <span>{error}</span>
              <button
                onClick={() => setError(null)}
                style={{ marginLeft: 12, color: "#fda4af", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "none", border: "none" }}
              >
                Dismiss
              </button>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[0.9fr_1.4fr] gap-5">
          <div className="glass-panel" style={{ padding: 18 }}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Thread queue</div>
                <div className="text-sm text-slate-300">Mission contexts Helios can reason over now.</div>
              </div>
              {loading && <div className="text-xs text-slate-500">Loading…</div>}
            </div>
            <div className="flex flex-col gap-3">
              {threads.length === 0 ? (
                <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                  <div className="text-sm text-slate-300">No mission threads yet.</div>
                </div>
              ) : threads.map((thread) => {
                const active = thread.id === selectedId;
                return (
                  <button
                    key={thread.id}
                    onClick={() => setSelectedId(thread.id)}
                    className="text-left rounded-3xl helios-focus-ring"
                    style={{
                      padding: "16px 18px",
                      border: `1px solid ${active ? T.accent : T.border}`,
                      background: active ? T.accentSoft : T.surface,
                      cursor: "pointer",
                    }}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-slate-100">{thread.name}</div>
                        <div className="mt-1 text-xs text-slate-400">{laneLabel(thread.theater)} · {laneLabel(thread.program)}</div>
                      </div>
                      <div className="text-xs font-semibold text-sky-300">{thread.member_count} members</div>
                    </div>
                    <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
                      <span>{laneLabel(thread.lane)}</span>
                      <span>{laneLabel(thread.status)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col gap-5">
            <div className="glass-panel" style={{ padding: 18 }}>
              <div className="flex items-center justify-between gap-4 mb-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Top brittle members</div>
                  <div className="text-sm text-slate-300">The members most likely to break the mission thread next.</div>
                </div>
                <div className="text-sm text-slate-300">
                  Avg resilience: <span className="font-semibold text-slate-100">{pct(resilience?.average_resilience_score)}</span>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3">
                {(briefingMembers.length ? briefingMembers : brittleMembers).length === 0 ? (
                  <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="text-sm text-slate-300">No brittle members yet. Add members to a thread to start ranking mission impact.</div>
                  </div>
                ) : (briefingMembers.length ? briefingMembers : brittleMembers).map((member) => {
                  const tone = memberTone(member);
                  const active = member.member_id === selectedMemberId;
                  return (
                    <button
                      key={member.member_id}
                      type="button"
                      onClick={() => setSelectedMemberId(member.member_id)}
                      className="rounded-3xl text-left helios-focus-ring"
                      style={{
                        padding: "16px 18px",
                        background: tone.bg,
                        border: `1px solid ${active ? T.accent : tone.border}`,
                        boxShadow: active ? "0 0 0 1px rgba(14,165,233,0.24)" : "none",
                        cursor: "pointer",
                      }}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className="text-sm font-semibold text-slate-100">{member.label}</div>
                          <div className="mt-1 text-xs text-slate-300">{laneLabel(member.role)} · {laneLabel(member.criticality)}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: tone.color }}>Brittle {pct(member.brittle_node_score)}</div>
                          <div className="mt-1 text-xs text-slate-300">Resilience {pct(member.resilience_score)}</div>
                        </div>
                      </div>
                      <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
                        <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                          <div className="text-[11px] uppercase tracking-wider text-slate-500">Impact</div>
                          <div className="text-sm font-semibold text-slate-100">{pct(member.mission_impact_score)}</div>
                        </div>
                        <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                          <div className="text-[11px] uppercase tracking-wider text-slate-500">Substitute</div>
                          <div className="text-sm font-semibold text-slate-100">{pct(member.substitute_coverage_score)}</div>
                        </div>
                        <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                          <div className="text-[11px] uppercase tracking-wider text-slate-500">Control path</div>
                          <div className="text-sm font-semibold text-slate-100">{pct(member.control_path_quality)}</div>
                        </div>
                        <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                          <div className="text-[11px] uppercase tracking-wider text-slate-500">Concentration</div>
                          <div className="text-sm font-semibold text-slate-100">{pct(member.dependency_concentration)}</div>
                        </div>
                      </div>
                      <div className="mt-3 flex items-start gap-2 text-sm text-slate-300">
                        <AlertTriangle size={14} style={{ marginTop: 2, flex: "0 0 auto", color: tone.color }} />
                        <span>{member.recommended_action}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-5">
              <div className="glass-panel" style={{ padding: 18 }}>
                <div className="flex items-center gap-2 mb-3">
                  <Network size={16} color={T.accent} />
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Mission-important nodes</div>
                    <div className="text-sm text-slate-300">Thread-conditioned importance, not global graph fame.</div>
                  </div>
                </div>
                <div className="flex flex-col gap-3">
                  {missionNodes.length === 0 ? (
                    <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                      <div className="text-sm text-slate-300">No nodes ranked yet.</div>
                    </div>
                  ) : missionNodes.slice(0, 6).map((node, index) => (
                    <div key={`${String(node.entity_id)}-${index}`} className="rounded-3xl" style={{ padding: "14px 16px", background: T.surface, border: `1px solid ${T.border}` }}>
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <div className="text-sm font-semibold text-slate-100">{String(node.entity_name || node.entity_id || "Unknown node")}</div>
                          <div className="mt-1 text-xs text-slate-400">{laneLabel(String(node.entity_type || "unknown"))}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs uppercase tracking-wider text-slate-500">Mission importance</div>
                          <div className="text-sm font-semibold text-sky-300">{pct(Number(node.mission_importance || 0))}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-5">
                <div className="glass-panel" style={{ padding: 18 }}>
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Control-path exposures</div>
                      <div className="text-sm text-slate-300">What can actually break the thread, not just what sits in the graph.</div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-3">
                    {controlPathExposures.length === 0 ? (
                      <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                        <div className="text-sm text-slate-300">No control-path exposures ranked yet.</div>
                      </div>
                    ) : controlPathExposures.slice(0, 4).map((exposure: MissionThreadBriefingExposure, index: number) => (
                      <div key={`${exposure.source_entity_id}-${exposure.target_entity_id}-${index}`} className="rounded-3xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="text-sm font-semibold text-slate-100">
                              {exposure.source_label} <span className="text-slate-500">→</span> {exposure.target_label}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">{laneLabel(exposure.rel_type)}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-xs uppercase tracking-wider text-slate-500">Intel</div>
                            <div className="text-sm font-semibold text-rose-300">{pct(exposure.intelligence_score)}</div>
                          </div>
                        </div>
                        {exposure.evidence && (
                          <div className="mt-3 text-sm text-slate-300">{exposure.evidence}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: 18 }}>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Evidence gaps</div>
                  <div className="flex flex-col gap-3">
                    {evidenceGaps.length === 0 ? (
                      <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                        <div className="text-sm text-slate-300">No unresolved evidence gaps were flagged for this thread.</div>
                      </div>
                    ) : evidenceGaps.slice(0, 4).map((gap, index) => (
                      <div key={`${gap.category}-${index}`} className="rounded-3xl" style={{ padding: "14px 16px", background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.18)" }}>
                        <div className="text-[11px] uppercase tracking-wider text-amber-300 mb-1">{laneLabel(gap.severity)}</div>
                        <div className="text-sm text-slate-100">{gap.detail}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: 18 }}>
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Member passport</div>
                      <div className="text-sm text-slate-300">Mission role plus the underlying supplier artifact.</div>
                    </div>
                    {passportLoading && <div className="text-xs text-slate-500">Loading…</div>}
                  </div>
                  {!memberPassport ? (
                    <div className="rounded-2xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                      <div className="text-sm text-slate-300">Select a brittle member to inspect its mission-thread passport.</div>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3">
                      <div className="rounded-3xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="text-sm font-semibold text-slate-100">
                              {String(supplierVendor?.name || memberVendor?.name || memberPassport.resilience.member.label || "Mission member")}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">
                              {laneLabel(memberPassport.mission_context.role)} · {laneLabel(memberPassport.mission_context.criticality)}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-xs uppercase tracking-wider text-slate-500">Posture</div>
                            <div className="text-sm font-semibold text-sky-300">{String(supplierPassport?.posture || "thread_only")}</div>
                          </div>
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-2">
                          <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                            <div className="text-[11px] uppercase tracking-wider text-slate-500">Tier</div>
                            <div className="text-sm font-semibold text-slate-100">{String(supplierScore?.calibrated_tier || "unscored")}</div>
                          </div>
                          <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                            <div className="text-[11px] uppercase tracking-wider text-slate-500">Alternates</div>
                            <div className="text-sm font-semibold text-slate-100">{memberPassport.mission_context.alternate_members.length}</div>
                          </div>
                          <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                            <div className="text-[11px] uppercase tracking-wider text-slate-500">Ownership paths</div>
                            <div className="text-sm font-semibold text-slate-100">{Number(controlPathSummary?.ownership_count || 0)}</div>
                          </div>
                          <div className="rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                            <div className="text-[11px] uppercase tracking-wider text-slate-500">Financing paths</div>
                            <div className="text-sm font-semibold text-slate-100">{Number(controlPathSummary?.financing_count || 0)}</div>
                          </div>
                        </div>
                        <div className="mt-3 text-sm text-slate-300">
                          {memberPassport.resilience.member.recommended_action}
                        </div>
                        <div className="mt-2 text-xs text-slate-400">
                          {memberPassport.mission_context.single_point_of_failure
                            ? "This member is currently acting like a single point of failure in the thread."
                            : "This member has at least some substitute or distribution relief in the thread."}
                        </div>
                      </div>

                      <div className="rounded-3xl" style={{ padding: "16px 18px", background: T.surface, border: `1px solid ${T.border}` }}>
                        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Focus nodes</div>
                        <div className="flex flex-col gap-2">
                          {memberPassport.focus_entities.length === 0 ? (
                            <div className="text-sm text-slate-300">No focus nodes resolved yet.</div>
                          ) : memberPassport.focus_entities.slice(0, 4).map((entity) => (
                            <div key={String(entity.id)} className="flex items-center justify-between gap-3 rounded-2xl" style={{ padding: "10px 12px", background: "rgba(8, 13, 23, 0.48)", border: `1px solid ${T.border}` }}>
                              <div>
                                <div className="text-sm font-semibold text-slate-100">{String(entity.canonical_name || entity.id)}</div>
                                <div className="mt-1 text-xs text-slate-400">{laneLabel(String(entity.entity_type || "unknown"))}</div>
                              </div>
                              <div className="text-right">
                                <div className="text-[11px] uppercase tracking-wider text-slate-500">Mission</div>
                                <div className="text-sm font-semibold text-sky-300">{pct(Number(entity.mission_importance || 0))}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="glass-panel" style={{ padding: 18 }}>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Operator moves</div>
                  <div className="grid grid-cols-1 gap-3">
                    <button
                      onClick={() => onNavigate?.("portfolio")}
                      className="text-left rounded-3xl helios-focus-ring"
                      style={{ padding: "16px 18px", border: `1px solid ${T.border}`, background: T.surface, cursor: "pointer" }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-100">Investigate in Workbench</div>
                          <div className="mt-1 text-xs text-slate-400">Use the existing analyst loop for the next case-level action.</div>
                        </div>
                        <ArrowRight size={14} color={T.accent} />
                      </div>
                    </button>
                    <button
                      onClick={() => onNavigate?.("graph")}
                      className="text-left rounded-3xl helios-focus-ring"
                      style={{ padding: "16px 18px", border: `1px solid ${T.border}`, background: T.surface, cursor: "pointer" }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-100">Open Graph Intel</div>
                          <div className="mt-1 text-xs text-slate-400">Pivot from brittle members into the broader relationship picture.</div>
                        </div>
                        <Grid3X3 size={14} color={T.accent} />
                      </div>
                    </button>
                    <button
                      onClick={() => onNavigate?.("helios")}
                      className="text-left rounded-3xl helios-focus-ring"
                      style={{ padding: "16px 18px", border: `1px solid ${T.border}`, background: T.surface, cursor: "pointer" }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-100">Seed more work through Intake</div>
                          <div className="mt-1 text-xs text-slate-400">Mission threads get stronger only if the underlying cases get richer.</div>
                        </div>
                        <Shield size={14} color={T.accent} />
                      </div>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
