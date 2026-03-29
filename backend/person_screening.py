#!/usr/bin/env python3
"""
Person/POI Screening Service for Xiphos.

Screens individuals against sanctions lists with deemed export evaluation
for ITAR/EAR controlled items.

Integrates with:
  - ofac.screen_name() for sanctions matching
  - Deemed export rules for USML/EAR items
  - Country group classification (ITAR Prohibited, Terrorist Designations, etc.)

Schema:
  person_screenings table:
    - id TEXT PK (ps-<uuid8>)
    - case_id TEXT FK nullable
    - person_name TEXT NOT NULL
    - nationalities JSON nullable (["US", "CN"])
    - employer TEXT nullable
    - screening_status TEXT (CLEAR, MATCH, PARTIAL_MATCH, ESCALATE)
    - matched_lists JSON nullable ([{list, entity_name, score, source_uid}])
    - composite_score REAL NOT NULL
    - deemed_export JSON nullable ({required: bool, license_type, rationale})
    - recommended_action TEXT NOT NULL
    - screened_by TEXT NOT NULL
    - created_at TEXT NOT NULL

Usage:
    from person_screening import screen_person, screen_person_batch, init_person_screening_db

    init_person_screening_db()
    result = screen_person(
        name="John Doe",
        nationalities=["CN"],
        employer="Huawei",
        item_classification="USML-Aircraft",
        case_id="case-123"
    )
    print(result.screening_status, result.recommended_action)
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from ofac import screen_name
from db import get_conn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ITAR prohibited countries (absolute ban)
ITAR_PROHIBITED_COUNTRIES = {"CU", "IR", "KP", "SY"}

# High-scrutiny countries (license likely required)
HIGH_SCRUTINY = {"CN", "RU", "BY", "VE", "MM", "AF"}

# Terrorist designations & regimes of concern
TERRORIST_DESIGNATIONS = {"IR", "SY", "KP", "CU"}

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class PersonScreeningResult:
    """Result of screening a person/POI."""
    id: str                                      # ps-<uuid8>
    case_id: Optional[str]                       # nullable FK
    person_name: str
    nationalities: list[str] = field(default_factory=list)
    employer: Optional[str] = None
    screening_status: str = "CLEAR"              # CLEAR, MATCH, PARTIAL_MATCH, ESCALATE
    matched_lists: list[dict] = field(default_factory=list)  # [{list, entity_name, score, source_uid}]
    composite_score: float = 0.0
    deemed_export: Optional[dict] = None         # {required: bool, license_type, rationale, country_group}
    recommended_action: str = "CLEAR TO PROCEED"
    screened_by: str = "system"
    created_at: str = ""


# ---------------------------------------------------------------------------
# Database Layer
# ---------------------------------------------------------------------------

def init_person_screening_db():
    """Create person_screenings table on first use."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS person_screenings (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                person_name TEXT NOT NULL,
                nationalities TEXT DEFAULT '[]',
                employer TEXT,
                screening_status TEXT NOT NULL CHECK(
                    screening_status IN ('CLEAR', 'MATCH', 'PARTIAL_MATCH', 'ESCALATE')
                ),
                matched_lists TEXT DEFAULT '[]',
                composite_score REAL NOT NULL,
                deemed_export TEXT,
                recommended_action TEXT NOT NULL,
                screened_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_person_case ON person_screenings(case_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_person_status ON person_screenings(screening_status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_person_name ON person_screenings(person_name)
        """)


def _save_person_screening(result: PersonScreeningResult):
    """Persist screening result to database."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO person_screenings (
                id, case_id, person_name, nationalities, employer,
                screening_status, matched_lists, composite_score,
                deemed_export, recommended_action, screened_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.id,
            result.case_id,
            result.person_name,
            json.dumps(result.nationalities),
            result.employer,
            result.screening_status,
            json.dumps(result.matched_lists),
            result.composite_score,
            json.dumps(result.deemed_export) if result.deemed_export else None,
            result.recommended_action,
            result.screened_by,
            result.created_at,
        ))


# ---------------------------------------------------------------------------
# Screening Logic
# ---------------------------------------------------------------------------

