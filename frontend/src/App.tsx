import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Shield, Search, Wifi, WifiOff, LogOut, User, Settings, MessageSquare, Grid3X3, LayoutDashboard, Network } from "lucide-react";
import { T, FS, FX } from "@/lib/tokens";
import { CaseDetail } from "@/components/xiphos/case-detail";
import { LoginScreen } from "@/components/xiphos/login-screen";
import { AdminPanel } from "@/components/xiphos/admin-panel";
import { HeliosLanding } from "@/components/xiphos/helios-landing";
import { MissionThreadsScreen } from "@/components/xiphos/mission-threads-screen";
import { PortfolioScreen } from "@/components/xiphos/portfolio-screen";
import { DemoCompare } from "@/components/xiphos/demo-compare";
import { GraphIntelligenceDashboard } from "@/components/xiphos/graph-intelligence-dashboard";
import ComplianceDashboard from "@/components/xiphos/compliance-dashboard";
import { ErrorBoundary } from "@/components/xiphos/error-boundary";
import { buildProtectedUrl, rescore, generateDossier as apiDossier, fetchCases, setAuthErrorHandler, submitBetaFeedback, trackBetaEvent } from "@/lib/api";
import { openDossier } from "@/lib/dossier";
import { checkAuthEnabled, getToken, getUser, clearSession, roleLabel, hasPermission } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";
import type { VettingCase, Calibration, ScreeningPolicyBasis, ScoringPolicyMetadata } from "@/lib/types";
import { parseTier, tierToRisk } from "@/lib/tokens";
import { WORKFLOW_LANE_META, portfolioDisposition, workflowLaneForCase } from "@/components/xiphos/portfolio-utils";
import type { WorkflowLane } from "@/components/xiphos/portfolio-utils";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

function mapCalibration(apiCal: Record<string, unknown>): Calibration {
  const cal = apiCal as {
    calibrated_probability: number;
    calibrated_tier: string;
    combined_tier?: string;
    interval: { lower: number; upper: number; coverage?: number };
    contributions: Array<{
      factor: string; raw_score: number; confidence?: number; weight?: number;
      signed_contribution: number; description: string;
    }>;
    hard_stop_decisions: Array<{ trigger: string; explanation: string; confidence: number }>;
    soft_flags: Array<{ trigger: string; explanation: string; confidence: number }>;
    narratives: { findings: string[] };
    marginal_information_values: Array<{
      recommendation?: string; factor?: string;
      expected_info_gain_pp?: number; expected_shift_pp?: number;
      tier_change_probability: number;
    }>;
    // v5.0 DoD fields
    is_dod_eligible?: boolean;
    is_dod_qualified?: boolean;
    program_recommendation?: string;
    regulatory_status?: string;
    regulatory_findings?: Array<Record<string, unknown>>;
    sensitivity_context?: string;
    supply_chain_tier?: number;
    model_version?: string;
    policy?: ScoringPolicyMetadata;
    screening?: {
      matched: boolean;
      best_score: number;
      best_raw_jw: number;
      matched_name: string;
      db_label: string;
      screening_ms: number;
      match_details?: Record<string, unknown>;
      policy_basis?: ScreeningPolicyBasis;
    };
  };

  const asNumber = (value: unknown, fallback = 0): number =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback;
  const contributions = Array.isArray(cal.contributions) ? cal.contributions : [];
  const hardStops = Array.isArray(cal.hard_stop_decisions) ? cal.hard_stop_decisions : [];
  const softFlags = Array.isArray(cal.soft_flags) ? cal.soft_flags : [];
  const findings = Array.isArray(cal.narratives?.findings) ? cal.narratives.findings : [];
  const marginalInformationValues = Array.isArray(cal.marginal_information_values)
    ? cal.marginal_information_values
    : [];
  const interval = cal.interval && typeof cal.interval === "object"
    ? cal.interval
    : { lower: 0, upper: 0, coverage: 0 };

  const meanConf = contributions.length > 0
    ? contributions.reduce((s, c) => s + asNumber(c.confidence ?? c.weight), 0) / contributions.length : 0;

  return {
    p: asNumber(cal.calibrated_probability),
    tier: parseTier(cal.combined_tier ?? cal.calibrated_tier),
    combinedTier: parseTier(cal.combined_tier ?? cal.calibrated_tier),
    lo: asNumber(interval.lower),
    hi: asNumber(interval.upper),
    cov: asNumber(interval.coverage),
    mc: meanConf,
    ct: contributions.map((c) => ({
      n: c.factor, raw: asNumber(c.raw_score), c: asNumber(c.confidence ?? c.weight), s: asNumber(c.signed_contribution), d: c.description,
    })),
    stops: hardStops.map((h) => ({ t: h.trigger, x: h.explanation, c: asNumber(h.confidence) })),
    flags: softFlags.map((f) => ({ t: f.trigger, x: f.explanation, c: asNumber(f.confidence) })),
    finds: findings,
    miv: marginalInformationValues.map((m) => ({
      t: m.recommendation ?? m.factor ?? "", i: asNumber(m.expected_info_gain_pp ?? m.expected_shift_pp), tp: asNumber(m.tier_change_probability),
    })),
    // v5.0 DoD layer
    dodEligible: cal.is_dod_eligible,
    dodQualified: cal.is_dod_qualified,
    recommendation: cal.program_recommendation,
    regulatoryStatus: cal.regulatory_status,
    regulatoryFindings: cal.regulatory_findings,
    sensitivityContext: cal.sensitivity_context,
    supplyChainTier: cal.supply_chain_tier,
    modelVersion: cal.model_version,
    policy: cal.policy,
    screening: cal.screening ? {
      matched: cal.screening.matched,
      bestScore: cal.screening.best_score,
      bestRawJw: cal.screening.best_raw_jw,
      matchedName: cal.screening.matched_name,
      dbLabel: cal.screening.db_label,
      screeningMs: cal.screening.screening_ms,
      matchDetails: cal.screening.match_details,
      policyBasis: cal.screening.policy_basis,
    } : undefined,
  };
}

