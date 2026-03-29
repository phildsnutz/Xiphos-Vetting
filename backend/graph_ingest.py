"""
Graph Ingestion Hook

Automatically extracts entities and relationships from enrichment reports
and feeds them into the knowledge graph. Runs as a post-enrichment step.

Relationship types extracted:
  - subcontractor_of / prime_contractor_of (USASpending subawards)
  - former_name (SEC EDGAR company history)
  - subsidiary_of / parent_of (SEC, OpenCorporates)
  - sanctioned_on (sanctions list matches)
  - litigant_in (RECAP court cases)
  - officer_of (SEC officer/director data)
  - contracts_with (FPDS, SAM.gov awards)
  - related_entity (cross-correlation aliases)
  - supplies_component_to / integrated_into (critical subsystem supply paths)
  - owned_by / beneficially_owned_by / backed_by (ownership, financing, and control chains)

Entity types:
  - company, person, government_agency, court_case, sanctions_list
  - component, subsystem, holding_company
"""

import logging
import re
import json
import hashlib
from datetime import datetime

from ownership_control_intelligence import looks_like_descriptor_owner

logger = logging.getLogger(__name__)

# Relationship type constants
REL_SUBCONTRACTOR = "subcontractor_of"
REL_PRIME_CONTRACTOR = "prime_contractor_of"
REL_FORMER_NAME = "former_name"
REL_SUBSIDIARY = "subsidiary_of"
REL_PARENT = "parent_of"
REL_SANCTIONED = "sanctioned_on"
REL_LITIGANT = "litigant_in"
REL_OFFICER = "officer_of"
REL_CONTRACTS_WITH = "contracts_with"
REL_ALIAS = "alias_of"
REL_RELATED = "related_entity"
REL_FILED_WITH = "filed_with"
REL_REGULATED_BY = "regulated_by"
REL_MENTIONED_WITH = "mentioned_with"
REL_SUPPLIES_COMPONENT_TO = "supplies_component_to"
REL_SUPPLIES_COMPONENT = "supplies_component"
REL_INTEGRATED_INTO = "integrated_into"
REL_OWNED_BY = "owned_by"
REL_BENEFICIALLY_OWNED_BY = "beneficially_owned_by"
REL_BACKED_BY = "backed_by"
REL_LED_BY = "led_by"
REL_DEPENDS_ON_NETWORK = "depends_on_network"
REL_ROUTES_PAYMENT_THROUGH = "routes_payment_through"
REL_DISTRIBUTED_BY = "distributed_by"
REL_OPERATES_FACILITY = "operates_facility"
REL_SHIPS_VIA = "ships_via"
REL_DEPENDS_ON_SERVICE = "depends_on_service"

# ---------------------------------------------------------------------------
# Relationship confidence scoring (Q3)
# Higher = stronger evidence supporting the relationship's existence
# ---------------------------------------------------------------------------
CONFIDENCE = {
    "deterministic":    0.95,  # Identifier match (CIK, LEI, CAGE)
    "structured_api":   0.85,  # Structured data from API (subaward records, SEC filings)
    "parsed_text":      0.70,  # Parsed from structured text (court docket listings)
    "inferred_text":    0.55,  # Inferred from title/detail text patterns
    "co_occurrence":    0.50,  # Co-occurrence in same enrichment report
    "news_mention":     0.40,  # Co-mentioned in news articles
}


def _safe_import_kg():
    """Safely import knowledge graph module. Returns None if unavailable."""
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        logger.debug("Knowledge graph module not available")
        return None


def _safe_import_er():
    """Safely import entity resolution module."""
    try:
        import entity_resolution as er
        return er
    except ImportError:
        logger.debug("Entity resolution module not available")
        return None


def _safe_import_db():
    """Safely import main database module."""
    try:
        import db
        return db
    except ImportError:
        logger.debug("Database module not available")
        return None


def _generate_graph_entity_id(er, name: str, identifiers: dict, entity_type: str) -> str:
    """Mint type-aware IDs for non-company graph nodes to avoid entity-type collisions."""
    if identifiers:
        return er.generate_entity_id(name, identifiers)

    normalized_type = (entity_type or "unknown").strip().lower()
    type_safe = {
        "component",
        "subsystem",
        "holding_company",
        "bank",
        "telecom_provider",
        "distributor",
        "facility",
        "shipment_route",
        "service",
        "product",
        "cve",
        "kev_entry",
        "country",
        "export_control",
        "trade_show_event",
    }
    if normalized_type in type_safe:
        normalized_name = er.normalize_name(name) or name.strip().upper()
        hash_val = hashlib.md5(normalized_name.encode()).hexdigest()[:12]
        return f"{normalized_type}:{hash_val}"

    return er.generate_entity_id(name, identifiers)


# ---------------------------------------------------------------------------
# Merge-on-ingest deduplication
# ---------------------------------------------------------------------------

def _find_or_create_entity(kg, er, name: str, identifiers: dict, entity_type: str = "company",
                            country: str = "", sources: list = None, confidence: float = 0.7,
                            aliases: list = None) -> str:
    """
    Deduplicated entity creation. Before inserting a new entity, checks:
    1. Exact identifier match (CIK, LEI, UEI, CAGE) -> merge
    2. Fuzzy name match (Jaro-Winkler >= 0.88) -> merge
    3. No match -> create new

    Returns the entity ID (existing or newly created).
    """
    sources = sources or []
    aliases = aliases or []
    now = datetime.utcnow().isoformat() + "Z"

    # 1. Check by identifier (deterministic, highest confidence)
    for id_type in ("cik", "lei", "uei", "cage", "ein"):
        id_val = identifiers.get(id_type)
        if id_val:
            # Search existing entities
            candidate_id = er.generate_entity_id(name, {id_type: id_val})
            existing = kg.get_entity(candidate_id)
            if existing:
                # Merge: update aliases, sources, confidence
                _merge_entity(kg, existing, name, identifiers, sources, aliases, now)
                logger.debug("Dedup: merged '%s' into existing entity '%s' (identifier match: %s=%s)",
                           name, existing.canonical_name, id_type, id_val)
                return existing.id

    # 2. Check by fuzzy name match
    try:
        candidates = kg.find_entities_by_name(name, entity_type=entity_type, threshold=0.0)
        for candidate in candidates:
            # Use Jaro-Winkler for precise matching
            score = er.jaro_winkler(
                er.normalize_name(name),
                er.normalize_name(candidate.canonical_name)
            )
            if score >= 0.88:
                # Country match boosts confidence
                if country and candidate.country and candidate.country.upper() == country.upper():
                    score = min(1.0, score + 0.05)

                if score >= 0.88:
                    _merge_entity(kg, candidate, name, identifiers, sources, aliases, now)
                    logger.debug("Dedup: merged '%s' into '%s' (name match: %.2f)",
                               name, candidate.canonical_name, score)
                    return candidate.id

            # Also check aliases
            for alias in candidate.aliases:
                alias_score = er.jaro_winkler(
                    er.normalize_name(name),
                    er.normalize_name(alias)
                )
                if alias_score >= 0.88:
                    _merge_entity(kg, candidate, name, identifiers, sources, aliases, now)
                    logger.debug("Dedup: merged '%s' into '%s' (alias match: '%s', %.2f)",
                               name, candidate.canonical_name, alias, alias_score)
                    return candidate.id
    except Exception as e:
        logger.debug("Dedup name search failed for '%s': %s", name, e)

    # 3. No match found -> create new entity
    entity_id = _generate_graph_entity_id(er, name, identifiers, entity_type)
    entity = er.ResolvedEntity(
        id=entity_id,
        canonical_name=name,
        entity_type=entity_type,
        aliases=aliases,
        identifiers=identifiers,
        country=country,
        sources=sources,
        confidence=confidence,
        last_updated=now,
    )
    kg.save_entity(entity)
    return entity_id


def _merge_entity(kg, existing, new_name: str, new_identifiers: dict,
                  new_sources: list, new_aliases: list, now: str):
    """Merge new data into an existing entity without duplicating."""
    changed = False

    # Merge aliases (add new name as alias if different from canonical)
    current_aliases = set(existing.aliases)
    if new_name and new_name.upper() != existing.canonical_name.upper():
        if new_name not in current_aliases:
            current_aliases.add(new_name)
            changed = True

    for alias in new_aliases:
        if alias and alias.upper() != existing.canonical_name.upper() and alias not in current_aliases:
            current_aliases.add(alias)
            changed = True

    # Merge identifiers (don't overwrite, only add new)
    current_ids = dict(existing.identifiers)
    for k, v in new_identifiers.items():
        if v and k not in current_ids:
            current_ids[k] = v
            changed = True

    # Merge sources
    current_sources = set(existing.sources)
    for src in new_sources:
        if src and src not in current_sources:
            current_sources.add(src)
            changed = True

    if changed:
        existing.aliases = list(current_aliases)
        existing.identifiers = current_ids
        existing.sources = list(current_sources)
        existing.last_updated = now
        kg.save_entity(existing)


