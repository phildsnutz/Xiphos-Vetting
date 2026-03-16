import { useState, useEffect } from "react";
import { T } from "@/lib/tokens";
import { ChevronLeft, FileText, Activity, Globe, Clock, XCircle, AlertTriangle, Loader2, TrendingUp, Radar, Brain } from "lucide-react";
import { TierBadge } from "./badges";
import { Gauge } from "./gauge";
import { ContribBar } from "./charts";
import { EnrichmentPanel } from "./enrichment-panel";
import { AIAnalysisPanel } from "./ai-analysis-panel";
import { enrichAndScore, fetchEnrichment } from "@/lib/api";
import type { EnrichmentReport } from "@/lib/api";
import type { VettingCase, ScoreSnapshot } from "@/lib/types";

interface CaseDetailProps {
  c: VettingCase;
  onBack: () => void;
  onRescore?: (caseId: string) => Promise<void>;
  onDossier?: (caseId: string) => Promise<void>;
}

/** SVG sparkline showing how the posterior has changed across re-scores */
function ScoreHistory({ history, current }: { history: ScoreSnapshot[]; current: { p: number; tier: string; ts: string } }) {
  // Combine current score with history
  const points = [...history, { p: current.p, tier: current.tier, sc: 0, ts: current.ts }];
  if (points.length < 2) return null;

  const w = 260;
  const h = 64;
  const padX = 24;
  const padY = 10;
  const chartW = w - padX * 2;
  const chartH = h - padY * 2;

  // Y axis: 0 to max(0.8, highest point + 0.05)
  const maxP = Math.max(0.8, ...points.map((p) => p.p) , 0.15) + 0.05;

  const x = (i: number) => padX + (i / (points.length - 1)) * chartW;
  const y = (p: number) => padY + chartH - (p / maxP) * chartH;

  // Build polyline
  const linePts = points.map((pt, i) => `${x(i)},${y(pt.p)}`).join(" ");

  // Tier threshold lines
  const thresholds = [
    { val: 0.15, label: "CLR", color: T.green },
    { val: 0.30, label: "MON", color: T.amber },
    { val: 0.60, label: "STP", color: T.red },
  ].filter((t) => t.val < maxP);

  return (
    <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
      <div className="flex items-center gap-1.5 mb-2">
        <TrendingUp size={12} color={T.muted} />
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
          Score History
        </span>
        <span className="font-mono" style={{ fontSize: 9, color: T.muted }}>
          ({points.length} assessments)
        </span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", width: "100%", maxWidth: w }}>
        {/* Threshold lines */}
        {thresholds.map((t) => (
          <g key={t.label}>
            <line
              x1={padX} y1={y(t.val)} x2={w - padX} y2={y(t.val)}
              stroke={t.color} strokeWidth={0.5} strokeDasharray="3,3" opacity={0.4}
            />
            <text x={w - padX + 3} y={y(t.val) + 3} fill={t.color} fontSize={7} fontFamily="monospace" opacity={0.6}>
              {t.label}
            </text>
          </g>
        ))}

        {/* Data line */}
        <polyline
          points={linePts}
          fill="none" stroke={T.accent} strokeWidth={1.5} strokeLinejoin="round"
        />

        {/* Data points */}
        {points.map((pt, i) => {
          const tierColor = pt.tier === "clear" ? T.green : pt.tier === "monitor" ? T.amber :
            pt.tier === "elevated" ? T.orange : T.red;
          return (
            <g key={i}>
              <circle cx={x(i)} cy={y(pt.p)} r={3.5} fill={T.bg} stroke={tierColor} strokeWidth={1.5} />
              {/* Label on first and last */}
              {(i === 0 || i === points.length - 1) && (
                <text
                  x={x(i)} y={y(pt.p) - 7}
                  textAnchor="middle" fill={T.dim} fontSize={8} fontFamily="monospace"
                >
                  {Math.round(pt.p * 100)}%
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between mt-1">
        <span className="font-mono" style={{ fontSize: 8, color: T.muted }}>
          {points[0].ts.split("T")[0]}
        </span>
        <span className="font-mono" style={{ fontSize: 8, color: T.muted }}>
          {points[points.length - 1].ts.split("T")[0]}
        </span>
      </div>
    </div>
  );
}

/** Format a signed contribution as probability-language string */
function fmtContrib(s: number): string {
  const pp = Math.abs(s * 100).toFixed(1);
  return s > 0 ? `+${pp} pp` : s < 0 ? `\u2212${pp} pp` : `${pp} pp`;
}

export function CaseDetail({ c, onBack, onRescore, onDossier }: CaseDetailProps) {
  const cal = c.cal;
  const [rescoring, setRescoring] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichment, setEnrichment] = useState<EnrichmentReport | null>(null);
  const [showEnrichment, setShowEnrichment] = useState(false);
  const [showAI, setShowAI] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Try to load existing enrichment on mount
  useEffect(() => {
    fetchEnrichment(c.id).then((r) => {
      if (r && r.findings && r.findings.length > 0) setEnrichment(r);
    }).catch(() => {});
  }, [c.id]);

  const handleEnrich = async () => {
    setEnriching(true);
    setError(null);
    try {
      const result = await enrichAndScore(c.id);
      setEnrichment(result.enrichment);
      setShowEnrichment(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Enrichment failed");
    } finally {
      setEnriching(false);
    }
  };

  const handleRescore = async () => {
    if (!onRescore) return;
    setRescoring(true);
    setError(null);
    try {
      await onRescore(c.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-score failed");
    } finally {
      setRescoring(false);
    }
  };

  const handleDossier = async () => {
    if (!onDossier) return;
    setGenerating(true);
    setError(null);
    try {
      await onDossier(c.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dossier generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const hasApi = !!onRescore;

  // Sort contributions by absolute impact
  const sortedCt = cal ? [...cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s)) : [];

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Back */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer shrink-0 self-start"
        style={{ fontSize: 11, color: T.muted }}
      >
        <ChevronLeft size={11} /> Back to Assessments
      </button>

      {/* Single scrollable view - no tabs */}
      <div className="flex-1 min-h-0 overflow-auto pr-1">
        {/* Header card - decision surface */}
        <div className="rounded-lg shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold" style={{ fontSize: 18, color: T.text }}>{c.name}</span>
                {cal && <TierBadge tier={cal.tier} />}
              </div>
              <div className="flex items-center gap-3 flex-wrap mt-1.5">
                <span className="inline-flex items-center gap-1" style={{ fontSize: 11, color: T.muted }}>
                  <Globe size={11} />{c.cc}
                </span>
                <span className="inline-flex items-center gap-1" style={{ fontSize: 11, color: T.muted }}>
                  <Clock size={11} />{c.date}
                </span>
                <span className="font-mono" style={{ fontSize: 11, color: T.muted }}>{c.id}</span>
              </div>
            </div>
            <div className="flex gap-2">
              {/* OSINT Enrich + Score */}
              <button
                onClick={handleEnrich}
                disabled={enriching}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "6px 12px", fontSize: 12,
                  background: enrichment ? T.raised : "#10b98122",
                  color: enrichment ? T.dim : "#10b981",
                  borderColor: enrichment ? T.border : "#10b98144",
                  opacity: enriching ? 0.5 : 1,
                }}
              >
                {enriching ? <Loader2 size={12} className="animate-spin" /> : <Radar size={12} />}
                {enriching ? "Enriching 16 sources..." : enrichment ? "Re-Enrich" : "OSINT Enrich"}
              </button>
              {/* View enrichment if available */}
              {enrichment && (
                <button
                  onClick={() => setShowEnrichment(!showEnrichment)}
                  className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                  style={{
                    padding: "6px 12px", fontSize: 12,
                    background: showEnrichment ? T.accent + "22" : T.raised,
                    color: showEnrichment ? T.accent : T.dim,
                    borderColor: showEnrichment ? T.accent + "44" : T.border,
                  }}
                >
                  <Radar size={12} />
                  {showEnrichment ? "Hide Intel" : `Intel (${enrichment.summary.findings_total})`}
                </button>
              )}
              {/* AI Analysis toggle */}
              <button
                onClick={() => setShowAI(!showAI)}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "6px 12px", fontSize: 12,
                  background: showAI ? T.accent + "22" : "#8b5cf622",
                  color: showAI ? T.accent : "#8b5cf6",
                  borderColor: showAI ? T.accent + "44" : "#8b5cf644",
                }}
              >
                <Brain size={12} />
                {showAI ? "Hide AI" : "AI Analysis"}
              </button>
              {/* Dossier */}
              <button
                onClick={handleDossier}
                disabled={generating || !cal}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "6px 12px", fontSize: 12,
                  background: T.raised, color: T.text, borderColor: T.border,
                  opacity: generating || !cal ? 0.5 : 1,
                }}
              >
                {generating ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
                {generating ? "Generating..." : "Dossier"}
              </button>
              {/* Re-Score: requires API */}
              {hasApi ? (
                <button
                  onClick={handleRescore}
                  disabled={rescoring}
                  className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-pointer"
                  style={{
                    padding: "6px 12px", fontSize: 12,
                    background: T.accent,
                    opacity: rescoring ? 0.5 : 1,
                  }}
                >
                  {rescoring ? <Loader2 size={12} className="animate-spin" /> : <Activity size={12} />}
                  {rescoring ? "Scoring..." : "Re-Score"}
                </button>
              ) : (
                <button
                  className="inline-flex items-center gap-1.5 rounded font-medium text-white border-none cursor-not-allowed pointer-events-none"
                  style={{ padding: "6px 12px", fontSize: 12, background: T.accent, opacity: 0.4 }}
                >
                  <Activity size={12} /> Re-Score <span style={{ fontSize: 10, color: T.muted }}>(Offline)</span>
                </button>
              )}
            </div>
          </div>

          {/* Hard stops */}
          {cal?.stops && cal.stops.length > 0 && (
            <div
              className="flex gap-2 mt-3 rounded-md"
              style={{ padding: 12, background: T.dRedBg, border: `1px solid ${T.dRed}44` }}
            >
              <XCircle size={16} color={T.dRed} className="shrink-0 mt-0.5" />
              <div>
                <div className="font-bold" style={{ fontSize: 12, color: T.dRed }}>
                  HARD STOP &mdash; {cal.stops[0].t}
                </div>
                <div style={{ fontSize: 11, color: T.red, marginTop: 2, lineHeight: 1.4 }}>
                  {cal.stops[0].x}
                </div>
                <div className="font-mono" style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                  Confidence: {Math.round(cal.stops[0].c * 100)}%
                </div>
              </div>
            </div>
          )}

          {/* Flags */}
          {cal?.flags && cal.flags.length > 0 && !(cal?.stops?.length) && (
            <div className="flex flex-wrap gap-2 mt-3">
              {cal.flags.map((f, i) => (
                <div
                  key={i}
                  className="flex gap-1.5 rounded flex-1 min-w-[200px]"
                  style={{ padding: 10, background: T.amberBg, border: `1px solid ${T.amber}33` }}
                >
                  <AlertTriangle size={13} color={T.amber} className="shrink-0 mt-0.5" />
                  <div>
                    <div className="font-bold" style={{ fontSize: 11, color: T.amber }}>{f.t}</div>
                    <div style={{ fontSize: 10, color: T.dim, marginTop: 1 }}>{f.x}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* API error */}
          {error && (
            <div
              className="flex items-center gap-2 mt-3 rounded"
              style={{ padding: "8px 12px", background: T.redBg, border: `1px solid ${T.red}33` }}
            >
              <XCircle size={12} color={T.red} className="shrink-0" />
              <span style={{ fontSize: 11, color: T.red }}>{error}</span>
            </div>
          )}
        </div>

        {/* OSINT Enrichment Panel */}
        {showEnrichment && enrichment && (
          <div className="mt-3">
            <EnrichmentPanel report={enrichment} />
          </div>
        )}

        {/* AI Analysis Panel */}
        {showAI && (
          <div className="mt-3">
            <AIAnalysisPanel caseId={c.id} vendorName={c.name} />
          </div>
        )}

        {/* Two-column assessment body */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-3">
          {/* Left: Probability + Risk Factors (the core assessment) */}
          <div className="flex flex-col gap-3">
            {/* Bayesian Posterior */}
            <div className="rounded-lg p-5" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
                Bayesian Posterior
              </div>
              <div style={{ fontSize: 9, color: T.muted, marginBottom: 10 }}>
                What the evidence suggests, given the statistical model
              </div>
              {cal ? (
                <div className="flex flex-col items-center">
                  <div className="mb-3">
                    <TierBadge tier={cal.tier} />
                  </div>
                  <div style={{ transform: "scale(1.3)", transformOrigin: "center", marginBottom: 12, marginTop: 4 }}>
                    <Gauge value={cal.p} lo={cal.lo} hi={cal.hi} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                      Coverage {Math.round(cal.cov * 100)}%
                    </span>
                    <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                      Mean Conf {Math.round(cal.mc * 100)}%
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8" style={{ fontSize: 11, color: T.muted }}>
                  Scoring in progress...
                </div>
              )}
            </div>

            {/* Score History (only shown when there are re-scores) */}
            {cal && c.history && c.history.length > 0 && (
              <ScoreHistory history={c.history} current={{ p: cal.p, tier: cal.tier, ts: new Date().toISOString() }} />
            )}

            {/* Risk Factor Contributions - full list, probability language, sorted by impact */}
            {cal && (
              <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: 10, color: T.muted }}>
                  Risk Factor Contributions
                </div>
                {sortedCt.map((ct, i) => (
                  <div
                    key={i}
                    style={{ padding: "8px 0", borderBottom: i < sortedCt.length - 1 ? `1px solid ${T.border}` : "none" }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium" style={{ fontSize: 12, color: T.text }}>{ct.n}</span>
                      <div className="flex items-center gap-3">
                        <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                          {Math.round(ct.c * 100)}% conf
                        </span>
                        <span
                          className="font-mono font-semibold"
                          style={{ fontSize: 11, color: ct.s > 0 ? T.red : ct.s < 0 ? T.green : T.muted }}
                        >
                          {fmtContrib(ct.s)}
                        </span>
                      </div>
                    </div>
                    <ContribBar value={ct.raw} color={ct.raw > 0.7 ? T.red : ct.raw > 0.4 ? T.amber : T.green} />
                    <div style={{ fontSize: 10, color: T.muted, marginTop: 3 }}>{ct.d}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: Details + Findings + MIV */}
          <div className="flex flex-col gap-3">
            {/* Case Details table with Rubric Score */}
            <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: 10, color: T.muted }}>
                Case Details
              </div>
              {[
                ["Vendor", c.name],
                ["Country", c.cc],
                ["Case ID", c.id],
                ["Date", c.date],
                ["Status", c.cal ? "Complete" : "Scoring"],
                ...(cal
                  ? [
                      ["Coverage", Math.round(cal.cov * 100) + "%"],
                      ["Mean Conf", Math.round(cal.mc * 100) + "%"],
                    ]
                  : []),
              ].map(([k, v], i) => (
                <div
                  key={i}
                  className="flex items-center justify-between"
                  style={{ padding: "5px 0", borderBottom: `1px solid ${T.border}` }}
                >
                  <span style={{ fontSize: 11, color: T.muted }}>{k}</span>
                  <span className="font-mono" style={{ fontSize: 11, color: T.dim }}>{v}</span>
                </div>
              ))}

              {/* Policy Rubric subsection */}
              <div style={{ padding: "10px 0 0", marginTop: 6 }}>
                <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 10, color: T.muted }}>
                  Policy Rubric
                </div>
                <div style={{ fontSize: 9, color: T.muted, marginBottom: 6 }}>
                  What procurement policy prescribes for this vendor profile
                </div>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className="font-mono font-bold" style={{ fontSize: 22, color: T.text }}>{c.sc}</span>
                  <span className="font-mono" style={{ fontSize: 12, color: T.muted }}>/100</span>
                  <span className="font-mono ml-2" style={{ fontSize: 10, color: T.muted }}>
                    ({Math.round(c.conf * 100)}% confidence)
                  </span>
                </div>
                <div className="w-full rounded-full overflow-hidden" style={{ height: 4, background: T.border }}>
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${c.sc}%`, background: c.sc > 70 ? T.red : c.sc > 40 ? T.amber : T.green }}
                  />
                </div>
                {/* Scoring divergence flag */}
                {cal && (() => {
                  const bayesPct = Math.round(cal.p * 100);
                  const divergence = Math.abs(bayesPct - c.sc);
                  if (divergence > 15) {
                    return (
                      <div
                        className="flex items-center gap-1.5 mt-2 rounded"
                        style={{ padding: "4px 8px", background: T.amberBg, border: `1px solid ${T.amber}33` }}
                      >
                        <AlertTriangle size={10} color={T.amber} className="shrink-0" />
                        <span style={{ fontSize: 9, color: T.amber }}>
                          Consensus break: Bayesian ({bayesPct}%) and Policy Rubric ({c.sc}) diverge by {divergence} points
                        </span>
                      </div>
                    );
                  }
                  return null;
                })()}
              </div>
            </div>

            {/* Key findings */}
            {cal?.finds && cal.finds.length > 0 && (
              <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: 10, color: T.muted }}>
                  Key Findings
                </div>
                {cal.finds.map((f, i) => (
                  <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                    <span className="font-mono font-bold shrink-0" style={{ fontSize: 11, color: T.accent }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>{f}</span>
                  </div>
                ))}
              </div>
            )}

            {/* MIV - Recommended Data Collection */}
            {cal?.miv && cal.miv.length > 0 && (
              <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: 10, color: T.muted }}>
                  Recommended Data Collection
                </div>
                {cal.miv.map((m, i) => (
                  <div
                    key={i}
                    className="rounded"
                    style={{ padding: 10, background: T.raised, border: `1px solid ${T.border}`, marginTop: i > 0 ? 8 : 0 }}
                  >
                    <div className="font-medium" style={{ fontSize: 11, color: T.text, lineHeight: 1.4 }}>{m.t}</div>
                    <div className="flex gap-3 mt-1.5">
                      <span className="font-mono" style={{ fontSize: 10, color: T.accent }}>
                        {m.i > 0 ? "\u2212" : "+"}{m.i.toFixed(1)} pp impact
                      </span>
                      <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                        {Math.round(m.tp * 100)}% tier change probability
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
