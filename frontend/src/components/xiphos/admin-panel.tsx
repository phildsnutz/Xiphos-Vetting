import { useCallback, useEffect, useState } from "react";
import { Users, Plus, Shield, Clock, ChevronUp, AlertTriangle, Brain, MessageSquare, Activity } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import { fetchUsers, createUser, fetchAuditLog, fetchBetaFeedback, fetchBetaOpsSummary } from "@/lib/api";
import type { ApiUser, AuditEntry, BetaFeedbackEntry, BetaOpsSummary } from "@/lib/api";
import { roleLabel } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";
import { AISettings } from "./ai-settings";

interface AdminPanelProps {
  currentUser: AuthUser;
}

const ROLE_COLORS: Record<string, { color: string; bg: string }> = {
  admin: { color: T.red, bg: T.redBg },
  analyst: { color: T.accent, bg: T.accent + "18" },
  auditor: { color: T.amber, bg: T.amberBg },
  reviewer: { color: T.green, bg: T.greenBg },
};

export function AdminPanel({ currentUser }: AdminPanelProps) {
  const isAdmin = currentUser.role === "admin";
  const canViewAudit = currentUser.role === "admin" || currentUser.role === "auditor";
  const canViewBetaOps = canViewAudit;
  const canManageUsers = isAdmin;
  const canManageAI = isAdmin;
  const [activeTab, setActiveTab] = useState<"users" | "audit" | "beta" | "ai">(isAdmin ? "users" : "audit");
  const [users, setUsers] = useState<ApiUser[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [betaFeedback, setBetaFeedback] = useState<BetaFeedbackEntry[]>([]);
  const [betaSummary, setBetaSummary] = useState<BetaOpsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Create user form state
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("analyst");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSuccess, setCreateSuccess] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      if (activeTab === "users" && canManageUsers) {
        const u = await fetchUsers();
        setUsers(u);
      } else if (activeTab === "audit" && canViewAudit) {
        const log = await fetchAuditLog(200);
        setAuditLog(log);
      } else if (activeTab === "beta" && canViewBetaOps) {
        const [feedback, summary] = await Promise.all([
          fetchBetaFeedback(100),
          fetchBetaOpsSummary(168),
        ]);
        setBetaFeedback(feedback);
        setBetaSummary(summary);
      }
    } catch {
      // Permission denied or API error
    } finally {
      setLoading(false);
    }
  }, [activeTab, canManageUsers, canViewAudit, canViewBetaOps]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setCreateSuccess(null);
    setCreating(true);

    try {
      const user = await createUser(newEmail, newPassword, newName, newRole);
      setCreateSuccess(`Created ${user.email} as ${roleLabel(user.role)}`);
      setNewEmail("");
      setNewPassword("");
      setNewName("");
      setNewRole("analyst");
      setShowCreateForm(false);
      // Reload user list
      const u = await fetchUsers();
      setUsers(u);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="h-full flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={16} color={T.accent} />
          <span style={{ fontSize: FS.md, fontWeight: 600, color: T.text }}>
            Admin tools
          </span>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center gap-1">
          {canManageUsers && (
            <button
              onClick={() => setActiveTab("users")}
              className="inline-flex items-center gap-1 rounded px-3 py-1.5 cursor-pointer"
              style={{
                fontSize: FS.sm,
                border: "none",
                background: activeTab === "users" ? T.accent + "22" : "transparent",
                color: activeTab === "users" ? T.accent : T.muted,
              }}
            >
              <Users size={12} />
              Users
            </button>
          )}
          {canViewAudit && (
            <button
              onClick={() => setActiveTab("audit")}
              className="inline-flex items-center gap-1 rounded px-3 py-1.5 cursor-pointer"
              style={{
                fontSize: FS.sm,
                border: "none",
                background: activeTab === "audit" ? T.accent + "22" : "transparent",
                color: activeTab === "audit" ? T.accent : T.muted,
              }}
            >
              <Clock size={12} />
              Activity
            </button>
          )}
          {canViewBetaOps && (
            <button
              onClick={() => setActiveTab("beta")}
              className="inline-flex items-center gap-1 rounded px-3 py-1.5 cursor-pointer"
              style={{
                fontSize: FS.sm,
                border: "none",
                background: activeTab === "beta" ? T.accent + "22" : "transparent",
                color: activeTab === "beta" ? T.accent : T.muted,
              }}
            >
              <MessageSquare size={12} />
              Beta Ops
            </button>
          )}
          {canManageAI && (
            <button
              onClick={() => setActiveTab("ai")}
              className="inline-flex items-center gap-1 rounded px-3 py-1.5 cursor-pointer"
              style={{
                fontSize: FS.sm,
                border: "none",
                background: activeTab === "ai" ? T.accent + "22" : "transparent",
                color: activeTab === "ai" ? T.accent : T.muted,
              }}
            >
              <Brain size={12} />
              AI Settings
            </button>
          )}
        </div>
      </div>

      {/* Success/error banners */}
      {createSuccess && (
        <div
          className="rounded p-3 flex items-center gap-2"
          style={{ background: T.greenBg, fontSize: FS.sm, color: T.green }}
        >
          <Shield size={14} />
          {createSuccess}
          <button
            onClick={() => setCreateSuccess(null)}
            className="ml-auto cursor-pointer"
            style={{ background: "none", border: "none", color: T.green, fontSize: FS.md }}
          >
            &times;
          </button>
        </div>
      )}

      {/* Users tab */}
      {activeTab === "users" && canManageUsers && (
        <div className="flex-1 flex flex-col gap-3">
          {/* Create user button (admin only) */}
          {isAdmin && (
            <div>
              <button
                onClick={() => setShowCreateForm(!showCreateForm)}
                className="inline-flex items-center gap-1.5 rounded px-3 py-2 cursor-pointer"
                style={{
                  fontSize: FS.sm,
                  background: T.accent,
                  color: "#fff",
                  border: "none",
                }}
              >
                {showCreateForm ? <ChevronUp size={12} /> : <Plus size={12} />}
                {showCreateForm ? "Cancel" : "Add user"}
              </button>
            </div>
          )}

          {/* Create user form */}
          {showCreateForm && isAdmin && (
            <div
              className="rounded-lg p-4"
              style={{ background: T.surface, border: `1px solid ${T.border}` }}
            >
              <div className="flex items-center gap-2 mb-3">
                <Plus size={13} color={T.accent} />
                <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>
                  Add user
                </span>
              </div>

              {createError && (
                <div
                  className="rounded p-2.5 mb-3 flex items-center gap-2"
                  style={{ background: T.redBg, fontSize: FS.sm, color: T.red }}
                >
                  <AlertTriangle size={12} />
                  {createError}
                </div>
              )}

              <form onSubmit={handleCreateUser} className="grid grid-cols-2 gap-3">
                <div>
                  <label style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 3 }}>
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Jane Doe"
                    required
                    className="w-full rounded outline-none"
                    style={{
                      padding: "6px 10px", fontSize: FS.sm,
                      background: T.bg, border: `1px solid ${T.border}`, color: T.text,
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 3 }}>
                    Email
                  </label>
                  <input
                    type="email"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="analyst@yourorg.com"
                    required
                    className="w-full rounded outline-none"
                    style={{
                      padding: "6px 10px", fontSize: FS.sm,
                      background: T.bg, border: `1px solid ${T.border}`, color: T.text,
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 3 }}>
                    Password
                  </label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Min 8 characters"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className="w-full rounded outline-none"
                    style={{
                      padding: "6px 10px", fontSize: FS.sm,
                      background: T.bg, border: `1px solid ${T.border}`, color: T.text,
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 3 }}>
                    Role
                  </label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    className="w-full rounded outline-none cursor-pointer"
                    style={{
                      padding: "6px 10px", fontSize: FS.sm,
                      background: T.bg, border: `1px solid ${T.border}`, color: T.text,
                    }}
                  >
                    <option value="analyst">Analyst (score, enrich, dossier)</option>
                    <option value="auditor">Auditor (read-only + audit log)</option>
                    <option value="reviewer">Reviewer (read-only)</option>
                    <option value="admin">Admin (full access)</option>
                  </select>
                </div>
                <div className="col-span-2">
                  <button
                    type="submit"
                    disabled={creating}
                    className="rounded px-4 py-2 cursor-pointer"
                    style={{
                      fontSize: FS.sm,
                      background: creating ? T.muted : T.accent,
                      color: "#fff",
                      border: "none",
                      opacity: creating ? 0.7 : 1,
                    }}
                  >
                    {creating ? "Creating..." : "Create User"}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* User table */}
          <div
            className="rounded-lg overflow-hidden flex-1"
            style={{ border: `1px solid ${T.border}` }}
          >
            {loading ? (
              <div className="p-8 text-center" style={{ fontSize: FS.sm, color: T.muted }}>
                Loading users...
              </div>
            ) : users.length === 0 ? (
              <div className="p-8 text-center" style={{ fontSize: FS.sm, color: T.muted }}>
                No users found. Create the first user above.
              </div>
            ) : (
              <table className="w-full" style={{ fontSize: FS.sm }}>
                <thead>
                  <tr style={{ background: T.surface, borderBottom: `1px solid ${T.border}` }}>
                    <th className="text-left px-4 py-2.5 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      USER
                    </th>
                    <th className="text-left px-4 py-2.5 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      EMAIL
                    </th>
                    <th className="text-left px-4 py-2.5 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      ROLE
                    </th>
                    <th className="text-left px-4 py-2.5 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      CREATED
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const rc = ROLE_COLORS[u.role] || ROLE_COLORS.reviewer;
                    return (
                      <tr
                        key={u.id}
                        style={{ borderBottom: `1px solid ${T.border}` }}
                      >
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <div
                              className="flex items-center justify-center rounded-full font-bold shrink-0"
                              style={{
                                width: 26, height: 26, fontSize: FS.sm,
                                background: rc.bg, color: rc.color,
                              }}
                            >
                              {(u.name || u.email).split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 2)}
                            </div>
                            <span style={{ color: T.text, fontWeight: 500 }}>
                              {u.name || u.email.split("@")[0]}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5" style={{ color: T.dim }}>
                          {u.email}
                        </td>
                        <td className="px-4 py-2.5">
                          <span
                            className="inline-block rounded font-mono px-2 py-0.5"
                            style={{ fontSize: FS.sm, background: rc.bg, color: rc.color }}
                          >
                            {roleLabel(u.role)}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono" style={{ color: T.muted, fontSize: FS.sm }}>
                          {u.created_at ? new Date(u.created_at).toLocaleDateString() : "N/A"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            {users.length} user{users.length !== 1 ? "s" : ""} registered
          </div>
        </div>
      )}

      {activeTab === "beta" && canViewBetaOps && (
        <div className="flex-1 flex flex-col gap-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              { label: "Open feedback", value: String(betaSummary?.open_feedback_count ?? 0), color: T.red, bg: T.redBg },
              { label: "Feedback (24h)", value: String(betaSummary?.feedback_last_24h ?? 0), color: T.accent, bg: `${T.accent}18` },
              { label: "Tracked events (7d)", value: String(betaSummary?.recent_event_count ?? 0), color: T.green, bg: T.greenBg },
            ].map((card) => (
              <div
                key={card.label}
                className="rounded-lg p-4"
                style={{ background: T.surface, border: `1px solid ${T.border}` }}
              >
                <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 4 }}>{card.label}</div>
                <div style={{ fontSize: FS.lg, fontWeight: 700, color: card.color }}>{card.value}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="flex items-center gap-2 mb-3">
                <Activity size={13} color={T.accent} />
                <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>Top beta events</span>
              </div>
              <div className="flex flex-col gap-2">
                {(betaSummary?.event_counts ?? []).slice(0, 6).map((item) => (
                  <div key={item.event_name} className="flex items-center justify-between">
                    <span style={{ fontSize: FS.sm, color: T.text }}>{item.event_name}</span>
                    <span style={{ fontSize: FS.sm, color: T.muted }}>{item.count}</span>
                  </div>
                ))}
                {(betaSummary?.event_counts ?? []).length === 0 && (
                  <div style={{ fontSize: FS.sm, color: T.muted }}>No beta events recorded yet.</div>
                )}
              </div>
            </div>

            <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="flex items-center gap-2 mb-3">
                <MessageSquare size={13} color={T.accent} />
                <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>Feedback by lane</span>
              </div>
              <div className="flex flex-col gap-2">
                {(betaSummary?.feedback_by_lane ?? []).map((item) => (
                  <div key={item.workflow_lane ?? "unknown"} className="flex items-center justify-between">
                    <span style={{ fontSize: FS.sm, color: T.text }}>{item.workflow_lane || "unspecified"}</span>
                    <span style={{ fontSize: FS.sm, color: T.muted }}>{item.count}</span>
                  </div>
                ))}
                {(betaSummary?.feedback_by_lane ?? []).length === 0 && (
                  <div style={{ fontSize: FS.sm, color: T.muted }}>No lane-specific feedback recorded yet.</div>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-lg overflow-hidden" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${T.border}` }}>
              <div className="flex items-center gap-2">
                <MessageSquare size={13} color={T.accent} />
                <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>Recent beta feedback</span>
              </div>
              <span style={{ fontSize: FS.sm, color: T.muted }}>{betaFeedback.length} items</span>
            </div>
            <div className="divide-y" style={{ borderColor: T.border }}>
              {betaFeedback.slice(0, 12).map((item) => (
                <div key={item.id} className="p-4 flex flex-col gap-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>{item.summary}</span>
                    <span
                      className="rounded"
                      style={{ fontSize: 11, padding: "2px 6px", background: `${T.accent}18`, color: T.accent }}
                    >
                      {item.workflow_lane || "unspecified"}
                    </span>
                    <span
                      className="rounded"
                      style={{ fontSize: 11, padding: "2px 6px", background: item.severity === "high" ? T.redBg : item.severity === "medium" ? T.amberBg : `${T.green}18`, color: item.severity === "high" ? T.red : item.severity === "medium" ? T.amber : T.green }}
                    >
                      {item.severity}
                    </span>
                    <span style={{ fontSize: FS.sm, color: T.muted }}>{item.category}</span>
                  </div>
                  {item.details && (
                    <div style={{ fontSize: FS.sm, color: T.muted }}>{item.details}</div>
                  )}
                  <div style={{ fontSize: FS.sm, color: T.dim }}>
                    {item.screen || "unknown screen"}{item.case_id ? ` · ${item.case_id}` : ""}{item.user_email ? ` · ${item.user_email}` : ""} · {item.created_at}
                  </div>
                </div>
              ))}
              {betaFeedback.length === 0 && (
                <div className="p-4" style={{ fontSize: FS.sm, color: T.muted }}>
                  No beta feedback submitted yet.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* AI Settings tab */}
      {activeTab === "ai" && canManageAI && (
        <div className="flex-1">
          <AISettings currentUser={currentUser} />
        </div>
      )}

      {/* Audit Log tab */}
      {activeTab === "audit" && canViewAudit && (
        <div className="flex-1 flex flex-col gap-3">
          <div
            className="rounded-lg overflow-auto flex-1"
            style={{ border: `1px solid ${T.border}`, maxHeight: "calc(100vh - 200px)" }}
          >
            {loading ? (
              <div className="p-8 text-center" style={{ fontSize: FS.sm, color: T.muted }}>
                Loading audit log...
              </div>
            ) : auditLog.length === 0 ? (
              <div className="p-8 text-center" style={{ fontSize: FS.sm, color: T.muted }}>
                No audit entries yet.
              </div>
            ) : (
              <table className="w-full" style={{ fontSize: FS.sm }}>
                <thead className="sticky top-0">
                  <tr style={{ background: T.surface, borderBottom: `1px solid ${T.border}` }}>
                    <th className="text-left px-3 py-2 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      TIMESTAMP
                    </th>
                    <th className="text-left px-3 py-2 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      USER
                    </th>
                    <th className="text-left px-3 py-2 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      ACTION
                    </th>
                    <th className="text-left px-3 py-2 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      DETAIL
                    </th>
                    <th className="text-left px-3 py-2 font-medium" style={{ color: T.muted, fontSize: FS.sm }}>
                      IP
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {auditLog.map((entry) => {
                    const actionColor =
                      entry.action.includes("failed") || entry.action.includes("denied")
                        ? T.red
                        : entry.action.includes("created") || entry.action.includes("success")
                          ? T.green
                          : T.dim;

                    return (
                      <tr
                        key={entry.id}
                        style={{ borderBottom: `1px solid ${T.border}` }}
                      >
                        <td className="px-3 py-2 font-mono whitespace-nowrap" style={{ color: T.muted, fontSize: FS.sm }}>
                          {new Date(entry.timestamp).toLocaleString()}
                        </td>
                        <td className="px-3 py-2" style={{ color: T.dim }}>
                          {entry.email || entry.user_id || "system"}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className="font-mono"
                            style={{ fontSize: FS.sm, color: actionColor }}
                          >
                            {entry.action}
                          </span>
                        </td>
                        <td className="px-3 py-2" style={{ color: T.text, maxWidth: 300 }}>
                          <span className="block truncate">{entry.detail || ""}</span>
                        </td>
                        <td className="px-3 py-2 font-mono" style={{ color: T.muted, fontSize: FS.sm }}>
                          {entry.ip_address || "N/A"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            Showing {auditLog.length} entries (most recent first)
          </div>
        </div>
      )}
    </div>
  );
}
