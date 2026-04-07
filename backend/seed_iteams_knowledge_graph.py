"""
Seed ITEAMS competitive intelligence relationships into the knowledge graph.

This script creates entities and relationships for ITEAMS contract vehicle analysis,
including:
- Organizations (prime contractors, owners, partners)
- Contract vehicles and predecessors
- Facilities and operational locations
- Relationship graph with provenance, confidence tiers, and evidence

Idempotent: Checks for existing entities before creating.
Runnable: python seed_iteams_knowledge_graph.py
"""

import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Import knowledge graph API
sys.path.insert(0, str(Path(__file__).parent))
import knowledge_graph as kg
from entity_resolution import ResolvedEntity

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Confidence tiers (from graph_ingest.py)
CONFIDENCE_TIERS = {
    "deterministic": 0.95,      # Identifier match (CIK, LEI, CAGE)
    "structured_api": 0.85,     # Structured data from API (contract records, SEC filings)
    "parsed_text": 0.70,        # Parsed from structured text (filings, dossiers)
    "inferred_text": 0.55,      # Inferred from title/detail text patterns
    "co_occurrence": 0.50,      # Co-occurrence in same enrichment report
    "news_mention": 0.40,       # Co-mentioned in news articles
    "humint_unconfirmed": 0.35, # Human intelligence, unconfirmed
}

# Relationship types (from graph_ingest.py)
REL_OWNED_BY = "owned_by"
REL_PARENT = "parent_of"
REL_SUCCESSOR_OF = "successor_of"
REL_PREDECESSOR_OF = "predecessor_of"
REL_AWARDED_UNDER = "awarded_under"
REL_TEAMED_WITH = "teamed_with"
REL_PERFORMED_AT = "performed_at"
REL_OPERATES_FACILITY = "operates_facility"
REL_BENEFICIALLY_OWNED_BY = "beneficially_owned_by"
REL_MERGED_WITH = "related_entity"  # Using related_entity for mergers
REL_SUBSIDIARY = "subsidiary_of"
REL_ACQUIRED = "related_entity"     # Using related_entity for acquisitions
REL_FUNDED_BY = "funded_by"
REL_CONTRACTS_WITH = "contracts_with"

