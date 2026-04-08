import { useState, useEffect } from "react";
import { T, FS } from "@/lib/tokens";
import {
  Brain, Loader2, RefreshCw, CheckCircle, XCircle,
  AlertTriangle, Shield, Clock, ChevronDown, ChevronUp,
} from "lucide-react";
import {
  executeCaseAssistantPlan,
  fetchCaseAssistantPlan,
  fetchCaseAssistantSituation,
  submitCaseAssistantFeedback,
  runAIAnalysis,
  fetchAIAnalysis,
  fetchAIConfig,
  submitDecision,
  getDecisions,
} from "@/lib/api";
import type {
  AIAnalysis,
  AssistantAssuranceHybridReview,
  AssistantExportHybridReview,
  AssistantFeedbackType,
  AssistantFeedbackVerdict,
  CaseAssistantExecutionResult,
  CaseAssistantPlan,
  CaseAssistantSituationBrief,
  CyberEvidenceSummary,
  Decision,
} from "@/lib/api";

interface AIAnalysisPanelProps {
  caseId: string;
  vendorName: string;
}

const VERDICT_STYLES: Record<string, { color: string; bg: string; icon: typeof CheckCircle }> = {
  APPROVE: { color: T.green, bg: T.greenBg, icon: CheckCircle },
  CONDITIONAL_APPROVE: { color: T.amber, bg: T.amberBg, icon: AlertTriangle },
  ENHANCED_DUE_DILIGENCE: { color: T.orange || T.amber, bg: T.amberBg, icon: AlertTriangle },
  REJECT: { color: T.red, bg: T.redBg, icon: XCircle },
};