/** Convert an API case to our internal VettingCase */
function apiCaseToVetting(ac: { id: string; vendor_name: string; status: string; created_at: string; score: Record<string, unknown> | null; profile?: string; program?: string; country?: string; workflow_lane?: "counterparty" | "cyber" | "export" }): VettingCase | null {
  if (!ac.score) return null;
  const score = ac.score as { composite_score: number; is_hard_stop: boolean; calibrated: Record<string, unknown> };
  if (!score.calibrated) return null;
  const cal = mapCalibration(score.calibrated);
  const mc = cal.ct.length > 0 ? cal.ct.reduce((s, c) => s + c.c, 0) / cal.ct.length : 0;
  return {
    id: ac.id,
    name: ac.vendor_name,
    cc: ac.country ?? "",
    date: ac.created_at,
    rl: tierToRisk(cal.tier),
    sc: score.composite_score,
    conf: mc,
    cal,
    profile: ac.profile,
    program: ac.program,
    workflowLane: ac.workflow_lane,
    ...(!ac.country ? (() => {
      const geoCt = cal.ct.find((c) => c.n === "Geography");
      const ccMatch = geoCt?.d?.match(/\(([A-Z]{2})\)/);
      return ccMatch ? { cc: ccMatch[1] } : {};
    })() : {}),
  };
}

type Tab = "dashboard" | "helios" | "portfolio" | "threads" | "graph" | "admin";

function shellPriorityRank(disposition: ReturnType<typeof portfolioDisposition>): number {
  if (disposition === "blocked") return 3;
  if (disposition === "review") return 2;
  if (disposition === "qualified") return 1;
  return 0;
}

