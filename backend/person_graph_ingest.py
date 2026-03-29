"""
Person-to-Graph Ingest Pipeline

Bridges person screening results into the knowledge graph, creating entities
and relationships so that screened persons become first-class nodes in the
entity network. This enables graph-aware export authorization, sanctions
cascade propagation, and visual network analysis.

Ingest triggers:
  - MATCH: Person matched sanctions list -> create person entity + sanctioned_on edge
  - PARTIAL_MATCH: Employer matched -> create person + employer entities + employed_by edge
  - ESCALATE: Deemed export concern -> create person entity + deemed_export_of edge to item
  - CLEAR with foreign national -> create person entity (lightweight, for network context)

New relationship types introduced:
  - employed_by: person -> company (employer affiliation)
  - screened_for: person -> case (screening association)
  - sanctioned_person: person -> sanctions_list (person-level sanctions hit)
  - deemed_export_subject: person -> item/classification (deemed export concern)
  - co_national: person -> person (shared nationality, inferred)

Entity types extended:
  - person (existing, now populated from screening)
  - sanctions_entry (new: specific sanctions list entry)
  - export_item (new: ITAR/EAR classified item or category)

Usage:
    from person_graph_ingest import ingest_person_screening, ingest_batch_screenings

    result = screen_person(name="John Doe", nationalities=["CN"], ...)
    ingest_person_screening(result, case_id="case-123")
"""

import logging
import hashlib
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Relationship types for person screening
# ---------------------------------------------------------------------------
REL_EMPLOYED_BY = "employed_by"
REL_SCREENED_FOR = "screened_for"
REL_SANCTIONED_PERSON = "sanctioned_person"
REL_DEEMED_EXPORT_SUBJECT = "deemed_export_subject"
REL_CO_NATIONAL = "co_national"
REL_NATIONAL_OF = "national_of"

# Confidence levels for person-screening-derived relationships
CONFIDENCE = {
    "sanctions_match": 0.95,       # Direct sanctions list hit
    "employer_match": 0.85,        # Employer matched sanctions/entity list
    "deemed_export": 0.80,         # Regulatory classification match
    "screening_association": 0.90, # Person was screened for this case
    "nationality": 0.99,           # Self-declared nationality
    "co_national_inferred": 0.30,  # Same nationality in same case (weak)
}


# ---------------------------------------------------------------------------
# Safe imports
# ---------------------------------------------------------------------------

def _safe_import_kg():
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        logger.debug("Knowledge graph module not available")
        return None


def _safe_import_er():
    try:
        import entity_resolution as er
        return er
    except ImportError:
        logger.debug("Entity resolution module not available")
        return None


# ---------------------------------------------------------------------------
# Entity ID generation for persons
# ---------------------------------------------------------------------------

def _generate_person_entity_id(name: str, nationalities: list = None) -> str:
    """
    Generate a stable entity ID for a person.
    Uses name + nationalities hash for dedup across screenings.
    """
    normalized = name.strip().upper()
    nat_str = ",".join(sorted(nationalities or []))
    composite = f"{normalized}|{nat_str}"
    hash_val = hashlib.md5(composite.encode()).hexdigest()[:12]
    return f"person:{hash_val}"


def _generate_employer_entity_id(employer: str) -> str:
    """Generate a stable entity ID for an employer/company."""
    normalized = employer.strip().upper()
    hash_val = hashlib.md5(normalized.encode()).hexdigest()[:12]
    return f"entity:{hash_val}"


def _generate_sanctions_entity_id(list_name: str, entity_name: str) -> str:
    """Generate a stable entity ID for a sanctions list entry."""
    composite = f"{list_name}|{entity_name}".upper()
    hash_val = hashlib.md5(composite.encode()).hexdigest()[:12]
    return f"sanctions:{hash_val}"


def _generate_country_entity_id(country_code: str) -> str:
    """Generate a stable entity ID for a country node."""
    return f"country:{country_code.upper()}"


def _link_screening_entities_to_case(case_id: str | None, entity_ids: list[str]) -> None:
    """Attach screening-derived entities to the vendor/case bucket for graph views."""
    if not case_id or not entity_ids:
        return

    kg = _safe_import_kg()
    if not kg:
        return

    seen: set[str] = set()
    for entity_id in entity_ids:
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        try:
            kg.link_entity_to_vendor(entity_id, case_id)
        except Exception as exc:
            logger.debug("Failed to link screening entity %s to case %s: %s", entity_id, case_id, exc)


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------

