#!/usr/bin/env python3
"""
Seed the AXIOM watchlist with initial monitoring targets.

Targets based on Contract Vehicle Intelligence POC validation:
  1. SMX Technologies -- LEIA contract (ASTRO vehicle), Camp Smith, INDOPACOM
  2. Amentum -- ITEAMS contract (OASIS vehicle), Camp Smith, INDOPACOM

Known subcontractors from HUMINT and grey zone validation:
  - SMX/LEIA: The Unconventional, Kavaliro, Peraton, CACI, Firebird AST, Google Public Sector, WWT
  - Amentum/ITEAMS: SAIC (7+ positions), Leidos (NGEN/SMIT adjacent), KBR (SOCPAC)

Run from backend directory:
    cd backend && python ../scripts/seed_axiom_watchlist.py
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from axiom_monitor import add_to_watchlist, init_axiom_monitor_tables

    print("Initializing AXIOM monitor tables...")
    init_axiom_monitor_tables()

    targets = [
        {
            "prime_contractor": "SMX Technologies",
            "contract_name": "LEIA",
            "vehicle_name": "ASTRO",
            "installation": "Camp Smith",
            "website": "https://smxtech.com",
            "priority": "critical",
            "metadata": {
                "piid": "GS00Q17GWD2455",
                "value": "$3.2B ceiling",
                "cocom": "INDOPACOM",
                "known_subs": [
                    "The Unconventional",
                    "Kavaliro",
                    "Peraton",
                    "CACI",
                    "Firebird AST",
                    "Google Public Sector",
                    "World Wide Technology",
                ],
                "predecessor": "C3PO",
                "fedsim_managed": True,
                "notes": "SAM Subaward API returns 0 records. Grey zone primary source.",
            },
        },
        {
            "prime_contractor": "Amentum",
            "contract_name": "ITEAMS",
            "vehicle_name": "OASIS Unrestricted",
            "installation": "Camp Smith",
            "website": "https://amentum.com",
            "priority": "critical",
            "metadata": {
                "piid": "47QFCA-23-F-0046",
                "value": "$441.3M",
                "cocom": "INDOPACOM",
                "fte_count": 474,
                "known_subs": ["SAIC", "Leidos", "KBR"],
                "fedsim_managed": True,
                "notes": "474 FTE positions. SAIC has 7+ related job postings.",
            },
        },
        {
            "prime_contractor": "SMX Technologies",
            "contract_name": "C3PO",
            "vehicle_name": "ASTRO",
            "installation": "Camp Smith",
            "website": "https://smxtech.com",
            "priority": "low",
            "metadata": {
                "status": "expired",
                "cocom": "INDOPACOM",
                "known_subs": ["The Unconventional", "Kavaliro"],
                "successor": "LEIA",
                "notes": "Expired predecessor to LEIA. Monitor for residual data and teaming persistence.",
            },
        },
    ]

    for target in targets:
        entry = add_to_watchlist(**target)
        print(f"  Added: [{entry.priority}] {entry.prime_contractor} / {target['contract_name']} (id: {entry.id})")

    print(f"\nDone. {len(targets)} entries added to AXIOM watchlist.")
    print("Start monitoring daemon: python axiom_monitor.py daemon")
    print("Or trigger scan via API: POST /api/axiom/scan/<watchlist_id>")


if __name__ == "__main__":
    main()
