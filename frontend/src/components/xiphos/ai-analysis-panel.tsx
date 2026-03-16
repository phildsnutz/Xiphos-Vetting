import { useState, useEffect } from "react";
import { T } from "@/lib/tokens";
import {
  Brain, Loader2, RefreshCw, CheckCircle, XCircle,
  AlertTriangle, Shield, Clock, ChevronDown, ChevronUp,
} from "lucide-react";
import { runAIAnalysis, fetchAIAnalysis, fetchAIConfig } from "@/lib/api";
import type { AIAnalysis } from "@/lib/api";

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
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["summary", "concerns", "actions"])
  );

  // Check if AI is configured and load existing analysis
  useEffect(() => {
    fetchAIConfig()
      .then((cfg) => setConfigured(cfg.configured))
      .catch(() => setConfigured(false));

    fetchAIAnalysis(caseId)
      .then((a) => setAnalysis(a))
      .catch(() => {}); // No existing analysis, that's fine
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

  if (configured === null) {
    return (
      <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2">
          <Brain size={14} color={T.muted} className="animate-pulse" />
          <span style={{ fontSize: 11, color: T.muted }}>Checking AI configuration...</span>
        </div>
      </div>
    );
  }

  if (!configured && !analysis) {
    return (
      <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2 mb-2">
          <Brain size={14} color={T.muted} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
            AI Risk Analysis
          </span>
        </div>
        <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>
          No AI provider configured. Go to <strong style={{ color: T.accent }}>Admin &gt; AI Settings</strong> to
          set up your API key for Claude, OpenAI, or Gemini.
        </div>
      </div>
    );
  }

  const a = analysis?.analysis;
  const verdict = a?.verdict || "";
  const vs = VERDICT_STYLES[verdict] || VERDICT_STYLES.ENHANCED_DUE_DILIGENCE;

  return (
    <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
      {/* Header */}
      <div className="flex items-center justify-between p-4" style={{ borderBottom: `1px solid ${T.border}` }}>
        <div className="flex items-center gap-2">
          <Brain size={14} color={T.accent} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
            AI Risk Analysis
          </span>
          {analysis && (
            <span className="font-mono" style={{ fontSize: 9, color: T.muted }}>
              via {analysis.provider}/{analysis.model}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {analysis && (
            <span className="flex items-center gap-1 font-mono" style={{ fontSize: 9, color: T.muted }}>
              <Clock size={10} />
              {(analysis.elapsed_ms / 1000).toFixed(1)}s
              {" | "}
              {analysis.prompt_tokens + analysis.completion_tokens} tokens
            </span>
          )}
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
            style={{
              padding: "5px 10px",
              fontSize: 11,
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
          <span style={{ fontSize: 11, color: T.red }}>{error}</span>
        </div>
      )}

      {/* Loading state */}
      {loading && !analysis && (
        <div className="p-8 flex flex-col items-center gap-3">
          <Loader2 size={24} color={T.accent} className="animate-spin" />
          <span style={{ fontSize: 12, color: T.muted }}>
            Generating intelligence assessment for {vendorName}...
          </span>
          <span style={{ fontSize: 10, color: T.muted }}>
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
            <span className="font-mono font-bold" style={{ fontSize: 13, color: vs.color }}>
              {verdict.replace(/_/g, " ")}
            </span>
          </div>

          {/* Executive Summary */}
          <Section
            title="Executive Summary"
            sectionKey="summary"
            expanded={expandedSections.has("summary")}
            onToggle={toggleSection}
          >
            <p style={{ fontSize: 12, color: T.dim, lineHeight: 1.6, margin: 0 }}>
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
            <p style={{ fontSize: 12, color: T.dim, lineHeight: 1.6, margin: 0 }}>
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
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: 10, color: T.red }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: 11, color: T.dim, lineHeight: 1.5 }}>{c}</span>
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
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: 10, color: T.green }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: 11, color: T.dim, lineHeight: 1.5 }}>{f}</span>
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
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: 10, color: T.accent }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: 11, color: T.dim, lineHeight: 1.5 }}>{act}</span>
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
            <p style={{ fontSize: 12, color: T.dim, lineHeight: 1.6, margin: 0 }}>
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
            <p style={{ fontSize: 12, color: T.dim, lineHeight: 1.6, margin: 0 }}>
              {a.confidence_assessment}
            </p>
          </Section>
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
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
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
