import React from "react";
import { ExpandableSection } from "../case-detail-sections";
import { T, FS, PAD, SP } from "@/lib/tokens";
import type { SupplierPassport as SupplierPassportRecord } from "@/lib/api";
import type { ToneConfig } from "./case-detail-types";

interface SupplierPassportProps {
  supplierPassport: SupplierPassportRecord | null;
  supplierPassportTone: ToneConfig;
  supplierPassportOfficialCorroboration: SupplierPassportRecord["identity"]["official_corroboration"] | null;
  supplierPassportOfficialTone: ToneConfig;
  downloadSupplierPassportJson: (passport: SupplierPassportRecord) => void;
  formatPassportPosture: (posture: string) => string;
}

export const SupplierPassport: React.FC<SupplierPassportProps> = ({
  supplierPassport,
  supplierPassportTone,
  supplierPassportOfficialCorroboration,
  supplierPassportOfficialTone,
  downloadSupplierPassportJson,
  formatPassportPosture,
}) => {
  if (!supplierPassport) return null;

  return (
    <ExpandableSection title="Supplier Passport" defaultOpen={true}>
      <div className="rounded-lg p-4 glass-card">
        <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
          <div>
            <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: 2, lineHeight: 1.55 }}>
              Portable trust artifact for control-path, identity, and connector coverage.
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => downloadSupplierPassportJson(supplierPassport)}
              className="rounded border cursor-pointer"
              aria-label="Download supplier passport as JSON"
              style={{
                padding: PAD.tight,
                fontSize: FS.sm,
                fontWeight: 700,
                color: T.accent,
                background: `${T.accent}12`,
                borderColor: `${T.accent}33`,
              }}
            >
              Download JSON
            </button>
            <span
              className="rounded-full"
              style={{
                padding: PAD.tight,
                fontSize: FS.sm,
                fontWeight: 700,
                color: supplierPassportTone.color,
                background: supplierPassportTone.background,
                border: `1px solid ${supplierPassportTone.border}`,
              }}
            >
              {formatPassportPosture(supplierPassport.posture)}
            </span>
          </div>
        </div>

        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", marginBottom: SP.md }}>
          {[
            { label: "Connectors with data", value: supplierPassport.identity.connectors_with_data, tone: T.accent },
            { label: "Findings", value: supplierPassport.identity.findings_total, tone: T.text },
            { label: "Control paths", value: supplierPassport.graph.control_paths.length, tone: T.amber },
            { label: "Artifacts", value: supplierPassport.artifacts.count, tone: T.green },
            {
              label: "Contradicted claims",
              value: supplierPassport.graph.claim_health.contradicted_claims,
              tone: supplierPassport.graph.claim_health.contradicted_claims > 0 ? T.red : T.green,
            },
            { label: "Stale paths", value: supplierPassport.graph.claim_health.stale_paths, tone: supplierPassport.graph.claim_health.stale_paths > 0 ? T.amber : T.green },
          ].map((item) => (
            <div key={item.label} className="rounded-lg" style={{ padding: SP.md, background: T.raised, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: FS.xs, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {item.label}
              </div>
              <div style={{ fontSize: FS.lg, fontWeight: 700, color: item.tone, marginTop: SP.xs, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                {item.value}
              </div>
            </div>
          ))}
        </div>

        {supplierPassportOfficialCorroboration && (
          <div
            className="rounded-lg"
            style={{
              padding: 12,
              background: supplierPassportOfficialTone.background,
              border: `1px solid ${supplierPassportOfficialTone.border}`,
              marginBottom: SP.md,
            }}
          >
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.xs, color: T.muted }}>
                  Official Corroboration
                </div>
                <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: SP.sm - 2 }}>
                  {supplierPassportOfficialCorroboration.coverage_label || "No official corroboration captured"}
                </div>
                <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.sm - 2, lineHeight: 1.5 }}>
                  {`${supplierPassportOfficialCorroboration.core_official_identifier_count ?? 0} core official identifiers verified`}
                  {` · ${supplierPassportOfficialCorroboration.relevant_official_connectors_with_data ?? supplierPassportOfficialCorroboration.official_connectors_with_data ?? 0}/${supplierPassportOfficialCorroboration.relevant_official_connector_count ?? supplierPassportOfficialCorroboration.official_connector_count ?? 0} relevant official connectors returned data`}
                </div>
              </div>
              <span
                className="rounded-full"
                style={{
                  padding: PAD.tight,
                  fontSize: FS.xs,
                  fontWeight: 700,
                  color: supplierPassportOfficialTone.color,
                  background: `${supplierPassportOfficialTone.color}12`,
                  border: `1px solid ${supplierPassportOfficialTone.border}`,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                {String(supplierPassportOfficialCorroboration.coverage_level || "missing").replaceAll("_", " ")}
              </span>
            </div>
          </div>
        )}
      </div>
    </ExpandableSection>
  );
};