# Entity definitions
ENTITIES = {
    # Organizations
    "amentum": {
        "name": "Amentum Holdings, Inc.",
        "type": "company",
        "identifiers": {
            "cage": "7V3P3",
            "uei": "XXXXXXXXXXXXXXX",
        },
        "country": "US",
        "sources": ["sec_edgar", "sam_gov"],
    },
    "mantech": {
        "name": "ManTech International Corporation",
        "type": "company",
        "identifiers": {
            "cage": "6E6G5",
            "cik": "0001368042",
        },
        "country": "US",
        "sources": ["sec_edgar", "sam_gov"],
    },
    "smx": {
        "name": "SMX",
        "type": "company",
        "identifiers": {
            "cage": "XXXXXXX",
        },
        "country": "US",
        "sources": ["sam_gov"],
    },
    "hii": {
        "name": "HII Mission Technologies",
        "type": "company",
        "identifiers": {
            "cage": "XXXXXXX",
        },
        "country": "US",
        "sources": ["sam_gov"],
    },
    "carlyle": {
        "name": "Carlyle Group",
        "type": "company",
        "identifiers": {
            "lei": "LHVCEM00KS86BQ7PGN85",
            "cik": "0001524519",
        },
        "country": "US",
        "sources": ["sec_edgar"],
    },
    "oceansound": {
        "name": "OceanSound Partners",
        "type": "company",
        "identifiers": {},
        "country": "US",
        "sources": ["capiq", "bloomberg"],
    },
    "jacobs": {
        "name": "Jacobs Solutions Inc.",
        "type": "company",
        "identifiers": {
            "cik": "0001022701",
        },
        "country": "US",
        "sources": ["sec_edgar"],
    },
    "kupono": {
        "name": "Kupono Government Services",
        "type": "company",
        "identifiers": {
            "cage": "XXXXXXX",
        },
        "country": "US",
        "sources": ["sam_gov"],
    },
    "aecom": {
        "name": "AECOM",
        "type": "company",
        "identifiers": {
            "cik": "0001335758",
        },
        "country": "US",
        "sources": ["sec_edgar"],
    },
    "cbeyonddata": {
        "name": "cBEYONData",
        "type": "company",
        "identifiers": {},
        "country": "US",
        "sources": ["press_release"],
    },
    "usindopacom": {
        "name": "USINDOPACOM",
        "type": "government_agency",
        "identifiers": {},
        "country": "US",
        "sources": ["dod_directory"],
    },

    # Contract vehicles
    "iteams": {
        "name": "ITEAMS",
        "type": "contract_vehicle",
        "identifiers": {
            "vehicle_id": "GS00Q14OADU140-47QFCA23F0046",
        },
        "country": "US",
        "sources": ["sam_gov", "gsa_schedule"],
    },
    "ipiess": {
        "name": "IPIESS",
        "type": "contract_vehicle",
        "identifiers": {},
        "country": "US",
        "sources": ["dod_contract_awards"],
    },
    "leia": {
        "name": "LEIA",
        "type": "contract_vehicle",
        "identifiers": {
            "contract_value": "$3.2B",
        },
        "country": "US",
        "sources": ["dod_contract_awards"],
    },
    "oasis": {
        "name": "OASIS",
        "type": "contract_vehicle",
        "identifiers": {},
        "country": "US",
        "sources": ["gsa_schedule"],
    },
    "pmrf_jv": {
        "name": "PMRF JV",
        "type": "contract_vehicle",
        "identifiers": {
            "contract_value": "$854M",
        },
        "country": "US",
        "sources": ["dod_contract_awards"],
    },
    "southcom_it": {
        "name": "SOUTHCOM IT",
        "type": "contract_vehicle",
        "identifiers": {
            "contract_value": "$910M",
        },
        "country": "US",
        "sources": ["dod_contract_awards"],
    },

    # Facilities
    "amentum_hq": {
        "name": "Amentum Hawaii HQ",
        "type": "facility",
        "identifiers": {},
        "country": "US",
        "sources": ["press_release", "hiring_signals"],
    },
    "camp_smith": {
        "name": "Camp Smith",
        "type": "facility",
        "identifiers": {},
        "country": "US",
        "sources": ["dod_directory"],
    },
    "mantech_kumaumau": {
        "name": "ManTech Kumaumau Center",
        "type": "facility",
        "identifiers": {},
        "country": "US",
        "sources": ["press_release"],
    },
}

