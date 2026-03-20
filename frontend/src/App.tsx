import { useCallback, useEffect, useState } from "react";
import { Shield, Search, Wifi, WifiOff, LogOut, User, Settings } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import { CaseDetail } from "@/components/xiphos/case-detail";
import { LoginScreen } from "@/components/xiphos/login-screen";
import { AdminPanel } from "@/components/xiphos/admin-panel";
import { HeliosLanding } from "@/components/xiphos/helios-landing";
import { PortfolioScreen } from "@/components/xiphos/portfolio-screen";
import { DemoCompare } from "@/components/xiphos/demo-compare";
import { rescore, generateDossier as apiDossier, fetchCases, setAuthErrorHandler } from "@/lib/api";
import { openDossier } from "@/lib/dossier";
import { checkAuthEnabled, getToken, getUser, clearSession, roleLabel, hasPermission } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";
import type { VettingCase, Calibration } from "@/lib/types";
import { parseTier, tierToRisk } from "@/lib/tokens";

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
  };

  const meanConf = cal.contributions.length > 0
    ? cal.contributions.reduce((s, c) => s + (c.confidence ?? c.weight ?? 0), 0) / cal.contributions.length : 0;

  return {
    p: cal.calibrated_probability,
    tier: parseTier(cal.calibrated_tier),
    combinedTier: parseTier(cal.combined_tier ?? cal.calibrated_tier),
    lo: cal.interval.lower,
    hi: cal.interval.upper,
    cov: cal.interval.coverage ?? 0,
    mc: meanConf,
    ct: cal.contributions.map((c) => ({
      n: c.factor, raw: c.raw_score, c: c.confidence ?? c.weight ?? 0, s: c.signed_contribution, d: c.description,
    })),
    stops: cal.hard_stop_decisions.map((h) => ({ t: h.trigger, x: h.explanation, c: h.confidence })),
    flags: cal.soft_flags.map((f) => ({ t: f.trigger, x: f.explanation, c: f.confidence })),
    finds: cal.narratives?.findings ?? [],
    miv: (cal.marginal_information_values ?? []).map((m) => ({
      t: m.recommendation ?? m.factor ?? "", i: m.expected_info_gain_pp ?? m.expected_shift_pp ?? 0, tp: m.tier_change_probability,
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
  };
}

/** Convert an API case to our internal VettingCase */
function apiCaseToVetting(ac: { id: string; vendor_name: string; status: string; created_at: string; score: Record<string, unknown> | null; profile?: string; program?: string; country?: string }): VettingCase | null {
  if (!ac.score) return null;
  const score = ac.score as { composite_score: number; is_hard_stop: boolean; calibrated: Record<string, unknown> };
  if (!score.calibrated) return null;
  const cal = mapCalibration(score.calibrated);
  const mc = cal.ct.length > 0 ? cal.ct.reduce((s, c) => s + c.c, 0) / cal.ct.length : 0;
  return {
    id: ac.id,
    name: ac.vendor_name,
    cc: (score.calibrated as { calibrated_tier?: string })?.calibrated_tier ? "" : "",
    date: ac.created_at,
    rl: tierToRisk(cal.tier),
    sc: score.composite_score,
    conf: mc,
    cal,
    profile: ac.profile,
    program: ac.program,
    ...(() => {
      const geoCt = cal.ct.find((c) => c.n === "Geography");
      const ccMatch = geoCt?.d?.match(/\(([A-Z]{2})\)/);
      return ccMatch ? { cc: ccMatch[1] } : {};
    })(),
  };
}

type Tab = "helios" | "portfolio" | "admin";

export default function App() {
  const isFileMode = window.location.protocol === "file:";

  // Auth state
  const [authRequired, setAuthRequired] = useState<boolean | null>(isFileMode ? false : null);
  const [user, setUser] = useState<AuthUser | null>(getUser());
  const [showUserMenu, setShowUserMenu] = useState(false);

  // App state -- start empty; cases load from backend after login
  const [cases, setCases] = useState<VettingCase[]>([]);
  const [selected, setSelected] = useState<VettingCase | null>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("helios");
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(isFileMode ? false : null);
  // onboarding dismissed state removed in UI redesign

  const loadCases = useCallback(() => {
    fetchCases(200)
      .then((apiCases) => {
        const converted = apiCases
          .map((ac) => apiCaseToVetting(ac as unknown as Parameters<typeof apiCaseToVetting>[0]))
          .filter((c): c is VettingCase => c !== null);
        if (converted.length > 0) {
          setCases(converted);
        }
      })
      .catch(() => {
        // Token might be expired
        if (authRequired) {
          clearSession();
          setUser(null);
        }
      });
  }, [authRequired]);

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

  function handleLogin(u: AuthUser) {
    setUser(u);
    setApiAvailable(true);
    loadCases();
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setShowUserMenu(false);
    setCases([]);
    setSelected(null);
    setTab("helios");
  }

  const handleCaseCreated = async (caseId: string) => {
    const fresh = await fetchCases();
    const mapped = fresh.map(apiCaseToVetting).filter(Boolean) as VettingCase[];
    setCases(mapped);
    const newCase = mapped.find((c) => c.id === caseId);
    if (newCase) setSelected(newCase);
  };

  // Demo mode: /demo or /#demo path renders public comparison page
  const isDemo = window.location.pathname === "/demo"
    || window.location.hash === "#demo"
    || window.location.hash === "#/demo";

  if (isDemo) {
    return (
      <div className="min-h-screen" style={{ background: T.bg, color: T.text }}>
        <DemoCompare />
      </div>
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
    return <LoginScreen onLogin={handleLogin} needsSetup={false} />;
  }

  const handleRescore = async (caseId: string) => {
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
    if (apiAvailable) {
      try {
        const result = await apiDossier(caseId);
        if (result.download_url) {
          const token = getToken();
          const sep = result.download_url.includes("?") ? "&" : "?";
          window.open(`${result.download_url}${token ? sep + "token=" + encodeURIComponent(token) : ""}`, "_blank");
          return;
        }
      } catch { /* fall through */ }
    }
    openDossier(c);
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
    <div className="h-screen flex flex-col overflow-hidden" style={{ background: T.bg, color: T.text }}>
      {/* Header */}
      <header
        className="flex items-center justify-between px-4 lg:px-6 shrink-0"
        style={{ height: 48, borderBottom: `1px solid ${T.border}`, background: T.bg }}
      >
        <div className="flex items-center gap-2">
          <Shield size={18} color={T.accent} />
          <div className="flex items-baseline gap-2">
            <span className="font-bold" style={{ fontSize: FS.md, color: T.text }}>
              Helios
            </span>
            <span style={{ fontSize: FS.sm, color: T.muted }}>
              by Xiphos
            </span>
          </div>


          {/* Tab navigation */}
          {!selected && (
            <div className="flex items-center gap-0.5 ml-4">
              <button
                onClick={() => setTab("helios")}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 border-none cursor-pointer"
                style={{
                  fontSize: FS.sm,
                  background: tab === "helios" ? "#C4A05222" : "transparent",
                  color: tab === "helios" ? "#C4A052" : T.muted,
                }}
              >
                <Shield size={12} />
                Helios
              </button>
              <button
                onClick={() => setTab("portfolio")}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 border-none cursor-pointer"
                style={{
                  fontSize: FS.sm,
                  background: tab === "portfolio" ? T.accent + "22" : "transparent",
                  color: tab === "portfolio" ? T.accent : T.muted,
                }}
              >
                <Shield size={12} />
                Portfolio
              </button>
              {hasPermission(user, "admin") && (
                <button
                  onClick={() => setTab("admin")}
                  className="inline-flex items-center gap-1 rounded px-2.5 py-1 border-none cursor-pointer"
                  style={{
                    fontSize: FS.sm,
                    background: tab === "admin" ? T.accent + "22" : "transparent",
                    color: tab === "admin" ? T.accent : T.muted,
                  }}
                >
                  <Settings size={12} />
                  Admin
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {apiAvailable !== null && (
            <div className="flex items-center gap-1" title={apiAvailable ? "API connected" : "Scoring engine runs client-side"}>
              {apiAvailable ? <Wifi size={12} color={T.green} /> : <WifiOff size={12} color={T.muted} />}
              <span style={{ fontSize: FS.sm, fontWeight: 600, color: apiAvailable ? T.green : T.muted }}>
                {apiAvailable ? "Live" : "Offline"}
              </span>
            </div>
          )}
          {tab === "portfolio" && !selected && (
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2" color={T.muted} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search vendors..."
                className="rounded outline-none"
                style={{
                  paddingLeft: 28, paddingRight: 10, paddingTop: 5, paddingBottom: 5,
                  fontSize: FS.sm, width: 200,
                  background: T.surface, border: `1px solid ${T.border}`, color: T.text,
                }}
              />
            </div>
          )}

          {/* User menu */}
          <div className="relative">
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="flex items-center gap-1.5 rounded cursor-pointer"
              style={{
                background: "transparent",
                border: "none",
                padding: "2px 4px",
              }}
            >
              <div
                className="flex items-center justify-center rounded-full font-bold"
                style={{ width: 28, height: 28, fontSize: FS.sm, background: T.accent + "22", color: T.accent }}
              >
                {initials}
              </div>
              {user && (
                <span className="hidden sm:inline" style={{ fontSize: FS.sm, color: T.muted, fontWeight: 600 }}>
                  {roleLabel(user.role)}
                </span>
              )}
            </button>

            {showUserMenu && (
              <>
                {/* Backdrop */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setShowUserMenu(false)}
                />
                {/* Dropdown */}
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
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-3 lg:p-4">
        <div className="max-w-[1400px] mx-auto h-full">
          {selected ? (
            <CaseDetail
              c={selected}
              onBack={() => setSelected(null)}
              onRescore={apiAvailable ? handleRescore : undefined}
              onDossier={handleDossier}
            />
          ) : tab === "helios" ? (
            <HeliosLanding
              onCaseCreated={handleCaseCreated}
              onNavigate={(t) => setTab(t as Tab)}
              cases={cases}
            />
          ) : tab === "portfolio" ? (
            <PortfolioScreen
              cases={filtered}
              onSelect={setSelected}
            />
          ) : tab === "admin" && user ? (
            <AdminPanel currentUser={user} />
          ) : (
            <HeliosLanding
              onCaseCreated={handleCaseCreated}
              onNavigate={(t) => setTab(t as Tab)}
              cases={cases}
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
    </div>
  );
}
