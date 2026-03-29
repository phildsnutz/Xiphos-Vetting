import { T, parseTier, tierBand } from "@/lib/tokens";
import type { VettingCase } from "@/lib/types";

export type PortfolioDisposition = "blocked" | "review" | "qualified" | "clear";
export type WorkflowLane = "counterparty" | "cyber" | "export";

export const WORKFLOW_LANE_META: Record<WorkflowLane, {
  label: string;
  shortLabel: string;
  description: string;
  accent: string;
  softBackground: string;
  softBorder: string;
}> = {
  counterparty: {
    label: "Defense counterparty trust",
    shortLabel: "Counterparty",
    description: "FOCI, ownership, and pre-award supplier adjudication",
    accent: T.gold,
    softBackground: T.goldSoft,
    softBorder: `${T.gold}33`,
  },
  cyber: {
    label: "Supply chain assurance",
    shortLabel: "Cyber",
    description: "Supplier, software, and dependency assurance with cyber evidence",
    accent: T.teal,
    softBackground: T.tealSoft,
    softBorder: `${T.teal}33`,
  },
  export: {
    label: "Export authorization",
    shortLabel: "Export",
    description: "Item, data, and foreign-person authorization review",
    accent: T.accent,
    softBackground: T.accentSoft,
    softBorder: `${T.accent}33`,
  },
};

export function portfolioDisposition(c: VettingCase): PortfolioDisposition {
  if (!c.cal?.tier) {
    return "clear";
  }

  const tier = parseTier(c.cal.tier);
  if (c.cal?.stops && c.cal.stops.length > 0) {
    return "blocked";
  }

  const band = tierBand(tier);

  // All TIER_1 (critical band) = blocked, not review
  if (band === "critical") {
    return "blocked";
  }
  if (tier === "TIER_4_CRITICAL_QUALIFIED") {
    return "qualified";
  }
  if (band === "elevated" || band === "conditional") {
    return "review";
  }

  return "clear";
}

function laneSignalText(c: VettingCase): string {
  const parts = [
    c.profile,
    c.program,
    c.cal?.recommendation,
    c.cal?.regulatoryStatus,
    c.cal?.sensitivityContext,
    ...(c.cal?.flags?.map((flag) => `${flag.t} ${flag.x}`) ?? []),
    ...(c.cal?.stops?.map((stop) => `${stop.t} ${stop.x}`) ?? []),
    ...(c.cal?.finds ?? []),
    ...((c.cal?.regulatoryFindings ?? []).map((finding) => JSON.stringify(finding))),
  ];
  return parts.filter(Boolean).join(" ").toLowerCase();
}

export function workflowLaneForCase(c: VettingCase): WorkflowLane {
  if (c.workflowLane) {
    return c.workflowLane;
  }

  const profile = String(c.profile || "").toLowerCase();
  const program = String(c.program || "").toLowerCase();
  const text = laneSignalText(c);

  if (
    profile.includes("cyber")
    || profile.includes("cmmc")
    || text.includes("cmmc")
    || text.includes("sprs")
    || text.includes("oscal")
    || text.includes("poa&m")
    || text.includes("poam")
    || text.includes("nvd")
    || text.includes("cve")
    || text.includes("kev")
    || text.includes("800-171")
    || text.includes("cyber")
  ) {
    return "cyber";
  }

  if (
    profile.includes("itar")
    || profile.includes("trade_compliance")
    || program.startsWith("cat_")
    || program.includes("dual_use")
    || program.includes("itar")
    || program.includes("ear")
    || text.includes("itar")
    || text.includes("ear")
    || text.includes("usml")
    || text.includes("eccn")
    || text.includes("deemed export")
    || text.includes("foreign-person access")
    || text.includes("technical data")
    || text.includes("license exception")
    || text.includes("license required")
    || text.includes("export authorization")
    || text.includes("commodity jurisdiction")
    || text.includes("classification memo")
  ) {
    return "export";
  }

  return "counterparty";
}