export function AIAnalysisPanel({ caseId, vendorName }: AIAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AIAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [assistantPrompt, setAssistantPrompt] = useState(`Why is ${vendorName} risky right now?`);
  const [assistantPlan, setAssistantPlan] = useState<CaseAssistantPlan | null>(null);
  const [assistantRunId, setAssistantRunId] = useState<string | null>(null);
  const [assistantSituation, setAssistantSituation] = useState<CaseAssistantSituationBrief | null>(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);
  const [assistantExecution, setAssistantExecution] = useState<CaseAssistantExecutionResult | null>(null);
  const [assistantExecutionLoading, setAssistantExecutionLoading] = useState(false);
  const [assistantExecutionError, setAssistantExecutionError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["summary", "concerns", "actions"])
  );
  const [latestDecision, setLatestDecision] = useState<Decision | null>(null);
  const [decidingLoading, setDecidingLoading] = useState(false);
  const [decidingError, setDecidingError] = useState<string | null>(null);

  // Check if AI is configured and load existing analysis and decisions
  useEffect(() => {
    fetchAIConfig()
      .then((cfg) => setConfigured(cfg.configured))
      .catch(() => setConfigured(false));

    fetchAIAnalysis(caseId)
      .then((a) => setAnalysis(a))
      .catch(() => {}); // No existing analysis, that's fine

    getDecisions(caseId, 1)
      .then((result) => setLatestDecision(result.latest_decision))
      .catch(() => {}); // No existing decisions, that's fine
  }, [caseId]);

  useEffect(() => {
    setAssistantPrompt(`Why is ${vendorName} risky right now?`);
    setAssistantPlan(null);
    setAssistantRunId(null);
    setAssistantSituation(null);
    setAssistantError(null);
    setAssistantExecution(null);
    setAssistantExecutionError(null);
  }, [caseId, vendorName]);

  useEffect(() => {
    fetchCaseAssistantSituation(caseId)
      .then((brief) => {
        setAssistantSituation(brief);
        if (brief.run_id) {
          setAssistantRunId(brief.run_id);
        }
      })
      .catch(() => {});
  }, [caseId]);

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runAIAnalysis(caseId);
      setAnalysis(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  const handleAssistantPlan = async (promptOverride?: string, autoExecute = false) => {
    const nextPrompt = (promptOverride ?? assistantPrompt).trim();
    if (!nextPrompt) {
      setAssistantError("Ask Helios what you want checked first.");
      return;
    }
    setAssistantPrompt(nextPrompt);
    setAssistantLoading(true);
    setAssistantError(null);
    setAssistantExecution(null);
    setAssistantExecutionError(null);
    try {
      const result = await fetchCaseAssistantPlan(caseId, nextPrompt, autoExecute);
      setAssistantPlan(result);
      setAssistantRunId(result.run_id ?? null);
      const nextSituation = await fetchCaseAssistantSituation(caseId);
      setAssistantSituation(nextSituation);
      if (result.execution) {
        setAssistantExecution(result.execution);
      }
    } catch (e) {
      setAssistantError(e instanceof Error ? e.message : "Planner request failed");
    } finally {
      setAssistantLoading(false);
    }
  };

  const handleAssistantExecute = async () => {
    if (!assistantPlan) {
      setAssistantExecutionError("Plan the next steps before executing tools.");
      return;
    }
    const approvedToolIds = assistantPlan.plan.filter((step) => step.required).map((step) => step.tool_id);
    setAssistantExecutionLoading(true);
    setAssistantExecutionError(null);
    try {
      const result = await executeCaseAssistantPlan(caseId, assistantPlan.analyst_prompt, approvedToolIds, assistantRunId ?? undefined);
      setAssistantExecution(result);
      if (result.run_id) {
        setAssistantRunId(result.run_id);
      }
      const nextSituation = await fetchCaseAssistantSituation(caseId);
      setAssistantSituation(nextSituation);
    } catch (e) {
      setAssistantExecutionError(e instanceof Error ? e.message : "Approved execution failed");
    } finally {
      setAssistantExecutionLoading(false);
    }
  };

  const handleDecision = async (decision: "approve" | "reject" | "escalate") => {
    setDecidingLoading(true);
    setDecidingError(null);
    try {
      const result = await submitDecision(caseId, decision);
      setLatestDecision({
        id: result.decision_id,
        vendor_id: result.vendor_id,
        decision: result.decision as "approve" | "reject" | "escalate",
        decided_by: result.decided_by,
        decided_by_email: result.decided_by_email,
        reason: result.reason,
        posterior_at_decision: result.posterior_at_decision,
        tier_at_decision: result.tier_at_decision,
        created_at: result.created_at,
      });
    } catch (e) {
      setDecidingError(e instanceof Error ? e.message : "Decision submission failed");
    } finally {
      setDecidingLoading(false);
    }
  };

  if (configured === null) {
    return (
      <div className="rounded-lg p-4 glass-card animate-fade-in">
        <div className="flex items-center gap-2">
          <Brain size={14} color={T.muted} className="animate-pulse" />
          <span style={{ fontSize: FS.sm, color: T.muted }}>Checking AI configuration...</span>
        </div>
      </div>
    );
  }

  if (!configured && !analysis) {
    return (
      <div className="rounded-lg p-4 glass-card animate-fade-in">
        <div className="flex items-center gap-2 mb-2">
          <Brain size={14} color={T.muted} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            AI Risk Analysis
          </span>
        </div>
        <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>
          No AI provider configured. Go to <strong style={{ color: T.accent }}>Admin &gt; AI Settings</strong> to
          set up your API key for Claude, OpenAI, or Gemini.
        </div>
        <div style={{ marginTop: 12 }}>
          <ControlPlaneSection
            caseId={caseId}
            vendorName={vendorName}
            prompt={assistantPrompt}
            onPromptChange={setAssistantPrompt}
            onRun={handleAssistantPlan}
            onAutoplay={handleAssistantPlan}
            onExecute={handleAssistantExecute}
            plan={assistantPlan}
            loading={assistantLoading}
            error={assistantError}
            execution={assistantExecution}
            executionLoading={assistantExecutionLoading}
            executionError={assistantExecutionError}
            runId={assistantRunId}
            onRunIdChange={setAssistantRunId}
            situation={assistantSituation}
            onSituationChange={setAssistantSituation}
          />
        </div>
      </div>
    );
  }

  const a = analysis?.analysis;
  const verdict = a?.verdict || "";
  const vs = VERDICT_STYLES[verdict] || VERDICT_STYLES.ENHANCED_DUE_DILIGENCE;
  const decisionStyle =
    latestDecision?.decision === "approve"
      ? { color: T.green, bg: T.greenBg, icon: CheckCircle }
      : latestDecision?.decision === "reject"
        ? { color: T.red, bg: T.redBg, icon: XCircle }
        : { color: T.amber, bg: T.amberBg, icon: AlertTriangle };

  return (
    <div className="rounded-lg glass-panel animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between p-4" style={{ borderBottom: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2">
          <Brain size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            AI Risk Analysis
          </span>
          <span style={{ fontSize: FS.sm, color: T.dim, fontWeight: 500 }}>
            Xiphos Intelligence Engine
          </span>
        </div>
        <div className="flex items-center gap-2">
          {analysis && (
            <span className="flex items-center gap-1 font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
              <Clock size={10} />
              {(analysis.elapsed_ms / 1000).toFixed(1)}s
              {" | "}
              {analysis.prompt_tokens + analysis.completion_tokens} tokens
            </span>
          )}
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: "5px 10px",
              fontSize: FS.sm,
              background: loading ? T.raised : T.accent + "18",
              color: loading ? T.muted : T.accent,
              borderColor: loading ? T.border : T.accent + "44",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? (
              <Loader2 size={11} className="animate-spin" />
            ) : analysis ? (
              <RefreshCw size={11} />
            ) : (
              <Brain size={11} />
            )}
            {loading ? "Analyzing..." : analysis ? "Re-Analyze" : "Run AI Analysis"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          className="flex items-center gap-2 mx-4 mt-3 rounded p-2.5"
          style={{ background: T.redBg, border: `1px solid ${T.red}33` }}
        >
          <XCircle size={12} color={T.red} className="shrink-0" />
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      <div className="p-4" style={{ borderBottom: `1px solid ${T.border}` }}>
        <ControlPlaneSection
          caseId={caseId}
          vendorName={vendorName}
          prompt={assistantPrompt}
          onPromptChange={setAssistantPrompt}
          onRun={handleAssistantPlan}
          onAutoplay={handleAssistantPlan}
          onExecute={handleAssistantExecute}
          plan={assistantPlan}
          loading={assistantLoading}
          error={assistantError}
          execution={assistantExecution}
          executionLoading={assistantExecutionLoading}
          executionError={assistantExecutionError}
          runId={assistantRunId}
          onRunIdChange={setAssistantRunId}
          situation={assistantSituation}
          onSituationChange={setAssistantSituation}
        />
      </div>

      {/* Loading state */}
      {loading && !analysis && (
        <div className="p-8 flex flex-col items-center gap-3">
          <Loader2 size={24} color={T.accent} className="animate-spin" />
          <span style={{ fontSize: FS.sm, color: T.muted }}>
            Generating intelligence assessment for {vendorName}...
          </span>
          <span style={{ fontSize: FS.sm, color: T.muted }}>
            This typically takes 5-15 seconds depending on provider
          </span>
        </div>
      )}

      {/* Analysis content */}
      {a && (
        <div className="p-4 flex flex-col gap-3">
          {/* Verdict badge */}
          <div
            className="flex items-center gap-2 rounded-lg p-3"
            style={{ background: vs.bg, border: `1px solid ${vs.color}33` }}
          >
            <vs.icon size={16} color={vs.color} />
            <span className="font-mono font-bold" style={{ fontSize: FS.md, color: vs.color }}>
              {verdict.replace(/_/g, " ")}
            </span>
          </div>

          {/* Decision workflow */}
          {latestDecision ? (
            <div
              className="flex items-center gap-2 p-3 rounded-lg"
              style={{ background: decisionStyle.bg, border: `1px solid ${decisionStyle.color}33` }}
            >
              <decisionStyle.icon size={14} color={decisionStyle.color} />
              <div className="flex flex-col gap-0.5" style={{ flex: 1 }}>
                <span className="font-semibold" style={{ fontSize: FS.sm, color: decisionStyle.color }}>
                  Decision Recorded: {latestDecision.decision.toUpperCase()}
                </span>
                <span style={{ fontSize: FS.sm, color: T.dim }}>
                  {new Date(latestDecision.created_at).toLocaleString()} by {latestDecision.decided_by_email || latestDecision.decided_by}
                </span>
              </div>
            </div>
          ) : (
            <div
              className="flex items-center gap-2 p-3 rounded-lg"
              style={{ background: T.raised, border: `1px solid ${T.border}` }}
            >
              <span style={{ fontSize: FS.sm, color: T.muted, fontWeight: 500 }}>Decision</span>
              <button
                onClick={() => handleDecision("approve")}
                disabled={decidingLoading}
                className="inline-flex items-center gap-1.5 rounded-lg font-semibold cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "5px 14px", fontSize: FS.sm,
                  background: decidingLoading ? T.border : T.greenBg,
                  color: decidingLoading ? T.muted : T.green,
                  border: `1px solid ${T.green}33`,
                  opacity: decidingLoading ? 0.7 : 1,
                }}
              >
                {decidingLoading ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                Approve
              </button>
              <button
                onClick={() => handleDecision("reject")}
                disabled={decidingLoading}
                className="inline-flex items-center gap-1.5 rounded-lg font-semibold cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "5px 14px", fontSize: FS.sm,
                  background: decidingLoading ? T.border : T.redBg,
                  color: decidingLoading ? T.muted : T.red,
                  border: `1px solid ${T.red}33`,
                  opacity: decidingLoading ? 0.7 : 1,
                }}
              >
                {decidingLoading ? <Loader2 size={12} className="animate-spin" /> : <XCircle size={12} />}
                Reject
              </button>
              <button
                onClick={() => handleDecision("escalate")}
                disabled={decidingLoading}
                className="inline-flex items-center gap-1.5 rounded-lg font-semibold cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "5px 14px", fontSize: FS.sm,
                  background: decidingLoading ? T.border : T.amberBg,
                  color: decidingLoading ? T.muted : T.amber,
                  border: `1px solid ${T.amber}33`,
                  opacity: decidingLoading ? 0.7 : 1,
                }}
              >
                {decidingLoading ? <Loader2 size={12} className="animate-spin" /> : <AlertTriangle size={12} />}
                Escalate
              </button>
              <span style={{ fontSize: FS.sm, color: T.muted, marginLeft: "auto" }}>
                Action will be recorded in audit trail
              </span>
            </div>
          )}

          {/* Decision error */}
          {decidingError && (
            <div
              className="flex items-center gap-2 p-3 rounded-lg"
              style={{ background: T.redBg, border: `1px solid ${T.red}33` }}
            >
              <XCircle size={12} color={T.red} className="shrink-0" />
              <span style={{ fontSize: FS.sm, color: T.red }}>{decidingError}</span>
            </div>
          )}

          {/* Executive Summary */}
          <Section
            title="Executive Summary"
            sectionKey="summary"
            expanded={expandedSections.has("summary")}
            onToggle={toggleSection}
          >
            <p style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6, margin: 0 }}>
              {a.executive_summary}
            </p>
          </Section>

          {/* Risk Narrative */}
          <Section
            title="Risk Narrative"
            sectionKey="narrative"
            expanded={expandedSections.has("narrative")}
            onToggle={toggleSection}
          >
            <p style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6, margin: 0 }}>
              {a.risk_narrative}
            </p>
          </Section>

          {/* Critical Concerns */}
          {a.critical_concerns && a.critical_concerns.length > 0 && (
            <Section
              title={`Critical Concerns (${a.critical_concerns.length})`}
              sectionKey="concerns"
              expanded={expandedSections.has("concerns")}
              onToggle={toggleSection}
              icon={<AlertTriangle size={11} color={T.red} />}
            >
              {a.critical_concerns.map((c, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.sm, color: T.red }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{c}</span>
                </div>
              ))}
            </Section>
          )}

          {/* Mitigating Factors */}
          {a.mitigating_factors && a.mitigating_factors.length > 0 && (
            <Section
              title={`Mitigating Factors (${a.mitigating_factors.length})`}
              sectionKey="mitigating"
              expanded={expandedSections.has("mitigating")}
              onToggle={toggleSection}
              icon={<Shield size={11} color={T.green} />}
            >
              {a.mitigating_factors.map((f, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.sm, color: T.green }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{f}</span>
                </div>
              ))}
            </Section>
          )}

          {/* Recommended Actions */}
          {a.recommended_actions && a.recommended_actions.length > 0 && (
            <Section
              title={`Recommended Actions (${a.recommended_actions.length})`}
              sectionKey="actions"
              expanded={expandedSections.has("actions")}
              onToggle={toggleSection}
            >
              {a.recommended_actions.map((act, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.sm, color: T.accent }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{act}</span>
                </div>
              ))}
            </Section>
          )}

          {/* Regulatory Exposure */}
          <Section
            title="Regulatory Exposure"
            sectionKey="regulatory"
            expanded={expandedSections.has("regulatory")}
            onToggle={toggleSection}
          >
            <p style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6, margin: 0 }}>
              {a.regulatory_exposure}
            </p>
          </Section>

          {/* Confidence Assessment */}
          <Section
            title="Confidence Assessment"
            sectionKey="confidence"
            expanded={expandedSections.has("confidence")}
            onToggle={toggleSection}
          >
            <p style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6, margin: 0 }}>
              {a.confidence_assessment}
            </p>
          </Section>
        </div>
      )}
    </div>
  );
}

