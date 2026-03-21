import { useState, useEffect, useMemo, useRef } from "react";
import { T, FS, tierColor, parseTier, SENSITIVITY_META, parseSensitivity, tierBand, probLabel } from "@/lib/tokens";
import { ChevronLeft, FileText, Activity, Globe, Clock, XCircle, AlertTriangle, Loader2, TrendingUp, Radar, Lock, MoreHorizontal } from "lucide-react";
import { TierBadge } from "./badges";
import { Gauge } from "./gauge";
import { ContribBar } from "./charts";
import { EnrichmentPanel } from "./enrichment-panel";
import { EnrichmentStream } from "./enrichment-stream";
import { AIAnalysisPanel } from "./ai-analysis-panel";
import { ActionPanel } from "./action-panel";
import { fetchEnrichment } from "@/lib/api";
import { getUser, getToken } from "@/lib/auth";
import type { EnrichmentReport } from "@/lib/api";
import type { VettingCase, ScoreSnapshot, Calibration } from "@/lib/types";

interface CaseDetailProps {
  c: VettingCase;
  onBack: () => void;
  onRescore?: (caseId: string) => Promise<void>;
  onDossier?: (caseId: string) => Promise<void>;
}

function ScoreHistory({ history, current }: { history: ScoreSnapshot[]; current: { p: number; tier: string; ts: string } }) {
  const points = [...history, { p: current.p, tier: current.tier, sc: 0, ts: current.ts }];
  if (points.length < 2) return null;

  const w = 260;
  const h = 64;
  const padX = 24;
  const padY = 10;
  const chartW = w - padX * 2;
  const chartH = h - padY * 2;
  const maxP = Math.max(0.8, ...points.map((p) => p.p), 0.15) + 0.05;

  const x = (i: number) => padX + (i / (points.length - 1)) * chartW;
  const y = (p: number) => padY + chartH - (p / maxP) * chartH;
  const linePts = points.map((pt, i) => `${x(i)},${y(pt.p)}`).join(" ");

  const thresholds = [
    { val: 0.15, label: "CLR", color: T.green },
    { val: 0.30, label: "MON", color: T.amber },
    { val: 0.60, label: "STP", color: T.red },
  ].filter((t) => t.val < maxP);

  return (
    <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
      <div className="flex items-center gap-1.5 mb-2">
        <TrendingUp size={12} color={T.muted} />
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
          Score History
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          ({points.length} assessments)
        </span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", width: "100%", maxWidth: w }}>
        {thresholds.map((threshold) => (
          <g key={threshold.label}>
            <line
              x1={padX} y1={y(threshold.val)} x2={w - padX} y2={y(threshold.val)}
              stroke={threshold.color} strokeWidth={0.5} strokeDasharray="3,3" opacity={0.4}
            />
            <text x={w - padX + 3} y={y(threshold.val) + 3} fill={threshold.color} fontSize={7} fontFamily="monospace" opacity={0.6}>
              {threshold.label}
            </text>
          </g>
        ))}

        <polyline
          points={linePts}
          fill="none" stroke={T.accent} strokeWidth={1.5} strokeLinejoin="round"
        />

        {points.map((pt, i) => {
          const color = tierColor(parseTier(pt.tier));
          return (
            <g key={i}>
              <circle cx={x(i)} cy={y(pt.p)} r={3.5} fill={T.bg} stroke={color} strokeWidth={1.5} />
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
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[0].ts.split("T")[0]}
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[points.length - 1].ts.split("T")[0]}
        </span>
      </div>
    </div>
  );
}

function fmtContrib(s: number): string {
  const pp = Math.abs(s * 100).toFixed(1);
  return s > 0 ? `+${pp} pp` : s < 0 ? `\u2212${pp} pp` : `${pp} pp`;
}

function RegulatoryPanel({ cal }: { cal: Calibration }) {
  if (!cal.regulatoryStatus || cal.regulatoryStatus === "NOT_EVALUATED") {
    return null;
  }

  return (
    <div
      className="rounded-lg"
      style={{
        padding: 16,
        background: T.surface,
        border: `1px solid ${cal.regulatoryStatus === "NON_COMPLIANT" ? T.hardStopBorder : cal.regulatoryStatus === "REQUIRES_REVIEW" ? T.amber + "66" : T.green + "44"}`,
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Globe size={16} color={T.accent} />
        <span className="font-bold" style={{ fontSize: FS.md, color: T.text }}>DoD Compliance Assessment</span>
        {cal.sensitivityContext && cal.sensitivityContext !== "COMMERCIAL" && (() => {
          const sensitivity = SENSITIVITY_META[parseSensitivity(cal.sensitivityContext)];
          return (
            <span
              className="rounded px-2 py-0.5 font-semibold"
              style={{ fontSize: FS.sm, background: sensitivity.bg, color: sensitivity.color, border: `1px solid ${sensitivity.tagColor}44` }}
            >
              {sensitivity.label}
            </span>
          );
        })()}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Regulatory Status</div>
          <div className="font-bold" style={{
            fontSize: FS.sm,
            color: cal.regulatoryStatus === "COMPLIANT" ? T.green
              : cal.regulatoryStatus === "NON_COMPLIANT" ? T.red
                : T.amber,
          }}>
            {cal.regulatoryStatus.replace(/_/g, " ")}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Recommendation</div>
          <div className="font-bold" style={{
            fontSize: FS.sm,
            color: cal.recommendation?.includes("APPROVED") ? T.green
              : cal.recommendation?.includes("DO_NOT") ? T.red
                : T.amber,
          }}>
            {(cal.recommendation || "").replace(/_/g, " ")}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Eligible</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodEligible ? T.green : T.red }}>
            {cal.dodEligible ? "YES" : "NO"}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Qualified</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodQualified ? T.green : T.red }}>
            {cal.dodQualified ? "YES" : "NO"}
          </div>
        </div>
      </div>

      {cal.regulatoryFindings && cal.regulatoryFindings.length > 0 && (
        <div className="mt-3" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Regulatory Gate Findings
          </div>
          {(cal.regulatoryFindings as Array<Record<string, unknown>>).map((finding, i) => (
            <div
              key={i}
              className="flex gap-2 mb-2 rounded p-2"
              style={{
                background: String(finding.status) === "FAIL" ? T.redBg : T.amberBg,
                border: `1px solid ${String(finding.status) === "FAIL" ? T.red + "33" : T.amber + "33"}`,
              }}
            >
              <div className="font-bold shrink-0" style={{
                fontSize: FS.sm,
                color: String(finding.status) === "FAIL" ? T.red : T.amber,
                minWidth: 40,
              }}>
                {String(finding.status)}
              </div>
              <div>
                <div className="font-semibold" style={{ fontSize: FS.sm, color: T.text }}>{String(finding.name)}</div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 1 }}>{String(finding.explanation)}</div>
                {finding.remediation ? (
                  <div style={{ fontSize: FS.sm, color: T.amber, marginTop: 3 }}>Remediation: {String(finding.remediation)}</div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {cal.modelVersion && (
        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, textAlign: "right" }}>
          Engine: {cal.modelVersion}
        </div>
      )}
    </div>
  );
}

export function CaseDetail({ c, onBack, onRescore, onDossier }: CaseDetailProps) {
  const cal = c.cal;
  const user = getUser();
  const isReviewer = user?.role === "reviewer";

  const [rescoring, setRescoring] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichment, setEnrichment] = useState<EnrichmentReport | null>(null);
  const [showStream, setShowStream] = useState(false);
  const [showAI, setShowAI] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [showDeepAnalysis, setShowDeepAnalysis] = useState(false);
  const [evidenceTab, setEvidenceTab] = useState<"intel" | "findings" | "events" | "model">("model");
  const [error, setError] = useState<string | null>(null);
  const evidenceRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchEnrichment(c.id).then((report) => {
      if (report && report.findings && report.findings.length > 0) {
        setEnrichment(report);
        setEvidenceTab(report.intel_summary ? "intel" : "findings");
      }
    }).catch(() => {});
  }, [c.id]);

  const handleEnrich = async () => {
    setEnriching(true);
    setShowStream(true);
    setShowAI(false);
    setError(null);
  };

  const handleStreamComplete = async () => {
    try {
      const fullReport = await fetchEnrichment(c.id);
      setEnrichment(fullReport);
      setEvidenceTab(fullReport.intel_summary ? "intel" : "findings");
      setShowStream(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load enrichment report");
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
    setGenerating(true);
    setError(null);
    try {
      // Generate the rich HTML dossier (with AI narrative, graphs, full layout)
      const resp = await fetch(`/api/cases/${c.id}/dossier`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${sessionStorage.getItem("xiphos_token") || localStorage.getItem("xiphos_token") || ""}`,
        },
      });
      if (!resp.ok) throw new Error(`Dossier failed: ${resp.status}`);
      const data = await resp.json();
      const url = data.download_url || `/api/dossiers/dossier-${c.id}.html`;
      // Open the HTML dossier in a new tab (user can print to PDF from browser)
      const token = sessionStorage.getItem("xiphos_token") || localStorage.getItem("xiphos_token") || "";
      window.open(`${url}?token=${encodeURIComponent(token)}`, "_blank");
    } catch (e) {
      // Fallback to client-side dossier
      if (onDossier) {
        try {
          await onDossier(c.id);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Dossier generation failed");
        }
      } else {
        setError(e instanceof Error ? e.message : "Dossier generation failed");
      }
    } finally {
      setGenerating(false);
    }
  };

  const hasApi = !!onRescore;
  const sortedCt = useMemo(
    () => (cal ? [...cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s)) : []),
    [cal],
  );
  const riskBand = cal ? tierBand(parseTier(cal.tier)) : "clear";
  const whyItems = useMemo(() => {
    if (!cal) return [];
    if (cal.stops.length > 0) {
      return cal.stops.slice(0, 3).map((stop) => stop.t);
    }

    const findings = cal.finds.slice(0, 3);
    if (findings.length > 0) return findings;

    const flags = cal.flags.slice(0, 3).map((flag) => `${flag.t}: ${flag.x}`);
    if (flags.length > 0) return flags;

    return sortedCt.slice(0, 3).map((factor) => factor.d);
  }, [cal, sortedCt]);

  const decisionHeadline = (() => {
    if (!cal) return "Assessment in progress";
    if (cal.stops.length > 0) return "Do not proceed";
    if (riskBand === "elevated") return "Enhanced review required";
    if (riskBand === "conditional") return "Conditional review recommended";
    return "Suitable for standard processing";
  })();

  const decisionSummary = (() => {
    if (!cal) return "Helios is assembling the evidence and recommendation.";
    if (cal.stops.length > 0) {
      return cal.stops[0]?.x || "A hard-stop condition prevents procurement until resolved.";
    }
    if (riskBand === "elevated") {
      return "The evidence warrants enhanced diligence before approval.";
    }
    if (riskBand === "conditional") {
      return "The vendor appears workable, but some targeted review is still warranted.";
    }
    return `${probLabel(cal.p)} with strong transparency and low immediate concern signals.`;
  })();

  const evidenceTabs = [
    { id: "intel" as const, label: "Intel Summary", disabled: !enrichment },
    { id: "findings" as const, label: "Raw Findings", disabled: !enrichment },
    { id: "events" as const, label: "Events", disabled: !enrichment || (enrichment?.events?.length ?? 0) === 0 },
    { id: "model" as const, label: "Model Factors", disabled: !cal },
  ];

  const openEvidence = (tab: "intel" | "findings" | "events" | "model") => {
    if (tab !== "model" && !enrichment) {
      void handleEnrich();
      return;
    }
    setEvidenceTab(tab);
    setTimeout(() => evidenceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };

  return (
    <div className="flex flex-col gap-3 h-full">
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer shrink-0 self-start"
        style={{ fontSize: FS.sm, color: T.muted }}
      >
        <ChevronLeft size={11} /> Back to Assessments
      </button>

      <div className="flex-1 min-h-0 overflow-auto pr-1">
        <div className="rounded-lg shrink-0" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16 }}>
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div style={{ flex: 1, minWidth: 260 }}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold" style={{ fontSize: FS.xl, color: T.text }}>{c.name}</span>
                {cal && <TierBadge tier={cal.tier} />}
                {isReviewer && (
                  <div className="inline-flex items-center gap-1 rounded px-2 py-1" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                    <Lock size={10} color={T.muted} />
                    <span style={{ fontSize: FS.sm, color: T.muted, fontWeight: 600 }}>Read only</span>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 flex-wrap mt-1.5">
                <span className="inline-flex items-center gap-1" style={{ fontSize: FS.sm, color: T.muted }}>
                  <Globe size={11} />{c.cc}
                </span>
                <span className="inline-flex items-center gap-1" style={{ fontSize: FS.sm, color: T.muted }}>
                  <Clock size={11} />{c.date}
                </span>
                <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>{c.id}</span>
              </div>
            </div>

            {cal && (
              <div className="flex items-center gap-3 flex-wrap justify-end">
                <div className="rounded-lg px-3 py-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Posterior</div>
                  <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text }}>{Math.round(cal.p * 100)}%</div>
                </div>
                <div className="rounded-lg px-3 py-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Rubric</div>
                  <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text }}>{c.sc}/100</div>
                </div>
                <div className="rounded-lg px-3 py-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Coverage</div>
                  <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text }}>{Math.round(cal.cov * 100)}%</div>
                </div>
              </div>
            )}
          </div>

          <div style={{ marginTop: 18, paddingTop: 18, borderTop: `1px solid ${T.border}` }}>
            <div style={{ fontSize: FS.lg, fontWeight: 700, color: T.text, marginBottom: 6 }}>{decisionHeadline}</div>
            <div style={{ fontSize: FS.base, color: T.dim, lineHeight: 1.6, maxWidth: 760 }}>{decisionSummary}</div>
          </div>

          {whyItems.length > 0 && (
            <div className="mt-4 rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 14 }}>
              <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
                Why Helios made this recommendation
              </div>
              <div className="flex flex-col gap-2">
                {whyItems.map((item, index) => (
                  <div key={`${item}-${index}`} className="flex gap-2">
                    <span style={{ color: T.accent, fontSize: FS.sm, lineHeight: 1.5 }}>•</span>
                    <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-2 flex-wrap mt-4">
            <button
              onClick={handleDossier}
              disabled={generating || !cal}
              className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
              style={{
                padding: "8px 12px", fontSize: FS.sm,
                background: T.raised, color: T.text, borderColor: T.border,
                opacity: generating || !cal ? 0.5 : 1,
              }}
            >
              {generating ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
              {generating ? "Generating..." : "Generate Dossier"}
            </button>

            <button
              onClick={() => openEvidence(enrichment?.intel_summary ? "intel" : "findings")}
              disabled={showStream}
              className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
              style={{
                padding: "8px 12px", fontSize: FS.sm,
                background: evidenceTab === "intel" || evidenceTab === "findings" ? T.accent + "18" : T.raised,
                color: evidenceTab === "intel" || evidenceTab === "findings" ? T.accent : T.dim,
                borderColor: evidenceTab === "intel" || evidenceTab === "findings" ? T.accent + "44" : T.border,
                opacity: showStream ? 0.6 : 1,
              }}
            >
              <Radar size={12} />
              {enrichment ? "Open Intel" : "Run Intel"}
            </button>

            {!isReviewer && (
              <button
                onClick={handleEnrich}
                disabled={enriching}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "8px 12px", fontSize: FS.sm,
                  background: T.raised, color: T.dim, borderColor: T.border,
                  opacity: enriching ? 0.5 : 1,
                }}
              >
                {enriching ? <Loader2 size={12} className="animate-spin" /> : <Radar size={12} />}
                {enriching ? "Enriching..." : enrichment ? "Re-Enrich" : "Run Screening"}
              </button>
            )}

            {!isReviewer && (
              <div style={{ position: "relative" }}>
                <button
                  onClick={() => setShowMoreActions((current) => !current)}
                  className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                  style={{
                    padding: "8px 12px", fontSize: FS.sm,
                    background: T.surface, color: T.dim, borderColor: T.border,
                  }}
                >
                  <MoreHorizontal size={12} /> More
                </button>

                {showMoreActions && (
                  <div
                    className="rounded-lg"
                    style={{
                      position: "absolute",
                      top: "calc(100% + 8px)",
                      right: 0,
                      minWidth: 180,
                      background: T.surface,
                      border: `1px solid ${T.border}`,
                      boxShadow: "0 12px 32px rgba(0,0,0,0.35)",
                      padding: 6,
                      zIndex: 20,
                    }}
                  >
                    <button
                      onClick={() => {
                        setShowAI((current) => !current);
                        setShowMoreActions(false);
                      }}
                      className="w-full text-left rounded border-none cursor-pointer"
                      style={{ padding: "9px 10px", background: "transparent", color: T.text, fontSize: FS.sm }}
                    >
                      {showAI ? "Hide AI Analysis" : "Open AI Analysis"}
                    </button>
                    {hasApi ? (
                      <button
                        onClick={() => {
                          void handleRescore();
                          setShowMoreActions(false);
                        }}
                        disabled={rescoring}
                        className="w-full text-left rounded border-none cursor-pointer"
                        style={{ padding: "9px 10px", background: "transparent", color: T.text, fontSize: FS.sm, opacity: rescoring ? 0.6 : 1 }}
                      >
                        {rescoring ? "Re-Scoring..." : "Re-Score"}
                      </button>
                    ) : (
                      <div style={{ padding: "9px 10px", color: T.muted, fontSize: FS.sm }}>
                        Re-Score unavailable offline
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {cal?.stops && cal.stops.length > 0 && (
            <div
              className="mt-3 rounded-lg"
              style={{
                padding: 16,
                background: T.hardStopBg,
                border: `2px solid ${T.hardStopBorder}`,
                boxShadow: "0 0 20px rgba(220,38,38,0.2)",
              }}
            >
              <div className="flex gap-3">
                <XCircle size={20} color="#ffffff" className="shrink-0 mt-0.5" />
                <div>
                  <div className="font-bold" style={{ fontSize: FS.lg, color: "#ffffff" }}>
                    PROHIBITED ENGAGEMENT
                  </div>
                  <div className="font-semibold" style={{ fontSize: FS.base, color: "#fca5a5", marginTop: 4 }}>
                    {cal.stops[0].t}
                  </div>
                  <div style={{ fontSize: FS.sm, color: "#fecaca", marginTop: 4, lineHeight: 1.5 }}>
                    {cal.stops[0].x}
                  </div>
                  <div style={{ fontSize: FS.sm, color: "#fca5a5", marginTop: 6, opacity: 0.8 }}>
                    Confidence: {Math.round(cal.stops[0].c * 100)}%
                  </div>
                </div>
              </div>
            </div>
          )}

          {cal?.flags && cal.flags.length > 0 && !(cal.stops.length > 0) && (
            <div className="flex flex-wrap gap-2 mt-3">
              {cal.flags.map((flag, i) => (
                <div
                  key={i}
                  className="flex gap-1.5 rounded flex-1 min-w-[200px]"
                  style={{ padding: 10, background: T.amberBg, border: `1px solid ${T.amber}33` }}
                >
                  <AlertTriangle size={13} color={T.amber} className="shrink-0 mt-0.5" />
                  <div>
                    <div className="font-bold" style={{ fontSize: FS.sm, color: T.amber }}>{flag.t}</div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 1 }}>{flag.x}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {error && (
            <div
              className="flex items-center gap-2 mt-3 rounded"
              style={{ padding: "8px 12px", background: T.redBg, border: `1px solid ${T.red}33` }}
            >
              <XCircle size={12} color={T.red} className="shrink-0" />
              <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
            </div>
          )}
        </div>

        {showStream && enriching && (
          <div className="mt-3">
            <EnrichmentStream
              caseId={c.id}
              token={getToken() || ""}
              apiBase={import.meta.env.VITE_API_URL ?? ""}
              onComplete={handleStreamComplete}
            />
          </div>
        )}

        <div ref={evidenceRef} className="mt-3 rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 14 }}>
          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
            Evidence
          </div>
          <div className="flex gap-2 flex-wrap mt-3">
            {evidenceTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => openEvidence(tab.id)}
                disabled={tab.disabled}
                className="rounded font-medium border cursor-pointer"
                style={{
                  padding: "7px 10px",
                  fontSize: FS.sm,
                  background: evidenceTab === tab.id ? T.accent + "18" : T.raised,
                  color: evidenceTab === tab.id ? T.accent : tab.disabled ? T.muted : T.dim,
                  borderColor: evidenceTab === tab.id ? T.accent + "44" : T.border,
                  opacity: tab.disabled ? 0.55 : 1,
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="mt-4">
            {evidenceTab === "model" && cal && (
              <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
                <div className="rounded-lg p-4" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
                    Model View
                  </div>
                  <div style={{ fontSize: FS.xl, fontWeight: 700, color: T.text, marginBottom: 4 }}>
                    {Math.round(cal.p * 100)}%
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>
                    {probLabel(cal.p)}. Coverage {Math.round(cal.cov * 100)}%. Confidence {Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)))}%.
                  </div>
                </div>
                <div className="rounded-lg p-4" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                    Top Model Factors
                  </div>
                  <div className="flex flex-col gap-3">
                    {sortedCt.slice(0, 4).map((factor, index) => (
                      <div key={`${factor.n}-${index}`} style={{ paddingBottom: index < 3 ? 12 : 0, borderBottom: index < 3 ? `1px solid ${T.border}` : "none" }}>
                        <div className="flex items-center justify-between gap-3">
                          <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>{factor.n}</span>
                          <span style={{ fontSize: FS.sm, color: factor.s > 0 ? T.red : factor.s < 0 ? T.green : T.muted, fontFamily: "monospace" }}>
                            {fmtContrib(factor.s)}
                          </span>
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>{factor.d}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {evidenceTab !== "model" && enrichment && !showStream && (
              <EnrichmentPanel caseId={c.id} report={enrichment} section={evidenceTab} />
            )}

            {evidenceTab !== "model" && !enrichment && !showStream && (
              <div
                className="rounded-lg p-5 text-center"
                style={{ background: T.raised, border: `1px solid ${T.border}`, fontSize: FS.sm, color: T.muted }}
              >
                Run screening to load evidence for this case.
              </div>
            )}
          </div>
        </div>

        {cal && (
          <div className="mt-3">
            <ActionPanel case={c} />
          </div>
        )}

        {showAI && (
          <div className="mt-3">
            <AIAnalysisPanel caseId={c.id} vendorName={c.name} />
          </div>
        )}

        <div className="mt-3">
          <button
            onClick={() => setShowDeepAnalysis((current) => !current)}
            className="inline-flex items-center gap-2 rounded-lg border cursor-pointer"
            style={{ padding: "9px 12px", background: T.surface, color: T.dim, borderColor: T.border, fontSize: FS.sm }}
          >
            <Activity size={12} />
            {showDeepAnalysis ? "Hide detailed analysis" : "Show detailed analysis"}
          </button>
        </div>

        {showDeepAnalysis && (
          <div className="flex flex-col gap-3 mt-3">
            {cal && <RegulatoryPanel cal={cal} />}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <div className="flex flex-col gap-3">
                <div className="rounded-lg p-5" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                    Bayesian Posterior
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 10 }}>
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
                        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                          Coverage {Math.round(cal.cov * 100)}%
                        </span>
                        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                          Confidence {Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)))}%
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-8" style={{ fontSize: FS.sm, color: T.muted }}>
                      Scoring in progress...
                    </div>
                  )}
                </div>

                {cal && c.history && c.history.length > 0 && (
                  <ScoreHistory history={c.history} current={{ p: cal.p, tier: cal.tier, ts: new Date().toISOString() }} />
                )}

                {cal && (
                  <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                      Risk Factor Contributions
                    </div>
                    {sortedCt.map((ct, i) => (
                      <div
                        key={i}
                        style={{ padding: "8px 0", borderBottom: i < sortedCt.length - 1 ? `1px solid ${T.border}` : "none" }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>{ct.n}</span>
                          <div className="flex items-center gap-3">
                            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                              w={ct.c.toFixed(1)}
                            </span>
                            <span
                              className="font-mono font-semibold"
                              style={{ fontSize: FS.sm, color: ct.s > 0 ? T.red : ct.s < 0 ? T.green : T.muted }}
                            >
                              {fmtContrib(ct.s)}
                            </span>
                          </div>
                        </div>
                        <ContribBar value={ct.raw} color={ct.raw > 0.7 ? T.red : ct.raw > 0.4 ? T.amber : T.green} />
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 3 }}>{ct.d}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
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
                          ["Confidence", Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100))) + "%"],
                        ]
                      : []),
                  ].map(([k, v], i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between"
                      style={{ padding: "5px 0", borderBottom: `1px solid ${T.border}` }}
                    >
                      <span style={{ fontSize: FS.sm, color: T.muted }}>{k}</span>
                      <span className="font-mono" style={{ fontSize: FS.sm, color: T.dim }}>{v}</span>
                    </div>
                  ))}

                  <div style={{ padding: "10px 0 0", marginTop: 6 }}>
                    <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                      Policy Rubric
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6 }}>
                      What procurement policy prescribes for this vendor profile
                    </div>
                    <div className="flex items-baseline gap-1 mb-2">
                      <span className="font-mono font-bold" style={{ fontSize: 22, color: T.text }}>{c.sc}</span>
                      <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>/100</span>
                      <span className="font-mono ml-2" style={{ fontSize: FS.sm, color: T.muted }}>
                        ({Math.min(99, Math.max(0, Math.round((c.conf || 0.85) * 100)))}% confidence)
                      </span>
                    </div>
                    <div className="w-full rounded-full overflow-hidden" style={{ height: 4, background: T.border }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${c.sc}%`, background: c.sc > 70 ? T.red : c.sc > 40 ? T.amber : T.green }}
                      />
                    </div>
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
                            <span style={{ fontSize: FS.sm, color: T.amber }}>
                              Consensus break: Bayesian ({bayesPct}%) and Policy Rubric ({c.sc}) diverge by {divergence} points
                            </span>
                          </div>
                        );
                      }
                      return null;
                    })()}
                  </div>
                </div>

                {cal?.finds && cal.finds.length > 0 && (
                  <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                      Key Findings
                    </div>
                    {cal.finds.map((finding, i) => (
                      <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                        <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.sm, color: T.accent }}>
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{finding}</span>
                      </div>
                    ))}
                  </div>
                )}

                {cal?.miv && cal.miv.length > 0 && (
                  <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                      Recommended Data Collection
                    </div>
                    {cal.miv.map((m, i) => (
                      <div
                        key={i}
                        className="rounded"
                        style={{ padding: 10, background: T.raised, border: `1px solid ${T.border}`, marginTop: i > 0 ? 8 : 0 }}
                      >
                        <div className="font-medium" style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.4 }}>{m.t}</div>
                        <div className="flex gap-3 mt-1.5">
                          <span className="font-mono" style={{ fontSize: FS.sm, color: T.accent }}>
                            {m.i > 0 ? "\u2212" : "+"}{m.i.toFixed(1)} pp impact
                          </span>
                          <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
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
        )}
      </div>
    </div>
  );
}
