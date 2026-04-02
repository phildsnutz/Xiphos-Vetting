import { useEffect, useState } from "react";
import { T, FS } from "@/lib/tokens";
import { Plus, Play, Loader, AlertCircle } from "lucide-react";
import { getToken } from "@/lib/auth";

interface WatchlistEntry {
  id: string;
  target: string;
  vehicle?: string;
  priority: "critical" | "high" | "medium" | "low";
  last_scan?: string;
  status: "idle" | "scanning" | "error";
  created_at: string;
}

interface AxiomWatchlistProps {
  onEntriesChange?: (entries: WatchlistEntry[]) => void;
}

export function AxiomWatchlist({ onEntriesChange }: AxiomWatchlistProps) {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [daemonRunning, setDaemonRunning] = useState(false);
  const [daemonStarting, setDaemonStarting] = useState(false);

  // Add watchlist form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [formTarget, setFormTarget] = useState("");
  const [formVehicle, setFormVehicle] = useState("");
  const [formPriority, setFormPriority] = useState<"high" | "medium" | "low">("high");
  const [isAddingEntry, setIsAddingEntry] = useState(false);

  // Scan state
  const [scanningIds, setScanningIds] = useState<Set<string>>(new Set());

  // Load watchlist entries
  const loadEntries = async () => {
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

      const data = (await response.json()) as { entries: WatchlistEntry[] };
      setEntries(data.entries || []);
      onEntriesChange?.(data.entries || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadEntries();
  }, []);

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
          target: formTarget,
          vehicle: formVehicle || undefined,
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

  const priorityColor = (priority: string) => {
    switch (priority) {
      case "critical":
        return T.red;
      case "high":
        return T.amber;
      case "medium":
        return T.accent;
      default:
        return T.muted;
    }
  };

  return (
    <div
      className="flex flex-col gap-4 p-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}` }}
    >
      <div className="flex items-center justify-between">
        <h3 style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>
          AXIOM Watchlist
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="flex items-center gap-1.5 rounded px-3 py-1.5 cursor-pointer font-medium"
            style={{
              background: T.accent + "20",
              border: `1px solid ${T.accent}`,
              color: T.accent,
              fontSize: FS.sm,
            }}
          >
            <Plus size={14} />
            Add Target
          </button>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="rounded-lg p-3 flex gap-2" style={{ background: T.red + "15", border: `1px solid ${T.red}` }}>
          <AlertCircle size={16} color={T.red} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: FS.sm, color: T.red }}>{error}</div>
        </div>
      )}

      {/* Add form */}
      {showAddForm && (
        <div
          className="p-3 rounded-lg space-y-3"
          style={{ background: T.bg, border: `1px solid ${T.border}` }}
        >
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
              Target Name *
            </label>
            <input
              type="text"
              value={formTarget}
              onChange={(e) => setFormTarget(e.target.value)}
              placeholder="e.g., Acme Corp"
              disabled={isAddingEntry}
              className="w-full rounded border outline-none"
              style={{
                padding: "8px 10px",
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
                  marginBottom: 6,
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
                className="w-full rounded border outline-none"
                style={{
                  padding: "8px 10px",
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
                  marginBottom: 6,
                }}
              >
                Priority
              </label>
              <select
                value={formPriority}
                onChange={(e) => setFormPriority(e.target.value as "high" | "medium" | "low")}
                disabled={isAddingEntry}
                className="w-full rounded border outline-none"
                style={{
                  padding: "8px 10px",
                  fontSize: FS.sm,
                  background: T.surface,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              >
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button
              onClick={handleAddEntry}
              disabled={isAddingEntry || !formTarget.trim()}
              className="flex-1 rounded px-3 py-2 cursor-pointer font-medium"
              style={{
                background: T.accent,
                color: "#000",
                fontSize: FS.sm,
                opacity: isAddingEntry || !formTarget.trim() ? 0.6 : 1,
                cursor: isAddingEntry || !formTarget.trim() ? "not-allowed" : "pointer",
              }}
            >
              {isAddingEntry ? "Adding..." : "Add Entry"}
            </button>
            <button
              onClick={() => setShowAddForm(false)}
              disabled={isAddingEntry}
              className="flex-1 rounded px-3 py-2 cursor-pointer font-medium"
              style={{
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

      {/* Daemon controls */}
      <div className="flex gap-2 pb-2 border-b" style={{ borderColor: T.border }}>
        <button
          onClick={daemonRunning ? handleDaemonStop : handleDaemonStart}
          disabled={daemonStarting}
          className="flex items-center gap-1.5 rounded px-3 py-1.5 cursor-pointer font-medium"
          style={{
            background: daemonRunning ? T.red + "20" : T.green + "20",
            border: `1px solid ${daemonRunning ? T.red : T.green}`,
            color: daemonRunning ? T.red : T.green,
            fontSize: FS.sm,
            opacity: daemonStarting ? 0.6 : 1,
            cursor: daemonStarting ? "not-allowed" : "pointer",
          }}
        >
          {daemonStarting ? <Loader size={14} /> : <Play size={14} />}
          {daemonStarting ? "Updating..." : daemonRunning ? "Stop Daemon" : "Start Daemon"}
        </button>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            paddingLeft: 12,
            borderRadius: 6,
            fontSize: FS.sm,
            color: daemonRunning ? T.green : T.muted,
            background: daemonRunning ? T.green + "10" : "transparent",
          }}
        >
          {daemonRunning ? "Daemon is running" : "Daemon is stopped"}
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div style={{ textAlign: "center", padding: "20px", color: T.muted }}>
          <Loader size={16} style={{ display: "inline-block", animation: "spin 2s linear infinite" }} />
          <div style={{ fontSize: FS.sm, marginTop: 8 }}>Loading watchlist...</div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && entries.length === 0 && (
        <div style={{ textAlign: "center", padding: "20px", color: T.muted }}>
          <div style={{ fontSize: FS.sm }}>No watchlist entries yet</div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
            Add a target to begin monitoring
          </div>
        </div>
      )}

      {/* Entries table */}
      {!isLoading && entries.length > 0 && (
        <div className="overflow-x-auto">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: FS.sm }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                <th
                  style={{
                    textAlign: "left",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Target
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Vehicle
                </th>
                <th
                  style={{
                    textAlign: "center",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Priority
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Last Scan
                </th>
                <th
                  style={{
                    textAlign: "center",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Status
                </th>
                <th
                  style={{
                    textAlign: "center",
                    padding: "8px",
                    color: T.muted,
                    fontWeight: 500,
                  }}
                >
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={entry.id}
                  style={{
                    borderBottom: `1px solid ${T.border}`,
                    background: entry.status === "error" ? T.red + "08" : "transparent",
                  }}
                >
                  <td style={{ padding: "8px", color: T.text }}>
                    {entry.target}
                  </td>
                  <td style={{ padding: "8px", color: T.muted }}>
                    {entry.vehicle || "-"}
                  </td>
                  <td
                    style={{
                      padding: "8px",
                      textAlign: "center",
                      color: priorityColor(entry.priority),
                      fontWeight: 600,
                    }}
                  >
                    {entry.priority}
                  </td>
                  <td style={{ padding: "8px", color: T.dim }}>
                    {entry.last_scan ? new Date(entry.last_scan).toLocaleDateString() : "Never"}
                  </td>
                  <td
                    style={{
                      padding: "8px",
                      textAlign: "center",
                      color: entry.status === "error" ? T.red : entry.status === "scanning" ? T.accent : T.green,
                    }}
                  >
                    {entry.status}
                  </td>
                  <td style={{ padding: "8px", textAlign: "center" }}>
                    <button
                      onClick={() => handleScan(entry.id)}
                      disabled={scanningIds.has(entry.id)}
                      className="rounded px-2 py-1 cursor-pointer"
                      style={{
                        background: T.accent + "20",
                        border: `1px solid ${T.accent}`,
                        color: T.accent,
                        fontSize: FS.sm,
                        opacity: scanningIds.has(entry.id) ? 0.6 : 1,
                        cursor: scanningIds.has(entry.id) ? "not-allowed" : "pointer",
                      }}
                    >
                      {scanningIds.has(entry.id) ? "Scanning" : "Scan"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
