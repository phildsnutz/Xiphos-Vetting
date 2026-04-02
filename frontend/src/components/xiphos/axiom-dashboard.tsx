import { useState } from "react";
import { T, FS } from "@/lib/tokens";
import { Search, Eye, Bell } from "lucide-react";
import { AxiomSearchPanel } from "./axiom-search-panel";
import { AxiomWatchlist } from "./axiom-watchlist";
import { AxiomAlerts } from "./axiom-alerts";

type TabId = "search" | "watchlist" | "alerts";

export function AxiomDashboard() {
  const [activeTab, setActiveTab] = useState<TabId>("search");

  const tabs: Array<{
    id: TabId;
    label: string;
    icon: React.ReactNode;
    description: string;
  }> = [
    {
      id: "search",
      label: "Search",
      icon: <Search size={14} />,
      description: "Run agent-driven intelligence searches",
    },
    {
      id: "watchlist",
      label: "Watchlist",
      icon: <Eye size={14} />,
      description: "Monitor persistent targets",
    },
    {
      id: "alerts",
      label: "Alerts",
      icon: <Bell size={14} />,
      description: "View monitoring alerts",
    },
  ];

  return (
    <div className="flex flex-col gap-4" style={{ height: "100%", overflow: "auto" }}>
      {/* Header */}
      <div className="shrink-0" style={{ padding: "16px", background: T.surface, borderBottom: `1px solid ${T.border}` }}>
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <h2 style={{ fontSize: FS.base * 1.5, fontWeight: 700, color: T.text, marginBottom: 6 }}>
              AXIOM Intelligence
            </h2>
            <p style={{ fontSize: FS.sm, color: T.muted }}>
              Agent-driven monitoring and discovery platform
            </p>
          </div>
        </div>
      </div>

      {/* Tab navigation */}
      <div
        className="flex items-center gap-1 px-4 shrink-0 overflow-x-auto"
        style={{ borderBottom: `1px solid ${T.border}` }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="flex items-center gap-1.5 px-3 py-2.5 cursor-pointer border-b-2 whitespace-nowrap"
            style={{
              fontSize: FS.sm,
              fontWeight: activeTab === tab.id ? 600 : 500,
              borderColor: activeTab === tab.id ? T.accent : "transparent",
              color: activeTab === tab.id ? T.accent : T.muted,
              background: "transparent",
              transition: "all 0.2s ease",
            }}
            title={tab.description}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div
        className="flex-1 overflow-auto px-4 py-4"
        style={{ minHeight: 0 }}
      >
        {activeTab === "search" && <AxiomSearchPanel />}
        {activeTab === "watchlist" && <AxiomWatchlist />}
        {activeTab === "alerts" && <AxiomAlerts />}
      </div>
    </div>
  );
}