def _evaluate_deemed_export(
    nationalities: list[str],
    item_classification: Optional[str] = None,
) -> Optional[dict]:
    """
    Evaluate deemed export implications based on nationality and item classification.

    Returns dict with:
      {
        "required": bool,
        "license_type": str,  # PROHIBITED, LICENSE_REQUIRED, LOW_RISK, etc.
        "rationale": str,
        "country_group": str
      }

    Or None if no deemed export concern.
    """
    if not nationalities:
        return None

    item_class = (item_classification or "").upper()

    # Check for absolute prohibitions
    prohibited_nationals = [n for n in nationalities if n in ITAR_PROHIBITED_COUNTRIES]
    if prohibited_nationals and ("USML" in item_class or "ITAR" in item_class):
        return {
            "required": True,
            "license_type": "PROHIBITED",
            "rationale": f"Foreign national from {prohibited_nationals[0]} with ITAR item is absolute deemed export",
            "country_group": "ITAR_PROHIBITED",
        }

    # Check for terrorist designations
    terrorist_nationals = [n for n in nationalities if n in TERRORIST_DESIGNATIONS]
    if terrorist_nationals:
        return {
            "required": True,
            "license_type": "PROHIBITED",
            "rationale": f"Foreign national from designated state {terrorist_nationals[0]}",
            "country_group": "TERRORIST_DESIGNATION",
        }

    # Check for USML items + foreign national
    if "USML" in item_class:
        # Any foreign national accessing USML = deemed export
        return {
            "required": True,
            "license_type": "DEEMED_EXPORT",
            "rationale": "Access to USML-controlled items by foreign national constitutes deemed export",
            "country_group": "ALL_FOREIGN",
        }

    # Check for high-scrutiny countries with USML/specific ECCN
    high_scrutiny_nationals = [n for n in nationalities if n in HIGH_SCRUTINY]
    if high_scrutiny_nationals:
        if "USML" in item_class:
            return {
                "required": True,
                "license_type": "LICENSE_LIKELY_REQUIRED",
                "rationale": f"Foreign national from high-scrutiny country {high_scrutiny_nationals[0]} with USML item",
                "country_group": "HIGH_SCRUTINY",
            }
        if item_class and "EAR99" not in item_class and "EAR" in item_class:
            return {
                "required": True,
                "license_type": "LICENSE_LIKELY_REQUIRED",
                "rationale": f"Foreign national from high-scrutiny country {high_scrutiny_nationals[0]} with EAR-controlled item",
                "country_group": "HIGH_SCRUTINY",
            }

    # EAR99 = no deemed export concern
    if item_class == "EAR99":
        return None

    # Generic foreign national without specific restrictions
    if len(nationalities) > 0 and not all(n == "US" for n in nationalities):
        return {
            "required": False,
            "license_type": "STANDARD_REVIEW",
            "rationale": "Foreign national requires standard deemed export review",
            "country_group": "OTHER_FOREIGN",
        }

    return None


def screen_person(
    name: str,
    nationalities: Optional[list[str]] = None,
    employer: Optional[str] = None,
    item_classification: Optional[str] = None,
    access_level: Optional[str] = None,
    case_id: Optional[str] = None,
    screened_by: str = "system",
) -> PersonScreeningResult:
    """
    Screen a person against sanctions lists with deemed export evaluation.

    Args:
        name: Person's name
        nationalities: List of nationality codes (["US"], ["CN", "HK"])
        employer: Organization they work for
        item_classification: Item type (USML-Aircraft, EAR-7A994, EAR99, etc.)
        access_level: Access classification (SECRET, CONFIDENTIAL, UNCLASSIFIED)
        case_id: Optional case identifier for grouping
        screened_by: User/system doing the screening

    Returns:
        PersonScreeningResult with detailed screening decision
    """
    nationalities = nationalities or []
    result = PersonScreeningResult(
        id=f"ps-{uuid.uuid4().hex[:8]}",
        case_id=case_id,
        person_name=name,
        nationalities=nationalities,
        employer=employer,
        screened_by=screened_by,
        created_at=datetime.utcnow().isoformat(),
    )

    # Screen person name against sanctions
    person_screening = screen_name(name)
    if person_screening.matched:
        result.matched_lists.append({
            "list": person_screening.matched_entry.list_type if person_screening.matched_entry else "UNKNOWN",
            "entity_name": person_screening.matched_name,
            "score": person_screening.best_score,
            "source_uid": person_screening.matched_entry.uid if person_screening.matched_entry else "",
        })
        result.composite_score = person_screening.best_score
        result.screening_status = "MATCH"
        result.recommended_action = f"SANCTIONS MATCH: {person_screening.matched_name} (score: {person_screening.best_score:.2f})"
        _save_person_screening(result)
        return result

    # Screen employer if provided
    if employer:
        employer_screening = screen_name(employer)
        if employer_screening.matched:
            result.matched_lists.append({
                "list": employer_screening.matched_entry.list_type if employer_screening.matched_entry else "UNKNOWN",
                "entity_name": f"{employer_screening.matched_name} (employer)",
                "score": employer_screening.best_score,
                "source_uid": employer_screening.matched_entry.uid if employer_screening.matched_entry else "",
            })
            result.composite_score = employer_screening.best_score
            result.screening_status = "PARTIAL_MATCH"
            result.recommended_action = f"EMPLOYER MATCH: {employer_screening.matched_name} (escalate for affiliation review)"
            _save_person_screening(result)
            return result

    # Evaluate deemed export
    deemed = _evaluate_deemed_export(nationalities, item_classification)
    if deemed:
        result.deemed_export = deemed
        if deemed["license_type"] in ("PROHIBITED", "LIKELY_PROHIBITED"):
            result.screening_status = "ESCALATE"
            result.recommended_action = f"PROHIBITED: {deemed['rationale']}"
            result.composite_score = 1.0
        elif deemed["license_type"] in ("LICENSE_REQUIRED", "LICENSE_LIKELY_REQUIRED"):
            result.screening_status = "ESCALATE"
            result.recommended_action = f"LICENSE REQUIRED: {deemed['rationale']}"
            result.composite_score = 0.85
        else:
            result.screening_status = "CLEAR"
            result.recommended_action = "CLEAR (deemed export review required)"
            result.composite_score = 0.3

    # Default clear if no sanctions match and no export concern
    if not result.matched_lists and not deemed:
        result.screening_status = "CLEAR"
        result.recommended_action = "CLEAR TO PROCEED"
        result.composite_score = 0.0

    _save_person_screening(result)
    return result


