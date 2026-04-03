/**
 * Cmd+K / Ctrl+K global command palette.
 * Fuzzy search across cases, navigation, and actions.
 * Portal-based with backdrop blur and focus trap.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search, ChevronRight, Zap, FileText, Navigation } from "lucide-react";
import { T, SP, FS, PAD, MOTION, O } from "@/lib/tokens";

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (tab: string) => void;
  onSelectCase: (caseId: string) => void;
  cases: Array<{ id: string; name: string; vendor?: string; tier?: string }>;
  currentCaseId?: string;
  onAction?: (action: string) => void;
}

interface CommandItem {
  id: string;
  type: "navigation" | "case" | "action";
  label: string;
  description?: string;
  icon?: React.ReactNode;
  badge?: string;
  action?: () => void;
}

/**
 * Simple fuzzy search: returns true if needle matches haystack.
 * Matches contiguous characters in order.
 */
function fuzzyMatch(needle: string, haystack: string): boolean {
  const n = needle.toLowerCase();
  const h = haystack.toLowerCase();
  let j = 0;

  for (let i = 0; i < n.length; i++) {
    const char = n[i];
    j = h.indexOf(char, j);
    if (j === -1) return false;
    j++;
  }

  return true;
}

/**
 * Calculate match score for sorting: higher is better.
 * Prefers matches at the start and shorter strings.
 */
