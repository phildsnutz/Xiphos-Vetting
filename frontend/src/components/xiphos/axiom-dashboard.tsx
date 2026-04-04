import { useState } from "react";
import { T, FS, PAD, SP, O } from "@/lib/tokens";
import { Search, Eye, Bell } from "lucide-react";
import { AxiomSearchPanel } from "./axiom-search-panel";
import { AxiomWatchlist } from "./axiom-watchlist";
import { AxiomAlerts } from "./axiom-alerts";
import { PanelHeader, StatusPill } from "./shell-primitives";

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
      label: "Collection",
      icon: <Search size={14} />,
      description: "Run a focused collection pass against the current gap.",
    },
    {
      id: "watchlist",
      label: "Watch",
      icon: <Eye size={14} />,
      description: "Keep persistent targets warm between dossier pulls.",
    },
    {
      id: "alerts",
      label: "Alerts",
      icon: <Bell size={14} />,
      description: "Escalate drift that materially changed the picture.",
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
          background: T.surface,
          border: `1px solid ${T.border}`,
        }}
      >
        <PanelHeader
          eyebrow="AXIOM"
          title={
            <span style={{ fontSize: FS.xl, fontWeight: 800, letterSpacing: "-0.04em", color: T.text }}>
              Case-officer workspace for collection, drift, and gap closure.
            </span>
          }
          description="Work the unknowns. Turn weak public residue into structured evidence, keep watch on the right targets, and feed the graph only when the signal is strong enough."
          meta={
            <>
              <StatusPill tone="info">Collection closes gaps</StatusPill>
              <StatusPill tone="neutral">Watch keeps targets warm</StatusPill>
              <StatusPill tone="warning">Alerts escalate drift</StatusPill>
            </>
          }
        />
      </div>

      <div
        className="flex items-center gap-2 px-4 shrink-0 overflow-x-auto"
        style={{ paddingBottom: SP.xs }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            aria-label={`Open AXIOM ${tab.label.toLowerCase()} tab`}
            aria-pressed={activeTab === tab.id}
            className="helios-focus-ring flex items-center gap-1.5 whitespace-nowrap rounded-full cursor-pointer"
            style={{
              padding: PAD.default,
              fontSize: FS.sm,
              fontWeight: activeTab === tab.id ? 700 : 500,
              border: `1px solid ${activeTab === tab.id ? `${T.accent}${O["30"]}` : T.border}`,
              color: activeTab === tab.id ? T.accent : T.textSecondary,
              background: activeTab === tab.id ? `${T.accent}${O["08"]}` : T.surface,
              transition: "all 0.2s ease",
            }}
            title={tab.description}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <div className="px-4 shrink-0" style={{ marginTop: -SP.xs }}>
        <div
          style={{
            fontSize: FS.sm,
            color: T.textSecondary,
            padding: `0 ${SP.xs}px`,
          }}
        >
          {tabs.find((tab) => tab.id === activeTab)?.description}
        </div>
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
