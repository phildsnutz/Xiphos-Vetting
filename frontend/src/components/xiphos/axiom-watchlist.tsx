import { useCallback, useEffect, useState } from "react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import { Plus, Play, Loader, AlertCircle, Square } from "lucide-react";
import { getToken } from "@/lib/auth";
import { EmptyPanel, InlineMessage, LoadingPanel, PanelHeader, StatusPill } from "./shell-primitives";

type WatchlistPriority = "critical" | "high" | "standard" | "low";
type WatchlistStatus = "idle" | "scanning" | "inactive" | "error";

interface RawWatchlistEntry {
  id: string;
  target?: string;
  prime_contractor?: string;
  vehicle?: string;
  vehicle_name?: string;
  priority?: WatchlistPriority | "medium";
  last_scan?: string;
  last_scan_at?: string;
  next_scan_at?: string;
  status?: WatchlistStatus;
  active?: boolean;
  created_at?: string;
}

interface WatchlistEntry {
  id: string;
  target: string;
  vehicle?: string;
  priority: WatchlistPriority;
  last_scan?: string;
  next_scan_at?: string;
  status: WatchlistStatus;
  active: boolean;
  created_at: string;
}

interface WatchlistResponse {
  entries?: RawWatchlistEntry[];
  watchlist?: RawWatchlistEntry[];
}

interface AxiomWatchlistProps {
  onEntriesChange?: (entries: WatchlistEntry[]) => void;
}

function normalizePriority(value?: string): WatchlistPriority {
  if (value === "critical" || value === "high" || value === "standard" || value === "low") {
    return value;
  }
  if (value === "medium") {
    return "standard";
  }
  return "standard";
}

function normalizeEntry(entry: RawWatchlistEntry): WatchlistEntry {
  const active = entry.active ?? true;
  return {
    id: entry.id,
    target: entry.target || entry.prime_contractor || "Unknown target",
    vehicle: entry.vehicle || entry.vehicle_name || "",
    priority: normalizePriority(entry.priority),
    last_scan: entry.last_scan || entry.last_scan_at || "",
    next_scan_at: entry.next_scan_at || "",
    status: entry.status || (active ? "idle" : "inactive"),
    active,
    created_at: entry.created_at || "",
  };
}

function formatTimestamp(timestamp?: string): string {
  if (!timestamp) return "-";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString();
}

