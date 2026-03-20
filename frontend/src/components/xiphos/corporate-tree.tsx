/**
 * Corporate Family Tree Visualization
 *
 * Displays the ownership hierarchy from SAM.gov data:
 * Highest Owner -> Immediate Owner -> Entity -> (Subsidiaries if known)
 *
 * Click any node to resolve and assess that entity.
 */

import { Building2, ChevronDown, Globe, Shield, AlertTriangle } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import type { EntityCandidate } from "@/lib/api";

const GOLD = "#C4A052";

const ALLIED = new Set(["US","GB","CA","AU","NZ","DE","FR","NL","NO","DK","SE","FI","IT","ES","PL","CZ","JP","KR","IL","SG","TW"]);

interface TreeNode {
  name: string;
  role: "highest_owner" | "immediate_owner" | "entity" | "subsidiary";
  country?: string;
  cage?: string;
  uei?: string;
  isForeign?: boolean;
  isAllied?: boolean;
}

interface CorporateTreeProps {
  entity: EntityCandidate;
  onSelectEntity?: (name: string) => void;
}

export function CorporateTree({ entity, onSelectEntity }: CorporateTreeProps) {
  const nodes: TreeNode[] = [];
  const entityCountry = entity.country?.toUpperCase() || "US";

  // Build tree from top down
  if (entity.highest_owner && entity.highest_owner !== entity.legal_name) {
    const hCountry = entity.highest_owner_country?.toUpperCase() || "";
    nodes.push({
      name: entity.highest_owner,
      role: "highest_owner",
      country: hCountry,
      isForeign: hCountry ? hCountry !== entityCountry : false,
      isAllied: hCountry ? ALLIED.has(hCountry) : true,
    });
  }

  if (entity.immediate_owner && entity.immediate_owner !== entity.legal_name
      && entity.immediate_owner !== entity.highest_owner) {
    const iCountry = entity.immediate_owner_country?.toUpperCase() || "";
    nodes.push({
      name: entity.immediate_owner,
      role: "immediate_owner",
      country: iCountry,
      isForeign: iCountry ? iCountry !== entityCountry : false,
      isAllied: iCountry ? ALLIED.has(iCountry) : true,
    });
  }

  // The entity itself
  nodes.push({
    name: entity.legal_name,
    role: "entity",
    country: entityCountry,
    cage: entity.cage,
    uei: entity.uei,
    isForeign: false,
    isAllied: true,
  });

  if (nodes.length <= 1) return null; // No ownership chain to show

  const roleLabels: Record<string, string> = {
    highest_owner: "ULTIMATE PARENT",
    immediate_owner: "IMMEDIATE PARENT",
    entity: "SUBJECT ENTITY",
    subsidiary: "SUBSIDIARY",
  };

  const roleColors: Record<string, string> = {
    highest_owner: T.amber,
    immediate_owner: T.dim,
    entity: GOLD,
    subsidiary: T.muted,
  };

  return (
    <div style={{ padding: "16px", borderRadius: 10, background: T.bg, border: `1px solid ${T.border}` }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, letterSpacing: "0.1em", marginBottom: 14 }}>
        CORPORATE OWNERSHIP CHAIN
      </div>

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
        {nodes.map((node, i) => (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%" }}>
            {/* Connector line */}
            {i > 0 && (
              <div style={{ width: 2, height: 20, background: `${T.border}`, margin: "0 auto" }}>
                <ChevronDown size={14} color={T.muted} style={{ position: "relative", left: -6, top: 4 }} />
              </div>
            )}

            {/* Node card */}
            <button
              onClick={() => node.role !== "entity" && onSelectEntity?.(node.name)}
              style={{
                width: "100%",
                maxWidth: 380,
                padding: "12px 16px",
                borderRadius: 8,
                border: `1px solid ${node.role === "entity" ? GOLD + "40" : T.border}`,
                background: node.role === "entity" ? `${GOLD}08` : T.surface,
                cursor: node.role !== "entity" ? "pointer" : "default",
                textAlign: "left",
                transition: "all 0.2s",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
              onMouseEnter={e => { if (node.role !== "entity") e.currentTarget.style.borderColor = GOLD + "40"; }}
              onMouseLeave={e => { if (node.role !== "entity") e.currentTarget.style.borderColor = T.border; }}
            >
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: `${roleColors[node.role]}10`,
                border: `1px solid ${roleColors[node.role]}20`,
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>
                {node.isForeign && !node.isAllied ? (
                  <AlertTriangle size={16} color={T.red} />
                ) : node.isForeign ? (
                  <Globe size={16} color={T.amber} />
                ) : (
                  <Building2 size={16} color={roleColors[node.role]} />
                )}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: roleColors[node.role], letterSpacing: "0.06em", marginBottom: 2 }}>
                  {roleLabels[node.role]}
                </div>
                <div style={{ fontSize: FS.sm, fontWeight: 600, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {node.name}
                </div>
                <div style={{ fontSize: 11, color: T.muted, marginTop: 2, display: "flex", gap: 8 }}>
                  {node.country && <span>{node.country}</span>}
                  {node.cage && <span>CAGE: {node.cage}</span>}
                  {node.uei && <span>UEI: {node.uei}</span>}
                  {node.isForeign && (
                    <span style={{ color: node.isAllied ? T.amber : T.red, fontWeight: 600 }}>
                      {node.isAllied ? "FOREIGN (ALLIED)" : "FOREIGN (NON-ALLIED)"}
                    </span>
                  )}
                </div>
              </div>

              {node.role === "entity" && (
                <Shield size={16} color={GOLD} style={{ flexShrink: 0 }} />
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