export default function App() {
  const isFileMode = window.location.protocol === "file:";
  const demoEnabled = import.meta.env.VITE_ENABLE_PUBLIC_DEMO === "true";

  // Auth state
  const [authRequired, setAuthRequired] = useState<boolean | null>(isFileMode ? false : null);
  const [user, setUser] = useState<AuthUser | null>(getUser());
  const [showUserMenu, setShowUserMenu] = useState(false);

  // App state -- start empty; cases load from backend after login
  const [cases, setCases] = useState<VettingCase[]>([]);
  const [selected, setSelected] = useState<VettingCase | null>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("portfolio");
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(isFileMode ? false : null);
  const [workflowMode, setWorkflowMode] = useState<WorkflowLane>("counterparty");
  const [showFeedbackDialog, setShowFeedbackDialog] = useState(false);
  const [feedbackCategory, setFeedbackCategory] = useState<"bug" | "confusion" | "request" | "general">("bug");
  const [feedbackSeverity, setFeedbackSeverity] = useState<"low" | "medium" | "high">("medium");
  const [feedbackSummary, setFeedbackSummary] = useState("");
  const [feedbackDetails, setFeedbackDetails] = useState("");
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [feedbackSuccess, setFeedbackSuccess] = useState<string | null>(null);
  const lastModeEventRef = useRef<string>("");
  const lastScreenEventRef = useRef<string>("");
  const homeTabInitializedRef = useRef(false);
  // onboarding dismissed state removed in UI redesign

  const refreshCases = useCallback(async (limit = 200) => {
    const apiCases = await fetchCases(limit);
    const converted = apiCases
      .map((ac) => apiCaseToVetting(ac as unknown as Parameters<typeof apiCaseToVetting>[0]))
      .filter((c): c is VettingCase => c !== null);
    setCases(converted);
    return converted;
  }, []);

  const loadCases = useCallback(() => {
    refreshCases(200)
      .then((loaded) => {
        if (!homeTabInitializedRef.current && !selected) {
          setTab(loaded.length > 0 ? "portfolio" : "helios");
          homeTabInitializedRef.current = true;
        }
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : String(err);
        if (authRequired && message.toLowerCase().includes("session expired")) {
          clearSession();
          setUser(null);
          return;
        }
        console.error("Failed to load cases after authentication", err);
      });
  }, [authRequired, refreshCases, selected]);

  // Handle 401 from any API call (auto-logout)
  useEffect(() => {
    setAuthErrorHandler(() => {
      setUser(null);
      setAuthRequired(true);
    });
  }, []);

  // Check if auth is required on mount
  useEffect(() => {
    if (isFileMode) {
      return;
    }

    checkAuthEnabled().then((enabled) => {
      setAuthRequired(enabled);
      if (!enabled || getToken()) {
        setApiAvailable(true);
        loadCases();
      }
    });
  }, [isFileMode, loadCases]);

  const shellLaneMeta = WORKFLOW_LANE_META[workflowMode];
  const shellLaneCases = useMemo(
    () => cases.filter((c) => workflowLaneForCase(c) === workflowMode),
    [cases, workflowMode],
  );
  const shellLaneBlocked = useMemo(
    () => shellLaneCases.filter((c) => portfolioDisposition(c) === "blocked").length,
    [shellLaneCases],
  );
  const shellLaneReview = useMemo(
    () => shellLaneCases.filter((c) => portfolioDisposition(c) === "review").length,
    [shellLaneCases],
  );
  const shellLaneWatch = useMemo(
    () => shellLaneCases.filter((c) => portfolioDisposition(c) === "qualified").length,
    [shellLaneCases],
  );
  const shellTopCase = useMemo(() => {
    const ranked = [...shellLaneCases].sort((a, b) => {
      const dispositionDiff = shellPriorityRank(portfolioDisposition(b)) - shellPriorityRank(portfolioDisposition(a));
      if (dispositionDiff !== 0) return dispositionDiff;
      return (b.cal?.p ?? b.sc) - (a.cal?.p ?? a.sc);
    });
    return ranked[0] ?? null;
  }, [shellLaneCases]);
  const shellSummary = useMemo(() => {
    if (shellLaneCases.length === 0) {
      return `No ${shellLaneMeta.label.toLowerCase()} cases are active yet. Start a new case in this lane.`;
    }
    if (shellLaneBlocked > 0) {
      return `${shellLaneBlocked} blocked ${shellLaneMeta.shortLabel.toLowerCase()} case${shellLaneBlocked === 1 ? "" : "s"} require immediate action.${shellTopCase ? ` Start with ${shellTopCase.name}.` : ""}`;
    }
    if (shellLaneReview > 0) {
      return `${shellLaneReview} ${shellLaneMeta.shortLabel.toLowerCase()} case${shellLaneReview === 1 ? "" : "s"} need focused review.${shellTopCase ? ` Start with ${shellTopCase.name}.` : ""}`;
    }
    if (shellLaneWatch > 0) {
      return `${shellLaneWatch} qualified ${shellLaneMeta.shortLabel.toLowerCase()} case${shellLaneWatch === 1 ? "" : "s"} remain on watch.${shellTopCase ? ` Highest priority: ${shellTopCase.name}.` : ""}`;
    }
    return `The ${shellLaneMeta.label.toLowerCase()} queue is currently stable.${shellTopCase ? ` Highest-priority case: ${shellTopCase.name}.` : ""}`;
  }, [shellLaneBlocked, shellLaneCases.length, shellLaneMeta.label, shellLaneMeta.shortLabel, shellLaneReview, shellLaneWatch, shellTopCase]);
  const shellLaneSummary = useMemo(() => ({
    lane: workflowMode,
    label: shellLaneMeta.label,
    shortLabel: shellLaneMeta.shortLabel,
    description: shellLaneMeta.description,
    activeCount: shellLaneCases.length,
    reviewCount: shellLaneReview,
    blockedCount: shellLaneBlocked,
    watchCount: shellLaneWatch,
    summary: shellSummary,
    topCaseName: shellTopCase?.name ?? null,
  }), [
    shellLaneBlocked,
    shellLaneCases.length,
    shellLaneMeta.description,
    shellLaneMeta.label,
    shellLaneMeta.shortLabel,
    shellLaneReview,
    shellLaneWatch,
    shellSummary,
    shellTopCase?.name,
    workflowMode,
  ]);

  function handleLogin(u: AuthUser) {
    setUser(u);
    setApiAvailable(true);
    homeTabInitializedRef.current = false;
    loadCases();
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setShowUserMenu(false);
    setCases([]);
    setSelected(null);
    homeTabInitializedRef.current = false;
    setTab("helios");
  }

  const emitBetaEvent = useCallback((eventName: string, payload: { workflow_lane?: WorkflowLane; screen?: string; case_id?: string; metadata?: Record<string, unknown> } = {}) => {
    if (!apiAvailable) return;
    void trackBetaEvent({
      event_name: eventName,
      workflow_lane: payload.workflow_lane,
      screen: payload.screen,
      case_id: payload.case_id,
      metadata: payload.metadata,
    }).catch(() => undefined);
  }, [apiAvailable]);

  const handleCaseCreated = async (caseId: string) => {
    const mapped = await refreshCases();
    const newCase = mapped.find((c) => c.id === caseId);
    if (newCase) setSelected(newCase);
  };

  useEffect(() => {
    if (!apiAvailable) return;
    const key = workflowMode;
    if (lastModeEventRef.current === key) return;
    lastModeEventRef.current = key;
    emitBetaEvent("shell_mode_changed", {
      workflow_lane: workflowMode,
      screen: selected ? "case" : tab,
      case_id: selected?.id,
      metadata: { tab, selected_case: selected?.name ?? null },
    });
  }, [apiAvailable, emitBetaEvent, selected, tab, workflowMode]);

  useEffect(() => {
    if (!apiAvailable) return;
    const key = selected ? `case:${selected.id}:${workflowMode}` : `screen:${tab}:${workflowMode}`;
    if (lastScreenEventRef.current === key) return;
    lastScreenEventRef.current = key;
    emitBetaEvent(selected ? "case_viewed" : "screen_viewed", {
      workflow_lane: selected ? workflowLaneForCase(selected) : workflowMode,
      screen: selected ? "case" : tab,
      case_id: selected?.id,
      metadata: { shell_lane: workflowMode, tab },
    });
  }, [apiAvailable, emitBetaEvent, selected, tab, workflowMode]);

  // Demo mode: /demo or /#demo path renders public comparison page
  const isDemo = demoEnabled && (window.location.pathname === "/demo"
    || window.location.hash === "#demo"
    || window.location.hash === "#/demo");

  if (isDemo) {
    return (
      <ErrorBoundary>
        <div className="min-h-screen" style={{ background: T.bg, color: T.text }}>
          <DemoCompare />
        </div>
      </ErrorBoundary>
    );
  }

  // If auth is required and no user, show login
  if (authRequired === null) {
    // Still checking
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: T.bg }}>
        <div className="flex flex-col items-center gap-3">
          <Shield size={24} color={T.accent} className="animate-pulse" />
          <span style={{ fontSize: FS.sm, color: T.muted }}>Connecting to Xiphos...</span>
        </div>
      </div>
    );
  }

  if (authRequired && !user) {
    return (
      <ErrorBoundary>
        <LoginScreen onLogin={handleLogin} needsSetup={false} />
      </ErrorBoundary>
    );
  }

  const handleRescore = async (caseId: string) => {
    emitBetaEvent("rescore_requested", {
      workflow_lane: selected ? workflowLaneForCase(selected) : workflowMode,
      screen: "case",
      case_id: caseId,
      metadata: { tab },
    });
    const result = await rescore(caseId);
    const cal = mapCalibration(result.calibrated as unknown as Record<string, unknown>);
    const rl = tierToRisk(cal.tier);
    const snapshot = { p: cal.p, tier: cal.tier, sc: result.composite_score, ts: new Date().toISOString() };
    setCases((prev) => prev.map((c) => {
      if (c.id !== caseId) return c;
      const history = [...(c.history ?? []), snapshot];
      return { ...c, sc: result.composite_score, cal, rl, history };
    }));
    setSelected((prev) => {
      if (!prev || prev.id !== caseId) return prev;
      const history = [...(prev.history ?? []), snapshot];
      return { ...prev, sc: result.composite_score, cal, rl, history };
    });
  };

  const handleDossier = async (caseId: string) => {
    const c = cases.find((x) => x.id === caseId);
    if (!c) return;
    emitBetaEvent("dossier_requested", {
      workflow_lane: workflowLaneForCase(c),
      screen: selected ? "case" : tab,
      case_id: caseId,
      metadata: { tab },
    });
    if (apiAvailable) {
      try {
        const result = await apiDossier(caseId);
        if (result.download_url) {
          const protectedUrl = await buildProtectedUrl(result.download_url);
          window.open(protectedUrl, "_blank");
          return;
        }
      } catch { /* fall through */ }
    }
    openDossier(c);
  };

  const handleSubmitFeedback = async (event: React.FormEvent) => {
    event.preventDefault();
    setFeedbackSubmitting(true);
    setFeedbackError(null);
    setFeedbackSuccess(null);
    try {
      const activeCase = selected ?? null;
      const lane = activeCase ? workflowLaneForCase(activeCase) : workflowMode;
      await submitBetaFeedback({
        summary: feedbackSummary.trim(),
        details: feedbackDetails.trim(),
        category: feedbackCategory,
        severity: feedbackSeverity,
        workflow_lane: lane,
        screen: activeCase ? "case" : tab,
        case_id: activeCase?.id,
        metadata: {
          shell_lane: workflowMode,
          selected_case_name: activeCase?.name ?? null,
          tab,
        },
      });
      emitBetaEvent("feedback_submitted", {
        workflow_lane: lane,
        screen: activeCase ? "case" : tab,
        case_id: activeCase?.id,
        metadata: { category: feedbackCategory, severity: feedbackSeverity },
      });
      setFeedbackSuccess("Feedback captured for beta review.");
      setFeedbackSummary("");
      setFeedbackDetails("");
      setFeedbackCategory("bug");
      setFeedbackSeverity("medium");
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : "Failed to submit feedback");
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  const filtered = cases.filter(
    (c) =>
      c.name.toLowerCase().includes(query.toLowerCase()) ||
      c.cc.toLowerCase().includes(query.toLowerCase()),
  );

  // User initials for avatar
  const initials = user
    ? (user.name || user.email).split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 2)
    : "TG";

  return (
    <ErrorBoundary>
      <div className="h-screen flex flex-col overflow-hidden" style={{ background: T.bg, color: T.text }}>
        {/* Header */}
        <header
          className="px-4 lg:px-6 shrink-0 helios-glass"
          style={{
            height: 52,
            borderBottom: `1px solid ${T.borderStrong}`,
            background: FX.shell,
            display: "flex",
            alignItems: "center",
          }}
        >
          <div className="flex items-center justify-between gap-3 w-full">
            {/* Left: Brand + Nav tabs in single row */}
            <div className="flex items-center gap-3 min-w-0 overflow-x-auto">
              <div
                className="inline-flex items-center gap-1.5 shrink-0"
                style={{ cursor: "default" }}
              >
                <Shield size={16} color={shellLaneMeta.accent} />
                <span className="font-bold" style={{ fontSize: FS.base, color: T.text, letterSpacing: "-0.02em" }}>
                  Helios
                </span>
              </div>

              <div style={{ width: 1, height: 20, background: T.border, flexShrink: 0 }} />

              {/* Nav tab pills (inline with brand) */}
              <div className="flex items-center gap-0.5 min-w-0 overflow-x-auto">
                {([
                  { id: "portfolio" as const, label: "Workbench", icon: Shield },
                  { id: "helios" as const, label: "Intake", icon: Shield },
                  { id: "dashboard" as const, label: "Overview", icon: LayoutDashboard },
                  { id: "threads" as const, label: "Threads", icon: Network },
                  { id: "graph" as const, label: "Graph Intel", icon: Grid3X3 },
                ] as const).map((t) => {
                  const isActive = tab === t.id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => { setTab(t.id); setSelected(null); }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 border-none cursor-pointer helios-focus-ring shrink-0 rounded"
                      style={{
                        fontSize: FS.sm,
                        fontWeight: isActive ? 700 : 500,
                        background: isActive ? T.accentSoft : "transparent",
                        color: isActive ? T.accent : T.muted,
                      }}
                    >
                      <t.icon size={12} />
                      {t.label}
                    </button>
                  );
                })}
                {hasPermission(user, "auditor") && (
                  <button
                    onClick={() => { setTab("admin"); setSelected(null); }}
                    className="inline-flex items-center gap-1 px-2.5 py-1 border-none cursor-pointer helios-focus-ring shrink-0 rounded"
                    style={{
                      fontSize: FS.sm,
                      fontWeight: tab === "admin" ? 700 : 500,
                      background: tab === "admin" ? T.accentSoft : "transparent",
                      color: tab === "admin" ? T.accent : T.muted,
                    }}
                  >
                    <Settings size={12} />
                    Admin
                  </button>
                )}
              </div>

              {/* Lane selector (inline, only for relevant tabs) */}
              {tab !== "admin" && tab !== "graph" && tab !== "dashboard" && tab !== "threads" && (
                <>
                  <div style={{ width: 1, height: 20, background: T.border, flexShrink: 0 }} />
                  <div className="flex items-center gap-0.5 shrink-0">
                    {(Object.keys(WORKFLOW_LANE_META) as WorkflowLane[]).map((lane) => {
                      const meta = WORKFLOW_LANE_META[lane];
                      const isActive = workflowMode === lane;
                      return (
                        <button
                          key={lane}
                          onClick={() => setWorkflowMode(lane)}
                          className="inline-flex items-center rounded px-2.5 py-1 border-none cursor-pointer helios-focus-ring shrink-0"
                          style={{
                            fontSize: FS.sm,
                            fontWeight: isActive ? 700 : 500,
                            background: isActive ? meta.softBackground : "transparent",
                            color: isActive ? meta.accent : T.muted,
                          }}
                          title={meta.description}
                        >
                          {meta.shortLabel}
                        </button>
                      );
                    })}
                  </div>
                </>
              )}
            </div>

            {/* Right: Search + Status + User (compact) */}
            <div className="flex items-center gap-2 shrink-0">
              {tab === "portfolio" && !selected && (
                <div className="relative hidden sm:block">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2" color={T.muted} />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search..."
                    className="rounded-full outline-none helios-focus-ring w-44"
                    style={{
                      paddingLeft: 28,
                      paddingRight: 10,
                      paddingTop: 5,
                      paddingBottom: 5,
                      fontSize: FS.sm,
                      background: T.surface,
                      border: `1px solid ${T.border}`,
                      color: T.text,
                    }}
                  />
                </div>
              )}
              {apiAvailable !== null && (
                <div className="flex items-center gap-1 px-2 py-1 rounded-full" title={apiAvailable ? "API connected" : "Offline"} style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                  {apiAvailable ? <Wifi size={10} color={T.green} /> : <WifiOff size={10} color={T.muted} />}
                  <span className="hidden lg:inline" style={{ fontSize: 11, fontWeight: 600, color: apiAvailable ? T.green : T.muted }}>
                    {apiAvailable ? "Live" : "Offline"}
                  </span>
                </div>
              )}
              {apiAvailable && (
                <button
                  onClick={() => {
                    setShowFeedbackDialog(true);
                    setFeedbackError(null);
                    setFeedbackSuccess(null);
                  }}
                  className="inline-flex items-center rounded-full p-1.5 cursor-pointer helios-focus-ring"
                  style={{ background: "transparent", border: `1px solid ${T.border}`, color: T.muted }}
                  title="Beta feedback"
                >
                  <MessageSquare size={14} color={T.accent} />
                </button>
              )}
              <div className="relative">
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-1 rounded cursor-pointer"
                  style={{ background: "transparent", border: "none", padding: "2px" }}
                >
                  <div
                    className="flex items-center justify-center rounded-full font-bold"
                    style={{ width: 26, height: 26, fontSize: 11, background: T.accent + "22", color: T.accent }}
                  >
                    {initials}
                  </div>
                </button>

                {showUserMenu && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowUserMenu(false)}
                    />
                    <div
                      className="absolute right-0 top-full mt-1 rounded-lg z-50 overflow-hidden"
                      style={{
                        width: 220,
                        background: T.surface,
                        border: `1px solid ${T.border}`,
                        boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                      }}
                    >
                      {user && (
                        <div className="p-3" style={{ borderBottom: `1px solid ${T.border}` }}>
                          <div className="flex items-center gap-2 mb-1">
                            <User size={12} color={T.accent} />
                            <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>
                              {user.name || user.email}
                            </span>
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.muted }}>{user.email}</div>
                          <div
                            className="inline-block rounded mt-1.5 font-mono"
                            style={{
                              fontSize: FS.sm,
                              padding: "2px 6px",
                              background: T.accent + "18",
                              color: T.accent,
                            }}
                          >
                            {roleLabel(user.role)}
                          </div>
                        </div>
                      )}
                      {authRequired && (
                        <button
                          onClick={handleLogout}
                          className="w-full flex items-center gap-2 px-3 py-2.5 cursor-pointer"
                          style={{
                            fontSize: FS.sm,
                            color: T.red,
                            background: "transparent",
                            border: "none",
                            textAlign: "left",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = T.hover)}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <LogOut size={12} />
                          Sign Out
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </header>

      {/* Main content */}
      <main className={`flex-1 overflow-auto ${tab === "graph" || tab === "dashboard" ? "p-0" : "p-4 lg:p-6"}`}>
        <div className={`${tab === "graph" || tab === "dashboard" ? "w-full h-full" : "max-w-[1400px] mx-auto"} h-full`}>
          {selected ? (
            <CaseDetail
              c={selected}
              onBack={() => setSelected(null)}
              onRescore={apiAvailable ? handleRescore : undefined}
              onDossier={handleDossier}
              onCaseRefresh={handleCaseCreated}
              globalLane={workflowMode}
              laneSummary={shellLaneSummary}
            />
          ) : tab === "dashboard" ? (
            <ComplianceDashboard />
          ) : tab === "helios" ? (
            <HeliosLanding
              onCaseCreated={handleCaseCreated}
              onNavigate={(t) => setTab(t as Tab)}
              onCasesRefresh={async () => { await refreshCases(); }}
              cases={cases}
              preferredLane={workflowMode}
              onPreferredLaneChange={setWorkflowMode}
            />
          ) : tab === "portfolio" ? (
            <PortfolioScreen
              key={`portfolio-${workflowMode}`}
              allCases={cases}
              cases={filtered}
              query={query}
              onSelect={setSelected}
              globalLane={workflowMode}
              onGlobalLaneChange={setWorkflowMode}
              onNavigate={(t) => setTab(t as Tab)}
              laneSummary={shellLaneSummary}
            />
          ) : tab === "threads" ? (
            <MissionThreadsScreen onNavigate={(t) => setTab(t as Tab)} />
          ) : tab === "graph" ? (
            <GraphIntelligenceDashboard />
          ) : tab === "admin" && user && hasPermission(user, "auditor") ? (
            <AdminPanel currentUser={user} />
          ) : (
            <HeliosLanding
              onCaseCreated={handleCaseCreated}
              onNavigate={(t) => setTab(t as Tab)}
              onCasesRefresh={async () => { await refreshCases(); }}
              cases={cases}
              preferredLane={workflowMode}
              onPreferredLaneChange={setWorkflowMode}
            />
          )}
        </div>
      </main>

        {/* Footer */}
        <footer
          className="text-center shrink-0"
          style={{ padding: "8px 0", fontSize: FS.sm, color: T.muted, borderTop: `1px solid ${T.border}` }}
        >
          Helios v5.2 · {cases.length} vendors in portfolio
          {user && <> · {user.email}</>}
          {" · "}
          <span style={{ color: T.dim }}>{apiAvailable ? "System live" : "Local mode"}</span>
        </footer>

        <Dialog open={showFeedbackDialog} onOpenChange={setShowFeedbackDialog}>
          <DialogContent style={{ background: T.surface, border: `1px solid ${T.border}`, color: T.text, maxWidth: 640 }}>
            <DialogHeader>
              <DialogTitle style={{ color: T.text }}>Submit beta feedback</DialogTitle>
              <DialogDescription style={{ color: T.muted }}>
                Captures the current lane, screen, and case context for triage.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSubmitFeedback} className="flex flex-col gap-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span style={{ fontSize: FS.sm, color: T.muted }}>Category</span>
                  <select
                    value={feedbackCategory}
                    onChange={(e) => setFeedbackCategory(e.target.value as typeof feedbackCategory)}
                    style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "8px 10px", fontSize: FS.sm }}
                  >
                    <option value="bug">Bug</option>
                    <option value="confusion">Confusion</option>
                    <option value="request">Request</option>
                    <option value="general">General</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span style={{ fontSize: FS.sm, color: T.muted }}>Severity</span>
                  <select
                    value={feedbackSeverity}
                    onChange={(e) => setFeedbackSeverity(e.target.value as typeof feedbackSeverity)}
                    style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "8px 10px", fontSize: FS.sm }}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>

              <div
                className="rounded-lg"
                style={{ background: T.bg, border: `1px solid ${T.border}`, padding: "10px 12px" }}
              >
                <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 4 }}>Current context</div>
                <div style={{ fontSize: FS.sm, color: T.text }}>
                  Lane: {selected ? WORKFLOW_LANE_META[workflowLaneForCase(selected)].label : shellLaneMeta.label}
                  {" · "}
                  Screen: {selected ? "case" : tab}
                  {selected ? ` · Case: ${selected.name}` : ""}
                </div>
              </div>

              <label className="flex flex-col gap-1">
                <span style={{ fontSize: FS.sm, color: T.muted }}>Summary</span>
                <input
                  value={feedbackSummary}
                  onChange={(e) => setFeedbackSummary(e.target.value)}
                  maxLength={240}
                  placeholder="What failed or slowed you down?"
                  style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "8px 10px", fontSize: FS.sm }}
                  required
                />
              </label>

              <label className="flex flex-col gap-1">
                <span style={{ fontSize: FS.sm, color: T.muted }}>Details</span>
                <textarea
                  value={feedbackDetails}
                  onChange={(e) => setFeedbackDetails(e.target.value)}
                  rows={5}
                  placeholder="Include what you expected, what happened instead, and any blockers."
                  style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "10px 12px", fontSize: FS.sm, resize: "vertical" }}
                />
              </label>

              {feedbackError && <div style={{ fontSize: FS.sm, color: T.red }}>{feedbackError}</div>}
              {feedbackSuccess && <div style={{ fontSize: FS.sm, color: T.green }}>{feedbackSuccess}</div>}

              <DialogFooter>
                <button
                  type="button"
                  onClick={() => setShowFeedbackDialog(false)}
                  className="rounded px-3 py-2 cursor-pointer"
                  style={{ background: T.bg, color: T.text, border: `1px solid ${T.border}`, fontSize: FS.sm, fontWeight: 700 }}
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={feedbackSubmitting || feedbackSummary.trim().length === 0}
                  className="rounded px-3 py-2 cursor-pointer"
                  style={{ background: T.accent, color: "#fff", border: "none", fontSize: FS.sm, fontWeight: 700, opacity: feedbackSubmitting ? 0.7 : 1 }}
                >
                  {feedbackSubmitting ? "Submitting..." : "Send feedback"}
                </button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
    </ErrorBoundary>
  );
}
