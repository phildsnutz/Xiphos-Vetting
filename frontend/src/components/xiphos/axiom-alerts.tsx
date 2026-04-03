import { useCallback, useEffect, useState } from "react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import { AlertCircle, TrendingUp, TrendingDown, Users, Info } from "lucide-react";
import { getToken } from "@/lib/auth";
import { EmptyPanel, InlineMessage, LoadingPanel, SectionEyebrow } from "./shell-primitives";

type AlertType = "new_sub" | "departed_sub" | "hiring_surge" | "position_drop" | "activity_change" | "initial_scan";
type AlertPriority = "critical" | "high" | "medium" | "low";

interface RawAlertItem {
  id: string;
  type?: AlertType;
  alert_type?: AlertType;
  severity?: string;
  priority?: AlertPriority;
  target?: string;
  title?: string;
  details?: string;
  description?: string;
  timestamp?: string;
  created_at?: string;
  watchlist_entry_id?: string;
  watchlist_id?: string;
}

interface AlertItem {
  id: string;
  type: AlertType;
  priority: AlertPriority;
  target: string;
  title: string;
  details: string;
  timestamp: string;
  watchlist_entry_id?: string;
}

interface AxiomAlertsProps {
  onAlertsChange?: (alerts: AlertItem[]) => void;
}

function normalizePriority(value?: string): AlertPriority {
  if (value === "critical" || value === "high" || value === "medium" || value === "low") {
    return value;
  }
  if (value === "info") {
    return "low";
  }
  return "low";
}

function normalizeAlertType(value?: string): AlertType {
  if (
    value === "new_sub" ||
    value === "departed_sub" ||
    value === "hiring_surge" ||
    value === "position_drop" ||
    value === "activity_change" ||
    value === "initial_scan"
  ) {
    return value;
  }
  return "activity_change";
}

function normalizeAlert(raw: RawAlertItem): AlertItem {
  return {
    id: raw.id,
    type: normalizeAlertType(raw.type || raw.alert_type),
    priority: normalizePriority(raw.priority || raw.severity),
    target: raw.target || "Unknown target",
    title: raw.title || "Alert",
    details: raw.details || raw.description || "No details available",
    timestamp: raw.timestamp || raw.created_at || "",
    watchlist_entry_id: raw.watchlist_entry_id || raw.watchlist_id,
  };
}

