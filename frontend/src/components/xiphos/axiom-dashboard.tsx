import { useState } from "react";
import { T, FS, PAD, SP } from "@/lib/tokens";
import { Search, Eye, Bell } from "lucide-react";
import { AxiomSearchPanel } from "./axiom-search-panel";
import { AxiomWatchlist } from "./axiom-watchlist";
import { AxiomAlerts } from "./axiom-alerts";
import { SectionEyebrow } from "./shell-primitives";

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
      <div
        className="shrink-0 glass-card"
        style={{
          padding: PAD.comfortable,
          borderRadius: 18,
          margin: `${SP.md}px ${SP.md}px 0`,
          display: "flex",
          flexDirection: "column",
          gap: SP.sm,
        }}
      >
        <SectionEyebrow>AXIOM</SectionEyebrow>
        <h1 style={{ fontSize: FS.xl, fontWeight: 800, color: T.text, margin: 0, letterSpacing: "-0.04em" }}>
          Close dossier gaps like a case officer, not a search box.
        </h1>
        <p style={{ fontSize: FS.sm, color: T.textSecondary, margin: 0, lineHeight: 1.6, maxWidth: 880 }}>
          AXIOM should develop collection hypotheses, turn weak public signal into structured evidence, and keep the graph warm as the world changes.
        </p>
      </div>

      <div
        className="flex items-center gap-1 px-4 shrink-0 overflow-x-auto"
        style={{ borderBottom: `1px solid ${T.border}`, paddingBottom: SP.sm }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            aria-label={`Open AXIOM ${tab.label.toLowerCase()} tab`}
            aria-pressed={activeTab === tab.id}
            className="helios-focus-ring flex items-center gap-1.5 px-3 py-2.5 cursor-pointer border-b-2 whitespace-nowrap rounded-t-xl"
            style={{
              fontSize: FS.sm,
              fontWeight: activeTab === tab.id ? 700 : 500,
              borderColor: activeTab === tab.id ? T.accent : "transparent",
              color: activeTab === tab.id ? T.accent : T.textSecondary,
              background: activeTab === tab.id ? `${T.accent}12` : "transparent",
              transition: "all 0.2s ease",
            }}
            title={tab.description}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

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
