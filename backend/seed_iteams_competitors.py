"""
ITEAMS Competitors Seed Script

Creates entity records for 4 key ITEAMS competitors:
  1. Amentum Holdings, Inc. (ITEAMS incumbent, Jacobs merger, PMRF JV)
  2. ManTech International Corporation (Carlyle-owned, SOUTHCOM IT, SDVOSB)
  3. SMX (LEIA contract, zero-trust INDOPACOM network, OceanSound PE)
  4. HII Mission Technologies (C5ISR, wargaming, network assessment)

Run:
    python seed_iteams_competitors.py          # Creates the entities
    python seed_iteams_competitors.py --clean  # Removes seeded data
"""

import json
import sys
import logging
from datetime import datetime

# Import from db.py in the same directory
import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')

# ---------------------------------------------------------------------------
# ITEAMS Competitor Definitions
# ---------------------------------------------------------------------------

SEED_PROGRAM = "iteams_competitive_intelligence"
SEED_PREFIX = "iteams-competitor-"
SEED_TAG = "iteams_competitive_intelligence"

COMPETITORS = [
    {
        "id": f"{SEED_PREFIX}amentum",
        "name": "Amentum Holdings, Inc.",
        "country": "US",
        "profile": "defense_acquisition",
        "data": {
            "website": "amentum.com",
            "revenue": "$14.4B",
            "employees": 53000,
            "industry": "Defense & Government Services",
            "headquarters": "Arlington, VA",
            "key_facts": [
                "ITEAMS incumbent vendor",
                "Merged with Jacobs Engineering Sept 2024",
                "$47.1B backlog (post-merger)",
                "1,000+ personnel stationed in Hawaii",
                "Center for Contested Logistics division",
                "PMRF Joint Venture with Kupono ($854M contract)",
                "DoD top-10 prime contractor",
            ],
            "iteams_position": "Incumbent prime. Strong position in logistics/supply chain, "
                              "personnel surge into INDOPACOM AOR",
            "competitive_notes": "Post-Jacobs integration ongoing. Controls significant "
                                "Hawaii footprint. Kupono partnership extends into civil "
                                "infrastructure and strategic sustainment.",
            "sources": ["DoD press releases", "SEC 8-K filings", "Defense News", "OSINT tracking"],
            "seed_timestamp": datetime.utcnow().isoformat(),
            "entity_type": "competitor",
            "program_type": SEED_PROGRAM,
        }
    },
    {
        "id": f"{SEED_PREFIX}mantech",
        "name": "ManTech International Corporation",
        "country": "US",
        "profile": "defense_acquisition",
        "data": {
            "website": "mantech.com",
            "revenue": "$2.2B",
            "employees": 7800,
            "industry": "Defense & Government Services",
            "headquarters": "Arlington, VA",
            "ownership": "Carlyle Group acquisition, Oct 2022 ($4.2B)",
            "key_facts": [
                "PE-backed (Carlyle Group)",
                "Kumaumau Center established in Hawaii, Oct 2024",
                "Col. Sattely as Executive Director of Contested Logistics",
                "$910M SOUTHCOM IT contract",
                "SDVOSB certification via ManTech Hawaii subsidiary",
                "ACRE cyber range operator",
                "Aggressive Hawaii expansion strategy",
            ],
            "iteams_position": "Competitive prime pursuing ITEAMS. Hawaii teaming strategy, "
                              "SOUTHCOM relationship, SDVOSB angle creates differentiation",
            "competitive_notes": "Recent PE buyout provides capital for aggressive expansion. "
                                "Hawaii presence and SOUTHCOM relationship create ITEAMS "
                                "advantage. SDVOSB positioning for small business set-asides.",
            "sources": ["ManTech press releases", "TRANSCOM announcements", "OSINT Hawaii contractors"],
            "seed_timestamp": datetime.utcnow().isoformat(),
            "entity_type": "competitor",
            "program_type": SEED_PROGRAM,
        }
    },
    {
        "id": f"{SEED_PREFIX}smx",
        "name": "SMX",
        "country": "US",
        "profile": "defense_acquisition",
        "data": {
            "website": "smxtech.com",
            "revenue_estimate": "$500M-$1B (private)",
            "employees_estimate": "3000-5000",
            "industry": "Defense IT & Network Services",
            "headquarters": "Arlington, VA",
            "ownership": "OceanSound Partners (private equity backing)",
            "key_facts": [
                "LEIA contract $3.2B awarded Oct 2024",
                "LEIA sourced via ASTRO IDIQ (multi-award)",
                "Zero-trust INDOPACOM network modernization",
                "Recently acquired cBEYONData (2025)",
                "OceanSound Partners PE-backed",
                "Potential teaming partner with Amentum (unconfirmed OSINT)",
                "Network assessment capability gap analysis platform",
            ],
            "iteams_position": "Emerging competitor. LEIA contract puts them in INDOPACOM "
                              "modernization space. ASTRO IDIQ position enables fast-track "
                              "teaming with larger primes.",
            "competitive_notes": "Private company with strong PE backing. LEIA win signals "
                                "DoD confidence in network modernization approach. cBEYONData "
                                "acquisition adds data analytics layer. Potential to serve as "
                                "technology prime or subcontractor.",
            "sources": ["SAM.gov LEIA award", "ASTRO IDIQ announcements", "LinkedIn OSINT"],
            "seed_timestamp": datetime.utcnow().isoformat(),
            "entity_type": "competitor",
            "program_type": SEED_PROGRAM,
        }
    },
    {
        "id": f"{SEED_PREFIX}hii-mission-tech",
        "name": "HII Mission Technologies",
        "country": "US",
        "profile": "defense_acquisition",
        "data": {
            "website": "hii.com",
            "parent_company": "Huntington Ingalls Industries",
            "parent_revenue": "$9B+",
            "division_revenue": "$3.0B (Mission Technologies division estimate)",
            "employees_estimate": "8000 (Mission Technologies)",
            "industry": "Defense C5ISR & Mission Solutions",
            "headquarters": "San Diego, CA",
            "key_facts": [
                "C5ISR mission solutions focus",
                "Live, Virtual, Constructive (LVC) integration",
                "Joint experimentation and wargaming capability",
                "Several hundred analysts/engineers in Hawaii",
                "$65M DoD IAC research contract",
                "$197M JTSE (Joint Training and Simulation Environment) recompete",
                "$151B MDA SHIELD IDIQ framework",
                "Network assessment evaluation: 'far behind' on ITEAMS readiness (per OSINT)",
            ],
            "iteams_position": "Incumbent contractor, but assessed as strategically weak on ITEAMS. "
                              "C5ISR strength in simulation/wargaming, but network modernization "
                              "positioning lags ManTech and SMX.",
            "competitive_notes": "Large division with strong government relationships but appears "
                                "behind curve on ITEAMS modernization strategy. Wargaming and "
                                "LVC capability may be leveraged in ITEAMS teaming. Hawaii presence "
                                "significant but needs ITEAMS-specific reposition.",
            "sources": ["HII corporate announcements", "DoD contract database", "GAO bid protest tracking"],
            "seed_timestamp": datetime.utcnow().isoformat(),
            "entity_type": "competitor",
            "program_type": SEED_PROGRAM,
        }
    },
]


