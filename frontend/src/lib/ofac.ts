/**
 * Embedded OFAC SDN / Entity List / CAATSA sanctions data.
 * In production this would pull from treasury.gov XML feeds.
 * For the demo we embed real sanctioned entities so the matching is genuine.
 */

export interface SanctionEntry {
  name: string;
  aliases: string[];
  program: string; // OFAC program (e.g., "UKRAINE-EO13661", "IRAN", "SDGT")
  list: "SDN" | "ENTITY" | "CAATSA" | "SSI" | "FSE";
  country: string;
  type: "entity" | "individual";
  id: string; // OFAC UID
}

export const SANCTIONS_DB: SanctionEntry[] = [
  {
    name: "ROSOBORONEXPORT",
    aliases: ["ROSOBORONEKSPORT", "ROSOBORON EXPORT", "FSUE ROSOBORONEXPORT"],
    program: "UKRAINE-EO13661",
    list: "SSI",
    country: "RU",
    type: "entity",
    id: "OFAC-18068",
  },
  {
    name: "ROSTEC",
    aliases: ["ROSTEC CORPORATION", "ROSTEKH", "STATE CORPORATION ROSTEC"],
    program: "UKRAINE-EO13661",
    list: "SDN",
    country: "RU",
    type: "entity",
    id: "OFAC-20939",
  },
  {
    name: "NORINCO",
    aliases: ["CHINA NORTH INDUSTRIES GROUP", "CHINA NORTH INDUSTRIES CORPORATION", "CNGC"],
    program: "CHINA-EO13959",
    list: "ENTITY",
    country: "CN",
    type: "entity",
    id: "OFAC-33102",
  },
  {
    name: "HUAWEI TECHNOLOGIES CO LTD",
    aliases: ["HUAWEI", "HUAWEI TECHNOLOGIES"],
    program: "CHINA-EO13959",
    list: "ENTITY",
    country: "CN",
    type: "entity",
    id: "OFAC-35012",
  },
  {
    name: "SHANGHAI MICRO ELECTRONICS EQUIPMENT",
    aliases: ["SMEE", "SHANGHAI MICRO", "SHANGHAI MICROELECTRONICS"],
    program: "CHINA-EO13959",
    list: "ENTITY",
    country: "CN",
    type: "entity",
    id: "OFAC-38901",
  },
  {
    name: "IRAN ELECTRONICS INDUSTRIES",
    aliases: ["IEI", "SAIRAN"],
    program: "IRAN",
    list: "SDN",
    country: "IR",
    type: "entity",
    id: "OFAC-9649",
  },
  {
    name: "KOREA MINING DEVELOPMENT TRADING CORPORATION",
    aliases: ["KOMID"],
    program: "NORTH-KOREA",
    list: "SDN",
    country: "KP",
    type: "entity",
    id: "OFAC-8985",
  },
  {
    name: "MAHAN AIR",
    aliases: ["MAHAN AIRLINES"],
    program: "IRAN",
    list: "SDN",
    country: "IR",
    type: "entity",
    id: "OFAC-13001",
  },
  {
    name: "OBRONPROM",
    aliases: ["UNITED INDUSTRIAL CORPORATION OBORONPROM", "OPK OBORONPROM"],
    program: "UKRAINE-EO13661",
    list: "SSI",
    country: "RU",
    type: "entity",
    id: "OFAC-18070",
  },
  {
    name: "WAGNER GROUP",
    aliases: ["PMC WAGNER", "VAGNER"],
    program: "RUSSIA-EO14024",
    list: "SDN",
    country: "RU",
    type: "entity",
    id: "OFAC-42215",
  },
];

/**
 * Jaro-Winkler similarity for fuzzy name matching.
 * Returns 0..1 where 1 = exact match.
 */
function jaroWinkler(s1: string, s2: string): number {
  const a = s1.toUpperCase().trim();
  const b = s2.toUpperCase().trim();
  if (a === b) return 1;
  if (!a.length || !b.length) return 0;

  const range = Math.max(0, Math.floor(Math.max(a.length, b.length) / 2) - 1);
  const aMatches = new Array(a.length).fill(false);
  const bMatches = new Array(b.length).fill(false);
  let matches = 0;
  let transpositions = 0;

  for (let i = 0; i < a.length; i++) {
    const lo = Math.max(0, i - range);
    const hi = Math.min(b.length - 1, i + range);
    for (let j = lo; j <= hi; j++) {
      if (bMatches[j] || a[i] !== b[j]) continue;
      aMatches[i] = true;
      bMatches[j] = true;
      matches++;
      break;
    }
  }

  if (matches === 0) return 0;

  let k = 0;
  for (let i = 0; i < a.length; i++) {
    if (!aMatches[i]) continue;
    while (!bMatches[k]) k++;
    if (a[i] !== b[k]) transpositions++;
    k++;
  }

  const jaro = (matches / a.length + matches / b.length + (matches - transpositions / 2) / matches) / 3;

  // Winkler prefix bonus
  let prefix = 0;
  for (let i = 0; i < Math.min(4, a.length, b.length); i++) {
    if (a[i] === b[i]) prefix++;
    else break;
  }

  return jaro + prefix * 0.1 * (1 - jaro);
}

export interface ScreeningResult {
  matched: boolean;
  bestScore: number;
  matchedEntry: SanctionEntry | null;
  matchedName: string;
  allMatches: Array<{ entry: SanctionEntry; score: number; matchedOn: string }>;
}

/**
 * Screen a vendor name against the sanctions database.
 * Returns best match score and all matches above threshold.
 */
export function screenName(vendorName: string, threshold = 0.82): ScreeningResult {
  const allMatches: Array<{ entry: SanctionEntry; score: number; matchedOn: string }> = [];
  let bestScore = 0;
  let bestEntry: SanctionEntry | null = null;
  let bestMatchedName = "";

  for (const entry of SANCTIONS_DB) {
    const names = [entry.name, ...entry.aliases];
    for (const name of names) {
      const score = jaroWinkler(vendorName, name);
      if (score >= threshold) {
        allMatches.push({ entry, score, matchedOn: name });
      }
      if (score > bestScore) {
        bestScore = score;
        bestEntry = entry;
        bestMatchedName = name;
      }
    }
  }

  // Sort by score descending
  allMatches.sort((a, b) => b.score - a.score);

  return {
    matched: allMatches.length > 0,
    bestScore,
    matchedEntry: allMatches.length > 0 ? allMatches[0].entry : bestEntry,
    matchedName: allMatches.length > 0 ? allMatches[0].matchedOn : bestMatchedName,
    allMatches,
  };
}