export function AxiomWatchlist({ onEntriesChange }: AxiomWatchlistProps) {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [daemonRunning, setDaemonRunning] = useState(false);
  const [daemonStarting, setDaemonStarting] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formTarget, setFormTarget] = useState("");
  const [formVehicle, setFormVehicle] = useState("");
  const [formPriority, setFormPriority] = useState<WatchlistPriority>("high");
  const [isAddingEntry, setIsAddingEntry] = useState(false);
  const [scanningIds, setScanningIds] = useState<Set<string>>(new Set());

  const loadEntries = useCallback(async () => {
    setIsLoading(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/watchlist", {
        headers: {
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to load watchlist: ${response.status}`);
      }

      const data = (await response.json()) as WatchlistResponse;
      const normalized = (data.entries || data.watchlist || []).map(normalizeEntry);
      setEntries(normalized);
      onEntriesChange?.(normalized);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [onEntriesChange]);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  const handleAddEntry = async () => {
    if (!formTarget.trim()) {
      setError("Target name is required");
      return;
    }

    setIsAddingEntry(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/watchlist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
        body: JSON.stringify({
          prime_contractor: formTarget,
          vehicle_name: formVehicle || undefined,
          priority: formPriority,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Failed to add entry: ${response.status}`);
      }

      setFormTarget("");
      setFormVehicle("");
      setFormPriority("high");
      setShowAddForm(false);
      await loadEntries();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsAddingEntry(false);
    }
  };

  const handleScan = async (entryId: string) => {
    setScanningIds((prev) => new Set([...prev, entryId]));
    setError("");

    try {
      const token = getToken();
      const response = await fetch(`/api/axiom/scan/${entryId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });

      if (!response.ok) {
        throw new Error(`Scan failed: ${response.status}`);
      }

      await loadEntries();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setScanningIds((prev) => {
        const next = new Set(prev);
        next.delete(entryId);
        return next;
      });
    }
  };

  const handleDaemonStart = async () => {
    setDaemonStarting(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/daemon/start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to start daemon: ${response.status}`);
      }

      setDaemonRunning(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setDaemonStarting(false);
    }
  };

  const handleDaemonStop = async () => {
    setDaemonStarting(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/daemon/stop", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to stop daemon: ${response.status}`);
      }

      setDaemonRunning(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setDaemonStarting(false);
    }
  };

  const priorityColor = (priority: WatchlistPriority) => {
    switch (priority) {
      case "critical":
        return T.red;
      case "high":
        return T.amber;
      case "standard":
        return T.accent;
      default:
        return T.muted;
    }
  };

  return (
    <div
      className="flex flex-col gap-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}`, padding: PAD.default }}
    >
      <PanelHeader
        eyebrow="Watchlist"
        title="Persistent collection targets"
        description="Keep vendors and vehicles warm between dossier pulls. Use this list for the things AXIOM should revisit without being asked."
        meta={
          <>
            <StatusPill tone={daemonRunning ? "success" : "neutral"}>
              {daemonRunning ? "Daemon running" : "Daemon stopped"}
            </StatusPill>
            <StatusPill tone="neutral">{entries.length} target{entries.length === 1 ? "" : "s"}</StatusPill>
          </>
        }
        actions={
          <button
            type="button"
            aria-label={showAddForm ? "Hide add watchlist target form" : "Show add watchlist target form"}
            onClick={() => setShowAddForm(!showAddForm)}
            className="helios-focus-ring flex items-center gap-1.5 rounded cursor-pointer font-medium"
            style={{
              padding: PAD.default,
              background: `${T.accent}20`,
              border: `1px solid ${T.accent}`,
              color: T.accent,
              fontSize: FS.sm,
            }}
          >
            <Plus size={SP.md + SP.xs} />
            Add Target
          </button>
        }
      />

      {error ? (
        <InlineMessage tone="danger" title="Watchlist error" message={error} icon={AlertCircle} />
      ) : null}

      {showAddForm && (
        <div
          className="rounded-lg space-y-3"
          style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}
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
              Target Name *
            </label>
            <input
              type="text"
              value={formTarget}
              onChange={(e) => setFormTarget(e.target.value)}
              placeholder="e.g., SMX Technologies"
              disabled={isAddingEntry}
              aria-label="AXIOM watchlist target"
              className="w-full rounded border outline-none"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                background: T.surface,
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
                value={formVehicle}
                onChange={(e) => setFormVehicle(e.target.value)}
                placeholder="Optional"
                disabled={isAddingEntry}
                aria-label="AXIOM watchlist vehicle"
                className="w-full rounded border outline-none"
                style={{
                  padding: PAD.default,
                  fontSize: FS.sm,
                  background: T.surface,
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
                Priority
              </label>
              <select
                value={formPriority}
                onChange={(e) => setFormPriority(e.target.value as WatchlistPriority)}
                disabled={isAddingEntry}
                aria-label="AXIOM watchlist priority"
                className="w-full rounded border outline-none"
                style={{
                  padding: PAD.default,
                  fontSize: FS.sm,
                  background: T.surface,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="standard">Standard</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              aria-label="Add watchlist entry"
              onClick={handleAddEntry}
              disabled={isAddingEntry || !formTarget.trim()}
              className="flex-1 rounded cursor-pointer font-medium"
              style={{
                padding: PAD.default,
                background: T.accent,
                color: T.textInverse,
                fontSize: FS.sm,
                opacity: isAddingEntry || !formTarget.trim() ? 0.6 : 1,
                cursor: isAddingEntry || !formTarget.trim() ? "not-allowed" : "pointer",
              }}
            >
              {isAddingEntry ? "Adding..." : "Add Entry"}
            </button>
            <button
              type="button"
              aria-label="Cancel add watchlist entry"
              onClick={() => setShowAddForm(false)}
              disabled={isAddingEntry}
              className="flex-1 rounded cursor-pointer font-medium"
              style={{
                padding: PAD.default,
                background: "transparent",
                border: `1px solid ${T.border}`,
                color: T.muted,
                fontSize: FS.sm,
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-2 border-b pb-2" style={{ borderColor: T.border }}>
        <button
          type="button"
          aria-label={daemonRunning ? "Stop AXIOM watchlist daemon" : "Start AXIOM watchlist daemon"}
          onClick={daemonRunning ? handleDaemonStop : handleDaemonStart}
          disabled={daemonStarting}
          className="flex items-center gap-1.5 rounded cursor-pointer font-medium"
          style={{
            padding: PAD.default,
            background: daemonRunning ? `${T.red}20` : `${T.green}20`,
            border: `1px solid ${daemonRunning ? T.red : T.green}`,
            color: daemonRunning ? T.red : T.green,
            fontSize: FS.sm,
            opacity: daemonStarting ? 0.6 : 1,
            cursor: daemonStarting ? "not-allowed" : "pointer",
          }}
        >
          {daemonStarting ? <Loader size={SP.md + SP.xs} /> : daemonRunning ? <Square size={SP.md + SP.xs} /> : <Play size={SP.md + SP.xs} />}
          {daemonStarting ? "Updating..." : daemonRunning ? "Stop Daemon" : "Start Daemon"}
        </button>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            paddingLeft: SP.md,
            borderRadius: SP.sm,
            fontSize: FS.sm,
            color: daemonRunning ? T.green : T.muted,
            background: daemonRunning ? `${T.green}10` : "transparent",
          }}
        >
          {daemonRunning ? "Daemon is running" : "Daemon is stopped"}
        </div>
      </div>

      {isLoading ? <LoadingPanel label="Loading watchlist" detail="Pulling saved AXIOM monitoring targets and daemon state." /> : null}

      {!isLoading && entries.length === 0 ? (
        <EmptyPanel
          title="No watchlist entries yet"
          description="Add a target to begin monitoring vendors, vehicles, and the changes AXIOM should revisit automatically."
          action={
            <button
              type="button"
              aria-label="Show add watchlist target form"
              onClick={() => setShowAddForm(true)}
              className="helios-focus-ring"
              style={{
                borderRadius: 999,
                border: "none",
                background: T.accent,
                color: T.textInverse,
                padding: "10px 14px",
                fontSize: FS.sm,
                fontWeight: 800,
                cursor: "pointer",
              }}
            >
              Add target
            </button>
          }
        />
      ) : null}

      {!isLoading && entries.length > 0 && (
        <div className="overflow-x-auto">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: FS.sm }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                {["Target", "Vehicle", "Priority", "Last Scan", "Next Scan", "Action"].map((header) => (
                  <th
                    key={header}
                    style={{
                      textAlign: header === "Priority" || header === "Action" ? "center" : "left",
                      padding: PAD.default,
                      color: T.muted,
                      fontWeight: 500,
                    }}
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const scanning = scanningIds.has(entry.id);
                return (
                  <tr
                    key={entry.id}
                    style={{
                      borderBottom: `1px solid ${T.border}`,
                      background: entry.status === "error" ? `${T.red}08` : "transparent",
                    }}
                  >
                    <td style={{ padding: PAD.default, color: T.text }}>{entry.target}</td>
                    <td style={{ padding: PAD.default, color: T.muted }}>{entry.vehicle || "-"}</td>
                    <td style={{ padding: PAD.default, textAlign: "center", color: priorityColor(entry.priority), fontWeight: 600 }}>
                      {entry.priority}
                    </td>
                    <td style={{ padding: PAD.default, color: T.muted }}>{formatTimestamp(entry.last_scan)}</td>
                    <td style={{ padding: PAD.default, color: T.muted }}>{formatTimestamp(entry.next_scan_at)}</td>
                    <td style={{ padding: PAD.default, textAlign: "center" }}>
                      <button
                        type="button"
                        aria-label={`Run AXIOM scan for ${entry.target}`}
                        onClick={() => void handleScan(entry.id)}
                        disabled={scanning}
                        className="rounded cursor-pointer font-medium"
                        style={{
                          padding: PAD.default,
                          background: `${T.accent}20`,
                          border: `1px solid ${T.accent}`,
                          color: T.accent,
                          fontSize: FS.sm,
                          opacity: scanning ? 0.6 : 1,
                          cursor: scanning ? "not-allowed" : "pointer",
                        }}
                      >
                        {scanning ? "Scanning..." : "Scan Now"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