function fuzzyScore(needle: string, haystack: string): number {
  const n = needle.toLowerCase();
  const h = haystack.toLowerCase();

  let score = 0;
  let j = 0;

  for (let i = 0; i < n.length; i++) {
    j = h.indexOf(n[i], j);
    if (j === -1) return -1;

    // Bonus for match at start
    if (j === 0) score += 10;
    // Bonus for match after space or uppercase
    if (j > 0 && (h[j - 1] === " " || h[j - 1].toUpperCase() === h[j - 1])) score += 5;

    j++;
  }

  // Penalize long strings
  score -= haystack.length * 0.05;

  return score;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onSelectCase,
  cases,
  currentCaseId,
  onAction,
}) => {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const sorted = useMemo(() => {
    const navigationItems: CommandItem[] = [
      { id: "nav-portfolio", type: "navigation", label: "Portfolio", description: "View all cases", icon: <Navigation size={16} />, action: () => { onNavigate("portfolio"); onClose(); } },
      { id: "nav-helios", type: "navigation", label: "New Assessment", description: "Start a new assessment", icon: <FileText size={16} />, action: () => { onNavigate("helios"); onClose(); } },
      { id: "nav-graph", type: "navigation", label: "Knowledge Graph", description: "Explore relationships", icon: <Navigation size={16} />, action: () => { onNavigate("graph"); onClose(); } },
      { id: "nav-threads", type: "navigation", label: "Mission Threads", description: "View active threads", icon: <Navigation size={16} />, action: () => { onNavigate("threads"); onClose(); } },
      { id: "nav-axiom", type: "navigation", label: "AXIOM Intelligence", description: "AI-powered analysis", icon: <Zap size={16} />, action: () => { onNavigate("axiom"); onClose(); } },
      { id: "nav-dashboard", type: "navigation", label: "Compliance Dashboard", description: "View compliance status", icon: <Navigation size={16} />, action: () => { onNavigate("dashboard"); onClose(); } },
      { id: "nav-admin", type: "navigation", label: "Admin", description: "Administrator tools", icon: <Navigation size={16} />, action: () => { onNavigate("admin"); onClose(); } },
    ];
    const actionItems: CommandItem[] = currentCaseId
      ? [
          { id: "action-dossier", type: "action", label: "Generate Dossier", description: "Create HTML dossier", icon: <FileText size={16} />, action: () => { onAction?.("generate-dossier"); onClose(); } },
          { id: "action-enrich", type: "action", label: "Run Enrichment", description: "Fetch latest data", icon: <Zap size={16} />, action: () => { onAction?.("run-enrichment"); onClose(); } },
          { id: "action-analyze", type: "action", label: "Run AI Analysis", description: "Analyze with AXIOM", icon: <Zap size={16} />, action: () => { onAction?.("run-analysis"); onClose(); } },
        ]
      : [];
    const caseItems: CommandItem[] = cases.map((c) => ({
      id: `case-${c.id}`,
      type: "case",
      label: c.name,
      description: c.vendor ? `${c.vendor}${c.tier ? ` • ${c.tier}` : ""}` : undefined,
      badge: c.id === currentCaseId ? "selected" : undefined,
      action: () => { onSelectCase(c.id); onClose(); },
    }));
    const allItems = [...navigationItems, ...actionItems, ...caseItems];
    const filtered = query
      ? allItems.filter((item) => fuzzyMatch(query, item.label) || (item.description && fuzzyMatch(query, item.description)))
      : allItems;

    return [...filtered].sort((a, b) => {
      const scoreA = fuzzyScore(query, a.label);
      const scoreB = fuzzyScore(query, b.label);
      return scoreB - scoreA;
    });
  }, [cases, currentCaseId, onAction, onClose, onNavigate, onSelectCase, query]);

  const grouped = useMemo(() => {
    const nav = sorted.filter((i) => i.type === "navigation");
    const act = sorted.filter((i) => i.type === "action");
    const cse = sorted.filter((i) => i.type === "case");

    const result: Array<{ category: string; items: CommandItem[] }> = [];
    if (nav.length) result.push({ category: "Navigation", items: nav });
    if (act.length) result.push({ category: "Actions", items: act });
    if (cse.length) result.push({ category: "Cases", items: cse });

    return result;
  }, [sorted]);

  // Flatten for keyboard nav
  const flatItems = grouped.flatMap((g) => g.items);

  // Focus trap & keyboard nav
  useEffect(() => {
    if (!isOpen) return;

    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }

      if (e.key === "ArrowDown") {
        if (flatItems.length === 0) return;
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % flatItems.length);
        return;
      }

      if (e.key === "ArrowUp") {
        if (flatItems.length === 0) return;
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + flatItems.length) % flatItems.length);
        return;
      }

      if (e.key === "Enter") {
        e.preventDefault();
        const selected = flatItems[selectedIndex];
        if (selected?.action) {
          selected.action();
        }
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    inputRef.current?.focus();

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [isOpen, flatItems, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden="true"
        style={{
          position: "fixed",
          inset: 0,
          backgroundColor: `#000000${O["50"]}`,
          backdropFilter: `blur(${SP.xs}px)`,
          zIndex: 999,
          animation: `fadeIn ${MOTION.fast} ${MOTION.easing}`,
        }}
        onClick={onClose}
      />

      {/* Container */}
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label="Global command palette"
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "90%",
          maxWidth: `${SP.xxxl * 12.5}px`,
          maxHeight: "70vh",
          backgroundColor: T.surface,
          border: `1px solid ${T.border}`,
          borderRadius: SP.md,
          boxShadow: `0 ${SP.xl - SP.sm}px ${SP.xxxl + SP.md}px #000000${O["50"]}`,
          display: "flex",
          flexDirection: "column",
          zIndex: 1000,
          animation: `slideUp ${MOTION.fast} ${MOTION.easing}`,
        }}
      >
        {/* Search input */}
        <div style={{ padding: PAD.default, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: SP.sm }}>
          <Search size={18} color={T.textSecondary} style={{ flexShrink: 0 }} />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search cases, navigate, or run actions..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            aria-label="Search commands, navigation, and cases"
            style={{
              flex: 1,
              backgroundColor: "transparent",
              border: "none",
              color: T.text,
              fontSize: FS.base,
              outline: "none",
              fontFamily: 'inherit',
            }}
          />
          <span style={{ fontSize: FS.xs, color: T.textTertiary }}>ESC</span>
        </div>

        {/* Results */}
        <div style={{ overflowY: "auto", flex: 1, padding: SP.sm }}>
          {flatItems.length === 0 ? (
            <div style={{ padding: SP.lg, textAlign: "center", color: T.textSecondary, fontSize: FS.sm }}>
              No results for "{query}"
            </div>
          ) : (
            grouped.map((group, groupIdx) => (
              <div key={group.category}>
                {/* Category header */}
                <div
                  style={{
                    padding: `${SP.sm}px ${SP.md}px`,
                    fontSize: FS.xs,
                    color: T.textTertiary,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    marginTop: groupIdx > 0 ? SP.md : 0,
                  }}
                >
                  {group.category}
                </div>

                {/* Items */}
                {group.items.map((item) => {
                  const globalIdx = flatItems.indexOf(item);
                  const isSelected = globalIdx === selectedIndex;

                  return (
                    <div
                      key={item.id}
                      role="button"
                      tabIndex={0}
                      aria-label={item.description ? `${item.label}. ${item.description}` : item.label}
                      aria-selected={isSelected}
                      onClick={() => {
                        setSelectedIndex(globalIdx);
                        item.action?.();
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedIndex(globalIdx);
                          item.action?.();
                        }
                      }}
                      style={{
                        padding: SP.md,
                        margin: `${SP.xs / 2}px 0`,
                        backgroundColor: isSelected ? T.surfaceElevated : "transparent",
                        border: isSelected ? `1px solid ${T.borderActive}` : "1px solid transparent",
                        borderRadius: SP.sm - 2,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        transition: `all ${MOTION.fast} ${MOTION.easing}`,
                      }}
                      onMouseEnter={() => setSelectedIndex(globalIdx)}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: SP.md, flex: 1, minWidth: 0 }}>
                        {item.icon && (
                          <div style={{ color: T.textSecondary, flexShrink: 0 }}>
                            {item.icon}
                          </div>
                        )}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ color: T.text, fontSize: FS.base, fontWeight: 500 }}>{item.label}</div>
                          {item.description && (
                            <div style={{ color: T.textSecondary, fontSize: FS.sm, marginTop: SP.xs / 2 }}>
                              {item.description}
                            </div>
                          )}
                        </div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: SP.sm, flexShrink: 0 }}>
                        {item.badge && (
                          <span style={{ fontSize: FS.xs, color: T.accent, fontWeight: 600 }}>
                            {item.badge.toUpperCase()}
                          </span>
                        )}
                        <ChevronRight size={16} color={T.textTertiary} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: SP.md,
            borderTop: `1px solid ${T.border}`,
            fontSize: FS.xs,
            color: T.textTertiary,
            display: "flex",
            gap: SP.lg,
            justifyContent: "flex-end",
          }}
        >
          <span>
            <kbd style={{ fontSize: FS.xs, color: T.textSecondary }}>↑↓</kbd> Navigate
          </span>
          <span>
            <kbd style={{ fontSize: FS.xs, color: T.textSecondary }}>Enter</kbd> Select
          </span>
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translate(-50%, -45%);
          }
          to {
            opacity: 1;
            transform: translate(-50%, -50%);
          }
        }
      `}</style>
    </>
  );
};