function getExportHybridReview(result: Record<string, unknown>): AssistantExportHybridReview | null {
  const review = result.hybrid_review;
  if (!review || typeof review !== "object") return null;
  const candidate = review as Record<string, unknown>;
  if (typeof candidate.deterministic_posture !== "string") return null;
  if (typeof candidate.ai_proposed_posture !== "string") return null;
  if (typeof candidate.final_posture !== "string") return null;
  return review as AssistantExportHybridReview;
}

function getAssuranceHybridReview(result: Record<string, unknown>): AssistantAssuranceHybridReview | null {
  const review = result.hybrid_review;
  if (!review || typeof review !== "object") return null;
  const candidate = review as Record<string, unknown>;
  if (typeof candidate.deterministic_posture !== "string") return null;
  if (typeof candidate.ai_proposed_posture !== "string") return null;
  if (typeof candidate.final_posture !== "string") return null;
  return review as AssistantAssuranceHybridReview;
}

function getCyberEvidenceSummary(result: Record<string, unknown>): CyberEvidenceSummary | null {
  const summary = result.cyber_evidence_summary;
  if (!summary || typeof summary !== "object") return null;
  return summary as CyberEvidenceSummary;
}

function stringList(values: string[] | undefined): string[] {
  if (!Array.isArray(values)) return [];
  const deduped: string[] = [];
  for (const value of values) {
    const text = String(value || "").trim();
    if (text && !deduped.includes(text)) deduped.push(text);
  }
  return deduped;
}