def screen_person_batch(
    persons: list[dict],
    screened_by: str = "system",
) -> list[PersonScreeningResult]:
    """
    Screen multiple persons in a batch operation (max 50).

    Args:
        persons: List of dicts with keys: name, nationalities, employer, item_classification, case_id
        screened_by: User/system doing the screening

    Returns:
        List of PersonScreeningResult objects
    """
    if len(persons) > 50:
        raise ValueError("Batch screening limited to 50 persons")

    results = []
    for person in persons:
        result = screen_person(
            name=person.get("name", ""),
            nationalities=person.get("nationalities"),
            employer=person.get("employer"),
            item_classification=person.get("item_classification"),
            access_level=person.get("access_level"),
            case_id=person.get("case_id"),
            screened_by=screened_by,
        )
        results.append(result)

    return results


def get_case_screenings(case_id: str) -> list[PersonScreeningResult]:
    """Get all person screenings for a case."""
    init_person_screening_db()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM person_screenings WHERE case_id = ? ORDER BY created_at DESC
        """, (case_id,)).fetchall()

        results = []
        for row in rows:
            result = PersonScreeningResult(
                id=row["id"],
                case_id=row["case_id"],
                person_name=row["person_name"],
                nationalities=json.loads(row["nationalities"] or "[]"),
                employer=row["employer"],
                screening_status=row["screening_status"],
                matched_lists=json.loads(row["matched_lists"] or "[]"),
                composite_score=row["composite_score"],
                deemed_export=json.loads(row["deemed_export"]) if row["deemed_export"] else None,
                recommended_action=row["recommended_action"],
                screened_by=row["screened_by"],
                created_at=row["created_at"],
            )
            results.append(result)

        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for testing."""
    import argparse
    parser = argparse.ArgumentParser(description="Person screening")
    parser.add_argument("name", help="Person name")
    parser.add_argument("--nationalities", default="", help="Comma-separated countries (CN,RU)")
    parser.add_argument("--employer", help="Employer name")
    parser.add_argument("--item-classification", help="USML-Aircraft, EAR99, etc.")
    args = parser.parse_args()

    init_person_screening_db()
    nationalities = [c.strip().upper() for c in args.nationalities.split(",") if c.strip()]

    result = screen_person(
        name=args.name,
        nationalities=nationalities or None,
        employer=args.employer,
        item_classification=args.item_classification,
    )

    print(f"Status: {result.screening_status}")
    print(f"Recommendation: {result.recommended_action}")
    print(f"Composite Score: {result.composite_score:.2f}")
    if result.matched_lists:
        print(f"Matches: {result.matched_lists}")
    if result.deemed_export:
        print(f"Deemed Export: {result.deemed_export}")


if __name__ == "__main__":
    main()