def ingest_enrichment_to_graph(
    vendor_id: str,
    vendor_name: str,
    enrichment_report: dict,
) -> dict:
    """
    Extract entities and relationships from an enrichment report
    and store them in the knowledge graph.

    Pipeline:
      1. Create/update primary vendor entity (with dedup)
      2. Extract explicit relationships from report.relationships[]
      3. Extract entities/relationships from individual findings (Layer 1)
      4. Extract agency relationships from contract data
      5. Post-processing relationship inference (Layer 2)

    Returns summary stats: {entities_created, relationships_created, errors}.
    """
    kg = _safe_import_kg()
    er = _safe_import_er()

    if not kg or not er:
        return {"entities_created": 0, "relationships_created": 0, "errors": ["knowledge graph modules unavailable"]}

    stats = {"entities_created": 0, "relationships_created": 0, "errors": [], "vendor_id": vendor_id}

    try:
        # Initialize the KG database if needed
        kg.init_kg_db()
        kg.clear_vendor_graph_state(vendor_id)

        # 1. Create/update the primary vendor entity (with dedup)
        identifiers = enrichment_report.get("identifiers", {})
        country = enrichment_report.get("country", "")
        aliases = _extract_aliases(vendor_name, enrichment_report)
        sources = list(enrichment_report.get("connector_status", {}).keys())

        entity_id = _find_or_create_entity(
            kg, er, vendor_name, identifiers,
            entity_type="company", country=country,
            sources=sources, confidence=0.95, aliases=aliases,
        )
        kg.link_entity_to_vendor(entity_id, vendor_id)
        stats["entities_created"] += 1

        # 2. Extract relationships from the enrichment report's relationship array
        for rel in enrichment_report.get("relationships", []):
            try:
                _ingest_relationship(kg, er, entity_id, vendor_name, rel, stats)
            except Exception as e:
                stats["errors"].append(f"relationship ingest: {e}")

        # 3. Extract entities/relationships from findings (Layer 1)
        for finding in enrichment_report.get("findings", []):
            try:
                _ingest_finding(kg, er, entity_id, vendor_name, finding, stats)
            except Exception as e:
                stats["errors"].append(f"finding ingest: {e}")

        # 4. Extract agency relationships from contract data
        _ingest_agency_relationships(kg, er, entity_id, vendor_name, enrichment_report, stats)

        # 5. Post-processing relationship inference (Layer 2)
        try:
            _infer_relationships(kg, er, entity_id, vendor_name, enrichment_report, stats)
        except Exception as e:
            stats["errors"].append(f"relationship inference: {e}")

        logger.info(
            "Graph ingest for %s: %d entities, %d relationships, %d errors",
            vendor_name, stats["entities_created"], stats["relationships_created"], len(stats["errors"]),
        )

    except Exception as e:
        stats["errors"].append(f"graph ingest top-level: {e}")
        logger.warning("Graph ingest failed for %s: %s", vendor_name, e)

    return stats


def _extract_aliases(vendor_name: str, report: dict) -> list[str]:
    """Extract name aliases from enrichment data."""
    aliases = set()
    # SEC registered name
    sec_name = report.get("identifiers", {}).get("sec_registered_name", "")
    if sec_name and sec_name.upper() != vendor_name.upper():
        aliases.add(sec_name)

    # Former names from relationships
    for rel in report.get("relationships", []):
        if rel.get("type") == "former_name":
            fn = rel.get("entity", "")
            if fn and fn.upper() != vendor_name.upper():
                aliases.add(fn)

    return list(aliases)