def seed_competitors():
    """Create ITEAMS competitor entities in database."""
    created = []
    updated = []

    for competitor in COMPETITORS:
        vendor_id = competitor["id"]
        
        # Check if vendor already exists
        existing = db.get_vendor(vendor_id)
        
        if existing:
            logger.info(f"  [UPDATE] {competitor['name']} (vendor_id={vendor_id})")
            updated.append(competitor['name'])
        else:
            logger.info(f"  [CREATE] {competitor['name']} (vendor_id={vendor_id})")
            created.append(competitor['name'])

        # Upsert vendor (idempotent)
        db.upsert_vendor(
            vendor_id=vendor_id,
            name=competitor["name"],
            country=competitor["country"],
            program=SEED_PROGRAM,
            profile=competitor["profile"],
            vendor_input=competitor["data"],
        )

    return created, updated


def clean_competitors():
    """Remove seeded competitor entities from database."""
    removed = []
    
    for competitor in COMPETITORS:
        vendor_id = competitor["id"]
        existing = db.get_vendor(vendor_id)
        
        if existing:
            logger.info(f"  [DELETE] {competitor['name']} (vendor_id={vendor_id})")
            removed.append(competitor['name'])
            
            # Delete vendor and cascade to scoring_results, alerts, enrichment_reports, monitoring_log, decisions
            with db.get_conn() as conn:
                conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
        else:
            logger.info(f"  [SKIP] {competitor['name']} not found")

    return removed


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        logger.info("Cleaning ITEAMS competitor entities...")
        removed = clean_competitors()
        if removed:
            logger.info(f"\nRemoved {len(removed)} entities:")
            for name in removed:
                logger.info(f"  - {name}")
        else:
            logger.info("No entities to remove")
        return 0

    logger.info("Seeding ITEAMS competitor entities...")
    created, updated = seed_competitors()

    logger.info(f"\nResults:")
    if created:
        logger.info(f"  Created {len(created)} entities:")
        for name in created:
            logger.info(f"    - {name}")
    else:
        logger.info(f"  Created 0 entities")

    if updated:
        logger.info(f"  Updated {len(updated)} entities:")
        for name in updated:
            logger.info(f"    - {name}")
    else:
        logger.info(f"  Updated 0 entities")

    logger.info(f"\nTotal: {len(created)} created, {len(updated)} updated")
    logger.info(f"\nEntities marked with program: {SEED_PROGRAM}")
    logger.info(f"Entity IDs use prefix: {SEED_PREFIX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
