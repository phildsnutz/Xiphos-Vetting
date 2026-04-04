import { T, parseTier, tierBand } from "@/lib/tokens";
import type { VettingCase } from "@/lib/types";

export type PortfolioDisposition = "blocked" | "review" | "qualified" | "clear";
export type WorkflowLane = "counterparty" | "cyber" | "export";
export type ProductPillar = "vendor_assessment" | "contract_vehicle";

export const PRODUCT_PILLAR_META: Record<ProductPillar, {
  label: string;
  shortLabel: string;
  description: string;
  accent: string;
  softBackground: string;
  softBorder: string;
}> = {
  vendor_assessment: {
    label: "Entity Intelligence",
    shortLabel: "Entity",
    description: "Work the full picture on a company, supplier, or target.",
    accent: T.gold,
    softBackground: T.goldSoft,
    softBorder: `${T.gold}33`,
  },
  contract_vehicle: {
    label: "Vehicle Intelligence",
    shortLabel: "Vehicle",
    description: "Start from the vehicle, map the ecosystem, and pull the right entities into the room.",
    accent: T.accent,
    softBackground: T.accentSoft,
    softBorder: `${T.accent}33`,
  },
};

export const WORKFLOW_LANE_META: Record<WorkflowLane, {
  label: string;
  shortLabel: string;
  description: string;
  accent: string;
  softBackground: string;
  softBorder: string;
}> = {
  counterparty: {
    label: "Ownership and control",
    shortLabel: "Control",
    description: "Core entity truth, ownership paths, FOCI, sanctions, and public-record evidence.",
    accent: T.gold,
    softBackground: T.goldSoft,
    softBorder: `${T.gold}33`,
  },
  cyber: {
    label: "Assurance signals",
    shortLabel: "Assurance",
    description: "Supplier assurance, cyber readiness, dependency, and software evidence when it changes the call.",
    accent: T.teal,
    softBackground: T.tealSoft,
    softBorder: `${T.teal}33`,
  },
  export: {
    label: "Access and transfer",
    shortLabel: "Access",
    description: "Access, transfer, foreign-person, and authorization evidence when it changes the call.",
    accent: T.accent,
    softBackground: T.accentSoft,
    softBorder: `${T.accent}33`,
  },
};

export function productPillarForCase(c: VettingCase): ProductPillar {
  void c;
  return "vendor_assessment";
}

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
