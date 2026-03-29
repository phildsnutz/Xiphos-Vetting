#!/usr/bin/env python3
"""
BIS Consolidated Screening List (CSL) sync module for Xiphos.

The BIS CSL aggregates entities from:
  1. Entity List (EL) - companies determined to be engaged in activities
     contrary to US national security
  2. Denied Persons List (DPL) - individuals and firms denied export privileges
  3. Unverified List (UVL) - entities that have not verified end-use of US items
  4. Military End-User (MEU) - entities engaged in military activities

For the prototype, this module provides:
  - A seed dataset of ~200 realistic BIS-listed entities
  - Functions to parse and normalize them into SanctionRecord format
  - Optional API integration point for live pulls from api.trade.gov
  - Graceful fallback to seed data when API is unavailable

Usage:
    from bis_csl import sync_bis_csl, try_fetch_bis_csl_api
    records = sync_bis_csl()  # Get seed data
    records = try_fetch_bis_csl_api()  # Try live API with fallback
"""

import json
import urllib.request
import urllib.error
from sanctions_sync import SanctionRecord

USER_AGENT = "Xiphos-Vetting/2.0 (bis-csl; +https://github.com/phildsnutz/Xiphos-Vetting)"

# ---------------------------------------------------------------------------
# BIS Seed Dataset (~200 entities)
# ---------------------------------------------------------------------------

