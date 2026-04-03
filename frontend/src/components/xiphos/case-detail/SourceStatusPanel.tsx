import React from "react";
import { T, FS, SP, PAD } from "@/lib/tokens";
import type { ConnectorStatus, EnrichmentReport } from "@/lib/api";

interface SourceStatusPanelProps {
  sourceStatusRef: React.RefObject<HTMLDivElement | null>;
  enrichment: EnrichmentReport | null;
  showStream: boolean;
}

export const SourceStatusPanel: React.FC<SourceStatusPanelProps> = ({
  sourceStatusRef,
  enrichment,
  showStream,
}) => {
  if (!enrichment || showStream) return null;

  const connectorStatus = enrichment.connector_status || {};

  return (
    <div
      ref={sourceStatusRef}
      className="rounded-lg"
      style={{
        background: T.surface,
        border: `1px solid ${T.border}`,
        padding: PAD.default,
      }}
    >
      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginBottom: SP.md }}>
        Source Status
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: SP.sm }}>
        {Object.entries(connectorStatus).map(([connector, status]: [string, ConnectorStatus]) => {
          const statusColor = status.error ? T.red : status.has_data ? T.green : T.muted;
          return (
            <div key={connector} style={{ padding: PAD.default, borderRadius: SP.sm, background: T.raised, border: `1px solid ${T.border}` }}>
              <div className="flex items-center justify-between">
                <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                  {String(connector).replaceAll("_", " ")}
                </span>
                <span
                  style={{
                    display: "inline-block",
                    padding: PAD.tight,
                    borderRadius: 999,
                    background: `${statusColor}18`,
                    border: `1px solid ${statusColor}44`,
                    color: statusColor,
                    fontSize: FS.xs,
                    fontWeight: 700,
                  }}
                >
                  {status.error ? "failed" : status.has_data ? "signal returned" : "checked clear"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
