import sys
sys.path.insert(0, "/app/backend")

from scoring import VendorInput, OwnershipProfile, DataQuality, ExecProfile, score_vendor
from profiles import get_profile

PROFILES = [
    "defense_acquisition",
    "itar_trade_compliance",
    "university_research_security",
    "grants_compliance",
    "commercial_supply_chain",
]
SHORT = {
    "defense_acquisition": "DEF",
    "itar_trade_compliance": "ITAR",
    "university_research_security": "UNIV",
    "grants_compliance": "GRANT",
    "commercial_supply_chain": "SUPPLY",
}

ENTITIES = [
    ("Rosoboronexport", "RU"),
    ("Huawei Technologies", "CN"),
    ("BAE Systems", "GB"),
    ("Lockheed Martin", "US"),
    ("Turkish Aerospace Industries", "TR"),
    ("Samsung Electronics", "KR"),
    ("Tsinghua University", "CN"),
    ("Iran Electronics Industries", "IR"),
    ("Airbus Defence and Space", "DE"),
    ("Kaspersky Lab", "RU"),
]

results = {}

for name, country in ENTITIES:
    results[name] = {}
    for profile_id in PROFILES:
        try:
            profile = get_profile(profile_id)
            program = profile.program_types[0]["id"] if profile.program_types else "standard_industrial"

            inp = VendorInput(
                name=name,
                country=country,
                ownership=OwnershipProfile(
                    publicly_traded=False,
                    state_owned=False,
                    beneficial_owner_known=True,
                    ownership_pct_resolved=0.85,
                    shell_layers=0,
                    pep_connection=False,
                ),
                data_quality=DataQuality(
                    has_lei=True,
                    has_cage=False,
                    has_duns=True,
                    has_tax_id=True,
                    has_audited_financials=True,
                    years_of_records=10,
                ),
                exec_profile=ExecProfile(
                    known_execs=5,
                    adverse_media=0,
                    pep_execs=0,
                    litigation_history=0,
                ),
                program=program,
            )

            result = score_vendor(inp, profile_id=profile_id)

            results[name][profile_id] = {
                "tier": result.calibrated_tier,
                "prob": result.calibrated_probability,
                "hs": len(result.hard_stop_decisions),
                "sf": len(result.soft_flags),
                "comp": result.composite_score,
            }
        except Exception as e:
            results[name][profile_id] = {
                "tier": "ERR",
                "prob": 0,
                "hs": 0,
                "sf": 0,
                "comp": 0,
                "error": str(e)[:80],
            }

sys.stdout.write("=" * 120 + "\n")
sys.stdout.write("XIPHOS v4.2 CROSS-PROFILE SCORING MATRIX\n")
sys.stdout.write("=" * 120 + "\n")
hdr = "{:30s}".format("Entity")
for p in PROFILES:
    hdr += " | {:>10s}".format(SHORT[p])
sys.stdout.write(hdr + "\n")
sys.stdout.write("-" * 120 + "\n")

for name, country in ENTITIES:
    row = "{:30s}".format(name)
    for p in PROFILES:
        r = results[name].get(p, {"tier": "--", "prob": 0, "hs": 0})
        tier = r["tier"]
        prob = r["prob"]
        hs = r.get("hs", 0)
        if hs > 0 or tier == "hard_stop":
            cell = "STOP {:.1%}".format(prob)
        elif tier == "elevated":
            cell = "ELEV {:.1%}".format(prob)
        elif tier == "monitor":
            cell = "MON  {:.1%}".format(prob)
        elif tier == "clear":
            cell = "CLR  {:.1%}".format(prob)
        elif tier == "ERR":
            cell = "ERR"
        else:
            cell = "{} {:.1%}".format(tier[:4], prob)
        row += " | {:>10s}".format(cell)
    sys.stdout.write(row + "\n")

sys.stdout.write("\n")
sys.stdout.write("=" * 80 + "\n")
sys.stdout.write("DIFFERENTIATION ANALYSIS\n")
sys.stdout.write("=" * 80 + "\n")
for name, country in ENTITIES:
    probs = [results[name].get(p, {"prob": 0})["prob"] for p in PROFILES]
    tiers = [results[name].get(p, {"tier": "?"})["tier"] for p in PROFILES]
    unique_tiers = len(set(tiers))
    spread = max(probs) - min(probs) if probs else 0
    min_p = min(probs) if probs else 0
    max_p = max(probs) if probs else 0
    sys.stdout.write("  {:30s}  {} tier(s) | {:.2%} -- {:.2%} (spread: {:.2%})\n".format(
        name, unique_tiers, min_p, max_p, spread))

has_errors = False
for name in results:
    for p in PROFILES:
        r = results[name].get(p, {})
        if "error" in r:
            if not has_errors:
                sys.stdout.write("\nERRORS:\n")
                has_errors = True
            sys.stdout.write("  {} / {}: {}\n".format(name, SHORT[p], r["error"]))

sys.stdout.flush()