def _ingest_relationship(kg, er, primary_entity_id: str, vendor_name: str, rel: dict, stats: dict):
    """Ingest a single relationship from the enrichment report."""
    rel_type = rel.get("type", "")
    vendor_id = stats.get("vendor_id", "")

    if rel_type in ("subcontractor_of", "prime_contractor_of"):
        if rel_type == "subcontractor_of":
            other_name = rel.get("target_entity", "")
        else:
            other_name = rel.get("source_entity", "")

        if not other_name or other_name.upper() == vendor_name.upper():
            return

        target_id = _find_or_create_entity(
            kg, er, other_name, {},
            entity_type="company",
            sources=[rel.get("data_source", "usaspending")],
            confidence=0.7,
        )
        stats["entities_created"] += 1

        # Determine direction
        if rel_type == "subcontractor_of":
            src, tgt = primary_entity_id, target_id
        else:
            src, tgt = target_id, primary_entity_id

        evidence = f"${rel.get('amount', 0):,.0f} across {rel.get('count', 0)} awards"
        kg.save_relationship(
            src,
            tgt,
            rel_type,
            confidence=0.8,
            data_source=rel.get("data_source", "usaspending"),
            evidence=evidence,
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1

    elif rel_type == "former_name":
        entity_name = rel.get("entity", "")
        if entity_name:
            # Don't create a separate entity for former names, just record as alias
            pass

    elif rel_type in ("mentioned_with", "related_entity"):
        source_name = rel.get("source_entity", "")
        target_name = rel.get("target_entity", "")

        if source_name.upper() == vendor_name.upper():
            other_name = target_name
        elif target_name.upper() == vendor_name.upper():
            other_name = source_name
        else:
            other_name = target_name or source_name

        if not other_name or other_name.upper() == vendor_name.upper():
            return

        target_id = _find_or_create_entity(
            kg,
            er,
            other_name,
            {},
            entity_type=rel.get("entity_type", "company"),
            country=rel.get("country", ""),
            sources=[rel.get("data_source", "derived_relationship")],
            confidence=rel.get("confidence", CONFIDENCE["inferred_text"]),
        )
        stats["entities_created"] += 1
        vendor_id = stats.get("vendor_id", "")
        if vendor_id:
            kg.link_entity_to_vendor(target_id, vendor_id)

        kg.save_relationship(
            primary_entity_id,
            target_id,
            rel_type,
            confidence=rel.get("confidence", CONFIDENCE["inferred_text"]),
            data_source=rel.get("data_source", "derived_relationship"),
            evidence=rel.get("evidence", "") or f"Relationship imported from {rel.get('data_source', 'fixture')}",
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1

    elif rel_type == "subsidiary_of":
        entity_name = rel.get("entity", "")
        jurisdiction = rel.get("jurisdiction", "")
        if entity_name and entity_name.upper() != vendor_name.upper():
            sub_id = _find_or_create_entity(
                kg, er, entity_name, {},
                entity_type="company", country=jurisdiction,
                sources=[rel.get("data_source", "sec_edgar")],
                confidence=rel.get("confidence", CONFIDENCE["structured_api"]),
            )
            stats["entities_created"] += 1
            # Link subsidiary entity to the same vendor case for graph visibility
            vendor_id = stats.get("vendor_id", "")
            if vendor_id:
                kg.link_entity_to_vendor(sub_id, vendor_id)
            # subsidiary -> parent relationship
            kg.save_relationship(
                sub_id, primary_entity_id, REL_SUBSIDIARY,
                confidence=rel.get("confidence", CONFIDENCE["structured_api"]),
                data_source=rel.get("data_source", "sec_edgar_ex21"),
                evidence=f"SEC Exhibit 21 subsidiary listing ({jurisdiction})",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    elif rel_type == "former_name_match":
        # CIK validation found entity under a different name
        entity_name = rel.get("entity", "")
        if entity_name:
            target_id = _find_or_create_entity(
                kg, er, entity_name, {},
                entity_type="company", sources=["sec_edgar"],
                confidence=rel.get("match_score", 0.7),
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, target_id, REL_RELATED,
                confidence=rel.get("match_score", 0.7),
                data_source="sec_edgar",
                evidence=f"Former name match: {rel.get('former_name', '')}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    elif rel_type in {
        REL_OFFICER,
        "has_vulnerability",
        "uses_product",
        REL_SUPPLIES_COMPONENT_TO,
        REL_SUPPLIES_COMPONENT,
        REL_INTEGRATED_INTO,
        REL_OWNED_BY,
        REL_BENEFICIALLY_OWNED_BY,
        REL_BACKED_BY,
        REL_LED_BY,
        REL_DEPENDS_ON_NETWORK,
        REL_ROUTES_PAYMENT_THROUGH,
        REL_DISTRIBUTED_BY,
        REL_OPERATES_FACILITY,
        REL_SHIPS_VIA,
        REL_DEPENDS_ON_SERVICE,
    }:
        source_name = (rel.get("source_entity") or vendor_name or "").strip()
        target_name = (rel.get("target_entity") or rel.get("entity") or "").strip()
        if not source_name or not target_name:
            return
        if rel_type in {REL_OWNED_BY, REL_BENEFICIALLY_OWNED_BY} and looks_like_descriptor_owner(target_name):
            logger.debug(
                "Skipping descriptor-only ownership relationship during graph ingest: %s -> %s",
                source_name,
                target_name,
            )
            return

        source_type = (rel.get("source_entity_type") or "company").strip().lower()
        target_type = (rel.get("target_entity_type") or "company").strip().lower()
        source_identifiers = rel.get("source_identifiers") or {}
        target_identifiers = rel.get("target_identifiers") or {}
        country = rel.get("country", "")
        data_source = rel.get("data_source", "component_supply_chain")
        confidence = rel.get("confidence", CONFIDENCE["structured_api"])
        evidence = rel.get("evidence", "") or f"Relationship imported from {data_source}"

        if source_name.upper() == vendor_name.upper():
            source_id = primary_entity_id
        else:
            source_id = _find_or_create_entity(
                kg,
                er,
                source_name,
                source_identifiers,
                entity_type=source_type,
                country=country,
                sources=[data_source],
                confidence=confidence,
            )
            stats["entities_created"] += 1

        target_id = _find_or_create_entity(
            kg,
            er,
            target_name,
            target_identifiers,
            entity_type=target_type,
            country=country,
            sources=[data_source],
            confidence=confidence,
        )
        stats["entities_created"] += 1

        vendor_id = stats.get("vendor_id", "")
        if vendor_id:
            kg.link_entity_to_vendor(source_id, vendor_id)
            kg.link_entity_to_vendor(target_id, vendor_id)

        kg.save_relationship(
            source_id,
            target_id,
            rel_type,
            confidence=confidence,
            data_source=data_source,
            evidence=evidence,
            observed_at=rel.get("observed_at", ""),
            valid_from=rel.get("valid_from", ""),
            valid_to=rel.get("valid_to", ""),
            claim_value=rel.get("claim_value", ""),
            contradiction_state=rel.get("contradiction_state", "unreviewed"),
            source_activity=rel.get("source_activity"),
            asserting_agent=rel.get("asserting_agent"),
            artifact_ref=rel.get("artifact_ref", ""),
            evidence_url=rel.get("evidence_url", "") or rel.get("url", ""),
            evidence_title=rel.get("evidence_title", "") or rel.get("title", ""),
            raw_data=rel.get("raw_data", {}) or {},
            structured_fields=rel.get("structured_fields", {}) or {},
            source_class=rel.get("source_class", ""),
            authority_level=rel.get("authority_level", ""),
            access_model=rel.get("access_model", ""),
            vendor_id=vendor_id,
        )
        stats["relationships_created"] += 1


def _ingest_finding(kg, er, primary_entity_id: str, vendor_name: str, finding: dict, stats: dict):
    """Extract entities and relationships from a single finding.

    Layer 1: parses the actual data structures produced by each connector.
    Confidence scoring reflects evidence quality:
      - Deterministic identifier match: 0.95
      - Structured API data (CIK, subaward records): 0.85
      - Parsed text (court docket details): 0.70
      - Inferred from title/detail text: 0.55
    """
    source = finding.get("source", "")
    category = finding.get("category", "")
    title = finding.get("title", "")
    detail = finding.get("detail", "")
    raw_data = finding.get("raw_data", {}) or {}
    vendor_id = stats.get("vendor_id", "")

    # ---- SEC EDGAR: extract related entities from filing search results ----
    if source == "sec_edgar" and category == "identity" and raw_data.get("cik"):
        cik = str(raw_data["cik"])
        # Extract entity name from title: "COMPANY NAME (TICKER) (CIK ...) - FORM (DATE)"
        # or "COMPANY NAME (CIK ...) - FORM (DATE)"
        entity_match = re.match(r"^(.+?)\s+(?:\(.+?\)\s+)?\(CIK\s", title)
        if not entity_match:
            entity_match = re.match(r"^(.+?)\s+-\s+\d", title)
        if entity_match:
            filing_entity = entity_match.group(1).strip()
            # Only create relationship if this is a DIFFERENT entity from the primary
            if filing_entity and filing_entity.upper() != vendor_name.upper():
                # Check if this is a name-similar entity (subsidiary, spin-off)
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, vendor_name.upper(), filing_entity.upper()).ratio()
                if similarity < 0.85:  # Different enough to be a separate entity
                    related_id = _find_or_create_entity(
                        kg, er, filing_entity, {"cik": cik},
                        entity_type="company", sources=["sec_edgar"],
                        confidence=0.85,
                    )
                    stats["entities_created"] += 1
                    kg.save_relationship(
                        primary_entity_id, related_id, REL_FILED_WITH,
                        confidence=CONFIDENCE["structured_api"],
                        data_source="sec_edgar",
                        evidence=f"Co-appears in SEC EDGAR search results (CIK {cik})",
                        vendor_id=vendor_id,
                    )
                    stats["relationships_created"] += 1

    # ---- USASpending supply chain is handled by structured relationships ----
    if source == "usaspending" and category == "supply_chain":
        return

    # ---- USASpending: extract agencies from contracts findings ----
    if source == "usaspending" and category == "contracts":
        agencies = raw_data.get("agencies", [])
        for agency_name in agencies[:5]:
            if not agency_name:
                continue
            agency_id = _find_or_create_entity(
                kg, er, agency_name, {},
                entity_type="government_agency", country="US",
                sources=["usaspending"], confidence=0.95,
            )
            stats["entities_created"] += 1
            total_amount = raw_data.get("total_amount", 0)
            kg.save_relationship(
                primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                confidence=CONFIDENCE["structured_api"],
                data_source="usaspending",
                evidence=f"Federal contract relationship (${total_amount:,.0f} total obligations)",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- USASpending: extract agency from contract_detail title ----
    if source == "usaspending" and category == "contract_detail":
        # Title format: "Award: $X -- Agency Name"
        agency_match = re.search(r"-- (.+)$", title)
        if agency_match:
            agency_name = agency_match.group(1).strip()
            if agency_name and agency_name != "Unknown":
                agency_id = _find_or_create_entity(
                    kg, er, agency_name, {},
                    entity_type="government_agency", country="US",
                    sources=["usaspending"], confidence=0.9,
                )
                stats["entities_created"] += 1
                # Extract dollar amount from title
                amt_match = re.search(r"\$([0-9,]+)", title)
                amount_str = amt_match.group(1) if amt_match else "?"
                kg.save_relationship(
                    primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                    confidence=CONFIDENCE["structured_api"],
                    data_source="usaspending",
                    evidence=f"Contract award: ${amount_str}",
                    vendor_id=vendor_id,
                )
                stats["relationships_created"] += 1

    # ---- RECAP courts: create court case entities ----
    if source == "recap_courts" and category == "litigation":
        # Two patterns to match:
        # Pattern A (high-risk case listing): "  - Case Name (court, date, docket)"
        cases_a = re.findall(r"- (.+?) \((\w+), (\d{4}-\d{2}-\d{2}), ([^)]+)\)", detail)
        # Pattern B (simpler): "  - Case Name (court, date)"
        if not cases_a:
            cases_a = re.findall(r"- (.+?) \((\w+), (\d{4}-\d{2}-\d{2})", detail)
            cases_a = [(n, c, d, "") for n, c, d in cases_a]

        for case_name, court, date, docket in cases_a[:8]:
            case_name = case_name.strip()[:100]
            if not case_name:
                continue
            ids = {"court": court, "date_filed": date}
            if docket:
                ids["docket_number"] = docket.strip()
            case_eid = _find_or_create_entity(
                kg, er, case_name, ids,
                entity_type="court_case", sources=["recap_courts"],
                confidence=CONFIDENCE["parsed_text"],
            )
            stats["entities_created"] += 1

            sev = finding.get("severity", "info")
            kg.save_relationship(
                primary_entity_id, case_eid, REL_LITIGANT,
                confidence=CONFIDENCE["parsed_text"],
                data_source="recap_courts",
                evidence=f"Court: {court}, Filed: {date}, Severity: {sev}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

        # If there are no structured cases but title mentions docket count,
        # create a summary court entity for the court system
        if not cases_a:
            courts_match = re.search(r"Courts: (.+?)(?:\n|$)", detail)
            if courts_match:
                court_ids = [c.strip() for c in courts_match.group(1).split(",")]
                for court_id in court_ids[:3]:
                    if court_id:
                        court_eid = _find_or_create_entity(
                            kg, er, f"U.S. {court_id.upper()} Court", {"court_id": court_id},
                            entity_type="court_case", sources=["recap_courts"],
                            confidence=CONFIDENCE["inferred_text"],
                        )
                        stats["entities_created"] += 1
                        kg.save_relationship(
                            primary_entity_id, court_eid, REL_LITIGANT,
                            confidence=CONFIDENCE["inferred_text"],
                            data_source="recap_courts",
                            evidence=f"Federal docket(s) in {court_id}",
                            vendor_id=vendor_id,
                        )
                        stats["relationships_created"] += 1

    # ---- Sanctions: create sanctions list entities and link ----
    if category in ("screening", "clearance", "sanctions", "international_debarment",
                     "pep_screening", "foreign_agent") and source in (
        "dod_sam_exclusions", "trade_csl", "un_sanctions", "ofac_sdn",
        "eu_sanctions", "uk_hmt_sanctions", "opensanctions_pep", "worldbank_debarred",
    ):
        severity = finding.get("severity", "info")
        if severity in ("high", "critical", "medium"):
            list_id = _find_or_create_entity(
                kg, er, _sanctions_list_name(source), {"list_id": source},
                entity_type="sanctions_list", sources=[source], confidence=1.0,
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, list_id, REL_SANCTIONED,
                confidence=CONFIDENCE["deterministic"],
                data_source=source,
                evidence=title[:200],
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- Cross-correlation: near-miss alias detection ----
    if source == "cross_correlation" and "near-miss" in title.lower():
        match = re.search(r"Near-miss match: '(.+?)' on", title)
        if match:
            alias_name = match.group(1)
            alias_id = _find_or_create_entity(
                kg, er, alias_name, {},
                entity_type="company", sources=["cross_correlation"],
                confidence=finding.get("confidence", 0.5),
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, alias_id, REL_ALIAS,
                confidence=CONFIDENCE["inferred_text"],
                data_source="cross_correlation",
                evidence=title[:200],
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1

    # ---- SAM.gov: extract registration details ----
    if source == "sam_gov" and category == "registration":
        # SAM registrations confirm the entity exists in federal procurement
        # The entity is already the primary; no new entities to create here
        pass

    # ---- EPA ECHO: environmental facility relationships ----
    if source == "epa_echo" and category == "environmental_compliance":
        # Extract EPA registry IDs from title if present
        epa_match = re.search(r"Registry ID:\s*(\d+)", detail)
        if epa_match:
            # These are facilities, not separate entities
            pass


def _ingest_agency_relationships(kg, er, primary_entity_id: str, vendor_name: str, report: dict, stats: dict):
    """Extract government agency relationships from non-USASpending sources.

    Note: USASpending agency extraction is now handled by _ingest_finding()
    for both 'contracts' and 'contract_detail' categories. This function
    handles FPDS, SAM.gov, and other sources that may reference agencies.
    """
    vendor_id = stats.get("vendor_id", "")
    for finding in report.get("findings", []):
        source = finding.get("source", "")
        # Skip usaspending -- already handled in _ingest_finding
        if source == "usaspending":
            continue

        raw = finding.get("raw_data", {}) or {}
        agencies = raw.get("agencies", [])
        if not agencies:
            continue

        for agency_name in agencies[:3]:
            if not agency_name:
                continue
            agency_id = _find_or_create_entity(
                kg, er, agency_name, {},
                entity_type="government_agency", country="US",
                sources=[source], confidence=0.9,
            )
            stats["entities_created"] += 1
            kg.save_relationship(
                primary_entity_id, agency_id, REL_CONTRACTS_WITH,
                confidence=CONFIDENCE["structured_api"],
                data_source=source,
                evidence=f"Agency relationship via {source}",
                vendor_id=vendor_id,
            )
            stats["relationships_created"] += 1


def _infer_relationships(kg, er, primary_entity_id: str, vendor_name: str, report: dict, stats: dict):
    """Layer 2: Post-processing relationship inference.

    After all entities are created from explicit data, this pass infers
    relationships from co-occurrence patterns and cross-source signals:
      1. News co-mentions: companies named together in media articles
      2. Regulatory co-filing: entities appearing in same SEC filing search
      3. Shared identifiers: entities sharing a common identifier prefix or parent
      4. Cross-domain correlation: entities linked by compound risk patterns
    """
    findings = report.get("findings", [])
    vendor_id = stats.get("vendor_id", "")

    # 1. News co-mentions: extract company names from news headlines
    news_entities = set()
    for f in findings:
        if f.get("source") in ("google_news", "gdelt_media") and f.get("category") == "media":
            t = f.get("title", "")
            # Look for company names in news titles (capitalized multi-word phrases)
            # that aren't the vendor itself
            candidates = re.findall(r"(?:^|\s)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", t)
            for c in candidates:
                c = c.strip()
                if len(c) > 5 and c.upper() != vendor_name.upper():
                    news_entities.add(c)

    for entity_name in list(news_entities)[:5]:
        # Only create relationship if the entity already exists in the graph
        try:
            existing = kg.find_entities_by_name(entity_name, entity_type="company", threshold=0.0)
            for candidate in existing:
                score = er.jaro_winkler(
                    er.normalize_name(entity_name),
                    er.normalize_name(candidate.canonical_name),
                )
                if score >= 0.85 and candidate.id != primary_entity_id:
                    kg.save_relationship(
                        primary_entity_id, candidate.id, REL_MENTIONED_WITH,
                        confidence=CONFIDENCE["news_mention"],
                        data_source="news_co_mention",
                        evidence="Co-mentioned in media coverage",
                        vendor_id=vendor_id,
                    )
                    stats["relationships_created"] += 1
                    break
        except Exception as e:
            logger.warning(f"Relationship inference failed for media co-mention: {e}")

    # 2. Cross-domain correlation: link entities from compound risk findings
    for f in findings:
        if f.get("source") == "cross_correlation" and f.get("category") == "risk_pattern":
            detail = f.get("detail", "")
            # Extract entity names mentioned in cross-domain findings
            # These are already-known entities referenced in compound patterns
            entity_refs = re.findall(r"'([^']+)'", detail)
            for ref in entity_refs:
                if ref and ref.upper() != vendor_name.upper() and len(ref) > 3:
                    try:
                        existing = kg.find_entities_by_name(ref, entity_type="company", threshold=0.0)
                        for candidate in existing:
                            score = er.jaro_winkler(
                                er.normalize_name(ref),
                                er.normalize_name(candidate.canonical_name),
                            )
                            if score >= 0.85 and candidate.id != primary_entity_id:
                                kg.save_relationship(
                                    primary_entity_id, candidate.id, REL_RELATED,
                                    confidence=CONFIDENCE["co_occurrence"],
                                    data_source="cross_correlation",
                                    evidence=f.get("title", "")[:200],
                                    vendor_id=vendor_id,
                                )
                                stats["relationships_created"] += 1
                                break
                    except Exception as e:
                        logger.warning(f"Cross-domain correlation failed: {e}")


def _sanctions_list_name(source: str) -> str:
    """Human-readable name for a sanctions source."""
    names = {
        "dod_sam_exclusions": "SAM.gov Exclusions List",
        "trade_csl": "Consolidated Screening List",
        "un_sanctions": "UN Security Council Sanctions",
        "ofac_sdn": "OFAC SDN List",
        "eu_sanctions": "EU Sanctions List",
        "uk_hmt_sanctions": "UK HMT Sanctions List",
        "opensanctions_pep": "PEP Screening Database",
        "worldbank_debarred": "World Bank Debarment List",
    }
    return names.get(source, source)


_WEAK_GRAPH_NAMES = {
    "",
    "entity",
    "entity name",
    "name",
    "name of entity",
    "name of subsidiary",
    "subsidiary name",
    "unknown",
    "n/a",
    "not available",
    "not applicable",
}


def _is_weak_graph_name(name: str) -> bool:
    """Detect generic or placeholder entity names that should not be shown verbatim."""
    normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
    if normalized in _WEAK_GRAPH_NAMES:
        return True
    if normalized.startswith("entity ") and len(normalized.split()) <= 3:
        return True
    return False


def _infer_graph_entity_type(entity_id: str) -> str:
    """Best-effort entity type inference for legacy relationship endpoints."""
    if not entity_id:
        return "unknown"

    prefix = entity_id.split(":", 1)[0].lower()
    if prefix in {"cik", "lei", "uei", "cage", "duns", "ein", "entity"}:
        return "company"
    if prefix == "person":
        return "person"
    if prefix == "product":
        return "product"
    if prefix == "cve":
        return "cve"
    if prefix == "kev":
        return "kev_entry"
    if prefix == "component":
        return "component"
    if prefix == "subsystem":
        return "subsystem"
    if prefix == "holding_company":
        return "holding_company"
    if prefix == "bank":
        return "bank"
    if prefix == "telecom_provider":
        return "telecom_provider"
    if prefix == "distributor":
        return "distributor"
    if prefix == "facility":
        return "facility"
    if prefix == "shipment_route":
        return "shipment_route"
    if prefix == "service":
        return "service"
    if prefix in {"event", "trade", "show"}:
        return "trade_show_event"
    if prefix in {"court", "case", "docket"}:
        return "court_case"
    if prefix in {"agency", "sam", "fpds"}:
        return "government_agency"
    if prefix in {"ofac", "sdn", "sanction"}:
        return "sanctions_list"
    return "unknown"


def _fallback_graph_label(entity_id: str) -> str:
    """Readable fallback name for graph endpoints missing a persisted entity row."""
    if not entity_id:
        return "Unknown entity"

    prefix, _, raw = entity_id.partition(":")
    if not raw:
        return entity_id

    cleaned = re.sub(r"[_-]+", " ", raw).strip()
    clipped = cleaned[:24] + ("..." if len(cleaned) > 24 else "")

    label_map = {
        "cik": f"CIK {raw}",
        "lei": f"LEI {raw.upper()}",
        "uei": f"UEI {raw.upper()}",
        "cage": f"CAGE {raw.upper()}",
        "duns": f"DUNS {raw}",
        "ein": f"EIN {raw}",
        "person": cleaned or "Person",
        "entity": f"Unresolved company {raw[:12].upper()}",
        "product": cleaned.title() if cleaned else "Product",
        "cve": raw.upper(),
        "kev": f"KEV {raw.upper()}",
        "component": cleaned.title() if cleaned else "Component",
        "subsystem": cleaned.title() if cleaned else "Subsystem",
        "holding_company": cleaned.title() if cleaned else "Holding company",
        "bank": cleaned.title() if cleaned else "Bank",
        "telecom_provider": cleaned.title() if cleaned else "Telecom provider",
        "distributor": cleaned.title() if cleaned else "Distributor",
        "facility": cleaned.title() if cleaned else "Facility",
        "shipment_route": cleaned.title() if cleaned else "Shipment route",
        "service": cleaned.title() if cleaned else "Service",
        "court": cleaned or "Court case",
        "case": cleaned or "Court case",
        "docket": f"Docket {clipped}",
        "agency": cleaned.title() if cleaned else "Government agency",
        "ofac": f"OFAC record {clipped}",
        "sdn": f"SDN record {clipped}",
        "sanction": f"Sanctions record {clipped}",
    }
    return label_map.get(prefix.lower(), f"{prefix.upper()} {clipped}".strip())


def _fallback_graph_identifiers(entity_id: str) -> dict:
    """Derive lightweight identifiers from an identifier-based entity ID."""
    prefix, _, raw = entity_id.partition(":")
    if prefix and raw and prefix.lower() in {"cik", "lei", "uei", "cage", "duns", "ein"}:
        return {prefix.lower(): raw}
    return {}


def _normalize_graph_country(country: str) -> str:
    if not country:
        return ""
    normalized = country.strip()
    if normalized.lower() in {"unknown", "n/a", "not available", "not applicable"}:
        return ""
    return normalized


def _pick_graph_display_name(entity: dict) -> str:
    """Choose the best human-readable label for a graph entity payload."""
    entity_id = entity.get("id", "")
    canonical_name = (entity.get("canonical_name") or "").strip()
    if canonical_name and canonical_name != entity_id and not _is_weak_graph_name(canonical_name):
        return canonical_name

    for alias in entity.get("aliases", []) or []:
        alias = (alias or "").strip()
        if alias and alias != entity_id and not _is_weak_graph_name(alias):
            return alias

    identifiers = entity.get("identifiers") or {}
    for key in ("cik", "lei", "uei", "cage", "duns", "ein"):
        if identifiers.get(key):
            return _fallback_graph_label(f"{key}:{identifiers[key]}")

    sources = set(entity.get("sources", []) or [])
    entity_type = entity.get("entity_type", "unknown")
    if "sec_edgar_ex21" in sources:
        return "Unresolved SEC subsidiary"
    if entity_type == "court_case" or "recap_courts" in sources:
        return "Unresolved court case"
    if entity_type == "government_agency":
        return "Unresolved government agency"
    if entity_type == "person":
        return "Unresolved person"
    if entity_type == "component":
        return "Unresolved component"
    if entity_type == "subsystem":
        return "Unresolved subsystem"
    if entity_type == "holding_company":
        return "Unresolved holding company"
    if entity_type == "bank":
        return "Unresolved bank"
    if entity_type == "telecom_provider":
        return "Unresolved telecom provider"
    if entity_type == "distributor":
        return "Unresolved distributor"
    if entity_type == "facility":
        return "Unresolved facility"
    if entity_type == "shipment_route":
        return "Unresolved shipment route"
    if entity_type == "service":
        return "Unresolved service"
    if entity_type == "sanctions_list" or sources.intersection(
        {"trade_csl", "ofac_sdn", "dod_sam_exclusions", "worldbank_debarred", "un_sanctions"}
    ):
        return "Unresolved sanctions record"

    return _fallback_graph_label(entity_id)


def _normalize_graph_entity_payload(entity: dict) -> dict:
    """Sanitize a graph entity before returning it to the API/UI."""
    normalized = dict(entity)
    normalized["country"] = _normalize_graph_country(entity.get("country", ""))
    normalized["canonical_name"] = _pick_graph_display_name(entity)
    return normalized


def _hydrate_missing_graph_entities(kg, all_entities: dict, relationships: list[dict]) -> dict:
    """
    Close the graph entity set over relationship endpoints.

    Legacy graph rows can reference endpoint IDs that are not present in the
    entity payload. We first hydrate anything that exists in kg_entities, then
    fall back to readable synthetic nodes so the API contract stays whole.
    """
    endpoint_ids = set()
    for rel in relationships:
        source_id = rel.get("source_entity_id", "")
        target_id = rel.get("target_entity_id", "")
        if source_id:
            endpoint_ids.add(source_id)
        if target_id:
            endpoint_ids.add(target_id)

    missing_ids = sorted(endpoint_ids.difference(all_entities.keys()))
    if not missing_ids:
        return all_entities

    hydrated_entities: dict[str, dict] = {}
    try:
        placeholders = ",".join("?" for _ in missing_ids)
        with kg.get_kg_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, last_updated
                FROM kg_entities
                WHERE id IN ({placeholders})
                """,
                missing_ids,
            ).fetchall()
        for row in rows:
            aliases = json.loads(row["aliases"]) if row["aliases"] else []
            identifiers = json.loads(row["identifiers"]) if row["identifiers"] else {}
            sources = json.loads(row["sources"]) if row["sources"] else []
            hydrated_entities[row["id"]] = {
                "id": row["id"],
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"] or _infer_graph_entity_type(row["id"]),
                "aliases": aliases,
                "identifiers": identifiers,
                "country": row["country"] or "",
                "sources": sources,
                "confidence": row["confidence"] if row["confidence"] is not None else 0.5,
                "last_updated": row["last_updated"],
            }
    except Exception as exc:
        logger.debug("Graph entity hydration fallback engaged: %s", exc)

    for entity_id in missing_ids:
        if entity_id in hydrated_entities:
            all_entities[entity_id] = _normalize_graph_entity_payload(hydrated_entities[entity_id])
            continue

        all_entities[entity_id] = _normalize_graph_entity_payload({
            "id": entity_id,
            "canonical_name": _fallback_graph_label(entity_id),
            "entity_type": _infer_graph_entity_type(entity_id),
            "aliases": [],
            "identifiers": _fallback_graph_identifiers(entity_id),
            "country": "",
            "sources": ["graph_fallback"],
            "confidence": 0.35,
            "last_updated": "",
            "synthetic": True,
        })

    return all_entities


def _vendor_root_fallback(vendor_id: str) -> dict | None:
    """Build a stable synthetic vendor root when a case has no graph entities yet."""
    db_mod = _safe_import_db()
    if not db_mod:
        return None

    vendor = db_mod.get_vendor(vendor_id)
    if not vendor:
        return None

    er = _safe_import_er()
    vendor_name = str(vendor.get("name") or vendor_id)
    identifiers = {
        key: value
        for key in ("lei", "cage", "uei", "duns", "ein")
        if (value := vendor.get(key))
    }
    root_entity_id = (
        _generate_graph_entity_id(er, vendor_name, identifiers, "company")
        if er
        else f"vendor:{vendor_id}"
    )

    return _normalize_graph_entity_payload(
        {
            "id": root_entity_id,
            "canonical_name": vendor_name,
            "entity_type": "company",
            "aliases": [],
            "identifiers": identifiers,
            "country": vendor.get("country") or "",
            "sources": ["vendor_record_fallback"],
            "confidence": 0.35,
            "last_updated": vendor.get("updated_at") or "",
            "synthetic": True,
        }
    )


def get_vendor_graph_summary(
    vendor_id: str,
    depth: int = 3,
    *,
    include_provenance: bool = True,
    max_claim_records: int = 4,
    max_evidence_records: int = 4,
) -> dict:
    """
    Get a summary of the knowledge graph for a specific vendor.
    Used by the API to power the graph visualization.
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "knowledge graph unavailable"}

    try:
        depth = max(1, min(int(depth), 4))
        kg.init_kg_db()
        entities = kg.get_vendor_entities(vendor_id)

        if not entities:
            root_entity = _vendor_root_fallback(vendor_id)
            return {
                "vendor_id": vendor_id,
                "graph_depth": depth,
                "root_entity_id": root_entity["id"] if root_entity else None,
                "root_entity_ids": [root_entity["id"]] if root_entity else [],
                "entity_count": 1 if root_entity else 0,
                "relationship_count": 0,
                "entities": [root_entity] if root_entity else [],
                "relationships": [],
            }

        # Get the full network for each entity
        all_entities = {}
        all_relationships = []
        root_entity_id = entities[0].id if entities else None

        for entity in entities:
            network = kg.get_entity_network(
                entity.id,
                depth=depth,
                include_provenance=include_provenance,
                max_claim_records=max_claim_records,
                max_evidence_records=max_evidence_records,
            )
            all_entities.update(network.get("entities", {}))
            all_relationships.extend(network.get("relationships", []))

        unique_rels = _aggregate_graph_relationships(all_relationships)
        if vendor_id and unique_rels and callable(getattr(kg, "attach_relationship_provenance", None)):
            # Even "light" graph reads need vendor-scoped claim hydration before filtering.
            # Otherwise globally deduped entity networks leak stale control edges from older cases.
            needs_scope_hydration = any(not (rel.get("claim_records") or []) for rel in unique_rels)
            if needs_scope_hydration:
                unique_rels = kg.attach_relationship_provenance(
                    unique_rels,
                    max_claim_records=max(1, int(max_claim_records or 1)),
                    max_evidence_records=max(1, int(max_evidence_records or 1)),
                )
        unique_rels = _filter_relationships_to_vendor_claims(unique_rels, vendor_id)
        if not include_provenance:
            for rel in unique_rels:
                rel["claim_records"] = []

        all_entities = _hydrate_missing_graph_entities(kg, all_entities, unique_rels)
        visible_entity_ids = {entity.id for entity in entities}
        for rel in unique_rels:
            source_id = str(rel.get("source_entity_id") or "")
            target_id = str(rel.get("target_entity_id") or "")
            if source_id:
                visible_entity_ids.add(source_id)
            if target_id:
                visible_entity_ids.add(target_id)
        all_entities = {
            entity_id: _normalize_graph_entity_payload(entity)
            for entity_id, entity in all_entities.items()
            if not visible_entity_ids or entity_id in visible_entity_ids
        }

        # Compute entity type distribution
        type_dist = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            type_dist[t] = type_dist.get(t, 0) + 1

        # Compute relationship type distribution
        rel_dist = {}
        for r in unique_rels:
            t = r.get("rel_type", "unknown")
            rel_dist[t] = rel_dist.get(t, 0) + 1

        return {
            "vendor_id": vendor_id,
            "root_entity_id": root_entity_id,
            "root_entity_ids": [entity.id for entity in entities],
            "graph_depth": depth,
            "entity_count": len(all_entities),
            "relationship_count": len(unique_rels),
            "entity_type_distribution": type_dist,
            "relationship_type_distribution": rel_dist,
            "entities": list(all_entities.values()),
            "relationships": unique_rels,
        }

    except Exception as e:
        logger.warning("Graph summary failed for vendor %s: %s", vendor_id, e)
        return {"error": str(e)}


def _aggregate_graph_relationships(all_relationships: list[dict]) -> list[dict]:
    """Collapse duplicate logical edges while preserving corroborating provenance."""
    aggregated: dict[tuple[str, str, str], dict] = {}

    for rel in all_relationships:
        key = (rel["source_entity_id"], rel["target_entity_id"], rel["rel_type"])
        data_source = (rel.get("data_source") or "").strip()
        evidence = (rel.get("evidence") or "").strip()
        created_at = rel.get("created_at") or ""
        first_seen_at = rel.get("first_seen_at") or created_at
        last_seen_at = rel.get("last_seen_at") or created_at
        rel_id = rel.get("id")
        rel_ids = list(rel.get("relationship_ids", []) or [])
        rel_sources = list(rel.get("data_sources", []) or [])
        rel_snippets = list(rel.get("evidence_snippets", []) or [])

        current = aggregated.get(key)
        if current is None:
            current = {
                "id": rel_id,
                "source_entity_id": rel["source_entity_id"],
                "target_entity_id": rel["target_entity_id"],
                "rel_type": rel["rel_type"],
                "confidence": rel.get("confidence", 0.0),
                "data_source": data_source,
                "evidence": evidence,
                "created_at": created_at,
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "corroboration_count": 0,
                "data_sources": [],
                "evidence_snippets": [],
                "claim_records": [],
                "_source_set": set(),
                "_evidence_set": set(),
                "_ids": [],
                "_claim_ids": set(),
            }
            aggregated[key] = current

        current["confidence"] = max(current["confidence"], rel.get("confidence", 0.0))
        if rel_id is not None and rel_id not in current["_ids"]:
            current["_ids"].append(rel_id)
        for existing_id in rel_ids:
            if existing_id is not None and existing_id not in current["_ids"]:
                current["_ids"].append(existing_id)

        if first_seen_at:
            if not current["first_seen_at"] or first_seen_at < current["first_seen_at"]:
                current["first_seen_at"] = first_seen_at
        if last_seen_at:
            if not current["last_seen_at"] or last_seen_at > current["last_seen_at"]:
                current["last_seen_at"] = last_seen_at

        for source_name in [data_source, *rel_sources]:
            if source_name and source_name not in current["_source_set"]:
                current["_source_set"].add(source_name)
                current["data_sources"].append(source_name)

        for snippet in [evidence, *rel_snippets]:
            if snippet and snippet not in current["_evidence_set"]:
                current["_evidence_set"].add(snippet)
                current["evidence_snippets"].append(snippet)

        for claim_record in rel.get("claim_records", []) or []:
            claim_id = claim_record.get("claim_id")
            if claim_id and claim_id in current["_claim_ids"]:
                existing_claim = next(
                    (existing for existing in current["claim_records"] if existing.get("claim_id") == claim_id),
                    None,
                )
                if existing_claim is not None:
                    existing_evidence_ids = {
                        evidence_record.get("evidence_id")
                        for evidence_record in existing_claim.get("evidence_records", [])
                        if evidence_record.get("evidence_id")
                    }
                    for evidence_record in claim_record.get("evidence_records", []) or []:
                        evidence_id = evidence_record.get("evidence_id")
                        if evidence_id and evidence_id in existing_evidence_ids:
                            continue
                        existing_claim.setdefault("evidence_records", []).append(evidence_record)
                        if evidence_id:
                            existing_evidence_ids.add(evidence_id)
                continue
            if claim_id:
                current["_claim_ids"].add(claim_id)
            current["claim_records"].append(claim_record)

    unique_rels: list[dict] = []
    for rel in aggregated.values():
        rel["corroboration_count"] = max(len(rel["data_sources"]), len(rel["_ids"]) or 1)
        rel["data_source"] = rel["data_sources"][0] if rel["data_sources"] else rel.get("data_source", "")
        rel["evidence"] = rel["evidence_snippets"][0] if rel["evidence_snippets"] else rel.get("evidence", "")
        rel["created_at"] = rel["first_seen_at"] or rel.get("created_at", "")
        rel["relationship_ids"] = rel["_ids"]
        rel["evidence_snippets"] = rel["evidence_snippets"][:5]
        rel["data_sources"] = rel["data_sources"][:5]
        rel["claim_records"] = [
            {
                **claim_record,
                "evidence_records": (claim_record.get("evidence_records") or [])[:4],
            }
            for claim_record in rel["claim_records"][:4]
        ]
        rel["evidence_summary"] = _build_relationship_evidence_summary(rel)
        rel.pop("_source_set", None)
        rel.pop("_evidence_set", None)
        rel.pop("_ids", None)
        rel.pop("_claim_ids", None)
        unique_rels.append(rel)

    unique_rels.sort(
        key=lambda rel: (
            rel.get("source_entity_id", ""),
            rel.get("target_entity_id", ""),
            rel.get("rel_type", ""),
        )
    )
    return unique_rels


def _filter_relationships_to_vendor_claims(all_relationships: list[dict], vendor_id: str) -> list[dict]:
    """Restrict case-level graph summaries to claims observed on the current vendor case."""
    if not vendor_id:
        return [dict(rel) for rel in all_relationships]

    filtered: list[dict] = []
    for relationship in all_relationships:
        rel_copy = dict(relationship)
        all_claim_records = [dict(claim_record) for claim_record in (relationship.get("claim_records") or [])]
        claim_records = [
            dict(claim_record)
            for claim_record in all_claim_records
            if str((claim_record or {}).get("vendor_id") or "") == vendor_id
        ]
        if not claim_records:
            if all_claim_records:
                continue
            # Preserve legacy or pre-provenance edges so the graph surface stays whole.
            rel_copy["claim_records"] = []
            rel_copy["legacy_unscoped"] = True
            rel_copy["data_sources"] = list(rel_copy.get("data_sources") or [])
            rel_copy["corroboration_count"] = max(int(rel_copy.get("corroboration_count") or 0), 1)
            rel_copy["evidence_summary"] = _build_relationship_evidence_summary(rel_copy)
            filtered.append(rel_copy)
            continue
        rel_copy["claim_records"] = claim_records
        rel_copy["data_sources"] = sorted(
            {
                str(claim_record.get("data_source") or "").strip()
                for claim_record in claim_records
                if str(claim_record.get("data_source") or "").strip()
            }
        )
        rel_copy["corroboration_count"] = max(len(claim_records), 1)
        rel_copy["first_seen_at"] = min(
            (claim_record.get("first_observed_at") or claim_record.get("observed_at") or "")
            for claim_record in claim_records
        )
        rel_copy["last_seen_at"] = max(
            (claim_record.get("last_observed_at") or claim_record.get("observed_at") or "")
            for claim_record in claim_records
        )
        if not rel_copy.get("data_source"):
            rel_copy["data_source"] = str(claim_records[0].get("data_source") or "")
        rel_copy["evidence_summary"] = _build_relationship_evidence_summary(rel_copy)
        filtered.append(rel_copy)
    return filtered


def _build_relationship_evidence_summary(rel: dict) -> str:
    snippets = [snippet for snippet in rel.get("evidence_snippets", []) if snippet]
    if not snippets:
        return rel.get("evidence", "")

    record_count = max(int(rel.get("corroboration_count") or 1), len(snippets))
    source_count = len(rel.get("data_sources", []))
    source_phrase = _format_graph_source_phrase(rel.get("data_sources", []))
    rel_type = rel.get("rel_type", "")

    if rel_type in {REL_CONTRACTS_WITH, REL_SUBCONTRACTOR, REL_PRIME_CONTRACTOR} and record_count > 1:
        amounts = _extract_evidence_amounts(snippets)
        if amounts:
            total = sum(amounts)
            largest = max(amounts)
            return (
                f"{record_count} award records"
                f"{f' via {source_phrase}' if source_phrase else ''}; "
                f"total {_format_compact_currency(total)}, "
                f"largest {_format_compact_currency(largest)}."
            )
        return (
            f"{record_count} corroborating award records"
            f"{f' via {source_phrase}' if source_phrase else ''}."
        )

    if record_count > 1 and source_count > 1:
        return f"{record_count} corroborating records across {source_count} sources."

    if record_count > 1:
        return f"{record_count} corroborating records support this relationship."

    return snippets[0]


def _extract_evidence_amounts(snippets: list[str]) -> list[float]:
    amounts: list[float] = []
    for snippet in snippets:
        for raw_value in re.findall(r"\$([0-9][0-9,]*(?:\.\d+)?)", snippet):
            try:
                amounts.append(float(raw_value.replace(",", "")))
            except ValueError:
                continue
    return amounts


def _format_compact_currency(amount: float) -> str:
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}K"
    return f"${amount:,.0f}"


def _format_graph_source_phrase(sources: list[str]) -> str:
    if not sources:
        return ""
    source_labels = {
        "usaspending": "USAspending",
        "usaspending_subawards": "USAspending Subawards",
        "sam_subaward_reporting": "SAM Subcontract Reports",
        "fpds_contracts": "FPDS Contracts",
        "sec_edgar": "SEC EDGAR",
        "sec_edgar_ex21": "SEC Exhibit 21",
        "recap_courts": "RECAP Courts",
        "trade_csl": "Trade CSL",
        "ofac_sdn": "OFAC SDN",
        "cross_correlation": "Cross Correlation",
        "news_co_mention": "News Co-Mention",
    }
    cleaned = [
        source_labels.get(source, source.replace("_", " ").replace("-", " ").title())
        for source in sources
    ]
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]}, {cleaned[1]}, and {len(cleaned) - 2} more"


# ---------------------------------------------------------------------------
# Batch backfill: replay all existing enrichment reports into graph
# ---------------------------------------------------------------------------

def backfill_all_vendors() -> dict:
    """
    Replay every stored enrichment report through graph ingestion.
    Call once to seed the knowledge graph from historical data.

    Returns: {vendors_processed, total_entities, total_relationships, errors}
    """
    try:
        import db
    except ImportError:
        return {"error": "db module not available"}

    kg = _safe_import_kg()
    if not kg:
        return {"error": "knowledge graph unavailable"}

    kg.init_kg_db()

    vendors = db.list_vendors()
    total_stats = {
        "vendors_processed": 0,
        "total_entities": 0,
        "total_relationships": 0,
        "errors": [],
    }

    for v in vendors:
        case_id = v.get("id", "")
        name = v.get("name", "")
        if not case_id or not name:
            continue

        try:
            enrichment = db.get_latest_enrichment(case_id)
            if not enrichment:
                logger.debug("No enrichment for %s, skipping backfill", case_id)
                continue

            stats = ingest_enrichment_to_graph(case_id, name, enrichment)
            total_stats["vendors_processed"] += 1
            total_stats["total_entities"] += stats.get("entities_created", 0)
            total_stats["total_relationships"] += stats.get("relationships_created", 0)
            total_stats["errors"].extend(stats.get("errors", []))

            logger.info("Backfilled %s: %d entities, %d rels",
                       name, stats.get("entities_created", 0), stats.get("relationships_created", 0))

        except Exception as e:
            total_stats["errors"].append(f"{case_id}/{name}: {e}")
            logger.warning("Backfill failed for %s: %s", name, e)

    logger.info("Backfill complete: %d vendors, %d entities, %d relationships",
               total_stats["vendors_processed"],
               total_stats["total_entities"],
               total_stats["total_relationships"])

    return total_stats


# ---------------------------------------------------------------------------
# Seed enrichment: lightweight assessment of discovered entities
# ---------------------------------------------------------------------------

SEED_CONNECTORS = ["sam_gov", "sec_edgar", "dod_sam_exclusions", "trade_csl", "ofac_sdn"]


def seed_enrich_entity(entity_name: str, entity_type: str = "company",
                       country: str = "US") -> dict:
    """
    Run a lightweight 'mini-assessment' on a discovered entity
    (subcontractor, related company, etc.) using only 5 core connectors
    instead of the full 28. Feeds results into the knowledge graph.

    Returns: {entity_name, findings_count, identifiers_found, graph_stats}
    """
    try:
        from osint.enrichment import enrich_vendor
    except ImportError:
        return {"error": "enrichment module not available"}

    kg = _safe_import_kg()
    er = _safe_import_er()
    if not kg or not er:
        return {"error": "graph modules unavailable"}

    kg.init_kg_db()

    # Run mini-enrichment with only seed connectors
    report = enrich_vendor(
        vendor_name=entity_name,
        country=country,
        connectors=SEED_CONNECTORS,
        timeout=30,
    )

    # Find or create the entity with discovered identifiers
    identifiers = report.get("identifiers", {})
    entity_id = _find_or_create_entity(
        kg, er, entity_name, identifiers,
        entity_type=entity_type, country=country,
        sources=SEED_CONNECTORS, confidence=0.6,
    )

    # Ingest findings into graph
    findings_count = len(report.get("findings", []))
    for finding in report.get("findings", []):
        try:
            _ingest_finding(kg, er, entity_id, entity_name, finding, {"entities_created": 0, "relationships_created": 0, "errors": []})
        except Exception as e:
            logger.warning(f"Seed enrichment ingestion failed for {entity_name}: {e}")

    return {
        "entity_name": entity_name,
        "entity_id": entity_id,
        "findings_count": findings_count,
        "identifiers_found": list(identifiers.keys()),
        "overall_risk": report.get("overall_risk", "UNKNOWN"),
    }


def seed_enrich_discovered_entities(vendor_id: str, max_entities: int = 10) -> dict:
    """
    For a given assessed vendor, find all discovered entities in the graph
    (subcontractors, related companies) that haven't been enriched yet,
    and run seed enrichment on them.

    Returns: {entities_enriched, results}
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "graph unavailable"}

    kg.init_kg_db()

    # Get all entities linked to this vendor
    entities = kg.get_vendor_entities(vendor_id)
    if not entities:
        return {"entities_enriched": 0, "results": []}

    # Find entities connected to them that have low confidence (not yet enriched)
    candidates = []
    for entity in entities:
        network = kg.get_entity_network(entity.id, depth=1)
        for eid, edata in network.get("entities", {}).items():
            if edata.get("entity_type") == "company" and edata.get("confidence", 1.0) <= 0.75:
                candidates.append(edata)

    # Deduplicate and limit
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique_candidates.append(c)
    unique_candidates = unique_candidates[:max_entities]

    results = []
    for candidate in unique_candidates:
        try:
            result = seed_enrich_entity(
                candidate["canonical_name"],
                entity_type=candidate.get("entity_type", "company"),
                country=candidate.get("country", "US") or "US",
            )
            results.append(result)
        except Exception as e:
            results.append({"entity_name": candidate["canonical_name"], "error": str(e)})

    return {
        "entities_enriched": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Graph-powered workflow: cascade alerts, concentration, pre-populated context
# ---------------------------------------------------------------------------

def check_cascade_risk(vendor_id: str) -> list[dict]:
    """
    Check if any entity in a vendor's network has been flagged.
    Returns cascade alerts for connected entities with adverse findings.

    Use case: A subcontractor gets sanctioned -> alert all primes using them.
    """
    kg = _safe_import_kg()
    if not kg:
        return []

    try:
        kg.init_kg_db()

        entities = kg.get_vendor_entities(vendor_id)
        if not entities:
            return []

        alerts = []
        for entity in entities:
            network = kg.get_entity_network(entity.id, depth=2)

            for rel in network.get("relationships", []):
                target_id = rel["target_entity_id"]
                target = network.get("entities", {}).get(target_id, {})

                if not target:
                    continue

                # Check if the target entity is linked to any vendor with adverse findings
                target_entity = kg.get_entity(target_id)
                if not target_entity:
                    continue

                # Look for sanctions relationships on connected entities
                from knowledge_graph import get_kg_conn
                with get_kg_conn() as conn:
                    sanctions_rels = conn.execute(
                        "SELECT * FROM kg_relationships WHERE source_entity_id = ? AND rel_type = ?",
                        (target_id, REL_SANCTIONED),
                    ).fetchall()

                    if sanctions_rels:
                        alerts.append({
                            "alert_type": "cascade_sanctions",
                            "severity": "high",
                            "vendor_id": vendor_id,
                            "affected_entity": target.get("canonical_name", ""),
                            "relationship_type": rel["rel_type"],
                            "detail": (
                                f"Connected entity '{target.get('canonical_name', '')}' "
                                f"({rel['rel_type']}) has {len(sanctions_rels)} sanctions flag(s). "
                                "Review supply chain exposure."
                            ),
                        })

        return alerts

    except Exception as e:
        logger.warning("Cascade risk check failed for %s: %s", vendor_id, e)
        return []


def get_portfolio_concentration(top_n: int = 10) -> dict:
    """
    Find entities that appear across multiple assessed vendors.
    These are single-points-of-failure in the portfolio.

    Returns: {concentrations: [{entity_name, entity_type, vendor_count, vendors}]}
    """
    kg = _safe_import_kg()
    if not kg:
        return {"error": "graph unavailable"}

    try:
        kg.init_kg_db()

        from knowledge_graph import get_kg_conn
        with get_kg_conn() as conn:
            # Find entities linked to multiple vendors
            rows = conn.execute("""
                SELECT e.id, e.canonical_name, e.entity_type, e.country,
                       COUNT(DISTINCT ev.vendor_id) as vendor_count,
                       GROUP_CONCAT(DISTINCT ev.vendor_id) as vendor_ids
                FROM kg_entities e
                JOIN kg_entity_vendors ev ON e.id = ev.entity_id
                GROUP BY e.id
                HAVING vendor_count >= 2
                ORDER BY vendor_count DESC
                LIMIT ?
            """, (top_n,)).fetchall()

            # Also find entities that are targets of relationships from multiple source entities
            cross_vendor_rows = conn.execute("""
                SELECT e.id, e.canonical_name, e.entity_type,
                       COUNT(DISTINCT r.source_entity_id) as connection_count
                FROM kg_entities e
                JOIN kg_relationships r ON e.id = r.target_entity_id
                WHERE e.entity_type = 'company'
                GROUP BY e.id
                HAVING connection_count >= 2
                ORDER BY connection_count DESC
                LIMIT ?
            """, (top_n,)).fetchall()

        concentrations = []
        seen = set()

        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                concentrations.append({
                    "entity_id": row["id"],
                    "entity_name": row["canonical_name"],
                    "entity_type": row["entity_type"],
                    "country": row["country"],
                    "vendor_count": row["vendor_count"],
                    "vendor_ids": row["vendor_ids"].split(",") if row["vendor_ids"] else [],
                    "concentration_type": "direct_link",
                })

        for row in cross_vendor_rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                concentrations.append({
                    "entity_id": row["id"],
                    "entity_name": row["canonical_name"],
                    "entity_type": row["entity_type"],
                    "connection_count": row["connection_count"],
                    "concentration_type": "relationship_target",
                })

        return {
            "concentration_count": len(concentrations),
            "concentrations": concentrations,
        }

    except Exception as e:
        logger.warning("Concentration analysis failed: %s", e)
        return {"error": str(e)}


def get_pre_populated_context(vendor_name: str) -> dict:
    """
    Check if a vendor (or fuzzy match) already exists in the knowledge graph.
    Returns pre-populated context for new assessments.

    Use case: Analyst starts new assessment, graph shows known history.
    """
    kg = _safe_import_kg()
    er = _safe_import_er()
    if not kg or not er:
        return {"found": False}

    try:
        kg.init_kg_db()

        # Search by name
        candidates = kg.find_entities_by_name(vendor_name, entity_type="company")
        if not candidates:
            return {"found": False, "vendor_name": vendor_name}

        # Find best match
        best = None
        best_score = 0.0
        for c in candidates:
            try:
                score = er.jaro_winkler(
                    er.normalize_name(vendor_name),
                    er.normalize_name(c.canonical_name),
                )
            except Exception as e:
                logger.debug(f"Entity resolution scoring failed: {e}")
                score = 0.0
            if score > best_score:
                best_score = score
                best = c

        if not best or best_score < 0.80:
            return {"found": False, "vendor_name": vendor_name}

        # Get the network
        network = kg.get_entity_network(best.id, depth=1)

        return {
            "found": True,
            "vendor_name": vendor_name,
            "matched_entity": best.canonical_name,
            "match_score": round(best_score, 3),
            "entity_id": best.id,
            "known_identifiers": best.identifiers,
            "known_aliases": best.aliases,
            "country": best.country,
            "sources": best.sources,
            "confidence": best.confidence,
            "last_assessed": best.last_updated,
            "network_size": network.get("entity_count", 0),
            "relationship_count": network.get("relationship_count", 0),
            "connected_entities": [
                {"name": e.get("canonical_name", ""), "type": e.get("entity_type", "")}
                for e in list(network.get("entities", {}).values())[:10]
                if e.get("id") != best.id
            ],
        }

    except Exception as e:
        logger.warning("Pre-populated context failed for '%s': %s", vendor_name, e)
        return {"found": False, "error": str(e)}