export function AxiomAlerts({ onAlertsChange }: AxiomAlertsProps) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [selectedTypes, setSelectedTypes] = useState<AlertType[]>([
    "new_sub",
    "departed_sub",
    "hiring_surge",
    "position_drop",
    "initial_scan",
  ]);
  const [selectedPriorities, setSelectedPriorities] = useState<AlertPriority[]>(["critical", "high", "medium", "low"]);

  const loadAlerts = useCallback(async () => {
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

      const data = (await response.json()) as { alerts?: RawAlertItem[] };
      const normalized = (data.alerts || []).map(normalizeAlert);
      setAlerts(normalized);
      onAlertsChange?.(normalized);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [onAlertsChange]);

  useEffect(() => {
    void loadAlerts();
    const interval = setInterval(loadAlerts, 30000);
    return () => clearInterval(interval);
  }, [loadAlerts]);

  const filteredAlerts = alerts.filter(
    (alert) => selectedTypes.includes(alert.type) && selectedPriorities.includes(alert.priority),
  );

  const getAlertColor = (type: AlertType) => {
    switch (type) {
      case "new_sub":
        return { icon: Users, color: T.green, bg: `${T.green}15` };
      case "departed_sub":
        return { icon: TrendingDown, color: T.amber, bg: `${T.amber}15` };
      case "hiring_surge":
        return { icon: TrendingUp, color: T.accent, bg: `${T.accent}15` };
      case "position_drop":
        return { icon: TrendingDown, color: T.red, bg: `${T.red}15` };
      case "initial_scan":
        return { icon: Info, color: T.accent, bg: `${T.accent}15` };
      default:
        return { icon: AlertCircle, color: T.muted, bg: `${T.muted}15` };
    }
  };

  const getPriorityColor = (priority: AlertPriority) => {
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

    if (Number.isNaN(date.getTime())) return timestamp || "unknown";
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  const alertTypeLabel = (type: AlertType) => {
    const labels: Record<AlertType, string> = {
      new_sub: "New Entity",
      departed_sub: "Departed Entity",
      hiring_surge: "Hiring Surge",
      position_drop: "Position Drop",
      activity_change: "Activity Change",
      initial_scan: "Initial Scan",
    };
    return labels[type];
  };

  return (
    <div
      className="flex flex-col gap-4 rounded-lg"
      style={{ background: T.surface, border: `1px solid ${T.border}`, padding: PAD.default }}
    >
      <div className="flex items-center justify-between">
        <div>
          <SectionEyebrow>Alerts</SectionEyebrow>
          <h2 style={{ fontSize: FS.base, fontWeight: 700, color: T.text, margin: `${SP.xs}px 0 0` }}>Monitoring signals that changed</h2>
        </div>
        <div
          style={{
            fontSize: FS.sm,
            fontWeight: 600,
            color: T.accent,
            background: `${T.accent}20`,
            padding: PAD.tight,
            borderRadius: SP.xs,
          }}
        >
          {filteredAlerts.length}
        </div>
      </div>

      {error ? <InlineMessage tone="danger" title="Alert load failed" message={error} icon={AlertCircle} /> : null}

      <div className="space-y-3 rounded-lg" style={{ background: T.bg, border: `1px solid ${T.border}`, padding: PAD.default }}>
        <div>
          <label style={{ fontSize: FS.sm, fontWeight: 500, color: T.muted, marginBottom: SP.sm, display: "block" }}>
            Alert Types
          </label>
          <div className="flex flex-wrap gap-2">
            {(["new_sub", "departed_sub", "hiring_surge", "position_drop", "initial_scan"] as AlertType[]).map((type) => (
              <button
                key={type}
                type="button"
                aria-label={`Toggle ${alertTypeLabel(type)} alerts`}
                aria-pressed={selectedTypes.includes(type)}
                onClick={() => {
                  if (selectedTypes.includes(type)) {
                    setSelectedTypes(selectedTypes.filter((selected) => selected !== type));
                  } else {
                    setSelectedTypes([...selectedTypes, type]);
                  }
                }}
                className="rounded cursor-pointer font-medium"
                style={{
                  padding: PAD.tight,
                  fontSize: FS.sm,
                  background: selectedTypes.includes(type) ? T.accent : T.surface,
                  border: `1px solid ${selectedTypes.includes(type) ? T.accent : T.border}`,
                  color: selectedTypes.includes(type) ? T.textInverse : T.muted,
                }}
              >
                {alertTypeLabel(type)}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: FS.sm, fontWeight: 500, color: T.muted, marginBottom: SP.sm, display: "block" }}>
            Priority
          </label>
          <div className="flex flex-wrap gap-2">
            {(["critical", "high", "medium", "low"] as AlertPriority[]).map((priority) => (
              <button
                key={priority}
                type="button"
                aria-label={`Toggle ${priority} priority alerts`}
                aria-pressed={selectedPriorities.includes(priority)}
                onClick={() => {
                  if (selectedPriorities.includes(priority)) {
                    setSelectedPriorities(selectedPriorities.filter((selected) => selected !== priority));
                  } else {
                    setSelectedPriorities([...selectedPriorities, priority]);
                  }
                }}
                className="rounded cursor-pointer font-medium"
                style={{
                  padding: PAD.tight,
                  fontSize: FS.sm,
                  background: selectedPriorities.includes(priority) ? getPriorityColor(priority) : T.surface,
                  border: `1px solid ${selectedPriorities.includes(priority) ? getPriorityColor(priority) : T.border}`,
                  color: selectedPriorities.includes(priority) ? T.textInverse : T.muted,
                }}
              >
                {priority}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? <LoadingPanel label="Loading alerts" detail="Refreshing AXIOM monitoring output for the current watchlist." /> : null}

      {!isLoading && filteredAlerts.length === 0 ? (
        <EmptyPanel
          title="No alerts match your filters"
          description={alerts.length === 0 ? "AXIOM has not generated any watchlist alerts yet." : "Try widening the alert-type or priority filters."}
          icon={Info}
        />
      ) : null}

      {!isLoading && filteredAlerts.length > 0 && (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {filteredAlerts.map((alert) => {
            const { icon: IconComponent, color, bg } = getAlertColor(alert.type);
            return (
              <div
                key={alert.id}
                className="rounded-lg border"
                style={{
                  background: bg,
                  border: `1px solid ${color}`,
                  padding: PAD.default,
                }}
              >
                <div className="flex gap-3">
                  <div style={{ flexShrink: 0, marginTop: SP.xs / 2 }}>
                    <IconComponent size={SP.md + SP.xs} color={color} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <div>
                        <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>{alert.title}</div>
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.xs / 2 }}>{alert.target}</div>
                      </div>
                      <div style={{ fontSize: FS.sm, color: getPriorityColor(alert.priority), fontWeight: 600, flexShrink: 0 }}>
                        {alert.priority}
                      </div>
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: SP.xs, lineHeight: 1.4 }}>
                      {alert.details}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.xs }}>
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