def ingest_person_screening(screening_result, case_id: Optional[str] = None) -> dict:
    """
    Ingest a person screening result into the knowledge graph.

    Creates:
      - Person entity node (always)
      - Employer entity node + employed_by edge (if employer provided)
      - Sanctions entry node + sanctioned_person edge (if MATCH)
      - Country entity nodes + national_of edges (if nationalities provided)
      - screened_for edge to case (if case_id provided)
      - deemed_export_subject edge (if deemed export flagged)

    Args:
        screening_result: PersonScreeningResult dataclass instance
        case_id: Optional case ID for screened_for relationship

    Returns:
        dict with counts: {entities_created, relationships_created, person_entity_id}
    """
    kg = _safe_import_kg()
    er = _safe_import_er()
    if not kg or not er:
        logger.warning("Knowledge graph or entity resolution not available, skipping person ingest")
        return {"entities_created": 0, "relationships_created": 0, "person_entity_id": None}

    kg.init_kg_db()

    now = datetime.utcnow().isoformat() + "Z"
    entities_created = 0
    relationships_created = 0

    # Extract fields from screening result (handles both dataclass and dict)
    if hasattr(screening_result, 'person_name'):
        name = screening_result.person_name
        nationalities = screening_result.nationalities or []
        employer = screening_result.employer
        status = screening_result.screening_status
        matched_lists = screening_result.matched_lists or []
        deemed_export = screening_result.deemed_export
        screening_id = screening_result.id
    else:
        name = screening_result.get("person_name", "")
        nationalities = screening_result.get("nationalities", [])
        employer = screening_result.get("employer")
        status = screening_result.get("screening_status", "CLEAR")
        matched_lists = screening_result.get("matched_lists", [])
        deemed_export = screening_result.get("deemed_export")
        screening_id = screening_result.get("id", "")
    effective_case_id = case_id or (
        screening_result.case_id if hasattr(screening_result, 'case_id') else screening_result.get("case_id")
    )
    relationship_vendor_id = effective_case_id or ""

    if not name:
        logger.warning("Cannot ingest person screening without a name")
        return {"entities_created": 0, "relationships_created": 0, "person_entity_id": None}

    # -----------------------------------------------------------------------
    # 1. Create person entity
    # -----------------------------------------------------------------------
    person_id = _generate_person_entity_id(name, nationalities)
    linked_entity_ids: list[str] = []

    # Determine confidence based on screening outcome
    person_confidence = 0.5  # baseline
    if status == "MATCH":
        person_confidence = 0.95
    elif status == "PARTIAL_MATCH":
        person_confidence = 0.85
    elif status == "ESCALATE":
        person_confidence = 0.80

    person_entity = er.ResolvedEntity(
        id=person_id,
        canonical_name=name,
        entity_type="person",
        aliases=[],
        identifiers={"screening_id": screening_id, "nationalities": nationalities},
        country=nationalities[0] if nationalities else "",
        sources=["person_screening"],
        confidence=person_confidence,
        last_updated=now,
    )

    try:
        kg.save_entity(person_entity)
        entities_created += 1
        linked_entity_ids.append(person_id)
        logger.info(f"Created/updated person entity: {name} ({person_id})")
    except Exception as e:
        logger.error(f"Failed to save person entity {name}: {e}")
        return {"entities_created": 0, "relationships_created": 0, "person_entity_id": person_id}

    # -----------------------------------------------------------------------
    # 2. Create country nodes + national_of edges
    # -----------------------------------------------------------------------
    for nat_code in nationalities:
        country_id = _generate_country_entity_id(nat_code)
        country_entity = er.ResolvedEntity(
            id=country_id,
            canonical_name=nat_code,
            entity_type="country",
            aliases=[],
            identifiers={"iso_alpha2": nat_code},
            country=nat_code,
            sources=["person_screening"],
            confidence=0.99,
            last_updated=now,
        )
        try:
            kg.save_entity(country_entity)
            entities_created += 1
            linked_entity_ids.append(country_id)
        except Exception:
            pass  # Country may already exist

        try:
            kg.save_relationship(
                source_entity_id=person_id,
                target_entity_id=country_id,
                rel_type=REL_NATIONAL_OF,
                confidence=CONFIDENCE["nationality"],
                data_source="person_screening",
                evidence=f"Declared nationality: {nat_code}",
                vendor_id=relationship_vendor_id,
            )
            relationships_created += 1
        except Exception:
            pass  # Relationship may already exist

    # -----------------------------------------------------------------------
    # 3. Create employer entity + employed_by edge
    # -----------------------------------------------------------------------
    employer_entity_id = None
    if employer:
        employer_entity_id = _generate_employer_entity_id(employer)
        employer_entity = er.ResolvedEntity(
            id=employer_entity_id,
            canonical_name=employer,
            entity_type="company",
            aliases=[],
            identifiers={},
            country="",
            sources=["person_screening"],
            confidence=0.7,
            last_updated=now,
        )
        try:
            kg.save_entity(employer_entity)
            entities_created += 1
            linked_entity_ids.append(employer_entity_id)
        except Exception:
            pass

        try:
            kg.save_relationship(
                source_entity_id=person_id,
                target_entity_id=employer_entity_id,
                rel_type=REL_EMPLOYED_BY,
                confidence=CONFIDENCE["employer_match"] if status == "PARTIAL_MATCH" else 0.70,
                data_source="person_screening",
                evidence=f"{name} employed by {employer}",
                vendor_id=relationship_vendor_id,
            )
            relationships_created += 1
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # 4. Create sanctions entry nodes + sanctioned_person edges (MATCH)
    # -----------------------------------------------------------------------
    if status == "MATCH" and matched_lists:
        for match in matched_lists:
            list_name = match.get("list", "UNKNOWN")
            matched_name = match.get("entity_name", "")
            match_score = match.get("score", 0.0)
            source_uid = match.get("source_uid", "")

            sanctions_id = _generate_sanctions_entity_id(list_name, matched_name)
            sanctions_entity = er.ResolvedEntity(
                id=sanctions_id,
                canonical_name=f"{matched_name} [{list_name}]",
                entity_type="sanctions_list",
                aliases=[matched_name],
                identifiers={"source_uid": source_uid, "list_type": list_name},
                country="",
                sources=["ofac", "person_screening"],
                confidence=0.95,
                last_updated=now,
            )
            try:
                kg.save_entity(sanctions_entity)
                entities_created += 1
                linked_entity_ids.append(sanctions_id)
            except Exception:
                pass

            try:
                kg.save_relationship(
                    source_entity_id=person_id,
                    target_entity_id=sanctions_id,
                    rel_type=REL_SANCTIONED_PERSON,
                    confidence=min(match_score, 1.0),
                    data_source="ofac_screening",
                    evidence=f"Person {name} matched {matched_name} on {list_name} (score: {match_score:.2f})",
                    vendor_id=relationship_vendor_id,
                )
                relationships_created += 1
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 5. Create employer sanctions edges (PARTIAL_MATCH)
    # -----------------------------------------------------------------------
    if status == "PARTIAL_MATCH" and matched_lists and employer_entity_id:
        for match in matched_lists:
            list_name = match.get("list", "UNKNOWN")
            matched_name = match.get("entity_name", "")
            match_score = match.get("score", 0.0)
            source_uid = match.get("source_uid", "")

            sanctions_id = _generate_sanctions_entity_id(list_name, matched_name.replace(" (employer)", ""))
            sanctions_entity = er.ResolvedEntity(
                id=sanctions_id,
                canonical_name=f"{matched_name.replace(' (employer)', '')} [{list_name}]",
                entity_type="sanctions_list",
                aliases=[matched_name.replace(" (employer)", "")],
                identifiers={"source_uid": source_uid, "list_type": list_name},
                country="",
                sources=["ofac", "person_screening"],
                confidence=0.95,
                last_updated=now,
            )
            try:
                kg.save_entity(sanctions_entity)
                entities_created += 1
                linked_entity_ids.append(sanctions_id)
            except Exception:
                pass

            # Link employer to sanctions entry
            try:
                kg.save_relationship(
                    source_entity_id=employer_entity_id,
                    target_entity_id=sanctions_id,
                    rel_type="sanctioned_on",
                    confidence=min(match_score, 1.0),
                    data_source="ofac_screening",
                    evidence=f"Employer {employer} matched {matched_name} on {list_name} (score: {match_score:.2f})",
                    vendor_id=relationship_vendor_id,
                )
                relationships_created += 1
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 6. Create deemed export edges (ESCALATE)
    # -----------------------------------------------------------------------
    if deemed_export and deemed_export.get("required"):
        license_type = deemed_export.get("license_type", "UNKNOWN")
        rationale = deemed_export.get("rationale", "")
        country_group = deemed_export.get("country_group", "")

        # Create an export classification node
        export_item_id = f"export_class:{country_group.lower()}_{license_type.lower()}"
        export_entity = er.ResolvedEntity(
            id=export_item_id,
            canonical_name=f"{license_type} ({country_group})",
            entity_type="export_control",
            aliases=[],
            identifiers={"license_type": license_type, "country_group": country_group},
            country="",
            sources=["deemed_export_eval"],
            confidence=0.90,
            last_updated=now,
        )
        try:
            kg.save_entity(export_entity)
            entities_created += 1
            linked_entity_ids.append(export_item_id)
        except Exception:
            pass

        try:
            kg.save_relationship(
                source_entity_id=person_id,
                target_entity_id=export_item_id,
                rel_type=REL_DEEMED_EXPORT_SUBJECT,
                confidence=CONFIDENCE["deemed_export"],
                data_source="deemed_export_eval",
                evidence=rationale,
                vendor_id=relationship_vendor_id,
            )
            relationships_created += 1
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # 7. Link to case (screened_for)
    # -----------------------------------------------------------------------
    if effective_case_id:
        case_entity_id = f"case:{effective_case_id}"
        # Create case entity if it doesn't exist
        case_entity = er.ResolvedEntity(
            id=case_entity_id,
            canonical_name=f"Case {effective_case_id}",
            entity_type="case",
            aliases=[],
            identifiers={"case_id": effective_case_id},
            country="",
            sources=["person_screening"],
            confidence=1.0,
            last_updated=now,
        )
        try:
            kg.save_entity(case_entity)
            entities_created += 1
            linked_entity_ids.append(case_entity_id)
        except Exception:
            pass

        try:
            kg.save_relationship(
                source_entity_id=person_id,
                target_entity_id=case_entity_id,
                rel_type=REL_SCREENED_FOR,
                confidence=CONFIDENCE["screening_association"],
                data_source="person_screening",
                evidence=f"Screened {name} for case {effective_case_id} (status: {status})",
                vendor_id=relationship_vendor_id,
            )
            relationships_created += 1
        except Exception:
            pass

    _link_screening_entities_to_case(effective_case_id, linked_entity_ids)

    logger.info(
        f"Person graph ingest complete: {name} -> "
        f"{entities_created} entities, {relationships_created} relationships "
        f"(status: {status})"
    )

    return {
        "entities_created": entities_created,
        "relationships_created": relationships_created,
        "person_entity_id": person_id,
        "employer_entity_id": employer_entity_id,
        "screening_status": status,
    }


