import React, { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, AlertTriangle, CheckCircle, Clock } from "lucide-react";
import { PieChart, Pie, BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from "recharts";
import { fetchComplianceDashboard as fetchComplianceDashboardApi } from "@/lib/api";

const T = {
  bg: "#0f172a",
  surface: "#1e293b",
  border: "#334155",
  muted: "#64748b",
  text: "#e2e8f0",
  primary: "#3b82f6",
  accent: "#0ea5e9",
  green: "#10b981",
  amber: "#f59e0b",
  red: "#ef4444",
  redBg: "#7f1d1d",
};

// TypeScript Interfaces
interface ComplianceSummary {
  total_cases: number;
  total_alerts: number;
  risk_distribution: Record<string, number>;
  compliance_score: number;
  timestamp?: string;
  error?: string;
}

interface ScreeningRecord {
  case_id: string;
  vendor_name: string;
  status: string;
  created_at: string;
  score?: Record<string, unknown> | null;
}

interface CounterpartyLane {
  cases_screened: number;
  high_risk_vendors: number;
  pending_reviews: number;
  recent_screenings: ScreeningRecord[];
  risk_trend: Array<{ date: string; counts?: Record<string, number> | null }>;
  error?: string;
}

interface AuthorizationRecord {
  case_id: string;
  vendor_name: string;
  recommendation?: string;
  created_at: string;
}

interface ExportLane {
  total_authorizations: number;
  posture_distribution: Record<string, number>;
  recent_authorizations: AuthorizationRecord[];
  pending_license_applications: number;
  error?: string;
}

interface CentralityEntity {
  entity_id: string;
  name: string;
  type: string;
  relationship_count: number;
}

interface RiskPropagation {
  entity_id: string;
  risk_score: number;
  propagated_at: string;
}

interface CyberLane {
  entities_in_graph: number;
  relationships: number;
  communities: number;
  high_centrality_entities: CentralityEntity[];
  recent_risk_propagations: RiskPropagation[];
  error?: string;
}

interface VendorIssue {
  case_id: string;
  vendor_name: string;
  status: string;
}

interface GraphEntity {
  entity_id: string;
  name: string;
  type: string;
}

interface ComplianceGap {
  type: string;
  count: number;
  severity: string;
  description: string;
}

interface CrossLaneInsights {
  vendors_with_export_issues: VendorIssue[];
  graph_connected_high_risk: GraphEntity[];
  compliance_gaps: ComplianceGap[];
  error?: string;
}

interface ActivityItem {
  type: string;
  case_id: string;
  vendor_name: string;
  action: string;
  timestamp: string;
}

interface DashboardData {
  summary: ComplianceSummary;
  counterparty_lane: CounterpartyLane;
  export_lane: ExportLane;
  cyber_lane: CyberLane;
  cross_lane_insights: CrossLaneInsights;
  activity_feed: ActivityItem[];
}

interface LoadingState {
  isLoading: boolean;
  error: string | null;
}

// API function
async function fetchComplianceDashboard(): Promise<DashboardData> {
  return fetchComplianceDashboardApi() as Promise<DashboardData>;
}

// KPI Card Component
function KPICard({ label, value, icon: Icon, trend }: { label: string; value: string | number; icon?: React.ComponentType<any>; trend?: string }) {
  return (
    <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-4">
      <div className="flex items-start justify-between">
        <div>
          <p style={{ color: T.muted }} className="text-sm font-medium">
            {label}
          </p>
          <p style={{ color: T.text }} className="text-2xl font-bold mt-2">
            {value}
          </p>
          {trend && (
            <p style={{ color: T.green }} className="text-xs mt-1 flex items-center gap-1">
              <TrendingUp size={14} /> {trend}
            </p>
          )}
        </div>
        {Icon && <Icon size={20} style={{ color: T.accent }} />}
      </div>
    </div>
  );
}

// Compliance Score Gauge
function ComplianceScoreGauge({ score }: { score: number }) {
  let scoreColor = T.red;
  let scoreLabel = "At Risk";
  
  if (score >= 80) {
    scoreColor = T.green;
    scoreLabel = "Strong";
  } else if (score >= 60) {
    scoreColor = T.accent;
    scoreLabel = "Acceptable";
  } else if (score >= 40) {
    scoreColor = T.amber;
    scoreLabel = "Needs Work";
  }

  const circumference = 2 * Math.PI * 45;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-6">
      <p style={{ color: T.muted }} className="text-sm font-medium mb-4">
        Compliance Score
      </p>
      <div className="flex items-center justify-center">
        <div className="relative w-32 h-32">
          <svg className="w-full h-full" style={{ transform: "rotate(-90deg)" }}>
            <circle cx="64" cy="64" r="45" fill="none" stroke={T.border} strokeWidth="8" />
            <circle
              cx="64"
              cy="64"
              r="45"
              fill="none"
              stroke={scoreColor}
              strokeWidth="8"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              strokeLinecap="round"
              style={{ transition: "stroke-dashoffset 0.3s ease" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <p style={{ color: scoreColor }} className="text-3xl font-bold">
              {score.toFixed(1)}
            </p>
            <p style={{ color: T.muted }} className="text-xs">
              out of 100
            </p>
          </div>
        </div>
      </div>
      <p style={{ color: scoreColor }} className="text-center mt-4 text-sm font-medium">
        {scoreLabel}
      </p>
    </div>
  );
}

// Lane Summary Card Component
function LaneSummaryCard({
  title,
  metrics,
  chart,
  recentItems,
}: {
  title: string;
  metrics: Array<{ label: string; value: string | number }>;
  chart?: React.ReactNode;
  recentItems?: Array<{ id: string; label: string; status?: string }>;
}) {
  return (
    <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-4">
      <h3 style={{ color: T.text }} className="text-lg font-semibold mb-4">
        {title}
      </h3>
      
      <div className="grid grid-cols-2 gap-3 mb-4">
        {metrics.map((m, i) => (
          <div key={i}>
            <p style={{ color: T.muted }} className="text-xs font-medium">
              {m.label}
            </p>
            <p style={{ color: T.text }} className="text-xl font-bold">
              {m.value}
            </p>
          </div>
        ))}
      </div>

      {chart && <div className="my-4">{chart}</div>}

      {recentItems && recentItems.length > 0 && (
        <div className="mt-4 pt-4 border-t" style={{ borderTopColor: T.border }}>
          <p style={{ color: T.muted }} className="text-xs font-medium mb-2">
            Recent Activity
          </p>
          <div className="space-y-2 max-h-32 overflow-y-auto">
            {recentItems.map((item, i) => (
              <div key={i} className="text-xs flex justify-between items-start">
                <span style={{ color: T.text }} className="flex-1">
                  {item.label}
                </span>
                {item.status && (
                  <span
                    style={{
                      backgroundColor: item.status === "APPROVED" ? `${T.green}22` : `${T.amber}22`,
                      color: item.status === "APPROVED" ? T.green : T.amber,
                    }}
                    className="px-2 py-1 rounded text-xs whitespace-nowrap ml-2"
                  >
                    {item.status}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Risk Distribution Donut Chart
function RiskDistributionChart({ data }: { data: Record<string, number> }) {
  const chartData = Object.entries(data).map(([name, value]) => ({
    name: name.replace(/_/g, " ").toUpperCase(),
    value,
  }));

  const colors: Record<string, string> = {
    APPROVED: T.green,
    QUALIFIED: T.accent,
    REVIEW: T.amber,
    WATCH: T.red,
    BLOCKED: T.red,
  };

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={60}
          outerRadius={90}
          paddingAngle={2}
          dataKey="value"
        >
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={colors[entry.name] || T.muted} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{ backgroundColor: T.surface, border: `1px solid ${T.border}`, color: T.text }}
          formatter={(value: any) => [value, "Count"]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

// Export Posture Distribution Bar Chart
function PostureDistributionChart({ data }: { data: Record<string, number> }) {
  const chartData = Object.entries(data).map(([name, value]) => ({
    name: name.replace(/_/g, " ").replace(/likely /, "").toUpperCase(),
    value,
  }));

  const getColor = (name: string) => {
    if (name.includes("NLR")) return T.green;
    if (name.includes("EXCEPTION")) return T.accent;
    if (name.includes("LICENSE")) return T.amber;
    if (name.includes("ESCALATE")) return T.amber;
    if (name.includes("PROHIBITED")) return T.red;
    return T.muted;
  };

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={chartData}>
        <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
        <XAxis
          dataKey="name"
          tick={{ fill: T.muted, fontSize: 12 }}
          angle={-45}
          textAnchor="end"
          height={80}
        />
        <YAxis tick={{ fill: T.muted, fontSize: 12 }} />
        <Tooltip
          contentStyle={{ backgroundColor: T.surface, border: `1px solid ${T.border}`, color: T.text }}
          formatter={(value: any) => [value, "Count"]}
        />
        <Bar dataKey="value" fill={T.accent} radius={[8, 8, 0, 0]}>
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={getColor(entry.name)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// Risk Trend Area Chart
function RiskTrendChart({ data }: { data: Array<{ date: string; counts?: Record<string, number> | null }> }) {
  if (data.length === 0) return <p style={{ color: T.muted }} className="text-xs p-4">No trend data available</p>;

  const chartData = data.map((item) => ({
    date: new Date(item.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    BLOCKED: item.counts?.BLOCKED ?? 0,
    WATCH: item.counts?.WATCH ?? 0,
    REVIEW: item.counts?.REVIEW ?? 0,
    QUALIFIED: item.counts?.QUALIFIED ?? 0,
    APPROVED: item.counts?.APPROVED ?? 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={chartData}>
        <CartesianGrid stroke={T.border} strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: T.muted, fontSize: 11 }} />
        <YAxis tick={{ fill: T.muted, fontSize: 11 }} />
        <Tooltip
          contentStyle={{ backgroundColor: T.surface, border: `1px solid ${T.border}`, color: T.text }}
        />
        <Area type="monotone" dataKey="BLOCKED" stackId="1" stroke={T.red} fill={T.red} />
        <Area type="monotone" dataKey="WATCH" stackId="1" stroke={T.amber} fill={T.amber} />
        <Area type="monotone" dataKey="REVIEW" stackId="1" stroke={`${T.amber}aa`} fill={`${T.amber}44`} />
        <Area type="monotone" dataKey="QUALIFIED" stackId="1" stroke={T.accent} fill={T.accent} />
        <Area type="monotone" dataKey="APPROVED" stackId="1" stroke={T.green} fill={T.green} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Insights Panel
function InsightsPanel({ insights }: { insights: CrossLaneInsights }) {
  const hasIssues =
    (insights.vendors_with_export_issues?.length || 0) > 0 ||
    (insights.graph_connected_high_risk?.length || 0) > 0 ||
    (insights.compliance_gaps?.length || 0) > 0;

  return (
    <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-4">
      <h3 style={{ color: T.text }} className="text-lg font-semibold mb-4">
        Cross-Lane Insights
      </h3>

      {!hasIssues && (
        <p style={{ color: T.muted }} className="text-sm">
          No critical cross-lane issues detected.
        </p>
      )}

      {insights.vendors_with_export_issues && insights.vendors_with_export_issues.length > 0 && (
        <div className="mb-4">
          <p style={{ color: T.amber }} className="text-sm font-medium flex items-center gap-2 mb-2">
            <AlertTriangle size={16} /> Export Issues Detected
          </p>
          <div className="space-y-1">
            {insights.vendors_with_export_issues.slice(0, 3).map((v, i) => (
              <p key={i} style={{ color: T.muted }} className="text-xs">
                {v.vendor_name} ({v.status})
              </p>
            ))}
          </div>
        </div>
      )}

      {insights.graph_connected_high_risk && insights.graph_connected_high_risk.length > 0 && (
        <div className="mb-4">
          <p style={{ color: T.red }} className="text-sm font-medium flex items-center gap-2 mb-2">
            <AlertTriangle size={16} /> Graph-Connected High Risk
          </p>
          <div className="space-y-1">
            {insights.graph_connected_high_risk.slice(0, 3).map((e, i) => (
              <p key={i} style={{ color: T.muted }} className="text-xs">
                {e.name} ({e.type})
              </p>
            ))}
          </div>
        </div>
      )}

      {insights.compliance_gaps && insights.compliance_gaps.length > 0 && (
        <div>
          <p style={{ color: T.accent }} className="text-sm font-medium flex items-center gap-2 mb-2">
            <AlertTriangle size={16} /> Compliance Gaps
          </p>
          <div className="space-y-1">
            {insights.compliance_gaps.map((g, i) => (
              <p key={i} style={{ color: T.muted }} className="text-xs">
                {g.description} ({g.count})
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Activity Feed
function ActivityFeed({ items }: { items: ActivityItem[] }) {
  const getIcon = (type: string) => {
    switch (type) {
      case "decision":
        return <CheckCircle size={14} />;
      case "screening":
        return <TrendingUp size={14} />;
      case "monitoring":
        return <Clock size={14} />;
      default:
        return null;
    }
  };

  const getColor = (type: string) => {
    switch (type) {
      case "decision":
        return T.green;
      case "screening":
        return T.accent;
      case "monitoring":
        return T.amber;
      default:
        return T.muted;
    }
  };

  return (
    <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-4">
      <h3 style={{ color: T.text }} className="text-lg font-semibold mb-4">
        Activity Feed
      </h3>
      <div className="space-y-3 max-h-96 overflow-y-auto">
        {items.length === 0 ? (
          <p style={{ color: T.muted }} className="text-sm">
            No recent activity.
          </p>
        ) : (
          items.map((item, i) => (
            <div key={i} className="flex gap-3">
              <div
                style={{ color: getColor(item.type) }}
                className="mt-1 flex-shrink-0"
              >
                {getIcon(item.type)}
              </div>
              <div className="flex-1 min-w-0">
                <p style={{ color: T.text }} className="text-sm font-medium truncate">
                  {item.vendor_name}
                </p>
                <p style={{ color: T.muted }} className="text-xs">
                  {item.action}
                </p>
                <p style={{ color: T.muted }} className="text-xs">
                  {new Date(item.timestamp).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// Loading Skeleton
function DashboardSkeleton() {
  return (
    <div style={{ backgroundColor: T.bg }} className="min-h-screen p-6">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{ backgroundColor: T.surface, borderColor: T.border }}
            className="border rounded-lg p-4 h-24 animate-pulse"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{ backgroundColor: T.surface, borderColor: T.border }}
            className="border rounded-lg p-4 h-80 animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}

// Main Component
export default function ComplianceDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState<LoadingState>({ isLoading: true, error: null });

  const fetchData = async () => {
    setLoading({ isLoading: true, error: null });
    try {
      const result = await fetchComplianceDashboard();
      setData(result);
    } catch (err) {
      setLoading({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load dashboard",
      });
    } finally {
      setLoading({ isLoading: false, error: null });
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading.isLoading) {
    return <DashboardSkeleton />;
  }

  if (loading.error) {
    return (
      <div style={{ backgroundColor: T.bg }} className="min-h-screen p-6">
        <div style={{ backgroundColor: T.surface, borderColor: T.red }} className="border rounded-lg p-4">
          <p style={{ color: T.red }} className="font-medium">
            Error Loading Dashboard
          </p>
          <p style={{ color: T.muted }} className="text-sm mt-1">
            {loading.error}
          </p>
          <button
            onClick={fetchData}
            style={{ backgroundColor: T.primary, color: T.text }}
            className="mt-4 px-4 py-2 rounded text-sm font-medium hover:opacity-90 transition"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return <DashboardSkeleton />;
  }

  return (
    <div style={{ backgroundColor: T.bg, color: T.text }} className="min-h-screen p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h1 style={{ color: T.text }} className="text-3xl font-bold">
          Compliance Dashboard
        </h1>
        <button
          onClick={fetchData}
          disabled={loading.isLoading}
          style={{
            backgroundColor: T.primary,
            color: T.text,
            opacity: loading.isLoading ? 0.5 : 1,
          }}
          className="p-2 rounded hover:opacity-90 transition disabled:cursor-not-allowed flex items-center gap-2"
        >
          <RefreshCw size={18} className={loading.isLoading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Top Row: KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KPICard
          label="Total Cases"
          value={data.summary.total_cases}
          icon={CheckCircle}
        />
        <KPICard
          label="Active Alerts"
          value={data.summary.total_alerts}
          icon={AlertTriangle}
        />
        <div className="lg:col-span-2">
          <ComplianceScoreGauge score={data.summary.compliance_score} />
        </div>
      </div>

      {/* Second Row: Lane Summaries */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {/* Counterparty Lane */}
        <LaneSummaryCard
          title="Counterparty Lane"
          metrics={[
            { label: "Cases Screened", value: data.counterparty_lane.cases_screened },
            { label: "High Risk", value: data.counterparty_lane.high_risk_vendors },
            { label: "Pending", value: data.counterparty_lane.pending_reviews },
          ]}
          chart={
            data.summary.risk_distribution && Object.keys(data.summary.risk_distribution).length > 0 ? (
              <RiskDistributionChart data={data.summary.risk_distribution} />
            ) : undefined
          }
          recentItems={
            data.counterparty_lane.recent_screenings?.map((s) => ({
              id: s.case_id,
              label: s.vendor_name,
              status: s.status,
            })) || []
          }
        />

        {/* Export Lane */}
        <LaneSummaryCard
          title="Export Lane"
          metrics={[
            { label: "Authorizations", value: data.export_lane.total_authorizations },
            { label: "NLR Path", value: data.export_lane.posture_distribution.likely_nlr || 0 },
            { label: "License Req'd", value: data.export_lane.pending_license_applications },
          ]}
          chart={
            data.export_lane.posture_distribution && Object.keys(data.export_lane.posture_distribution).length > 0 ? (
              <PostureDistributionChart data={data.export_lane.posture_distribution} />
            ) : undefined
          }
          recentItems={
            data.export_lane.recent_authorizations?.map((a) => ({
              id: a.case_id,
              label: a.vendor_name,
              status: a.recommendation,
            })) || []
          }
        />

        {/* Cyber Lane */}
        <LaneSummaryCard
          title="Supply Chain Assurance"
          metrics={[
            { label: "Entities", value: data.cyber_lane.entities_in_graph },
            { label: "Relationships", value: data.cyber_lane.relationships },
            { label: "Communities", value: data.cyber_lane.communities },
          ]}
          recentItems={
            data.cyber_lane.high_centrality_entities?.map((e) => ({
              id: e.entity_id,
              label: e.name,
              status: `${e.relationship_count} rels`,
            })) || []
          }
        />
      </div>

      {/* Risk Trend Chart */}
      {data.counterparty_lane.risk_trend && data.counterparty_lane.risk_trend.length > 0 && (
        <div style={{ backgroundColor: T.surface, borderColor: T.border }} className="border rounded-lg p-4 mb-6">
          <h3 style={{ color: T.text }} className="text-lg font-semibold mb-4">
            Risk Trend (Last 30 Days)
          </h3>
          <RiskTrendChart data={data.counterparty_lane.risk_trend} />
        </div>
      )}

      {/* Bottom Row: Insights & Activity Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <InsightsPanel insights={data.cross_lane_insights} />
        <ActivityFeed items={data.activity_feed} />
      </div>

      {/* Footer */}
      <div style={{ color: T.muted }} className="text-xs mt-6 text-center">
        Last updated: {data.summary.timestamp ? new Date(data.summary.timestamp).toLocaleString() : "—"}
      </div>
    </div>
  );
}