# Relationships to create
RELATIONSHIPS = [
    # Amentum prime on ITEAMS
    {
        "source": "amentum",
        "target": "iteams",
        "rel_type": "prime_contractor_of",
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "sam_gov",
        "evidence": "GSA Schedule contract award record",
        "evidence_url": "https://sam.gov/opp/XXXXXXX",
        "evidence_title": "ITEAMS Contract Vehicle",
        "observed_at": "2026-04-02T00:00:00Z",
    },
    # Amentum successor to AECOM on IPIESS
    {
        "source": "amentum",
        "target": "ipiess",
        "rel_type": REL_SUCCESSOR_OF,
        "confidence": CONFIDENCE_TIERS["parsed_text"],
        "data_source": "dod_press_release",
        "evidence": "Amentum acquired AECOM's program management business, became incumbent on IPIESS",
        "evidence_title": "Amentum IPIESS Successor",
        "observed_at": "2025-06-01T00:00:00Z",
    },
    # AECOM predecessor of IPIESS
    {
        "source": "aecom",
        "target": "ipiess",
        "rel_type": REL_PREDECESSOR_OF,
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "dod_contract_awards",
        "evidence": "AECOM was original incumbent on IPIESS contract",
        "evidence_title": "AECOM IPIESS Predecessor",
        "observed_at": "2024-01-01T00:00:00Z",
    },
    # ManTech owned by Carlyle
    {
        "source": "mantech",
        "target": "carlyle",
        "rel_type": REL_OWNED_BY,
        "confidence": CONFIDENCE_TIERS["deterministic"],
        "data_source": "sec_edgar",
        "evidence": "Carlyle Group private equity ownership of ManTech International",
        "evidence_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001368042",
        "evidence_title": "ManTech SEC Filings",
        "observed_at": "2022-04-28T00:00:00Z",
    },
    # SMX owned by OceanSound
    {
        "source": "smx",
        "target": "oceansound",
        "rel_type": REL_OWNED_BY,
        "confidence": CONFIDENCE_TIERS["parsed_text"],
        "data_source": "capiq",
        "evidence": "OceanSound Partners private equity ownership of SMX",
        "evidence_title": "SMX Ownership Structure",
        "observed_at": "2023-06-15T00:00:00Z",
    },
    # SMX prime on LEIA
    {
        "source": "smx",
        "target": "leia",
        "rel_type": "prime_contractor_of",
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "dod_contract_awards",
        "evidence": "SMX prime contractor on LEIA $3.2B vehicle",
        "evidence_title": "LEIA Contract Award",
        "observed_at": "2024-09-12T00:00:00Z",
    },
    # SMX acquired cBEYONData
    {
        "source": "smx",
        "target": "cbeyonddata",
        "rel_type": REL_ACQUIRED,
        "confidence": CONFIDENCE_TIERS["news_mention"],
        "data_source": "press_release",
        "evidence": "SMX acquired cBEYONData to expand data analytics capabilities",
        "evidence_title": "SMX Acquisition of cBEYONData",
        "observed_at": "2024-07-20T00:00:00Z",
    },
    # cBEYONData subcontract posture on LEIA
    {
        "source": "cbeyonddata",
        "target": "leia",
        "rel_type": "subcontractor_of",
        "confidence": CONFIDENCE_TIERS["parsed_text"],
        "data_source": "press_release",
        "evidence": "cBEYONData capabilities were folded into the LEIA execution stack after the SMX acquisition.",
        "evidence_title": "LEIA teammate integration",
        "observed_at": "2025-01-18T00:00:00Z",
    },
    # Amentum merged with Jacobs (simplified as related_entity)
    {
        "source": "amentum",
        "target": "jacobs",
        "rel_type": REL_MERGED_WITH,
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "sec_edgar",
        "evidence": "Amentum absorbed Jacobs Solutions program management operations",
        "evidence_url": "https://www.sec.gov/Archives/edgar/",
        "evidence_title": "Amentum / Jacobs Integration",
        "observed_at": "2024-03-01T00:00:00Z",
    },
    # Amentum joint venture with Kupono (PMRF)
    {
        "source": "amentum",
        "target": "kupono",
        "rel_type": REL_TEAMED_WITH,
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "sam_gov",
        "evidence": "Joint venture partnership on PMRF $854M contract",
        "evidence_title": "PMRF Joint Venture",
        "observed_at": "2024-02-15T00:00:00Z",
    },
    # Amentum operates Hawaii HQ
    {
        "source": "amentum",
        "target": "amentum_hq",
        "rel_type": REL_OPERATES_FACILITY,
        "confidence": CONFIDENCE_TIERS["inferred_text"],
        "data_source": "press_release",
        "evidence": "Amentum quadrupled Hawaii HQ capacity March 2026 for Indo-Pacific expansion",
        "evidence_title": "Amentum Hawaii Expansion",
        "observed_at": "2026-03-15T00:00:00Z",
    },
    # Amentum hiring at Camp Smith
    {
        "source": "amentum",
        "target": "camp_smith",
        "rel_type": REL_OPERATES_FACILITY,
        "confidence": CONFIDENCE_TIERS["co_occurrence"],
        "data_source": "hiring_signals",
        "evidence": "Active recruitment of USINDOPACOM-cleared personnel for Camp Smith location",
        "evidence_title": "Camp Smith Hiring Signals",
        "observed_at": "2026-03-20T00:00:00Z",
    },
    # ManTech operates Kumaumau Center
    {
        "source": "mantech",
        "target": "mantech_kumaumau",
        "rel_type": REL_OPERATES_FACILITY,
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "press_release",
        "evidence": "ManTech Kumaumau Center opened October 2024 for Pacific operations",
        "evidence_title": "ManTech Kumaumau Center Opening",
        "observed_at": "2024-10-15T00:00:00Z",
    },
    # ManTech prime on SOUTHCOM IT
    {
        "source": "mantech",
        "target": "southcom_it",
        "rel_type": "prime_contractor_of",
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "dod_contract_awards",
        "evidence": "ManTech prime on SOUTHCOM IT $910M vehicle",
        "evidence_title": "SOUTHCOM IT Contract Award",
        "observed_at": "2024-11-30T00:00:00Z",
    },
    # HII operates near Camp Smith
    {
        "source": "hii",
        "target": "camp_smith",
        "rel_type": REL_OPERATES_FACILITY,
        "confidence": CONFIDENCE_TIERS["co_occurrence"],
        "data_source": "sam_gov",
        "evidence": "HII operates in Camp Smith area for USINDOPACOM support",
        "evidence_title": "HII Camp Smith Operations",
        "observed_at": "2024-06-01T00:00:00Z",
    },
    # LEIA performed at Camp Smith
    {
        "source": "leia",
        "target": "camp_smith",
        "rel_type": REL_PERFORMED_AT,
        "confidence": CONFIDENCE_TIERS["parsed_text"],
        "data_source": "dod_contract_awards",
        "evidence": "LEIA execution is anchored to Camp Smith support activity.",
        "evidence_title": "LEIA place of performance",
        "observed_at": "2024-09-12T00:00:00Z",
    },
    # LEIA supports USINDOPACOM
    {
        "source": "leia",
        "target": "usindopacom",
        "rel_type": REL_CONTRACTS_WITH,
        "confidence": CONFIDENCE_TIERS["parsed_text"],
        "data_source": "dod_contract_awards",
        "evidence": "LEIA supports USINDOPACOM zero-trust modernization demand.",
        "evidence_title": "LEIA customer base",
        "observed_at": "2024-09-12T00:00:00Z",
    },
    # HII visible challenger pressure on LEIA
    {
        "source": "hii",
        "target": "leia",
        "rel_type": "competed_on",
        "confidence": CONFIDENCE_TIERS["inferred_text"],
        "data_source": "osint_tracking",
        "evidence": "HII remained visible in the LEIA challenger set during the Indo-Pacific network modernization posture shift.",
        "evidence_title": "LEIA challenger pressure",
        "observed_at": "2025-03-02T00:00:00Z",
    },
    # Amentum visible challenger pressure on LEIA
    {
        "source": "amentum",
        "target": "leia",
        "rel_type": "competed_on",
        "confidence": CONFIDENCE_TIERS["humint_unconfirmed"],
        "data_source": "network_intelligence",
        "evidence": "Amentum was discussed in the LEIA challenger picture but did not emerge as the prime.",
        "evidence_title": "LEIA challenger watchlist",
        "observed_at": "2025-02-11T00:00:00Z",
    },
    # ITEAMS awarded under OASIS
    {
        "source": "iteams",
        "target": "oasis",
        "rel_type": REL_AWARDED_UNDER,
        "confidence": CONFIDENCE_TIERS["structured_api"],
        "data_source": "gsa_schedule",
        "evidence": "ITEAMS is a GSA Schedule vehicle awarded under OASIS",
        "evidence_url": "https://sam.gov/opp/OASIS",
        "evidence_title": "OASIS Vehicle",
        "observed_at": "2014-07-01T00:00:00Z",
    },
    # ITEAMS supports USINDOPACOM
    {
        "source": "iteams",
        "target": "usindopacom",
        "rel_type": REL_CONTRACTS_WITH,
        "confidence": CONFIDENCE_TIERS["inferred_text"],
        "data_source": "dod_contract_awards",
        "evidence": "ITEAMS prime purpose: provide contract vehicle intelligence for USINDOPACOM",
        "evidence_title": "ITEAMS Customer Base",
        "observed_at": "2024-01-01T00:00:00Z",
    },
    # Potential teaming: Amentum + SMX (unconfirmed HUMINT)
    {
        "source": "amentum",
        "target": "smx",
        "rel_type": REL_TEAMED_WITH,
        "confidence": CONFIDENCE_TIERS["humint_unconfirmed"],
        "data_source": "network_intelligence",
        "evidence": "Unconfirmed: Amentum and SMX exploring potential partnership on Indo-Pacific bids",
        "evidence_title": "Amentum / SMX Potential Teaming",
        "observed_at": "2026-03-25T00:00:00Z",
    },
]