# ---------------------------------------------------------------------------
# Batch ingest
# ---------------------------------------------------------------------------

def ingest_batch_screenings(
    screening_results: list,
    case_id: Optional[str] = None,
) -> dict:
    """
    Ingest multiple person screening results into the knowledge graph.
    Also detects co-national relationships within the batch.

    Args:
        screening_results: List of PersonScreeningResult instances or dicts
        case_id: Optional case ID for all screenings

    Returns:
        dict with aggregate counts and co-national edges created
    """
    total_entities = 0
    total_relationships = 0
    person_ids = []
    nationality_map = {}  # {nationality: [person_id, ...]}

    for result in screening_results:
        ingest_result = ingest_person_screening(result, case_id=case_id)
        total_entities += ingest_result["entities_created"]
        total_relationships += ingest_result["relationships_created"]

        person_id = ingest_result["person_entity_id"]
        if person_id:
            person_ids.append(person_id)

            # Track nationalities for co-national detection
            nats = result.nationalities if hasattr(result, 'nationalities') else result.get("nationalities", [])
            for nat in (nats or []):
                if nat not in nationality_map:
                    nationality_map[nat] = []
                nationality_map[nat].append(person_id)

    # -----------------------------------------------------------------------
    # Create co-national edges (within batch, same case)
    # -----------------------------------------------------------------------
    kg = _safe_import_kg()
    co_national_edges = 0

    if kg and len(person_ids) > 1:
        for nat_code, pids in nationality_map.items():
            if len(pids) > 1:
                # Create edges between all pairs sharing this nationality
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        try:
                            kg.save_relationship(
                                source_entity_id=pids[i],
                                target_entity_id=pids[j],
                                rel_type=REL_CO_NATIONAL,
                                confidence=CONFIDENCE["co_national_inferred"],
                                data_source="batch_screening",
                                evidence=f"Shared nationality {nat_code} in same screening batch",
                            )
                            co_national_edges += 1
                            total_relationships += 1
                        except Exception:
                            pass

    logger.info(
        f"Batch person graph ingest complete: {len(screening_results)} persons -> "
        f"{total_entities} entities, {total_relationships} relationships, "
        f"{co_national_edges} co-national edges"
    )

    return {
        "persons_ingested": len(screening_results),
        "entities_created": total_entities,
        "relationships_created": total_relationships,
        "co_national_edges": co_national_edges,
        "person_entity_ids": person_ids,
    }


