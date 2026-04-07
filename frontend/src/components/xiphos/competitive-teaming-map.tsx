import type { ChangeEvent } from "react";

import { T, FS } from "@/lib/tokens";
import type { VehicleTeamingIntelligenceReport } from "@/lib/api";

interface CompetitiveTeamingMapProps {
  report: VehicleTeamingIntelligenceReport | null;
  loading: boolean;
  error: string | null;
  scenarioPartner: string;
  onScenarioPartnerChange: (partner: string) => void;
}

const CLASS_LABELS: Record<string, string> = {
  "incumbent-core": "Incumbent Core",
  locked: "Locked",
  swing: "Swing",
  recruitable: "Recruitable",
  cooling: "Cooling",
  emerging: "Emerging",
};

const CLASS_COLORS: Record<string, string> = {
  "incumbent-core": T.gold,
  locked: T.red,
  swing: T.amber,
  recruitable: T.green,
  cooling: T.accent,
  emerging: T.dim,
};

function badgeStyles(classification: string) {
  const color = CLASS_COLORS[classification] || T.dim;
  return {
    color,
    border: `1px solid ${color}33`,
    background: `${color}12`,
  };
}

export function CompetitiveTeamingMap({
  report,
  loading,
  error,
  scenarioPartner,
  onScenarioPartnerChange,
}: CompetitiveTeamingMapProps) {
  if (loading) {
    return (
      <div style={{ padding: 18, borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 8 }}>Competitive Teaming Map</div>
        <div style={{ fontSize: FS.sm, color: T.dim }}>Building the current vehicle partner map from the active graph snapshot...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 18, borderRadius: 12, border: `1px solid ${T.red}33`, background: T.redBg }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: T.red, letterSpacing: "0.08em", marginBottom: 8 }}>Competitive Teaming Map</div>
        <div style={{ fontSize: FS.sm, color: T.red }}>{error}</div>
      </div>
    );
  }

  if (!report) {
    return null;
  }

  const incumbentName = report.incumbent_prime?.name || "Unresolved";
  const grouped = report.assessed_partners.reduce<Record<string, typeof report.assessed_partners>>((acc, partner) => {
    const key = partner.classification;
    if (!acc[key]) acc[key] = [];
    acc[key].push(partner);
    return acc;
  }, {});
  const scenarioCandidates = report.assessed_partners.filter((partner) => partner.classification !== "incumbent-core");

  return (
    <div style={{ padding: 18, borderRadius: 12, border: `1px solid ${T.border}`, background: T.surface }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 8 }}>Competitive Teaming Map</div>
          <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.text, marginBottom: 4 }}>{report.vehicle_name}</div>
          <div style={{ fontSize: FS.sm, color: T.dim }}>
            Observed graph edges stay separate from assessed partner classes and predicted scenario moves.
          </div>
        </div>
        <div style={{ minWidth: 220 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 6 }}>Scenario Probe</div>
          <select
            value={scenarioPartner}
            onChange={(event: ChangeEvent<HTMLSelectElement>) => onScenarioPartnerChange(event.target.value)}
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 10,
              border: `1px solid ${T.border}`,
              background: T.bg,
              color: T.text,
              fontSize: FS.sm,
            }}
          >
            <option value="">Pick a partner to test</option>
            {scenarioCandidates.map((partner) => (
              <option key={partner.entity_id} value={partner.entity_name}>
                {partner.display_name} · {CLASS_LABELS[partner.classification] || partner.classification}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!report.supported && (
        <div style={{ marginBottom: 16, padding: 12, borderRadius: 10, border: `1px solid ${T.amber}33`, background: T.amberBg, color: T.amber, fontSize: FS.sm }}>
          {report.message || "Helios does not yet have enough graph-backed signal to build a stable teaming read for this vehicle."}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 18 }}>
        <div style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 6 }}>Vehicle</div>
          <div style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>{report.vehicle_name}</div>
        </div>
        <div style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.gold}33`, background: `${T.gold}10` }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 6 }}>Incumbent Core</div>
          <div style={{ fontSize: FS.base, fontWeight: 600, color: T.text }}>{incumbentName}</div>
        </div>
        <div style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 6 }}>Graph Snapshot</div>
          <div style={{ fontSize: 12, color: T.dim, wordBreak: "break-all" }}>{report.graph_snapshot_signature}</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 18 }}>
        {["locked", "swing", "recruitable", "cooling", "emerging"].map((classification) => {
          const partners = grouped[classification] || [];
          return (
            <div key={classification} style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 10 }}>
                {CLASS_LABELS[classification] || classification} ({partners.length})
              </div>
              {partners.length === 0 ? (
                <div style={{ fontSize: 12, color: T.dim }}>No assessed partners in this class yet.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {partners.map((partner) => (
                    <div key={partner.entity_id} style={{ padding: 10, borderRadius: 10, border: `1px solid ${T.border}`, background: T.surface }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start", marginBottom: 6 }}>
                        <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>{partner.display_name}</div>
                        <span style={{ ...badgeStyles(partner.classification), padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700 }}>
                          {partner.confidence_label.toUpperCase()}
                        </span>
                      </div>
                      <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>{partner.rationale}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {report.top_conclusions.length > 0 && (
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 8 }}>Top Conclusions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {report.top_conclusions.map((conclusion) => (
              <div key={conclusion} style={{ padding: "10px 12px", borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg, fontSize: 12, color: T.text, lineHeight: 1.5 }}>
                {conclusion}
              </div>
            ))}
          </div>
        </div>
      )}

      {report.scenario && (
        <div style={{ marginBottom: 18, padding: 12, borderRadius: 10, border: `1px solid ${T.accent}33`, background: T.accentSoft }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.accent, letterSpacing: "0.08em", marginBottom: 6 }}>Predicted Scenario</div>
          <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600, marginBottom: 4 }}>{report.scenario.recommendation.replace(/_/g, " ")}</div>
          <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>{report.scenario.rationale}</div>
        </div>
      )}

      {report.assessed_partners.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.08em", marginBottom: 8 }}>Evidence-bound Partner Reads</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {report.assessed_partners.map((partner) => (
              <div key={partner.entity_id} style={{ padding: 12, borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
                  <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text }}>{partner.display_name}</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ ...badgeStyles(partner.classification), padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700 }}>
                      {CLASS_LABELS[partner.classification] || partner.classification}
                    </span>
                    <span style={{ padding: "2px 8px", borderRadius: 999, border: `1px solid ${T.border}`, color: T.dim, fontSize: 10, fontWeight: 700 }}>
                      {Math.round(partner.confidence * 100)}%
                    </span>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5, marginBottom: 8 }}>{partner.rationale}</div>
                {partner.observed_signals.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {partner.observed_signals.slice(0, 2).map((signal) => (
                      <div key={signal} style={{ fontSize: 11, color: T.muted, lineHeight: 1.45 }}>
                        {signal}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