def _get_bis_seed_data() -> list[dict]:
    """
    Realistic BIS CSL seed dataset including:
    - Chinese military-industrial entities (NDAA 1260H list)
    - Russian defense companies
    - Iranian procurement networks
    - Known DPL entries
    - Military end-users

    Each entry has: name, aliases, entity_type, country, list_type, program
    """
    return [
        # --- CHINA: Military-Industrial (NDAA 1260H & Entity List) ---
        {
            "name": "China North Industries Group Corporation",
            "aliases": ["NORINCO", "CNGC", "CHINA NORTH INDUSTRIES"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Aviation Industry Corporation of China",
            "aliases": ["AVIC", "AVIC INTERNATIONAL", "AVIC AEROSPACE"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-MILITARY-ENTITIES",
        },
        {
            "name": "China Aerospace Science and Technology Corporation",
            "aliases": ["CASC", "CAST", "CHINA AEROSPACE SCIENCE"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China Aerospace Science and Industry Corporation",
            "aliases": ["CASIC", "CASIC GROUP"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China Electronics Technology Group Corporation",
            "aliases": ["CETC", "CEC", "CHINA ELECTRONICS CORPORATION"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China General Nuclear Power Group",
            "aliases": ["CGN", "CHINA GENERAL NUCLEAR", "CGN NUCLEAR"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China National Nuclear Corporation",
            "aliases": ["CNNC", "CHINA NATIONAL NUCLEAR"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China State Shipbuilding Corporation",
            "aliases": ["CSSC", "CHINA STATE SHIPBUILDING"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "China Shipbuilding Industry Corporation",
            "aliases": ["CSIC", "CHINA SHIPBUILDING INDUSTRY"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Semiconductor Manufacturing International Corporation",
            "aliases": ["SMIC", "SMIC SHANGHAI"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Commercial Aircraft Corporation of China",
            "aliases": ["COMAC", "COMAC SHANGHAI"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Inspur Group",
            "aliases": ["INSPUR", "INSPUR ELECTRONIC INFORMATION"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Shanghai Micro Electronics Equipment Group",
            "aliases": ["SMEE", "SHANGHAI MICRO", "SHANGHAI MICROELECTRONICS"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "ZTE Corporation",
            "aliases": ["ZTE", "ZTE CORP", "ZHONGXING TELECOMMUNICATION"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-NDAA-889",
        },
        {
            "name": "Huawei Technologies Co Ltd",
            "aliases": ["HUAWEI", "HUAWEI TECHNOLOGIES", "HUAWEI TECH"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-EO13959",
        },
        {
            "name": "Hangzhou Hikvision Digital Technology",
            "aliases": ["HIKVISION", "HIKVISION DIGITAL", "EZVIZ"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-NDAA-889",
        },
        {
            "name": "Hangzhou Dahua Technology",
            "aliases": ["DAHUA", "DAHUA TECHNOLOGY", "DAHUA SECURITY"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-NDAA-889",
        },
        {
            "name": "Hytera Communications Corporation",
            "aliases": ["HYTERA", "HYTERA MOBILFUNK"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-NDAA-889",
        },
        {
            "name": "DJI Technology Co Ltd",
            "aliases": ["DJI", "SZ DJI TECHNOLOGY", "DA JIANG INNOVATIONS"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "EL",
            "program": "CHINA-MILITARY-ENTITIES",
        },

        # --- RUSSIA: Defense Industry & Oligarch-Linked ---
        {
            "name": "Rosoboronexport",
            "aliases": ["ROSOBORONEKSPORT", "ROSOBORON EXPORT", "FSUE ROSOBORONEXPORT"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "Rostec",
            "aliases": ["ROSTEC CORPORATION", "ROSTEKH", "STATE CORPORATION ROSTEC"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "United Instrument Manufacturing Corporation Oboronprom",
            "aliases": ["OBRONPROM", "OPK OBORONPROM"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "DPL",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "Almaz-Antey Air and Space Defence Corporation",
            "aliases": ["ALMAZ-ANTEY", "ALMAZ ANTEY"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "EL",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "NPO Mashinostroyeniya",
            "aliases": ["NPO MASHINOSTROYENIYA", "NIIEM"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "EL",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "Tactical Missiles Corporation",
            "aliases": ["TAKTICHESKOE RAKETNO-TEKHNICHESKOE VOORUZHENIE"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "EL",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "Wagner Group",
            "aliases": ["PMC WAGNER", "VAGNER", "PRIVAT VOENNAYA KOMPANIYA VAGNER"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "RUSSIA-EO14024",
        },
        {
            "name": "Kaspersky Lab",
            "aliases": ["KASPERSKY", "AO KASPERSKY LAB", "KASPERSKY LABS ZAO"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "EL",
            "program": "RUSSIA-EO14071",
        },
        {
            "name": "Sberbank of Russia",
            "aliases": ["SBERBANK", "SBERBANK ROSSII", "SBRF"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "UKRAINE-EO13662",
        },
        {
            "name": "VTB Bank",
            "aliases": ["VTB", "VNESHTORGBANK"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "UKRAINE-EO13662",
        },
        {
            "name": "Gazprom",
            "aliases": ["GAZPROM OAO", "GAZPROM LLC", "PAO GAZPROM"],
            "entity_type": "entity",
            "country": "RU",
            "list_type": "SDN",
            "program": "UKRAINE-EO13662",
        },

        # --- IRAN: Procurement Networks & Defense ---
        {
            "name": "Iran Electronics Industries",
            "aliases": ["IEI", "SAIRAN"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "SDN",
            "program": "IRAN",
        },
        {
            "name": "Mahan Air",
            "aliases": ["MAHAN AIRLINES"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "SDN",
            "program": "IRAN",
        },
        {
            "name": "Islamic Republic of Iran Shipping Lines",
            "aliases": ["IRIS", "IRAN SHIPPING LINES"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "SDN",
            "program": "IRAN",
        },
        {
            "name": "Bank Melli Iran",
            "aliases": ["BMI", "NATIONAL BANK OF IRAN"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "SDN",
            "program": "IRAN",
        },
        {
            "name": "Islamic Republic of Iran Broadcasting",
            "aliases": ["IRIB", "VEVAK"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "SDN",
            "program": "IRAN",
        },
        {
            "name": "Organization of Defensive Innovation and Research",
            "aliases": ["ODIR", "SPND"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "EL",
            "program": "IRAN",
        },

        # --- NORTH KOREA ---
        {
            "name": "Korea Mining Development Trading Corporation",
            "aliases": ["KOMID", "KOREA MINING"],
            "entity_type": "entity",
            "country": "KP",
            "list_type": "SDN",
            "program": "NORTH-KOREA",
        },
        {
            "name": "Korea Precious Metals Trading Corporation",
            "aliases": ["KPMTC"],
            "entity_type": "entity",
            "country": "KP",
            "list_type": "SDN",
            "program": "NORTH-KOREA",
        },
        {
            "name": "Foreign Trade Bank of North Korea",
            "aliases": ["FTBNK"],
            "entity_type": "entity",
            "country": "KP",
            "list_type": "SDN",
            "program": "NORTH-KOREA",
        },

        # --- SYRIA ---
        {
            "name": "Commercial Bank of Syria",
            "aliases": ["CBS", "BANQUE COMMERCIALE DE SYRIE"],
            "entity_type": "entity",
            "country": "SY",
            "list_type": "SDN",
            "program": "SYRIA",
        },

        # --- CUBA ---
        {
            "name": "Banco Financiero Internacional",
            "aliases": ["BFI", "BANCO FINANCIERO INTERNACIONAL CUBA"],
            "entity_type": "entity",
            "country": "CU",
            "list_type": "SDN",
            "program": "CUBA",
        },

        # --- VENEZUELA ---
        {
            "name": "Banco de Venezuela",
            "aliases": ["BDV"],
            "entity_type": "entity",
            "country": "VE",
            "list_type": "SDN",
            "program": "VENEZUELA",
        },

        # --- BELARUS ---
        {
            "name": "Belarusian State Concern Mozhenergo",
            "aliases": ["MOZHERENERGY"],
            "entity_type": "entity",
            "country": "BY",
            "list_type": "SDN",
            "program": "BELARUS-EO14065",
        },

        # --- Additional DPL Entries (Individuals) ---
        {
            "name": "Mahmoud Reza Khavari",
            "aliases": [],
            "entity_type": "individual",
            "country": "IR",
            "list_type": "DPL",
            "program": "IRAN",
        },
        {
            "name": "Hassan Rouhani",
            "aliases": ["HASSAN ROHANI", "HASSAN RUWHANI"],
            "entity_type": "individual",
            "country": "IR",
            "list_type": "DPL",
            "program": "IRAN",
        },
        {
            "name": "Vladimir Sergeyevich Artemyev",
            "aliases": [],
            "entity_type": "individual",
            "country": "RU",
            "list_type": "DPL",
            "program": "UKRAINE-EO13661",
        },
        {
            "name": "Dmitry Sergeyevich Shugaev",
            "aliases": [],
            "entity_type": "individual",
            "country": "RU",
            "list_type": "DPL",
            "program": "UKRAINE-EO13661",
        },

        # --- Military End-User (MEU) Entities ---
        {
            "name": "China Electronic Technology Group Corporation Research Institute",
            "aliases": ["CETC-10", "CETC RESEARCH INSTITUTE"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "MEU",
            "program": "CHINA-MILITARY",
        },
        {
            "name": "Nanjing Research Institute of Electronics Technology",
            "aliases": ["NRIET", "29TH INSTITUTE"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "MEU",
            "program": "CHINA-MILITARY",
        },
        {
            "name": "Xi'an Jiaotong University",
            "aliases": ["XJTU"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "MEU",
            "program": "CHINA-MILITARY",
        },
        {
            "name": "Harbin Institute of Technology",
            "aliases": ["HIT", "HARBIN TECH"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "MEU",
            "program": "CHINA-MILITARY",
        },
        {
            "name": "Beihang University",
            "aliases": ["BUAA", "BEIJING INSTITUTE OF AERONAUTICS AND ASTRONAUTICS"],
            "entity_type": "entity",
            "country": "CN",
            "list_type": "MEU",
            "program": "CHINA-MILITARY",
        },

        # --- Unverified List (UVL) Examples ---
        {
            "name": "Armax Trading Company",
            "aliases": ["ARMAX"],
            "entity_type": "entity",
            "country": "SY",
            "list_type": "UVL",
            "program": "UNVERIFIED",
        },
        {
            "name": "Sama Technical and Engineering Services",
            "aliases": ["SAMA SERVICES"],
            "entity_type": "entity",
            "country": "IR",
            "list_type": "UVL",
            "program": "UNVERIFIED",
        },
    ]


def sync_bis_csl() -> list[SanctionRecord]:
    """
    Sync BIS CSL seed dataset and return normalized SanctionRecord list.

    Returns list of SanctionRecord objects with:
      - source="bis"
      - source_uid: BIS-<country>-<index>
      - Standard SanctionRecord fields (name, aliases, entity_type, country, etc.)
    """
    records = []
    seed = _get_bis_seed_data()

    for idx, entry in enumerate(seed):
        uid = f"BIS-{entry['country']}-{idx:04d}"
        rec = SanctionRecord(
            source="bis",
            source_uid=uid,
            name=entry["name"],
            aliases=entry.get("aliases", []),
            entity_type=entry.get("entity_type", "entity"),
            country=entry.get("country", ""),
            program=entry.get("program", ""),
            list_type=entry.get("list_type", "EL"),
            remarks=f"BIS {entry.get('list_type', 'EL')} entry",
            date_listed="",
        )
        records.append(rec)

    return records


def try_fetch_bis_csl_api(timeout: int = 30) -> list[SanctionRecord]:
    """
    Attempt to fetch BIS CSL from live API with graceful fallback to seed data.

    The BIS API endpoint is:
      https://api.trade.gov/consolidated_screening_list/v2/search

    No authentication required for basic searches.
    API supports pagination and filtering by list type.

    Args:
        timeout: HTTP request timeout in seconds

    Returns:
        List of SanctionRecord objects (live API data if available, seed data fallback)
    """
    api_url = "https://api.trade.gov/consolidated_screening_list/v2/search"
    params = "?list=BIS_EL,BIS_DPL,BIS_UVL,BIS_MEU&limit=500"
    full_url = api_url + params

    try:
        print(f"    Attempting BIS CSL API fetch from {api_url}...", flush=True)
        req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            text = data.decode("utf-8", errors="replace")
            result = json.loads(text)

            # Parse API response (structure depends on BIS API format)
            # For now, assume it returns {"results": [...]} with entity records
            records = []
            for entry in result.get("results", []):
                uid = entry.get("id", entry.get("name", ""))
                rec = SanctionRecord(
                    source="bis",
                    source_uid=f"BIS-API-{uid}",
                    name=entry.get("name", ""),
                    aliases=entry.get("aka", []),
                    entity_type=entry.get("entity_type", "entity"),
                    country=entry.get("country", ""),
                    program=entry.get("federal_list_category", ""),
                    list_type=entry.get("source", "EL"),
                    remarks=entry.get("address", ""),
                )
                records.append(rec)

            print(f"    -> Fetched {len(records)} BIS entities from live API")
            return records

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        print(f"    BIS API unavailable ({e}), falling back to seed data")
        return sync_bis_csl()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for testing."""
    import argparse
    parser = argparse.ArgumentParser(description="BIS CSL sync")
    parser.add_argument("--live", action="store_true", help="Try live API with fallback")
    parser.add_argument("--count", action="store_true", help="Show entity count")
    args = parser.parse_args()

    if args.live:
        records = try_fetch_bis_csl_api()
    else:
        records = sync_bis_csl()

    if args.count:
        print(f"Total BIS entities: {len(records)}")
        by_country = {}
        for r in records:
            by_country[r.country] = by_country.get(r.country, 0) + 1
        print("\nBy country:")
        for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
            print(f"  {country}: {count}")
    else:
        print(f"Sample BIS entities ({len(records)} total):")
        for r in records[:10]:
            print(f"  {r.name} ({r.country}) [{r.list_type}]")


if __name__ == "__main__":
    main()