def init_persons_db() -> None:
    """Initialize the underlying person screening storage for retroactive ingest."""
    from person_screening import init_person_screening_db

    init_person_screening_db()


def ingest_persons_for_case(case_id: str) -> dict:
    """
    Replay persisted person screenings for a case into the knowledge graph.

    This powers the retroactive ingest route for cases that were screened
    before person-to-graph ingest was enabled.
    """
    from person_screening import get_case_screenings

    screenings = get_case_screenings(case_id)
    if not screenings:
        return {
            "case_id": case_id,
            "persons_ingested": 0,
            "entities_created": 0,
            "relationships_created": 0,
            "co_national_edges": 0,
            "person_entity_ids": [],
            "details": [],
        }

    result = ingest_batch_screenings(screenings, case_id=case_id)
    details = [
        {
            "screening_id": screening.id,
            "person_name": screening.person_name,
            "screening_status": screening.screening_status,
            "employer": screening.employer,
        }
        for screening in screenings
    ]
    return {
        "case_id": case_id,
        **result,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Graph query helpers for export authorization
# ---------------------------------------------------------------------------

def get_person_network_risk(person_name: str, nationalities: list = None) -> dict:
    """
    Query the knowledge graph for network risk around a screened person.
    Returns connected entities within 2 hops that carry risk signals.

    Used by the export authorization engine to check if a person has
    concerning graph connections even if they personally cleared screening.
    """
    kg = _safe_import_kg()
    if not kg:
        return {"risk_signals": [], "network_risk_level": "UNKNOWN"}

    person_id = _generate_person_entity_id(person_name, nationalities)

    try:
        network = kg.get_entity_network(person_id, depth=2)
    except Exception as e:
        logger.error(f"Failed to get person network: {e}")
        return {"risk_signals": [], "network_risk_level": "UNKNOWN"}

    if not network or network.get("entity_count", 0) == 0:
        return {"risk_signals": [], "network_risk_level": "CLEAR", "person_entity_id": person_id}

    # Analyze network for risk signals
    risk_signals = []

    for eid, entity in network.get("entities", {}).items():
        if eid == person_id:
            continue

        entity_type = entity.get("entity_type", "")
        entity_name = entity.get("canonical_name", "")

        # Sanctions list connections = critical risk
        if entity_type == "sanctions_list":
            risk_signals.append({
                "signal": "SANCTIONS_CONNECTION",
                "severity": "CRITICAL",
                "entity_id": eid,
                "entity_name": entity_name,
                "description": f"Connected to sanctions entry: {entity_name}",
            })

        # Export control connections = high risk
        elif entity_type == "export_control":
            risk_signals.append({
                "signal": "EXPORT_CONTROL_CONNECTION",
                "severity": "HIGH",
                "entity_id": eid,
                "entity_name": entity_name,
                "description": f"Connected to export control: {entity_name}",
            })

        # High-confidence company with sanctions link
        elif entity_type == "company" and entity.get("confidence", 0) >= 0.85:
            # Check if this company has sanctions relationships
            for rel in network.get("relationships", []):
                if (rel.get("source_entity_id") == eid or rel.get("target_entity_id") == eid):
                    if rel.get("rel_type") in ("sanctioned_on", REL_SANCTIONED_PERSON):
                        risk_signals.append({
                            "signal": "EMPLOYER_SANCTIONS_LINK",
                            "severity": "HIGH",
                            "entity_id": eid,
                            "entity_name": entity_name,
                            "description": f"Employer {entity_name} has sanctions connections",
                        })
                        break

    # Classify overall network risk
    severities = [s["severity"] for s in risk_signals]
    if "CRITICAL" in severities:
        network_risk_level = "CRITICAL"
    elif "HIGH" in severities:
        network_risk_level = "HIGH"
    elif len(risk_signals) > 0:
        network_risk_level = "MEDIUM"
    else:
        network_risk_level = "CLEAR"

    return {
        "person_entity_id": person_id,
        "risk_signals": risk_signals,
        "network_risk_level": network_risk_level,
        "network_size": network.get("entity_count", 0),
        "relationship_count": network.get("relationship_count", 0),
    }
