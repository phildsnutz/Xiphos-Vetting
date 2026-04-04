import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Shield, Search, Wifi, WifiOff, LogOut, User, Settings, MessageSquare, Grid3X3, LayoutDashboard, Network, Radar, ArrowLeft, ChevronRight, HelpCircle, Command } from "lucide-react";
import { T, FS, FX, PAD, SP, O } from "@/lib/tokens";
import { CaseDetail } from "@/components/xiphos/case-detail";
import { CommandPalette } from "@/components/xiphos/command-palette";
import { useHotkey } from "@/lib/use-hotkeys";
import { AdminPanel } from "@/components/xiphos/admin-panel";
import { FrontPorchLanding } from "@/components/xiphos/front-porch-landing";
import { MissionThreadsScreen } from "@/components/xiphos/mission-threads-screen";
import { PortfolioScreen } from "@/components/xiphos/portfolio-screen";
import { DemoCompare } from "@/components/xiphos/demo-compare";
import { GraphIntelligenceDashboard } from "@/components/xiphos/graph-intelligence-dashboard";
import ComplianceDashboard from "@/components/xiphos/compliance-dashboard";
import { ErrorBoundary } from "@/components/xiphos/error-boundary";
import { WarRoom } from "@/components/xiphos/war-room";
import { PortfolioSkeleton } from "@/components/xiphos/skeletons";
import { buildProtectedUrl, rescore, generateDossier as apiDossier, fetchCases, setAuthErrorHandler, submitBetaFeedback, trackBetaEvent } from "@/lib/api";
import { openDossier } from "@/lib/dossier";
import { checkAuthEnabled, getToken, getUser, clearSession, roleLabel, hasPermission, login } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";
import type { VettingCase, Calibration, ScreeningPolicyBasis, ScoringPolicyMetadata } from "@/lib/types";
import { parseTier, tierToRisk } from "@/lib/tokens";
import {
  PRODUCT_PILLAR_META,
  WORKFLOW_LANE_META,
  portfolioDisposition,
  productPillarForCase,
  workflowLaneForCase,
} from "@/components/xiphos/portfolio-utils";
import type { ProductPillar, WorkflowLane } from "@/components/xiphos/portfolio-utils";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { InlineMessage, ShortcutBadge, StatusPill } from "@/components/xiphos/shell-primitives";

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

