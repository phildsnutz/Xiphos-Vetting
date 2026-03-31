import { T, FS, tierBand } from "@/lib/tokens";
import { CheckCircle2, AlertTriangle, Shield, ChevronRight } from "lucide-react";
import type { VettingCase } from "@/lib/types";

interface ActionPanelProps {
  case: VettingCase;
}

function ActionStep({ number, text, isDone = false }: { number: number; text: string; isDone?: boolean }) {
  return (
    <div className="flex gap-3 items-start">
      <div
        className="flex-shrink-0 flex items-center justify-center rounded-full mt-0.5"
        style={{
          width: 24,
          height: 24,
          background: isDone ? T.green + "22" : T.raised,
          border: `1.5px solid ${isDone ? T.green : T.border}`,
        }}
      >
        {isDone ? (
          <CheckCircle2 size={14} color={T.green} />
        ) : (
          <span style={{ fontSize: FS.sm, fontWeight: 600, color: T.muted }}>{number}</span>
        )}
      </div>
      <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{text}</span>
    </div>
  );
}

function fmtPct(value?: number, digits = 0): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(digits)}%`;
}

function PolicyBasisDisclosure({ case: c }: ActionPanelProps) {
  const cal = c.cal;
  if (!cal?.policy) return null;

  const screeningPolicy = cal.policy.screening;
  const sanctionsPolicy = cal.policy.sanctions_policy;
  const uncertainty = cal.policy.uncertainty;
  const screening = cal.screening;

  return (
    <details
      className="mt-4 rounded-lg"
      style={{ background: T.raised, border: `1px solid ${T.border}` }}
    >
      <summary
        className="cursor-pointer select-none px-3 py-2"
        style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}
      >
        Policy Basis
      </summary>
      <div className="px-3 pb-3 pt-1 space-y-3">
        <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>
          {cal.modelVersion || "Model"} · {cal.policy.mode || "layered"} scoring · {cal.policy.profile || "default"} profile
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6 }}>Sanctions Screening</div>
            <div style={{ fontSize: FS.sm, color: T.text }}>Composite threshold: {fmtPct(screeningPolicy?.composite_threshold)}</div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
              Prefilter JW floor: {fmtPct(screeningPolicy?.prefilter?.jaro_winkler_floor)}
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2 }}>
              Token overlap floor: {fmtPct(screeningPolicy?.prefilter?.token_overlap_ratio)}
            </div>
            {screening && (
              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 6 }}>
                Latest screen: {screening.matched ? fmtPct(screening.bestScore) : "No active match"} from {screening.dbLabel}
              </div>
            )}
          </div>

          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6 }}>Escalation Thresholds</div>
            <div style={{ fontSize: FS.sm, color: T.text }}>
              Hard stop: {fmtPct(sanctionsPolicy?.hard_stop_threshold_default)}
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
              Allied cross-country hard stop: {fmtPct(sanctionsPolicy?.hard_stop_threshold_allied_cross_country)}
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2 }}>
              Soft flag floor: {fmtPct(sanctionsPolicy?.soft_flag_floor)}
            </div>
          </div>
        </div>

        {uncertainty && (
          <div className="rounded-lg p-3" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
            <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6 }}>Uncertainty Model</div>
            <div style={{ fontSize: FS.sm, color: T.text }}>
              Effective evidence strength: {uncertainty.effective_n_final?.toFixed(1) ?? "N/A"}
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4 }}>
              Base n: {uncertainty.effective_n_base?.toFixed(1) ?? "N/A"} · source reliability {fmtPct(uncertainty.source_reliability_avg)}
            </div>
            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2 }}>
              Identifier boost: {typeof uncertainty.identifier_boost === "number" ? uncertainty.identifier_boost : "N/A"}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}

export function ActionPanel({ case: c }: ActionPanelProps) {
  if (!c.cal) return null;

  const cal = c.cal;
  const tier = cal.tier;

  // CRITICAL tier
  if (tierBand(tier) === "critical") {
    return (
      <div className="rounded-lg p-4 glass-panel animate-fade-in">
        <div
          className="rounded-lg p-4 mb-4"
          style={{
            background: T.dRedBg,
            border: `2px solid ${T.dRed}`,
            boxShadow: `0 0 16px ${T.dRed}33`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={16} color={T.dRed} />
            <span className="font-bold" style={{ fontSize: FS.md, color: T.dRed }}>
              COMPLIANCE BLOCK – Immediate Action Required
            </span>
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim }}>
            This vendor triggers one or more hard-stop rules and cannot proceed with procurement.
          </div>
        </div>

        {/* Hard stop reasons */}
        {cal.stops && cal.stops.length > 0 && (
          <div className="mb-4 rounded-lg p-3 glass-card">
            <div className="font-semibold mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
              Hard Stop Triggers
            </div>
            {cal.stops.map((stop, i) => (
              <div key={i} style={{ marginTop: i > 0 ? 8 : 0 }}>
                <div className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>
                  {stop.t}
                </div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2, marginBottom: 3 }}>{stop.x}</div>
                <div style={{ fontSize: FS.sm, color: T.muted }}>Confidence: {Math.round(stop.c * 100)}%</div>
              </div>
            ))}
          </div>
        )}

        {/* Action steps */}
        <div className="space-y-3">
          <ActionStep number={1} text="Do not proceed with procurement of this vendor" />
          <ActionStep number={2} text="Document the hard stop trigger(s) in your case file" />
          <ActionStep number={3} text="Escalate to your Compliance Officer immediately" />
          <ActionStep number={4} text="If you believe this is a false positive, submit an override request with detailed justification" />
        </div>

        {/* Risk reduction */}
        <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            Estimated risk reduction: <strong style={{ color: T.text }}>N/A (categorical prohibition)</strong>
          </div>
        </div>

        <PolicyBasisDisclosure case={c} />
      </div>
    );
  }

  // ELEVATED tier
  if (tierBand(tier) === "elevated") {
    // Analyze top contributing factors to provide context-specific recommendations
    const topFactors = cal.ct.slice().sort((a, b) => Math.abs(b.s) - Math.abs(a.s)).slice(0, 3);
    const factorNames = topFactors.map((f) => f.n.toLowerCase());

    const recommendations: { title: string; description: string; expectedReduction: number }[] = [];

    if (factorNames.some((n) => n.includes("ownership"))) {
      recommendations.push({
        title: "Obtain beneficial ownership documentation (Form 5369-B or equivalent)",
        description: "Verify beneficial ownership structure and resolve shell company concerns",
        expectedReduction: 0.08,
      });
    }

    if (factorNames.some((n) => n.includes("data") || n.includes("quality"))) {
      recommendations.push({
        title: "Request vendor to provide CAGE code, LEI, and DUNS number",
        description: "Improve data quality signals and entity resolution confidence",
        expectedReduction: 0.06,
      });
    }

    if (factorNames.some((n) => n.includes("geograph") || n.includes("location"))) {
      recommendations.push({
        title: "Verify end-use certificate and confirm no transshipment risk",
        description: "Validate geographic risk and end-destination controls",
        expectedReduction: 0.07,
      });
    }

    if (factorNames.some((n) => n.includes("sanction"))) {
      recommendations.push({
        title: "Conduct manual sanctions name review – compare against SDN list directly",
        description: "Resolve fuzzy matches through manual screening",
        expectedReduction: 0.09,
      });
    }

    if (factorNames.some((n) => n.includes("executive") || n.includes("principal"))) {
      recommendations.push({
        title: "Run enhanced background check on key principals",
        description: "Verify executive backgrounds and adverse media",
        expectedReduction: 0.05,
      });
    }

    // If no specific recommendations, use generic ones
    if (recommendations.length === 0) {
      recommendations.push({
        title: "Conduct comprehensive vendor review",
        description: "Review all available data and conduct enhanced due diligence",
        expectedReduction: 0.1,
      });
    }

    return (
      <div className="rounded-lg p-4 glass-panel animate-fade-in">
        <div
          className="rounded-lg p-4 mb-4"
          style={{
            background: T.orangeBg,
            border: `2px solid ${T.orange}`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={16} color={T.orange} />
            <span className="font-bold" style={{ fontSize: FS.md, color: T.orange }}>
              ENHANCED DUE DILIGENCE REQUIRED
            </span>
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim }}>
            This vendor requires comprehensive review before procurement approval. Complete all recommended actions below.
          </div>
        </div>

        {/* Soft flags if any */}
        {cal.flags && cal.flags.length > 0 && (
          <div className="mb-4 rounded-lg p-3 glass-card">
            <div className="font-semibold mb-2" style={{ fontSize: FS.sm, color: T.amber }}>
              Soft Flags Detected
            </div>
            {cal.flags.map((flag, i) => (
              <div key={i} style={{ marginTop: i > 0 ? 6 : 0 }}>
                <div className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>
                  {flag.t}
                </div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2 }}>{flag.x}</div>
              </div>
            ))}
          </div>
        )}

        {/* Recommended actions */}
        <div className="mb-4">
          <div className="font-semibold mb-3" style={{ fontSize: FS.sm, color: T.text }}>
            Recommended Actions
          </div>
          <div className="space-y-3">
            {recommendations.map((rec, i) => (
              <div
                key={i}
                className="rounded-lg p-3"
                style={{ background: T.raised, border: `1px solid ${T.border}` }}
              >
                <div className="flex items-start gap-2">
                  <ChevronRight size={14} color={T.accent} className="shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>
                      {rec.title}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 1, marginBottom: 2 }}>
                      {rec.description}
                    </div>
                    <div
                      className="inline-block rounded px-2 py-1"
                      style={{ background: T.green + "11", border: `1px solid ${T.green}33` }}
                    >
                      <span className="font-mono" style={{ fontSize: FS.sm, color: T.green }}>
                        Est. -
                        {Math.round(rec.expectedReduction * 100)}pp risk reduction
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* MIV recommendations if available */}
        {cal.miv && cal.miv.length > 0 && (
          <div className="pt-4" style={{ borderTop: `1px solid ${T.border}` }}>
            <div className="font-semibold mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
              Marginal Information Value (MIV) Insights
            </div>
            {cal.miv.slice(0, 3).map((m, i) => (
              <div
                key={i}
                className="rounded-lg p-3 mt-2"
                style={{ background: T.raised, border: `1px solid ${T.border}` }}
              >
                <div className="flex items-start justify-between">
                  <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.4 }}>{m.t}</div>
                  <div className="font-mono text-right shrink-0">
                    <div style={{ fontSize: FS.sm, color: T.accent }}>{m.i > 0 ? "−" : "+"}
                      {Math.abs(m.i).toFixed(1)}pp</div>
                    <div style={{ fontSize: FS.sm, color: T.muted }}>{Math.round(m.tp * 100)}% tier prob</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <PolicyBasisDisclosure case={c} />
      </div>
    );
  }

  // CONDITIONAL tier
  if (tierBand(tier) === "conditional") {
    return (
      <div className="rounded-lg p-4 glass-panel animate-fade-in">
        <div
          className="rounded-lg p-4 mb-4"
          style={{
            background: T.amberBg,
            border: `2px solid ${T.amber}`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={16} color={T.amber} />
            <span className="font-bold" style={{ fontSize: FS.md, color: T.amber }}>
              STANDARD MONITORING – Periodic Review
            </span>
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim }}>
            This vendor may proceed with standard procurement workflow with routine monitoring.
          </div>
        </div>

        {/* Soft flags if any */}
        {cal.flags && cal.flags.length > 0 && (
          <div className="mb-4 rounded-lg p-3 glass-card">
            <div className="font-semibold mb-2" style={{ fontSize: FS.sm, color: T.amber }}>
              Items Requiring Attention
            </div>
            {cal.flags.map((flag, i) => (
              <div key={i} style={{ marginTop: i > 0 ? 6 : 0 }}>
                <div className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>
                  {flag.t}
                </div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 2 }}>{flag.x}</div>
              </div>
            ))}
          </div>
        )}

        {/* Action steps */}
        <div className="space-y-3">
          <ActionStep number={1} text="Approve for standard procurement workflow" />
          <ActionStep number={2} text="Schedule re-screening in 6 months" />
          <ActionStep number={3} text="Monitor for adverse media alerts and risk changes" />
        </div>

        {/* Next review date */}
        <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            Recommended next review:{" "}
            <strong style={{ color: T.text }}>
              {new Date(new Date(c.date).getTime() + 180 * 24 * 60 * 60 * 1000)
                .toISOString()
                .split("T")[0]}
            </strong>
          </div>
        </div>

        <PolicyBasisDisclosure case={c} />
      </div>
    );
  }

  // CLEAR tier
  if (tierBand(tier) === "clear") {
    const meanConfidence = Math.min(99, Math.max(0, Math.round((cal.mc ?? 0.85) * 100)));
    return (
      <div className="rounded-lg p-4 glass-panel animate-fade-in">
        <div
          className="rounded-lg p-4 mb-4"
          style={{
            background: T.greenBg,
            border: `2px solid ${T.green}`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Shield size={16} color={T.green} />
            <span className="font-bold" style={{ fontSize: FS.md, color: T.green }}>
              LOW RISK – Standard Processing
            </span>
          </div>
          <div style={{ fontSize: FS.sm, color: T.dim }}>
            This vendor is cleared for standard procurement without additional due diligence.
          </div>
        </div>

        {/* Action steps */}
        <div className="space-y-3">
          <ActionStep number={1} text="Proceed with standard procurement workflow" />
          <ActionStep number={2} text="Schedule annual re-screening" />
          <ActionStep number={3} text="No additional due diligence required" />
        </div>

        {/* Confidence indicator */}
        <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted }}>
            Assessment confidence: <strong style={{ color: T.green }}>{meanConfidence}%</strong>
          </div>
        </div>

        <PolicyBasisDisclosure case={c} />
      </div>
    );
  }

  return null;
}