def _generate_entity_id(name: str, entity_type: str) -> str:
    """Generate stable entity ID from name and type."""
    import hashlib
    normalized = f"{name}:{entity_type}".lower().strip()
    return f"ent_{hashlib.sha1(normalized.encode()).hexdigest()[:16]}"


def _entity_exists(entity_id: str) -> bool:
    """Check if entity already exists in knowledge graph."""
    try:
        with kg.get_kg_conn() as conn:
            row = conn.execute(
                "SELECT id FROM kg_entities WHERE id = ?",
                (entity_id,)
            ).fetchone()
            return row is not None
    except Exception as e:
        logger.warning(f"Error checking entity existence: {e}")
        return False


def _relationship_exists(source_id: str, target_id: str, rel_type: str, data_source: str) -> bool:
    """Check if relationship already exists."""
    try:
        with kg.get_kg_conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM kg_relationships
                WHERE source_entity_id = ? AND target_entity_id = ?
                  AND rel_type = ? AND data_source = ?
                """,
                (source_id, target_id, rel_type, data_source),
            ).fetchone()
            return row is not None
    except Exception as e:
        logger.warning(f"Error checking relationship existence: {e}")
        return False


def seed_iteams_graph():
    """Seed ITEAMS entities and relationships into knowledge graph."""
    kg.init_kg_db()

    created_entity_ids = {}
    stats = {
        "entities_created": 0,
        "entities_skipped": 0,
        "relationships_created": 0,
        "relationships_skipped": 0,
    }

    # Create all entities first
    logger.info("Creating entities...")
    for key, entity_def in ENTITIES.items():
        entity_id = _generate_entity_id(entity_def["name"], entity_def["type"])
        created_entity_ids[key] = entity_id

        if _entity_exists(entity_id):
            logger.debug(f"  Skipping existing entity: {entity_def['name']}")
            stats["entities_skipped"] += 1
            continue

        entity = ResolvedEntity(
            id=entity_id,
            canonical_name=entity_def["name"],
            entity_type=entity_def["type"],
            aliases=[],
            identifiers=entity_def.get("identifiers", {}),
            country=entity_def.get("country", ""),
            sources=entity_def.get("sources", []),
            confidence=CONFIDENCE_TIERS["structured_api"],
            last_updated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        )

        kg.save_entity(entity)
        logger.info(f"  Created: {entity_def['name']}")
        stats["entities_created"] += 1

    # Create all relationships
    logger.info("\nCreating relationships...")
    for rel in RELATIONSHIPS:
        source_id = created_entity_ids.get(rel["source"])
        target_id = created_entity_ids.get(rel["target"])

        if not source_id or not target_id:
            logger.warning(
                f"  Skipping relationship: source or target not found "
                f"({rel.get('source')} -> {rel.get('target')})"
            )
            stats["relationships_skipped"] += 1
            continue

        if _relationship_exists(source_id, target_id, rel["rel_type"], rel["data_source"]):
            logger.debug(
                f"  Skipping existing relationship: "
                f"{ENTITIES[rel['source']]['name']} -> {rel['rel_type']} -> "
                f"{ENTITIES[rel['target']]['name']}"
            )
            stats["relationships_skipped"] += 1
            continue

        kg.save_relationship(
            source_entity_id=source_id,
            target_entity_id=target_id,
            rel_type=rel["rel_type"],
            confidence=rel.get("confidence", CONFIDENCE_TIERS["structured_api"]),
            data_source=rel.get("data_source", ""),
            evidence=rel.get("evidence", ""),
            evidence_url=rel.get("evidence_url", ""),
            evidence_title=rel.get("evidence_title", ""),
            observed_at=rel.get("observed_at", ""),
        )

        logger.info(
            f"  Created: {ENTITIES[rel['source']]['name']} -> {rel['rel_type']} -> "
            f"{ENTITIES[rel['target']]['name']}"
        )
        stats["relationships_created"] += 1

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("ITEAMS Knowledge Graph Seeding Summary")
    logger.info("=" * 60)
    logger.info(f"Entities created:        {stats['entities_created']}")
    logger.info(f"Entities skipped:        {stats['entities_skipped']}")
    logger.info(f"Relationships created:   {stats['relationships_created']}")
    logger.info(f"Relationships skipped:   {stats['relationships_skipped']}")
    logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    try:
        stats = seed_iteams_graph()
        if stats["entities_created"] + stats["relationships_created"] > 0:
            logger.info("Seeding completed successfully")
            sys.exit(0)
        else:
            logger.info("No new entities or relationships created (already seeded)")
            sys.exit(0)
    except Exception as e:
        logger.error(f"Seeding failed: {e}", exc_info=True)
        sys.exit(1)
