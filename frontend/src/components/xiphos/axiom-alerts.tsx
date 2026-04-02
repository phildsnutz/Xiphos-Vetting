import { useEffect, useState } from "react";
import { T, FS } from "@/lib/tokens";
import { AlertCircle, TrendingUp, TrendingDown, Users, Loader } from "lucide-react";
import { getToken } from "@/lib/auth";

interface AlertItem {
  id: string;
  type: "new_sub" | "departed_sub" | "hiring_surge" | "position_drop" | "activity_change";
  severity: "critical" | "high" | "medium" | "low";
  target: string;
  priority: "critical" | "high" | "medium" | "low";
  details: string;
  timestamp: string;
  watchlist_entry_id?: string;
}

interface AxiomAlertsProps {
  onAlertsChange?: (alerts: AlertItem[]) => void;
}

export function AxiomAlerts({ onAlertsChange }: AxiomAlertsProps) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>(["new_sub", "departed_sub", "hiring_surge", "position_drop"]);
  const [selectedPriorities, setSelectedPriorities] = useState<string[]>(["critical", "high", "medium", "low"]);

  // Load alerts
  const loadAlerts = async () => {
    setIsLoading(true);
    setError("");

    try {
      const token = getToken();
      const response = await fetch("/api/axiom/alerts", {
        headers: {
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to load alerts: ${response.status}`);
      }

      const data = (await response.json()) as { alerts: AlertItem[] };
      setAlerts(data.alerts || []);
      onAlertsChange?.(data.alerts || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAlerts();
    // Poll for new alerts every 30 seconds
    const interval = setInterval(loadAlerts, 30000);
    return () => clearInterval(interval);
  }, []);

  const filteredAlerts = alerts.filter(
    (alert) =>
      selectedTypes.includes(alert.type) &&
      selectedPriorities.includes(alert.priority)
  );

  const getAlertColor = (type: string) => {
    switch (type) {
      case "new_sub":
        return { icon: Users, color: T.green, bg: T.green + "15" };
      case "departed_sub":
        return { icon: TrendingDown, color: T.amber, bg: T.amber + "15" };
      case "hiring_surge":
        return { icon: TrendingUp, color: T.accent, bg: T.accent + "15" };
      case "position_drop":
        return { icon: TrendingDown, color: T.red, bg: T.red + "15" };
      default:
        return { icon: AlertCircle, color: T.muted, bg: T.muted + "15" };
    }
  };

  const getPriorityColor = (priority: string) => {
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

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  const alertTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      new_sub: "New Subsidiary",
      departed_sub: "Departed Subsidiary",
      hiring_surge: "Hiring Surge",
      position_drop: "Position Drop",
      activity_change: "Activity Change",
    };
    return labels[type] || type;
  };

  return (
    <div
      className="flex flex-col gap-4 p-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}` }}
    >
      <div className="flex items-center justify-between">
        <h3 style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>
          AXIOM Alerts
        </h3>
        <div
          style={{
            fontSize: FS.sm,
            fontWeight: 600,
            color: T.accent,
            background: T.accent + "20",
            padding: "4px 10px",
            borderRadius: 4,
          }}
        >
          {filteredAlerts.length}
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="rounded-lg p-3 flex gap-2" style={{ background: T.red + "15", border: `1px solid ${T.red}` }}>
          <AlertCircle size={16} color={T.red} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: FS.sm, color: T.red }}>{error}</div>
        </div>
      )}

      {/* Filters */}
      <div className="space-y-3 p-3 rounded-lg" style={{ background: T.bg, border: `1px solid ${T.border}` }}>
        <div>
          <label style={{ fontSize: FS.sm, fontWeight: 500, color: T.muted, marginBottom: 8, display: "block" }}>
            Alert Types
          </label>
          <div className="flex flex-wrap gap-2">
            {["new_sub", "departed_sub", "hiring_surge", "position_drop"].map((type) => (
              <button
                key={type}
                onClick={() => {
                  if (selectedTypes.includes(type)) {
                    setSelectedTypes(selectedTypes.filter((t) => t !== type));
                  } else {
                    setSelectedTypes([...selectedTypes, type]);
                  }
                }}
                className="rounded px-2.5 py-1 cursor-pointer font-medium"
                style={{
                  fontSize: FS.sm,
                  background: selectedTypes.includes(type) ? T.accent : T.surface,
                  border: `1px solid ${selectedTypes.includes(type) ? T.accent : T.border}`,
                  color: selectedTypes.includes(type) ? "#000" : T.muted,
                }}
              >
                {alertTypeLabel(type)}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: FS.sm, fontWeight: 500, color: T.muted, marginBottom: 8, display: "block" }}>
            Priority
          </label>
          <div className="flex flex-wrap gap-2">
            {["critical", "high", "medium", "low"].map((priority) => (
              <button
                key={priority}
                onClick={() => {
                  if (selectedPriorities.includes(priority)) {
                    setSelectedPriorities(selectedPriorities.filter((p) => p !== priority));
                  } else {
                    setSelectedPriorities([...selectedPriorities, priority]);
                  }
                }}
                className="rounded px-2.5 py-1 cursor-pointer font-medium"
                style={{
                  fontSize: FS.sm,
                  background: selectedPriorities.includes(priority)
                    ? getPriorityColor(priority)
                    : T.surface,
                  border: `1px solid ${selectedPriorities.includes(priority) ? getPriorityColor(priority) : T.border}`,
                  color: selectedPriorities.includes(priority) ? "#000" : T.muted,
                }}
              >
                {priority}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div style={{ textAlign: "center", padding: "20px", color: T.muted }}>
          <Loader size={16} style={{ display: "inline-block", animation: "spin 2s linear infinite" }} />
          <div style={{ fontSize: FS.sm, marginTop: 8 }}>Loading alerts...</div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && filteredAlerts.length === 0 && (
        <div style={{ textAlign: "center", padding: "20px", color: T.muted }}>
          <div style={{ fontSize: FS.sm }}>No alerts match your filters</div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
            {alerts.length === 0 ? "No alerts yet" : "Try adjusting your filters"}
          </div>
        </div>
      )}

      {/* Alerts feed */}
      {!isLoading && filteredAlerts.length > 0 && (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {filteredAlerts.map((alert) => {
            const { icon: IconComponent, color, bg } = getAlertColor(alert.type);
            return (
              <div
                key={alert.id}
                className="p-3 rounded-lg border"
                style={{
                  background: bg,
                  border: `1px solid ${color}`,
                }}
              >
                <div className="flex gap-3">
                  <div style={{ flexShrink: 0, marginTop: 2 }}>
                    <IconComponent size={16} color={color} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div>
                        <div
                          style={{
                            fontSize: FS.sm,
                            fontWeight: 600,
                            color: T.text,
                          }}
                        >
                          {alertTypeLabel(alert.type)}
                        </div>
                        <div
                          style={{
                            fontSize: FS.sm,
                            color: T.muted,
                            marginTop: 2,
                          }}
                        >
                          {alert.target}
                        </div>
                      </div>
                      <div
                        style={{
                          fontSize: FS.sm,
                          color: getPriorityColor(alert.priority),
                          fontWeight: 600,
                          flexShrink: 0,
                        }}
                      >
                        {alert.priority}
                      </div>
                    </div>
                    <div
                      style={{
                        fontSize: FS.sm,
                        color: T.dim,
                        marginTop: 4,
                        lineHeight: 1.4,
                      }}
                    >
                      {alert.details}
                    </div>
                    <div
                      style={{
                        fontSize: FS.sm,
                        color: T.muted,
                        marginTop: 4,
                      }}
                    >
                      {formatTime(alert.timestamp)}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