function threatPressureTone(pressure?: string | null) {
  switch (String(pressure || "").toLowerCase()) {
    case "high":
      return { color: T.red, background: T.redBg };
    case "medium":
      return { color: T.amber, background: T.amberBg };
    case "low":
      return { color: T.green, background: T.greenBg };
    default:
      return { color: T.muted, background: T.raised };
  }
}

function ControlPlaneSection({
  caseId,
  vendorName,
  prompt,
  onPromptChange,
  onRun,
  onAutoplay,
  onExecute,
  plan,
  loading,
  error,
  execution,
  executionLoading,
  executionError,
  runId,
  onRunIdChange,
  situation,
  onSituationChange,
}: {
  caseId: string;
  vendorName: string;
  prompt: string;
  onPromptChange: (value: string) => void;
  onRun: (prompt?: string, autoExecute?: boolean) => void;
  onAutoplay: (prompt?: string, autoExecute?: boolean) => void;
  onExecute: () => void;
  plan: CaseAssistantPlan | null;
  loading: boolean;
  error: string | null;
  execution: CaseAssistantExecutionResult | null;
  executionLoading: boolean;
  executionError: string | null;
  runId: string | null;
  onRunIdChange: (value: string | null) => void;
  situation: CaseAssistantSituationBrief | null;
  onSituationChange: (value: CaseAssistantSituationBrief | null) => void;
}) {
  const [feedbackVerdict, setFeedbackVerdict] = useState<AssistantFeedbackVerdict>("partial");
  const [feedbackType, setFeedbackType] = useState<AssistantFeedbackType>("tool_missing");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [suggestedToolsInput, setSuggestedToolsInput] = useState("");
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [feedbackSuccess, setFeedbackSuccess] = useState<string | null>(null);

  const quickPrompts = [
    `Why is ${vendorName} risky right now?`,
    "Trace the strongest control path and show the evidence.",
    "Tell me which missing identifiers would most change the decision.",
  ];
  const anomalyTone = (severity: string) =>
    severity === "high"
      ? { color: T.red, background: T.redBg }
      : severity === "medium"
        ? { color: T.amber, background: T.amberBg }
        : { color: T.muted, background: T.raised };
  const stepTone = (mode: string) =>
    mode === "generate"
      ? { color: T.accent, background: `${T.accent}18` }
      : mode === "error" || mode === "blocked"
        ? { color: T.red, background: T.redBg }
      : mode === "unavailable"
          ? { color: T.muted, background: T.surface }
      : mode === "review"
        ? { color: T.amber, background: T.amberBg }
        : { color: T.green, background: T.greenBg };

  useEffect(() => {
    setFeedbackVerdict("partial");
    setFeedbackType("tool_missing");
    setFeedbackComment("");
    setSuggestedToolsInput("");
    setFeedbackError(null);
    setFeedbackSuccess(null);
  }, [plan?.generated_at, execution?.executed_at, vendorName]);

  const handleFeedbackSubmit = async () => {
    if (!plan) {
      setFeedbackError("Plan the assistant path before sending feedback.");
      return;
    }
    setFeedbackSubmitting(true);
    setFeedbackError(null);
    setFeedbackSuccess(null);
    try {
      const suggestedToolIds = suggestedToolsInput
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
      const approvedToolIds = plan.plan.filter((step) => step.required).map((step) => step.tool_id);
      const executedToolIds = execution?.executed_steps.map((step) => step.tool_id) ?? [];
      const anomalyCodes = plan.anomalies.map((item) => item.code);
      const result = await submitCaseAssistantFeedback(caseId, {
        run_id: runId ?? undefined,
        prompt: plan.analyst_prompt,
        objective: plan.objective,
        verdict: feedbackVerdict,
        feedback_type: feedbackType,
        comment: feedbackComment.trim(),
        approved_tool_ids: approvedToolIds,
        executed_tool_ids: executedToolIds,
        suggested_tool_ids: suggestedToolIds,
        anomaly_codes: anomalyCodes,
      });
      if (result.run_id) {
        onRunIdChange(result.run_id);
      }
      const nextSituation = await fetchCaseAssistantSituation(caseId);
      onSituationChange(nextSituation);
      setFeedbackSuccess(`Captured signal #${result.feedback_id}`);
    } catch (e) {
      setFeedbackError(e instanceof Error ? e.message : "Failed to capture assistant feedback");
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 12 }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <Brain size={13} color={T.accent} />
            <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
              AI Control Plane
            </span>
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
            Natural-language front door with typed tools, visible plan, and analyst guardrails.
          </div>
        </div>
        {plan && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.text, background: T.surface, border: `1px solid ${T.border}` }}>
              Objective: {plan.objective.replace(/_/g, " ")}
            </span>
            {plan.recommended_view && (
              <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.accent, background: `${T.accent}18`, border: `1px solid ${T.accent}44` }}>
                View: {plan.recommended_view}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-3">
        <textarea
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          placeholder="Ask Helios what to inspect, verify, or explain."
          rows={3}
          style={{
            width: "100%",
            borderRadius: 8,
            border: `1px solid ${T.border}`,
            background: T.surface,
            color: T.text,
            padding: 10,
            fontSize: FS.sm,
            resize: "vertical",
          }}
        />
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => onRun()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: "6px 12px",
              fontSize: FS.sm,
              background: loading ? T.border : `${T.accent}18`,
              color: loading ? T.muted : T.accent,
              borderColor: loading ? T.border : `${T.accent}44`,
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? <Loader2 size={11} className="animate-spin" /> : <Brain size={11} />}
            {loading ? "Planning..." : "Plan next steps"}
          </button>
          <button
            onClick={() => onAutoplay(undefined, true)}
            disabled={loading || executionLoading}
            className="inline-flex items-center gap-1.5 rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: "6px 12px",
              fontSize: FS.sm,
              background: loading || executionLoading ? T.border : `${T.accent}18`,
              color: loading || executionLoading ? T.muted : T.accent,
              borderColor: loading || executionLoading ? T.border : `${T.accent}44`,
              opacity: loading || executionLoading ? 0.7 : 1,
            }}
          >
            {loading ? <Loader2 size={11} className="animate-spin" /> : <Shield size={11} />}
            {loading ? "Vesper working..." : "Let Vesper work"}
          </button>
          {quickPrompts.map((quickPrompt) => (
            <button
              key={quickPrompt}
              onClick={() => onRun(quickPrompt)}
              disabled={loading}
              className="rounded border cursor-pointer"
              style={{
                padding: "5px 10px",
                fontSize: FS.sm,
                background: T.surface,
                color: T.muted,
                borderColor: T.border,
                opacity: loading ? 0.6 : 1,
              }}
            >
              {quickPrompt}
            </button>
          ))}
          <button
            onClick={onExecute}
            disabled={loading || executionLoading || !plan}
            className="inline-flex items-center gap-1.5 rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
            style={{
              padding: "6px 12px",
              fontSize: FS.sm,
              background: loading || executionLoading || !plan ? T.border : T.greenBg,
              color: loading || executionLoading || !plan ? T.muted : T.green,
              borderColor: loading || executionLoading || !plan ? T.border : `${T.green}44`,
              opacity: loading || executionLoading || !plan ? 0.7 : 1,
            }}
          >
            {executionLoading ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />}
            {executionLoading ? "Executing..." : "Execute required tools"}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 mt-3 rounded p-2.5" style={{ background: T.redBg, border: `1px solid ${T.red}33` }}>
          <XCircle size={12} color={T.red} className="shrink-0" />
          <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
        </div>
      )}

      {executionError && (
        <div className="flex items-center gap-2 mt-3 rounded p-2.5" style={{ background: T.redBg, border: `1px solid ${T.red}33` }}>
          <XCircle size={12} color={T.red} className="shrink-0" />
          <span style={{ fontSize: FS.sm, color: T.red }}>{executionError}</span>
        </div>
      )}

      {situation && (
        <div className="mt-4 rounded-lg" style={{ padding: 12, background: `${T.accent}10`, border: `1px solid ${T.accent}33` }}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.accent }}>
              Vesper Situation Brief
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted }}>
              {situation.phase} · {situation.run_status}
            </div>
          </div>
          <div style={{ fontSize: FS.sm, color: T.text, marginTop: 8, lineHeight: 1.6 }}>
            {situation.current_situation}
          </div>
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", marginTop: 10 }}>
            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Best Next Play
              </div>
              <div style={{ fontSize: FS.sm, color: T.text, marginTop: 6, fontWeight: 700 }}>
                {situation.best_next_play.label}
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                {situation.best_next_play.reason}
              </div>
            </div>
            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Coach Boundary
              </div>
              <div style={{ fontSize: FS.sm, color: T.text, marginTop: 6, lineHeight: 1.6 }}>
                Vesper can: {situation.coach_boundary.vesper_can_do.slice(0, 2).join("; ")}.
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                Coach holds: {situation.coach_boundary.coach_required_for[0]}.
              </div>
            </div>
          </div>
          {situation.audibles.length > 0 && (
            <div className="flex flex-wrap gap-2" style={{ marginTop: 10 }}>
              {situation.audibles.map((audible) => (
                <span
                  key={`${audible.label}-${audible.authority}`}
                  className="rounded-full"
                  style={{ padding: "5px 10px", fontSize: 11, fontWeight: 700, color: audible.authority === "coach_gate" ? T.amber : T.accent, background: audible.authority === "coach_gate" ? T.amberBg : `${T.accent}18` }}
                >
                  {audible.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {plan && (
        <div className="mt-4 flex flex-col gap-3">
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            {plan.quarterback && (
              <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
                <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                  Quarterback
                </div>
                <div style={{ fontSize: FS.sm, color: T.text, marginTop: 8, lineHeight: 1.6 }}>
                  <strong>{plan.quarterback.call_sign}</strong> · {plan.quarterback.breed}<br />
                  {plan.quarterback.summary}
                </div>
                {plan.playbook && (
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, lineHeight: 1.5 }}>
                    Playbook: {plan.playbook.label}
                  </div>
                )}
              </div>
            )}
            <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Context Snapshot
              </div>
              <div style={{ fontSize: FS.sm, color: T.text, marginTop: 8, lineHeight: 1.6 }}>
                Tier: {plan.context_snapshot.tier || "Unknown"}<br />
                Findings: {plan.context_snapshot.findings_total}<br />
                Control paths: {plan.context_snapshot.control_path_count}<br />
                Contradictions: {plan.context_snapshot.contradicted_claims}
              </div>
            </div>
            <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Guardrails
              </div>
              <div className="flex flex-col gap-2" style={{ marginTop: 8 }}>
                {plan.guardrails.slice(0, 2).map((guardrail) => (
                  <div key={guardrail} style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.5 }}>
                    • {guardrail}
                  </div>
                ))}
              </div>
            </div>
            {plan.preflight && (
              <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
                <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                  Situation
                </div>
                <div style={{ fontSize: FS.sm, color: T.text, marginTop: 8, lineHeight: 1.6 }}>
                  Lane: {plan.preflight.workflow_lane || "counterparty"}<br />
                  Pressure: {plan.preflight.anomaly_pressure}<br />
                  Mode: {plan.preflight.execution_mode}
                </div>
              </div>
            )}
          </div>

          {plan.pack && plan.pack.length > 0 && (
            <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Pack Status
              </div>
              <div className="flex flex-wrap gap-2" style={{ marginTop: 10 }}>
                {plan.pack.map((member) => (
                  <div
                    key={`${member.call_sign}-${member.role}`}
                    className="rounded-lg"
                    style={{ padding: "8px 10px", background: member.call_sign === "Vesper" ? `${T.accent}18` : T.raised, border: `1px solid ${member.call_sign === "Vesper" ? `${T.accent}33` : T.border}` }}
                  >
                    <div style={{ fontSize: 11, fontWeight: 700, color: member.call_sign === "Vesper" ? T.accent : T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                      {member.call_sign}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.text, marginTop: 4 }}>
                      {member.role}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4, lineHeight: 1.4 }}>
                      {member.duty}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {plan.anomalies.length > 0 && (
            <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Outliers And Gaps
              </div>
              <div className="flex flex-wrap gap-2" style={{ marginTop: 10 }}>
                {plan.anomalies.map((anomaly) => {
                  const tone = anomalyTone(anomaly.severity);
                  return (
                    <div key={`${anomaly.code}-${anomaly.message}`} className="rounded-lg" style={{ padding: "8px 10px", background: tone.background, color: tone.color, border: `1px solid ${tone.color}33`, minWidth: 180 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                        {anomaly.severity}
                      </div>
                      <div style={{ fontSize: FS.sm, marginTop: 4, lineHeight: 1.5 }}>
                        {anomaly.message}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
              Planned Tool Path
            </div>
            <div className="flex flex-col gap-3" style={{ marginTop: 10 }}>
              {plan.plan.map((step, index) => {
                const tone = stepTone(step.mode);
                return (
                  <div key={`${step.tool_id}-${index}`} className="rounded-lg card-interactive" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}` }}>
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: tone.color, background: tone.background }}>
                          {step.mode}
                        </span>
                        <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                          {index + 1}. {step.label}
                        </span>
                      </div>
                      <span style={{ fontSize: FS.sm, color: step.required ? T.text : T.muted }}>
                        {step.required ? "required" : "optional"}
                      </span>
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                      {step.reason}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {execution && (
            <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                  Approved Execution
                </div>
                <div style={{ fontSize: FS.sm, color: T.muted }}>
                  {execution.executed_steps.length} step{execution.executed_steps.length === 1 ? "" : "s"} executed
                </div>
              </div>
              <div className="flex flex-col gap-3" style={{ marginTop: 10 }}>
                {execution.executed_steps.map((step) => {
                  const tone = stepTone(step.status);
                  const exportHybridReview = step.tool_id === "export_guidance" ? getExportHybridReview(step.result) : null;
                  const assuranceHybridReview = step.tool_id === "cyber_evidence" ? getAssuranceHybridReview(step.result) : null;
                  const cyberEvidenceSummary = step.tool_id === "cyber_evidence" ? getCyberEvidenceSummary(step.result) : null;
                  return (
                    <div key={`${step.tool_id}-${step.status}`} className="rounded-lg card-interactive" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}` }}>
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <div className="flex items-center gap-2">
                          <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: tone.color, background: tone.background }}>
                            {step.status}
                          </span>
                          <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                            {step.tool_id}
                          </span>
                        </div>
                      </div>
                      {exportHybridReview ? (
                        <div className="mt-3 flex flex-col gap-3">
                          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Rules Posture
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                                {exportHybridReview.deterministic_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {exportHybridReview.deterministic_reason_summary}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                AI Challenge
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.accent, fontWeight: 700, marginTop: 6 }}>
                                {exportHybridReview.ai_proposed_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {exportHybridReview.ai_explanation}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Final Posture
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.green, fontWeight: 700, marginTop: 6 }}>
                                {exportHybridReview.final_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {exportHybridReview.disagrees_with_deterministic
                                  ? "AI elevated this case above the deterministic floor."
                                  : "AI held the deterministic floor without escalation."}
                              </div>
                            </div>
                          </div>
                          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Ambiguity Flags
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {(exportHybridReview.ambiguity_flags.length ? exportHybridReview.ambiguity_flags : ["none"]).map((flag) => (
                                  <span key={flag} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: flag === "none" ? T.muted : T.amber, background: flag === "none" ? T.raised : T.amberBg }}>
                                    {flag.replace(/_/g, " ")}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Missing Facts
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {(exportHybridReview.missing_facts.length ? exportHybridReview.missing_facts : ["none"]).map((fact) => (
                                  <span key={fact} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: fact === "none" ? T.muted : T.red, background: fact === "none" ? T.raised : T.redBg }}>
                                    {fact.replace(/_/g, " ")}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                          {exportHybridReview.recommended_questions.length > 0 && (
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Next Questions
                              </div>
                              <div className="flex flex-col gap-2" style={{ marginTop: 8 }}>
                                {exportHybridReview.recommended_questions.map((question) => (
                                  <div key={question} style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                                    - {question}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : assuranceHybridReview ? (
                        <div className="mt-3 flex flex-col gap-3">
                          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Evidence Posture
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                                {assuranceHybridReview.deterministic_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {assuranceHybridReview.deterministic_reason_summary}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                AI Challenge
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.accent, fontWeight: 700, marginTop: 6 }}>
                                {assuranceHybridReview.ai_proposed_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {assuranceHybridReview.ai_explanation}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Final Posture
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.green, fontWeight: 700, marginTop: 6 }}>
                                {assuranceHybridReview.final_posture}
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                                {assuranceHybridReview.disagrees_with_deterministic
                                  ? "AI changed the assurance posture because the artifact mix still leaves material uncertainty."
                                  : "AI held the evidence floor without escalation."}
                              </div>
                            </div>
                          </div>
                          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Ambiguity Flags
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {(assuranceHybridReview.ambiguity_flags.length ? assuranceHybridReview.ambiguity_flags : ["none"]).map((flag) => (
                                  <span key={flag} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: flag === "none" ? T.muted : T.amber, background: flag === "none" ? T.raised : T.amberBg }}>
                                    {flag.replace(/_/g, " ")}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Missing Evidence
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {(assuranceHybridReview.missing_facts.length ? assuranceHybridReview.missing_facts : ["none"]).map((fact) => (
                                  <span key={fact} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: fact === "none" ? T.muted : T.red, background: fact === "none" ? T.raised : T.redBg }}>
                                    {fact.replace(/_/g, " ")}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Artifact Sources
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {(assuranceHybridReview.artifact_sources.length ? assuranceHybridReview.artifact_sources : ["none"]).map((source) => (
                                  <span key={source} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: source === "none" ? T.muted : T.accent, background: source === "none" ? T.raised : `${T.accent}18` }}>
                                    {source.replace(/_/g, " ")}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Safe Boundary
                              </div>
                              <div className="flex flex-col gap-2" style={{ marginTop: 8 }}>
                                <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                                  - AI can elevate: {assuranceHybridReview.safe_boundary.ai_can_elevate ? "yes" : "no"}
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                                  - AI can downgrade blocked: {assuranceHybridReview.safe_boundary.ai_can_downgrade_blocked ? "yes" : "no"}
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                                  - AI can downgrade review with strong evidence: {assuranceHybridReview.safe_boundary.ai_can_downgrade_review_with_artifact_backed_evidence ? "yes" : "no"}
                                </div>
                              </div>
                            </div>
                          </div>
                          {(assuranceHybridReview.threat_pressure
                            || assuranceHybridReview.attack_technique_ids.length
                            || assuranceHybridReview.cisa_advisory_ids.length
                            || assuranceHybridReview.attack_actor_families.length
                            || assuranceHybridReview.threat_sectors.length
                            || assuranceHybridReview.open_source_advisory_count > 0
                            || assuranceHybridReview.scorecard_low_repo_count > 0) && (
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div className="flex items-center justify-between gap-3 flex-wrap">
                                <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                  Active Threat Signal
                                </div>
                                <span
                                  className="rounded-full"
                                  style={{
                                    padding: "4px 8px",
                                    fontSize: 11,
                                    fontWeight: 700,
                                    color: threatPressureTone(assuranceHybridReview.threat_pressure).color,
                                    background: threatPressureTone(assuranceHybridReview.threat_pressure).background,
                                  }}
                                >
                                  {String(assuranceHybridReview.threat_pressure || "none").replace(/_/g, " ")}
                                </span>
                              </div>
                              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", marginTop: 8 }}>
                                <div>
                                  <div style={{ fontSize: 11, color: T.muted }}>ATT&CK</div>
                                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 4 }}>
                                    {assuranceHybridReview.attack_technique_ids.length} techniques
                                  </div>
                                </div>
                                <div>
                                  <div style={{ fontSize: 11, color: T.muted }}>CISA</div>
                                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 4 }}>
                                    {assuranceHybridReview.cisa_advisory_ids.length} advisories
                                  </div>
                                </div>
                                <div>
                                  <div style={{ fontSize: 11, color: T.muted }}>OSS</div>
                                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 4 }}>
                                    {assuranceHybridReview.open_source_advisory_count} advisories
                                  </div>
                                </div>
                                <div>
                                  <div style={{ fontSize: 11, color: T.muted }}>Repo Hygiene</div>
                                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 4 }}>
                                    {assuranceHybridReview.scorecard_low_repo_count} low-score repos
                                  </div>
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2" style={{ marginTop: 8 }}>
                                {stringList(assuranceHybridReview.attack_actor_families).slice(0, 3).map((family) => (
                                  <span key={family} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.red, background: T.redBg }}>
                                    {family}
                                  </span>
                                ))}
                                {stringList(assuranceHybridReview.threat_sectors).slice(0, 3).map((sector) => (
                                  <span key={sector} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.accent, background: `${T.accent}18` }}>
                                    {sector}
                                  </span>
                                ))}
                                {stringList(assuranceHybridReview.attack_technique_ids).slice(0, 4).map((technique) => (
                                  <span key={technique} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.amber, background: T.amberBg }}>
                                    {technique}
                                  </span>
                                ))}
                                {stringList(assuranceHybridReview.cisa_advisory_ids).slice(0, 3).map((advisory) => (
                                  <span key={advisory} className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.text, background: T.raised }}>
                                    {advisory}
                                  </span>
                                ))}
                                {assuranceHybridReview.open_source_risk_level && (
                                  <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.text, background: T.raised }}>
                                    OSS risk {assuranceHybridReview.open_source_risk_level}
                                  </span>
                                )}
                              </div>
                              {cyberEvidenceSummary?.threat_intel_sources && cyberEvidenceSummary.threat_intel_sources.length > 0 && (
                                <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, lineHeight: 1.5 }}>
                                  Sources: {stringList(cyberEvidenceSummary.threat_intel_sources).join(", ")}
                                </div>
                              )}
                            </div>
                          )}
                          {assuranceHybridReview.recommended_questions.length > 0 && (
                            <div className="rounded-lg" style={{ padding: 10, background: T.surface, border: `1px solid ${T.border}` }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                Next Questions
                              </div>
                              <div className="flex flex-col gap-2" style={{ marginTop: 8 }}>
                                {assuranceHybridReview.recommended_questions.map((question) => (
                                  <div key={question} style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                                    - {question}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <pre style={{ margin: "10px 0 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12, color: T.muted }}>
                          {JSON.stringify(step.result, null, 2)}
                        </pre>
                      )}
                    </div>
                  );
                })}
                {execution.blocked_tools.length > 0 && (
                  <div className="rounded-lg" style={{ padding: 12, background: T.amberBg, border: `1px solid ${T.amber}33` }}>
                    <div style={{ fontSize: FS.sm, color: T.amber, fontWeight: 700 }}>
                      Blocked tools
                    </div>
                    <div className="flex flex-col gap-2" style={{ marginTop: 8 }}>
                      {execution.blocked_tools.map((tool) => (
                        <div key={`${tool.tool_id}-${tool.reason}`} style={{ fontSize: FS.sm, color: T.text }}>
                          {tool.tool_id}: {tool.message}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                Analyst Feedback Loop
              </div>
              <span style={{ fontSize: FS.sm, color: T.dim }}>
                Turn plan corrections into structured training signals
              </span>
            </div>
            <div className="grid gap-3 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
              <label className="flex flex-col gap-1">
                <span style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Verdict
                </span>
                <select
                  value={feedbackVerdict}
                  onChange={(event) => setFeedbackVerdict(event.target.value as AssistantFeedbackVerdict)}
                  style={{ borderRadius: 8, border: `1px solid ${T.border}`, background: T.raised, color: T.text, padding: "8px 10px", fontSize: FS.sm }}
                >
                  <option value="accepted">Accepted</option>
                  <option value="partial">Partial</option>
                  <option value="rejected">Rejected</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Feedback Type
                </span>
                <select
                  value={feedbackType}
                  onChange={(event) => setFeedbackType(event.target.value as AssistantFeedbackType)}
                  style={{ borderRadius: 8, border: `1px solid ${T.border}`, background: T.raised, color: T.text, padding: "8px 10px", fontSize: FS.sm }}
                >
                  <option value="tool_missing">Tool missing</option>
                  <option value="tool_noise">Tool noise</option>
                  <option value="objective_wrong">Wrong objective</option>
                  <option value="missing_evidence">Missing evidence</option>
                  <option value="wrong_explanation">Wrong explanation</option>
                  <option value="helpful">Helpful</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Suggested Tools
                </span>
                <input
                  value={suggestedToolsInput}
                  onChange={(event) => setSuggestedToolsInput(event.target.value)}
                  placeholder="graph_probe, enrichment_findings"
                  style={{ borderRadius: 8, border: `1px solid ${T.border}`, background: T.raised, color: T.text, padding: "8px 10px", fontSize: FS.sm }}
                />
              </label>
            </div>
            <label className="flex flex-col gap-1 mt-3">
              <span style={{ fontSize: 11, fontWeight: 700, color: T.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Analyst Comment
              </span>
              <textarea
                value={feedbackComment}
                onChange={(event) => setFeedbackComment(event.target.value)}
                placeholder="Tell Helios what was missing, noisy, or wrong."
                rows={3}
                style={{ borderRadius: 8, border: `1px solid ${T.border}`, background: T.raised, color: T.text, padding: 10, fontSize: FS.sm, resize: "vertical" }}
              />
            </label>
            <div className="flex items-center justify-between gap-3 flex-wrap mt-3">
              <div style={{ fontSize: FS.sm, color: T.muted }}>
                Helios will store the prompt, objective, executed tools, anomaly codes, and your correction as a structured signal.
              </div>
              <button
                onClick={handleFeedbackSubmit}
                disabled={feedbackSubmitting || !plan}
                className="inline-flex items-center gap-1.5 rounded-lg font-medium border cursor-pointer btn-interactive focus-ring"
                style={{
                  padding: "6px 12px",
                  fontSize: FS.sm,
                  background: feedbackSubmitting || !plan ? T.border : `${T.accent}18`,
                  color: feedbackSubmitting || !plan ? T.muted : T.accent,
                  borderColor: feedbackSubmitting || !plan ? T.border : `${T.accent}44`,
                  opacity: feedbackSubmitting || !plan ? 0.7 : 1,
                }}
              >
                {feedbackSubmitting ? <Loader2 size={11} className="animate-spin" /> : <Shield size={11} />}
                {feedbackSubmitting ? "Saving..." : "Save assistant feedback"}
              </button>
            </div>
            {feedbackError && (
              <div className="mt-3 rounded p-2.5" style={{ background: T.redBg, border: `1px solid ${T.red}33`, color: T.red, fontSize: FS.sm }}>
                {feedbackError}
              </div>
            )}
            {feedbackSuccess && (
              <div className="mt-3 rounded p-2.5" style={{ background: T.greenBg, border: `1px solid ${T.green}33`, color: T.green, fontSize: FS.sm }}>
                {feedbackSuccess}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Collapsible section */
function Section({
  title, sectionKey, expanded, onToggle, icon, children,
}: {
  title: string;
  sectionKey: string;
  expanded: boolean;
  onToggle: (key: string) => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
      <button
        onClick={() => onToggle(sectionKey)}
        className="w-full flex items-center justify-between p-3 cursor-pointer"
        style={{ background: "transparent", border: "none", textAlign: "left" }}
      >
        <div className="flex items-center gap-1.5">
          {icon}
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            {title}
          </span>
        </div>
        {expanded ? <ChevronUp size={12} color={T.muted} /> : <ChevronDown size={12} color={T.muted} />}
      </button>
      {expanded && (
        <div className="px-3 pb-3">
          {children}
        </div>
      )}
    </div>
  );
}