type Tab = "dashboard" | "helios" | "portfolio" | "threads" | "graph" | "axiom" | "admin";
type WarRoomSeed = {
  targetEntity: string;
  vehicleName?: string;
  domainFocus?: string;
  seedLabel?: string;
  autoRun?: boolean;
} | null;

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
  const [showLoginDialog, setShowLoginDialog] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginSubmitting, setLoginSubmitting] = useState(false);

  // App state -- start empty; cases load from backend after login
  const [cases, setCases] = useState<VettingCase[]>([]);
  const [selected, setSelected] = useState<VettingCase | null>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("helios");
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(isFileMode ? false : null);
  const [warRoomSeed, setWarRoomSeed] = useState<WarRoomSeed>(null);
  const [productFocus, setProductFocus] = useState<ProductPillar>("vendor_assessment");
  const [workflowMode, setWorkflowMode] = useState<WorkflowLane>("counterparty");
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [casesLoading, setCasesLoading] = useState(!isFileMode);
  const [showShortcutDialog, setShowShortcutDialog] = useState(false);
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

  // Global hotkey to open command palette
  useHotkey("cmd+k", () => setCmdPaletteOpen(true), { ignoreInputs: false });

  const refreshCases = useCallback(async (limit = 200) => {
    setCasesLoading(true);
    try {
      const apiCases = await fetchCases(limit);
      const converted = apiCases
        .map((ac) => apiCaseToVetting(ac as unknown as Parameters<typeof apiCaseToVetting>[0]))
        .filter((c): c is VettingCase => c !== null);
      setCases(converted);
      return converted;
    } finally {
      setCasesLoading(false);
    }
  }, []);

  const loadCases = useCallback(() => {
    refreshCases(200)
      .then(() => {
        if (!homeTabInitializedRef.current && !selected) {
          setTab("helios");
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
      const token = getToken();
      if (!enabled) {
        setApiAvailable(true);
        setCasesLoading(false);
      }
      if (token) {
        setApiAvailable(true);
        loadCases();
      }
    });
  }, [isFileMode, loadCases]);

  const activePillar = selected ? productPillarForCase(selected) : productFocus;
  const shellPillarMeta = PRODUCT_PILLAR_META[activePillar];
  const shellLaneCases = useMemo(() => cases, [cases]);
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
    if (activePillar === "contract_vehicle") {
      return "Start from the vehicle, map primes and subs, then turn the right entities into AXIOM-backed brief work.";
    }
    if (shellLaneCases.length === 0) {
      return "No entity briefs are active yet. Start from a supplier, company, or pivot in from a vehicle.";
    }
    if (shellLaneBlocked > 0) {
      return `${shellLaneBlocked} blocked brief${shellLaneBlocked === 1 ? "" : "s"} require immediate action.${shellTopCase ? ` Start with ${shellTopCase.name}.` : ""}`;
    }
    if (shellLaneReview > 0) {
      return `${shellLaneReview} active brief${shellLaneReview === 1 ? "" : "s"} need focused review.${shellTopCase ? ` Start with ${shellTopCase.name}.` : ""}`;
    }
    if (shellLaneWatch > 0) {
      return `${shellLaneWatch} qualified brief${shellLaneWatch === 1 ? "" : "s"} remain on watch.${shellTopCase ? ` Highest priority: ${shellTopCase.name}.` : ""}`;
    }
    return `The entity queue is currently stable.${shellTopCase ? ` Highest-priority case: ${shellTopCase.name}.` : ""}`;
  }, [activePillar, shellLaneBlocked, shellLaneCases.length, shellLaneReview, shellLaneWatch, shellTopCase]);
  const shellLaneSummary = useMemo(() => ({
    lane: workflowMode,
    label: activePillar === "contract_vehicle" ? "Vehicle intelligence" : "Entity intelligence queue",
    shortLabel: activePillar === "contract_vehicle" ? "Vehicle" : "Entity",
    description: activePillar === "contract_vehicle"
      ? "Start from the vehicle and spin the right vendors into assessment."
      : "All active entity briefs, with deeper support surfaces pulled in only when they change the call.",
    activeCount: shellLaneCases.length,
    reviewCount: shellLaneReview,
    blockedCount: shellLaneBlocked,
    watchCount: shellLaneWatch,
    summary: shellSummary,
    topCaseName: shellTopCase?.name ?? null,
  }), [
    activePillar,
    shellLaneBlocked,
    shellLaneCases.length,
    shellLaneReview,
    shellLaneWatch,
    shellSummary,
    shellTopCase?.name,
    workflowMode,
  ]);

  function handleLogin(u: AuthUser) {
    setUser(u);
    setApiAvailable(true);
    setShowLoginDialog(false);
    setLoginError(null);
    setLoginPassword("");
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

  const requestLogin = useCallback(() => {
    setLoginError(null);
    setShowLoginDialog(true);
  }, []);

  const handleDialogLogin = useCallback(async (event: React.FormEvent) => {
    event.preventDefault();
    setLoginSubmitting(true);
    setLoginError(null);
    try {
      const result = await login(loginEmail, loginPassword);
      handleLogin(result.user);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoginSubmitting(false);
    }
  }, [handleLogin, loginEmail, loginPassword]);

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
    if (newCase) {
      setProductFocus("vendor_assessment");
      setSelected(newCase);
    }
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

  const screenTitle = selected
    ? selected.name
    : tab === "portfolio"
      ? "Workbench"
      : tab === "helios"
        ? "Briefing"
        : tab === "dashboard"
          ? "Overview"
          : tab === "threads"
            ? "Mission Threads"
            : tab === "graph"
              ? "Graph Intelligence"
              : tab === "axiom"
                ? "War Room"
                : "Admin";

  const screenSubtitle = selected
    ? `Working brief • ${WORKFLOW_LANE_META[workflowLaneForCase(selected)].label.toLowerCase()}`
    : tab === "portfolio"
      ? shellSummary
      : tab === "helios"
        ? "Start with whatever you know. AXIOM will narrow the problem and take it from there."
        : tab === "dashboard"
          ? "Status, drift, and pressure across the workspace."
          : tab === "threads"
            ? "Model contested sustainment as a mission problem, not a single-vendor problem."
            : tab === "graph"
              ? "Interrogate the relationship map, not just the case in front of you."
              : tab === "axiom"
                ? "Work the problem with AXIOM, keep the trail visible, and surface only what changes the judgment."
                : "Workspace administration, access, AI configuration, and beta review.";

  const relevantCaseList = query ? filtered : cases;

  const cycleSelectedCase = useCallback((delta: number) => {
    if (!selected || relevantCaseList.length === 0) return;
    const currentIndex = relevantCaseList.findIndex((item) => item.id === selected.id);
    if (currentIndex === -1) return;
    const nextIndex = (currentIndex + delta + relevantCaseList.length) % relevantCaseList.length;
    setSelected(relevantCaseList[nextIndex]);
  }, [relevantCaseList, selected]);

  const movePortfolioFocus = useCallback((delta: number) => {
    if (typeof document === "undefined") return;
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-case-row="true"]'));
    if (rows.length === 0) return;
    const active = document.activeElement as HTMLElement | null;
    const currentIndex = rows.findIndex((row) => row === active || row.contains(active));
    const fallbackIndex = delta > 0 ? 0 : rows.length - 1;
    const nextIndex = currentIndex === -1 ? fallbackIndex : (currentIndex + delta + rows.length) % rows.length;
    const next = rows[nextIndex];
    next.focus();
    next.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, []);

  const activateFocusedCase = useCallback(() => {
    if (typeof document === "undefined") return;
    const active = document.activeElement as HTMLElement | null;
    const row = active?.closest?.('[data-case-row="true"]') as HTMLElement | null;
    row?.click();
  }, []);

  const triggerCaseWorkspace = useCallback((view: "decision" | "evidence" | "graph") => {
    if (typeof document === "undefined") return;
    const target = document.querySelector<HTMLElement>(`[data-case-view="${view}"]`);
    target?.click();
    target?.focus();
  }, []);

  const handleGlobalEscape = useCallback(() => {
    if (showUserMenu) {
      setShowUserMenu(false);
      return;
    }
    if (showFeedbackDialog) {
      setShowFeedbackDialog(false);
      return;
    }
    if (showShortcutDialog) {
      setShowShortcutDialog(false);
      return;
    }
    if (cmdPaletteOpen) {
      setCmdPaletteOpen(false);
      return;
    }
    if (selected) {
      setSelected(null);
    }
  }, [cmdPaletteOpen, selected, showFeedbackDialog, showShortcutDialog, showUserMenu]);

  useHotkey("?", () => setShowShortcutDialog((current) => !current));
  useHotkey("escape", handleGlobalEscape);
  useHotkey("j", () => {
    if (selected) {
      cycleSelectedCase(1);
      return;
    }
    if (tab === "portfolio") {
      movePortfolioFocus(1);
    }
  });
  useHotkey("k", () => {
    if (selected) {
      cycleSelectedCase(-1);
      return;
    }
    if (tab === "portfolio") {
      movePortfolioFocus(-1);
    }
  });
  useHotkey("enter", () => {
    if (!selected && tab === "portfolio") {
      activateFocusedCase();
    }
  });
  useHotkey("d", () => {
    if (selected) triggerCaseWorkspace("decision");
  });
  useHotkey("e", () => {
    if (selected) triggerCaseWorkspace("evidence");
  });
  useHotkey("g", () => {
    if (selected) {
      triggerCaseWorkspace("graph");
      return;
    }
    setSelected(null);
    setTab("graph");
  });

  const shellTabs: Array<{
    id: Tab;
    label: string;
    description: string;
    icon: typeof Shield;
    badge?: string;
  }> = [
    {
      id: "portfolio",
      label: "Workbench",
      description: "Work the queue and close decisions.",
      icon: Shield,
      badge: shellLaneBlocked + shellLaneReview > 0 ? String(shellLaneBlocked + shellLaneReview) : undefined,
    },
    {
      id: "helios",
      label: "Briefing",
      description: "Start from an entity, a vehicle, or the knot you cannot quite name yet.",
      icon: Shield,
    },
    {
      id: "dashboard",
      label: "Overview",
      description: "Read posture, drift, and room pressure.",
      icon: LayoutDashboard,
    },
    {
      id: "threads",
      label: "Threads",
      description: "Model mission brittleness and alternates.",
      icon: Network,
    },
    {
      id: "graph",
      label: "Graph Intel",
      description: "Interrogate the relationship fabric.",
      icon: Grid3X3,
    },
    {
      id: "axiom",
      label: "War Room",
      description: "Work collection, drift, and evidence at practitioner depth.",
      icon: Radar,
    },
    ...(user && hasPermission(user, "auditor")
      ? [{
          id: "admin" as const,
          label: "Admin",
          description: "Access, feedback, and operator settings.",
          icon: Settings,
        }]
      : []),
  ];

  // User initials for avatar
  const initials = user
    ? (user.name || user.email).split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 2)
    : "TG";

  const activeShellTab = shellTabs.find((item) => item.id === tab) ?? shellTabs[0];
  const showSupportingLayerControls = false;
  const frontPorchMode = !selected && tab === "helios";
  const warRoomMode = !selected && tab === "axiom";
  const shellContent = selected ? (
    <CaseDetail
      c={selected}
      onBack={() => setSelected(null)}
      onRescore={apiAvailable ? handleRescore : undefined}
      onDossier={handleDossier}
      onCaseRefresh={handleCaseCreated}
      laneSummary={shellLaneSummary}
    />
  ) : tab === "dashboard" ? (
    <ComplianceDashboard />
  ) : tab === "portfolio" ? (
    casesLoading ? (
      <PortfolioSkeleton />
    ) : (
      <PortfolioScreen
        key="portfolio"
        allCases={cases}
        cases={filtered}
        query={query}
        onSelect={setSelected}
        onNavigate={(t) => setTab(t as Tab)}
        laneSummary={shellLaneSummary}
      />
    )
  ) : tab === "threads" ? (
    <MissionThreadsScreen onNavigate={(t) => setTab(t as Tab)} />
  ) : tab === "graph" ? (
    <GraphIntelligenceDashboard />
  ) : tab === "axiom" ? (
    <WarRoom
      seed={warRoomSeed}
      cases={cases}
      onNavigate={(nextTab) => setTab(nextTab as Tab)}
      onOpenCase={(caseId) => {
        const found = cases.find((item) => item.id === caseId);
        if (found) {
          setSelected(found);
          setTab("portfolio");
          return;
        }
        void handleCaseCreated(caseId);
      }}
    />
  ) : tab === "admin" && user && hasPermission(user, "auditor") ? (
    <AdminPanel currentUser={user} />
  ) : (
    <FrontPorchLanding
      cases={cases}
      loginRequired={Boolean(authRequired && !user)}
      onOpenWarRoomIntent={(intent) => setWarRoomSeed(intent)}
      onRequestLogin={requestLogin}
      onNavigate={(nextTab) => {
        if (authRequired && !user && nextTab !== "helios") {
          requestLogin();
          return;
        }
        if (nextTab !== "axiom") {
          setWarRoomSeed(null);
        }
        setTab(nextTab as Tab);
      }}
      onOpenCase={(caseId) => {
        if (authRequired && !user) {
          requestLogin();
          return;
        }
        const found = cases.find((item) => item.id === caseId);
        if (found) {
          setSelected(found);
          setTab("portfolio");
          return;
        }
        void handleCaseCreated(caseId);
      }}
    />
  );

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

  if (authRequired === null) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: T.bg }}>
        <div className="flex flex-col items-center gap-3">
          <Shield size={24} color={T.accent} className="animate-pulse" />
          <span style={{ fontSize: FS.sm, color: T.muted }}>Connecting to Xiphos...</span>
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <div
        className="h-screen"
        style={{
          background: T.bg,
          color: T.text,
          overflow: warRoomMode ? "hidden" : authRequired && !user || frontPorchMode ? "auto" : "hidden",
        }}
      >
        {authRequired && !user ? (
          <FrontPorchLanding
            cases={cases}
            loginRequired
            onRequestLogin={requestLogin}
            onNavigate={(nextTab) => {
              if (nextTab !== "helios") {
                requestLogin();
              }
            }}
            onOpenCase={() => requestLogin()}
          />
        ) : frontPorchMode ? (
          <FrontPorchLanding
            cases={cases}
            loginRequired={Boolean(authRequired && !user)}
            onOpenWarRoomIntent={(intent) => setWarRoomSeed(intent)}
            onRequestLogin={requestLogin}
            onNavigate={(nextTab) => {
              if (nextTab !== "axiom") {
                setWarRoomSeed(null);
              }
              setSelected(null);
              setTab(nextTab as Tab);
            }}
            onOpenCase={(caseId) => {
              const found = cases.find((item) => item.id === caseId);
              if (found) {
                setSelected(found);
                setTab("portfolio");
                return;
              }
              void handleCaseCreated(caseId);
            }}
          />
        ) : warRoomMode ? (
          <WarRoom
            seed={warRoomSeed}
            cases={cases}
            onNavigate={(nextTab) => {
              setSelected(null);
              if (nextTab !== "axiom") {
                setWarRoomSeed(null);
              }
              setTab(nextTab as Tab);
            }}
            onOpenCase={(caseId) => {
              const found = cases.find((item) => item.id === caseId);
              if (found) {
                setSelected(found);
                setTab("portfolio");
                return;
              }
              void handleCaseCreated(caseId);
            }}
          />
        ) : (
          <div className="h-screen flex overflow-hidden">
            <aside
              className="hidden lg:flex lg:flex-col shrink-0"
              style={{
                width: 288,
                borderRight: `1px solid ${T.borderStrong}`,
                background: FX.shell,
                padding: PAD.comfortable,
                gap: SP.lg,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: SP.md }}>
                <div style={{ display: "flex", alignItems: "center", gap: SP.sm, minWidth: 0 }}>
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 12,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: shellPillarMeta.softBackground,
                      border: `1px solid ${shellPillarMeta.accent}${O["20"]}`,
                      flexShrink: 0,
                    }}
                  >
                    <Shield size={18} color={shellPillarMeta.accent} />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: FS.base, fontWeight: 800, letterSpacing: "-0.03em", color: T.text }}>Helios</div>
                    <div style={{ fontSize: FS.sm, color: T.textSecondary }}>Entity and vehicle intelligence</div>
                  </div>
                  <ShortcutBadge>⌘K</ShortcutBadge>
                </div>

                <div style={{ display: "flex", gap: SP.sm, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => {
                      setTab("helios");
                      setSelected(null);
                    }}
                    className="helios-focus-ring"
                    aria-label="Open briefing"
                    style={{
                      border: "none",
                      background: shellPillarMeta.accent,
                      color: "#04101f",
                      borderRadius: 999,
                      padding: "8px 12px",
                      fontSize: FS.sm,
                      fontWeight: 800,
                      cursor: "pointer",
                    }}
                  >
                    New brief
                  </button>
                  <button
                    type="button"
                    onClick={() => setCmdPaletteOpen(true)}
                    className="helios-focus-ring"
                    aria-label="Open command palette"
                    style={{
                      border: `1px solid ${T.border}`,
                      background: T.surface,
                      color: T.textSecondary,
                      borderRadius: 999,
                      padding: "8px 12px",
                      fontSize: FS.sm,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    Command menu
                  </button>
                </div>
              </div>

              <nav style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
                {shellTabs.map((item) => {
                  const Icon = item.icon;
                  const active = item.id === tab;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setSelected(null);
                        setTab(item.id);
                      }}
                      className="helios-focus-ring"
                      aria-label={`${item.label}. ${item.description}`}
                      style={{
                        border: `1px solid ${active ? `${shellPillarMeta.accent}${O["20"]}` : "transparent"}`,
                        background: active ? shellPillarMeta.softBackground : "transparent",
                        color: active ? T.text : T.textSecondary,
                        borderRadius: 16,
                        padding: PAD.default,
                        display: "flex",
                        alignItems: "center",
                        gap: SP.sm,
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                      aria-current={active ? "page" : undefined}
                      title={item.description}
                    >
                      <div
                        style={{
                          width: 30,
                          height: 30,
                          borderRadius: 10,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          background: active ? `${shellPillarMeta.accent}${O["12"]}` : T.surface,
                          border: `1px solid ${active ? `${shellPillarMeta.accent}${O["20"]}` : T.border}`,
                          flexShrink: 0,
                        }}
                      >
                        <Icon size={15} color={active ? shellPillarMeta.accent : T.textTertiary} />
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: FS.sm, fontWeight: 700, color: active ? T.text : T.textSecondary }}>
                          {item.label}
                        </div>
                      </div>
                      {item.badge ? (
                        <span
                          style={{
                            minWidth: 24,
                            height: 24,
                            borderRadius: 999,
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            background: `${T.red}${O["12"]}`,
                            color: T.red,
                            fontSize: FS.xs,
                            fontWeight: 800,
                            padding: "0 6px",
                          }}
                        >
                          {item.badge}
                        </span>
                      ) : active ? <ChevronRight size={14} color={shellPillarMeta.accent} /> : null}
                    </button>
                  );
                })}
              </nav>

              <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: SP.sm }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: SP.xs }}>
                  <StatusPill tone="info">{shellPillarMeta.label}</StatusPill>
                  {selected ? (
                    <StatusPill tone="neutral">{WORKFLOW_LANE_META[workflowLaneForCase(selected)].label}</StatusPill>
                  ) : (
                    <StatusPill tone="neutral">{productFocus === "vendor_assessment" ? "Full picture" : "Vehicle-first"}</StatusPill>
                  )}
                </div>

                <InlineMessage
                  tone={apiAvailable ? "success" : "warning"}
                  title={apiAvailable ? "System live" : "Local mode"}
                  message={
                    apiAvailable
                      ? "API, monitoring, and dossier actions are available."
                      : "Running in local mode. Some production-linked actions may degrade."
                  }
                />
              </div>
            </aside>

            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
              <header
                className="shrink-0"
                style={{
                  borderBottom: `1px solid ${T.borderStrong}`,
                  background: FX.shell,
                  padding: PAD.default,
                }}
              >
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="flex items-center gap-2 flex-wrap" style={{ marginBottom: SP.xs }}>
                        <span style={{ fontSize: FS.xs, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: T.textTertiary }}>
                          {selected ? "Case workspace" : activeShellTab.label}
                        </span>
                        {selected ? <ChevronRight size={14} color={T.textTertiary} /> : null}
                        {selected ? (
                          <span style={{ fontSize: FS.xs, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: PRODUCT_PILLAR_META.vendor_assessment.accent }}>
                            {PRODUCT_PILLAR_META.vendor_assessment.label}
                          </span>
                        ) : null}
                        {selected ? (
                          <span style={{ fontSize: FS.xs, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: WORKFLOW_LANE_META[workflowLaneForCase(selected)].accent }}>
                            {WORKFLOW_LANE_META[workflowLaneForCase(selected)].shortLabel}
                          </span>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        {selected ? (
                          <button
                            type="button"
                            onClick={() => setSelected(null)}
                            className="helios-focus-ring"
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: SP.xs,
                              border: `1px solid ${T.border}`,
                              background: T.surface,
                              color: T.textSecondary,
                              borderRadius: 999,
                              padding: "6px 10px",
                              fontSize: FS.sm,
                              fontWeight: 700,
                              cursor: "pointer",
                            }}
                          >
                            <ArrowLeft size={14} />
                            Back
                          </button>
                        ) : null}
                        <h1 style={{ fontSize: FS.xl, fontWeight: 800, letterSpacing: "-0.04em", color: T.text, margin: 0 }}>
                          {screenTitle}
                        </h1>
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55, marginTop: SP.sm, maxWidth: 860 }}>
                        {screenSubtitle}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => setShowShortcutDialog(true)}
                        className="helios-focus-ring hidden sm:inline-flex"
                        aria-label="Open keyboard shortcuts"
                        style={{
                          alignItems: "center",
                          gap: SP.xs,
                          border: `1px solid ${T.border}`,
                          background: T.surface,
                          color: T.textSecondary,
                          borderRadius: 999,
                          padding: "8px 12px",
                          fontSize: FS.sm,
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                      >
                        <HelpCircle size={14} />
                        <ShortcutBadge>?</ShortcutBadge>
                      </button>
                      {apiAvailable && (
                        <button
                          type="button"
                          onClick={() => {
                            setShowFeedbackDialog(true);
                            setFeedbackError(null);
                            setFeedbackSuccess(null);
                          }}
                          className="helios-focus-ring inline-flex"
                          aria-label="Open beta feedback dialog"
                          style={{
                            alignItems: "center",
                            gap: SP.xs,
                            border: `1px solid ${T.border}`,
                            background: T.surface,
                            color: T.textSecondary,
                            borderRadius: 999,
                            padding: "8px 12px",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            cursor: "pointer",
                          }}
                        >
                          <MessageSquare size={14} color={T.accent} />
                          <span className="hidden sm:inline">Feedback</span>
                        </button>
                      )}
                      <div className="relative">
                        <button
                          type="button"
                          onClick={() => setShowUserMenu((current) => !current)}
                          className="helios-focus-ring"
                          aria-label="Open user menu"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: 36,
                            height: 36,
                            borderRadius: 999,
                            border: `1px solid ${T.border}`,
                            background: T.surface,
                            color: T.accent,
                            fontSize: FS.xs,
                            fontWeight: 800,
                            cursor: "pointer",
                          }}
                        >
                          {initials}
                        </button>

                        {showUserMenu && (
                          <>
                            <div className="fixed inset-0 z-40" onClick={() => setShowUserMenu(false)} />
                            <div
                              className="absolute right-0 top-full mt-2 rounded-xl z-50 overflow-hidden"
                              style={{
                                width: 240,
                                background: T.surface,
                                border: `1px solid ${T.border}`,
                                boxShadow: "0 18px 48px rgba(0,0,0,0.38)",
                              }}
                            >
                              {user ? (
                                <div style={{ padding: PAD.default, borderBottom: `1px solid ${T.border}` }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: SP.sm, marginBottom: SP.xs }}>
                                    <User size={14} color={T.accent} />
                                    <span style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{user.name || user.email}</span>
                                  </div>
                                  <div style={{ fontSize: FS.sm, color: T.textSecondary }}>{user.email}</div>
                                  <div
                                    style={{
                                      marginTop: SP.sm,
                                      display: "inline-flex",
                                      alignItems: "center",
                                      borderRadius: 999,
                                      background: `${T.accent}${O["12"]}`,
                                      color: T.accent,
                                      fontSize: FS.xs,
                                      fontWeight: 800,
                                      padding: "4px 8px",
                                    }}
                                  >
                                    {roleLabel(user.role)}
                                  </div>
                                </div>
                              ) : null}
                              <button
                                type="button"
                                onClick={() => {
                                  setShowUserMenu(false);
                                  setShowShortcutDialog(true);
                                }}
                                className="helios-focus-ring"
                                style={{
                                  width: "100%",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  gap: SP.sm,
                                  padding: PAD.default,
                                  background: "transparent",
                                  border: "none",
                                  color: T.textSecondary,
                                  fontSize: FS.sm,
                                  fontWeight: 600,
                                  cursor: "pointer",
                                  textAlign: "left",
                                }}
                              >
                                <span style={{ display: "inline-flex", alignItems: "center", gap: SP.sm }}>
                                  <Command size={14} />
                                  Keyboard shortcuts
                                </span>
                                <ShortcutBadge>?</ShortcutBadge>
                              </button>
                              {authRequired ? (
                                <button
                                  type="button"
                                  onClick={handleLogout}
                                  className="helios-focus-ring"
                                  style={{
                                    width: "100%",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: SP.sm,
                                    padding: PAD.default,
                                    background: "transparent",
                                    border: "none",
                                    color: T.red,
                                    fontSize: FS.sm,
                                    fontWeight: 700,
                                    cursor: "pointer",
                                    textAlign: "left",
                                  }}
                                >
                                  <LogOut size={14} />
                                  Sign out
                                </button>
                              ) : null}
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex lg:hidden items-center gap-2 overflow-x-auto pb-1">
                        {shellTabs.map((item) => {
                          const Icon = item.icon;
                          const active = item.id === tab;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => {
                                setSelected(null);
                                setTab(item.id);
                              }}
                              className="helios-focus-ring shrink-0"
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: SP.xs,
                                border: `1px solid ${active ? `${shellPillarMeta.accent}${O["20"]}` : T.border}`,
                                background: active ? shellPillarMeta.softBackground : T.surface,
                                color: active ? shellPillarMeta.accent : T.textSecondary,
                                borderRadius: 999,
                                padding: "8px 12px",
                                fontSize: FS.sm,
                                fontWeight: 700,
                                cursor: "pointer",
                              }}
                            >
                              <Icon size={14} />
                              {item.label}
                            </button>
                          );
                        })}
                      </div>

                      {showSupportingLayerControls ? (
                        <div className="flex flex-wrap items-center gap-2">
                          {(Object.keys(WORKFLOW_LANE_META) as WorkflowLane[]).map((lane) => {
                            const meta = WORKFLOW_LANE_META[lane];
                            const active = workflowMode === lane;
                            return (
                              <button
                                key={lane}
                                type="button"
                                onClick={() => setWorkflowMode(lane)}
                                className="helios-focus-ring"
                                style={{
                                  border: `1px solid ${active ? `${meta.accent}${O["20"]}` : T.border}`,
                                  background: active ? meta.softBackground : T.surface,
                                  color: active ? meta.accent : T.textSecondary,
                                  borderRadius: 999,
                                  padding: "8px 12px",
                                  fontSize: FS.sm,
                                  fontWeight: 700,
                                  cursor: "pointer",
                                }}
                                title={meta.description}
                              >
                                {meta.shortLabel}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {tab === "portfolio" && !selected ? (
                        <label
                          className="helios-focus-ring"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: SP.xs,
                            borderRadius: 999,
                            border: `1px solid ${T.border}`,
                            background: T.surface,
                            padding: "0 12px",
                            minWidth: 240,
                          }}
                        >
                          <Search size={14} color={T.textTertiary} />
                          <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search cases, vendors, or countries"
                            aria-label="Search cases"
                            style={{
                              flex: 1,
                              minWidth: 0,
                              background: "transparent",
                              border: "none",
                              outline: "none",
                              color: T.text,
                              fontSize: FS.sm,
                              padding: "10px 0",
                            }}
                          />
                        </label>
                      ) : null}

                      {!selected && tab === "portfolio" ? (
                        <button
                          type="button"
                          onClick={() => {
                            setSelected(null);
                            setTab("helios");
                          }}
                          className="helios-focus-ring"
                          aria-label="Open briefing"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: SP.xs,
                            border: `1px solid ${T.border}`,
                            background: T.surface,
                            color: T.textSecondary,
                            borderRadius: 999,
                            padding: "8px 12px",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            cursor: "pointer",
                          }}
                        >
                          <Shield size={14} />
                          Briefing
                        </button>
                      ) : null}

                      <div
                        title={apiAvailable ? "API connected" : "Offline"}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: SP.xs,
                          borderRadius: 999,
                          border: `1px solid ${apiAvailable ? `${T.green}${O["20"]}` : T.border}`,
                          background: apiAvailable ? `${T.green}${O["08"]}` : T.surface,
                          color: apiAvailable ? T.green : T.textSecondary,
                          padding: "8px 12px",
                          fontSize: FS.sm,
                          fontWeight: 700,
                        }}
                      >
                        {apiAvailable ? <Wifi size={14} /> : <WifiOff size={14} />}
                        {apiAvailable ? "Live" : "Offline"}
                      </div>
                    </div>
                  </div>
                </div>
              </header>

              <main className="flex-1 min-h-0 overflow-auto" style={{ padding: selected || tab === "graph" || tab === "dashboard" || tab === "axiom" ? 0 : PAD.default }}>
                <div
                  style={{
                    minHeight: "100%",
                    padding: selected || tab === "graph" || tab === "dashboard" || tab === "axiom" ? 0 : 0,
                  }}
                >
                  {shellContent}
                </div>
              </main>

              <footer
                className="shrink-0"
                style={{
                  borderTop: `1px solid ${T.borderStrong}`,
                  background: FX.shell,
                  padding: `${SP.sm}px ${PAD.default}`,
                }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div style={{ fontSize: FS.sm, color: T.textSecondary }}>
                    Helios v5.2.1 · {cases.length} cases in memory
                    {user ? ` · ${user.email}` : ""}
                  </div>
                  <div style={{ fontSize: FS.xs, color: T.textTertiary }}>
                    AXIOM closes collection gaps. The graph keeps the evidence relationships visible.
                  </div>
                </div>
              </footer>
            </div>
          </div>
        )}

        <Dialog
          open={showLoginDialog}
          onOpenChange={(open) => {
            setShowLoginDialog(open);
            if (!open) {
              setLoginError(null);
              setLoginPassword("");
            }
          }}
        >
          <DialogContent style={{ background: T.surface, border: `1px solid ${T.border}`, color: T.text, maxWidth: 480 }}>
            <DialogHeader>
              <DialogTitle style={{ color: T.text }}>Sign in to continue</DialogTitle>
              <DialogDescription style={{ color: T.muted }}>
                Briefing stays simple. Sign in only when AXIOM needs to actually work the brief.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleDialogLogin} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span style={{ fontSize: FS.sm, color: T.muted }}>Email</span>
                <input
                  value={loginEmail}
                  onChange={(event) => setLoginEmail(event.target.value)}
                  type="email"
                  autoComplete="email"
                  required
                  className="helios-focus-ring"
                  style={{
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                    borderRadius: 12,
                    padding: `${SP.sm}px ${PAD.default}px`,
                    fontSize: FS.sm,
                  }}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span style={{ fontSize: FS.sm, color: T.muted }}>Password</span>
                <input
                  value={loginPassword}
                  onChange={(event) => setLoginPassword(event.target.value)}
                  type="password"
                  autoComplete="current-password"
                  required
                  className="helios-focus-ring"
                  style={{
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                    borderRadius: 12,
                    padding: `${SP.sm}px ${PAD.default}px`,
                    fontSize: FS.sm,
                  }}
                />
              </label>
              {loginError ? (
                <InlineMessage tone="danger" message={loginError} />
              ) : null}
              <DialogFooter>
                <button
                  type="button"
                  onClick={() => setShowLoginDialog(false)}
                  className="helios-focus-ring"
                  style={{
                    background: T.bg,
                    color: T.text,
                    border: `1px solid ${T.border}`,
                    borderRadius: 999,
                    padding: `${SP.sm}px ${PAD.default}px`,
                    fontSize: FS.sm,
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Not now
                </button>
                <button
                  type="submit"
                  disabled={loginSubmitting}
                  className="helios-focus-ring"
                  style={{
                    background: loginSubmitting ? `${T.accent}${O["20"]}` : T.accent,
                    color: T.textInverse,
                    border: "none",
                    borderRadius: 999,
                    padding: `${SP.sm}px ${PAD.default}px`,
                    fontSize: FS.sm,
                    fontWeight: 800,
                    cursor: loginSubmitting ? "default" : "pointer",
                  }}
                >
                  {loginSubmitting ? "Signing in..." : "Continue"}
                </button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        <Dialog open={showFeedbackDialog} onOpenChange={setShowFeedbackDialog}>
          <DialogContent style={{ background: T.surface, border: `1px solid ${T.border}`, color: T.text, maxWidth: 640 }}>
            <DialogHeader>
              <DialogTitle style={{ color: T.text }}>Submit beta feedback</DialogTitle>
              <DialogDescription style={{ color: T.muted }}>
                Captures the current workflow, screen, and case context for triage.
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
                  Workflow: {selected ? PRODUCT_PILLAR_META.vendor_assessment.label : PRODUCT_PILLAR_META[productFocus].label}
                  {selected ? ` · Emphasis: ${WORKFLOW_LANE_META[workflowLaneForCase(selected)].label}` : ""}
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

        <Dialog open={showShortcutDialog} onOpenChange={setShowShortcutDialog}>
          <DialogContent style={{ background: T.surface, border: `1px solid ${T.border}`, color: T.text, maxWidth: 720 }}>
            <DialogHeader>
              <DialogTitle style={{ color: T.text }}>Keyboard shortcuts</DialogTitle>
              <DialogDescription style={{ color: T.muted }}>
                Helios is moving toward a queue-first operator workflow. These shortcuts keep the shell and case workspace fast.
              </DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[
                { keys: ["⌘K"], label: "Open command palette" },
                { keys: ["J", "K"], label: "Move through the queue or cycle the active case" },
                { keys: ["Enter"], label: "Open the focused case from Workbench" },
                { keys: ["D"], label: "Jump to decision workspace in case detail" },
                { keys: ["E"], label: "Jump to evidence workspace in case detail" },
                { keys: ["G"], label: "Jump to graph view or open Graph Intel" },
                { keys: ["Esc"], label: "Close overlays or return to the previous shell state" },
                { keys: ["?"], label: "Open this shortcuts overlay" },
              ].map((shortcut) => (
                <div
                  key={shortcut.label}
                  className="rounded-xl"
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: "space-between",
                    gap: SP.sm,
                    padding: PAD.default,
                    border: `1px solid ${T.border}`,
                    background: T.bg,
                  }}
                >
                  <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>{shortcut.label}</div>
                  <div style={{ display: "inline-flex", gap: SP.xs, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    {shortcut.keys.map((key) => (
                      <ShortcutBadge key={`${shortcut.label}-${key}`}>{key}</ShortcutBadge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </DialogContent>
        </Dialog>

        {/* Global Command Palette */}
        <CommandPalette
          isOpen={cmdPaletteOpen}
          onClose={() => setCmdPaletteOpen(false)}
          onNavigate={(tabId) => {
            setTab(tabId as Tab);
            setSelected(null);
            setCmdPaletteOpen(false);
          }}
          onSelectCase={(caseId) => {
            const c = cases.find(cs => cs.id === caseId);
            if (c) {
              setSelected(c);
              setTab("portfolio");
              setCmdPaletteOpen(false);
            }
          }}
          cases={cases.map(c => ({
            id: c.id,
            name: c.name || "",
            vendor: c.name || "",
            tier: parseTier(c.cal?.tier).toUpperCase(),
          }))}
          currentCaseId={selected?.id}
        />
      </div>
    </ErrorBoundary>
  );
}
