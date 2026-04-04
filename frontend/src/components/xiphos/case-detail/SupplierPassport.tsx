import React, { useMemo } from "react";
import { ExpandableSection } from "../case-detail-sections";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { SupplierPassport as SupplierPassportRecord } from "@/lib/api";
import type { ToneConfig } from "./case-detail-types";
import { InlineMessage, SectionEyebrow, StatusPill } from "../shell-primitives";

interface SupplierPassportProps {
  supplierPassport: SupplierPassportRecord | null;
  supplierPassportTone: ToneConfig;
  supplierPassportOfficialCorroboration: SupplierPassportRecord["identity"]["official_corroboration"] | null;
  supplierPassportOfficialTone: ToneConfig;
  downloadSupplierPassportJson: (passport: SupplierPassportRecord) => void;
  formatPassportPosture: (posture: string) => string;
}

function formatTimestamp(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function toneLabel(value: unknown): string {
  if (typeof value === "string" && value.trim()) {
    return value.replaceAll("_", " ");
  }
  return "Unknown";
}

export const SupplierPassport: React.FC<SupplierPassportProps> = ({
  supplierPassport,
  supplierPassportTone,
  supplierPassportOfficialCorroboration,
  supplierPassportOfficialTone,
  downloadSupplierPassportJson,
  formatPassportPosture,
}) => {
  const ownershipIntel = supplierPassport?.ownership.oci ?? null;
  const graphIntel = supplierPassport?.graph.intelligence ?? null;
  const generatedLabel = formatTimestamp(supplierPassport?.generated_at);
  const enrichedLabel = formatTimestamp(supplierPassport?.identity.enriched_at);
  const tribunalLabel = supplierPassport
    ? supplierPassport.tribunal.recommended_label || toneLabel(supplierPassport.tribunal.recommended_view)
    : "Unknown";
  const coverageLevel = toneLabel(supplierPassportOfficialCorroboration?.coverage_level);

  const passportMetrics = useMemo(
    () => [
      {
        label: "Connectors with data",
        value: supplierPassport?.identity.connectors_with_data ?? 0,
        detail: `${supplierPassport?.identity.findings_total ?? 0} findings surfaced`,
      },
      {
        label: "Control paths",
        value: supplierPassport?.graph.control_paths.length ?? 0,
        detail: `${supplierPassport?.graph.claim_health.corroborated_paths ?? 0} corroborated`,
      },
      {
        label: "Monitoring checks",
        value: supplierPassport?.monitoring.check_count ?? 0,
        detail: `${supplierPassport?.artifacts.count ?? 0} artifacts attached`,
      },
      {
        label: "Contradicted claims",
        value: supplierPassport?.graph.claim_health.contradicted_claims ?? 0,
        detail: `${supplierPassport?.graph.claim_health.stale_paths ?? 0} stale paths`,
      },
    ],
    [supplierPassport],
  );

  const passportSignals = useMemo(
    () => [
      {
        label: "Official corroboration",
        value: supplierPassportOfficialCorroboration?.coverage_label || coverageLevel,
        detail:
          supplierPassportOfficialCorroboration
            ? `${supplierPassportOfficialCorroboration.core_official_identifier_count ?? 0} core identifiers verified`
            : "No official corroboration captured yet",
      },
      {
        label: "Ownership resolution",
        value: ownershipIntel ? `${Math.round(ownershipIntel.ownership_resolution_pct)}%` : "Unknown",
        detail:
          ownershipIntel?.named_beneficial_owner
            ? `Named owner: ${ownershipIntel.named_beneficial_owner}`
            : "Named beneficial owner still unresolved",
      },
      {
        label: "Controlling parent",
        value: ownershipIntel?.controlling_parent_known ? "Known" : "Unknown",
        detail:
          ownershipIntel?.controlling_parent
            ? ownershipIntel.controlling_parent
            : "No controlling parent confirmed",
      },
      {
        label: "Graph claim coverage",
        value: graphIntel?.claim_coverage_pct != null ? `${Math.round(graphIntel.claim_coverage_pct)}%` : "Unknown",
        detail:
          graphIntel?.dominant_edge_family
            ? `Dominant edge family: ${toneLabel(graphIntel.dominant_edge_family)}`
            : "No dominant edge family established",
      },
      {
        label: "Tribunal recommendation",
        value: tribunalLabel,
        detail: `Consensus ${toneLabel(supplierPassport?.tribunal.consensus_level)}`,
      },
      {
        label: "Last warm run",
        value: enrichedLabel || generatedLabel || "Unknown",
        detail: generatedLabel ? `Passport generated ${generatedLabel}` : "Passport timing not captured",
      },
    ],
    [
      coverageLevel,
      generatedLabel,
      enrichedLabel,
      graphIntel,
      ownershipIntel,
      supplierPassport?.tribunal.consensus_level,
      supplierPassportOfficialCorroboration,
      tribunalLabel,
    ],
  );

  if (!supplierPassport) {
    return (
      <ExpandableSection title="Supplier Passport" defaultOpen={true}>
        <div
          style={{
            borderRadius: SP.lg,
            border: `1px dashed ${T.borderActive}`,
            background: T.surface,
            padding: PAD.comfortable,
          }}
        >
          <SectionEyebrow>Portable trust artifact</SectionEyebrow>
          <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text, marginTop: SP.sm }}>
            Passport warming
          </div>
          <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs, lineHeight: 1.55 }}>
            Helios will publish the portable trust summary after enrichment, graph sync, and official corroboration checks return enough signal.
          </div>
        </div>
      </ExpandableSection>
    );
  }

  return (
    <ExpandableSection
      title="Supplier Passport"
      badge={
        <span
          className="rounded-full"
          style={{
            padding: PAD.tight,
            fontSize: FS.xs,
            fontWeight: 700,
            color: supplierPassportTone.color,
            background: supplierPassportTone.background,
            border: `1px solid ${supplierPassportTone.border}`,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {formatPassportPosture(supplierPassport.posture)}
        </span>
      }
      defaultOpen={true}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: SP.md }}>
        <div
          className="flex items-start justify-between gap-3 flex-wrap"
          style={{
            borderRadius: SP.lg,
            border: `1px solid ${T.border}`,
            background: T.surface,
            padding: PAD.comfortable,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: SP.xs }}>
            <SectionEyebrow>Portable trust artifact</SectionEyebrow>
            <div style={{ fontSize: FS.base, fontWeight: 700, color: T.text }}>
              Identity, control path, and corroboration summary for {supplierPassport.vendor.name}
            </div>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.55 }}>
              Use the passport to decide whether the supplier story is corroborated enough to trust, challenge, or keep collecting.
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill tone="neutral">{supplierPassport.vendor.profile || "Unknown profile"}</StatusPill>
            <StatusPill tone="neutral">{supplierPassport.identity.connectors_with_data} connectors with data</StatusPill>
            <button
              onClick={() => downloadSupplierPassportJson(supplierPassport)}
              className="helios-focus-ring"
              aria-label="Download supplier passport as JSON"
              style={{
                padding: PAD.default,
                fontSize: FS.sm,
                fontWeight: 700,
                color: T.accent,
                background: T.accentSoft,
                border: `1px solid ${T.border}`,
                borderRadius: 999,
                cursor: "pointer",
              }}
            >
              Download JSON
            </button>
          </div>
        </div>

        {supplierPassportOfficialCorroboration ? (
          <InlineMessage
            tone="info"
            title="Official corroboration"
            message={
              <>
                {supplierPassportOfficialCorroboration.coverage_label || "Coverage available"}
                <span style={{ display: "block", marginTop: SP.xs, color: supplierPassportOfficialTone.color }}>
                  {`${supplierPassportOfficialCorroboration.core_official_identifier_count ?? 0} core identifiers verified`}
                  {` · ${supplierPassportOfficialCorroboration.relevant_official_connectors_with_data ?? supplierPassportOfficialCorroboration.official_connectors_with_data ?? 0}/${supplierPassportOfficialCorroboration.relevant_official_connector_count ?? supplierPassportOfficialCorroboration.official_connector_count ?? 0} relevant official connectors returned data`}
                </span>
              </>
            }
          />
        ) : null}

        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {passportMetrics.map((item) => (
            <div
              key={item.label}
              style={{
                borderRadius: SP.lg,
                border: `1px solid ${T.border}`,
                background: T.raised,
                padding: PAD.default,
              }}
            >
              <div style={{ fontSize: FS.xs, color: T.textTertiary, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>
                {item.label}
              </div>
              <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, marginTop: SP.xs }}>
                {item.value}
              </div>
              <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: SP.xs, lineHeight: 1.5 }}>
                {item.detail}
              </div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {[
            {
              title: "Identity and ownership",
              rows: passportSignals.slice(0, 3),
            },
            {
              title: "Graph and monitoring",
              rows: passportSignals.slice(3),
            },
          ].map((section) => (
            <div
              key={section.title}
              style={{
                borderRadius: SP.lg,
                border: `1px solid ${T.border}`,
                background: T.surface,
                padding: PAD.comfortable,
              }}
            >
              <SectionEyebrow>{section.title}</SectionEyebrow>
              <div style={{ display: "flex", flexDirection: "column", gap: SP.sm, marginTop: SP.sm }}>
                {section.rows.map((row) => (
                  <div
                    key={row.label}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0, 0.95fr) minmax(0, 1.05fr)",
                      gap: SP.sm,
                      paddingTop: SP.sm,
                      borderTop: `1px solid ${T.border}`,
                    }}
                  >
                    <div style={{ fontSize: FS.sm, color: T.textSecondary }}>{row.label}</div>
                    <div>
                      <div style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{row.value}</div>
                      <div style={{ fontSize: FS.sm, color: T.textSecondary, lineHeight: 1.5, marginTop: SP.xs }}>
                        {row.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </ExpandableSection>
  );
};
