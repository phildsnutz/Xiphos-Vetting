"""
CVE/KEV to Knowledge Graph Pipeline.

Ingests CISA KEV findings and NVD CVE data from enrichment results into the
knowledge graph as entities and relationships. Creates CVE, product, and KEV
entities with proper risk level propagation.

Pattern: enrichment findings -> graph entities -> network risk signals
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from typing import Any

try:
    from knowledge_graph import get_kg_conn, init_kg_db
    HAS_KG = True
except ImportError:
    HAS_KG = False


def _safe_import_er():
    try:
        import entity_resolution as er
        return er
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Deterministic ID Generation
# ---------------------------------------------------------------------------

def _make_cve_id(cve_number: str) -> str:
    """Generate deterministic CVE entity ID."""
    normalized = cve_number.strip().upper()
    if not normalized.startswith("CVE-"):
        normalized = f"CVE-{normalized}"
    return f"cve:{normalized}"


def _make_product_id(vendor_name: str, product_name: str) -> str:
    """Generate deterministic product entity ID."""
    key = f"{vendor_name}|{product_name}".lower().strip()
    hash_suffix = hashlib.md5(key.encode()).hexdigest()[:8]
    clean_product = product_name.lower().replace(" ", "_").replace("/", "_")
    return f"product:{clean_product}_{hash_suffix}"


def _make_kev_id(cve_number: str) -> str:
    """Generate deterministic KEV entry entity ID."""
    normalized = cve_number.strip().upper()
    if not normalized.startswith("CVE-"):
        normalized = f"CVE-{normalized}"
    return f"kev:{normalized}"


def _slugify_entity_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return cleaned or fallback


def _make_component_id(vendor_name: str, component_name: str) -> str:
    """Generate deterministic component entity ID."""
    key = f"{vendor_name}|{component_name}".lower().strip()
    hash_suffix = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"component:{_slugify_entity_name(component_name, 'component')}_{hash_suffix}"


def _make_subsystem_id(subsystem_name: str, platform_name: str = "") -> str:
    """Generate deterministic subsystem entity ID."""
    key = f"{platform_name}|{subsystem_name}".lower().strip()
    hash_suffix = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"subsystem:{_slugify_entity_name(platform_name + ' ' + subsystem_name, 'subsystem')}_{hash_suffix}"


def _make_holding_company_id(company_name: str) -> str:
    """Generate deterministic holding-company entity ID."""
    key = company_name.lower().strip()
    hash_suffix = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"holding_company:{_slugify_entity_name(company_name, 'holding_company')}_{hash_suffix}"


def _resolve_vendor_company_entity_id(conn, vendor_name: str) -> str:
    """
    Resolve the canonical company entity for a vendor.

    Prefer an existing company node whose canonical name or alias matches the
    supplied vendor name. If no match exists, create one using the canonical
    entity-resolution ID model instead of minting a separate company:* ID.
    """
    vendor_name = (vendor_name or "").strip()
    if not vendor_name:
        return ""

    er = _safe_import_er()
    if er is None:
        raise RuntimeError("entity_resolution module unavailable")

    requested_norm = er.normalize_name(vendor_name)
    best_match_id = ""
    best_match_score = 0.0

    rows = conn.execute(
        """
        SELECT id, canonical_name, aliases, confidence
        FROM kg_entities
        WHERE entity_type = 'company'
        """
    ).fetchall()

    for row in rows:
        canonical_name = row["canonical_name"] or ""
        canonical_norm = er.normalize_name(canonical_name)
        if canonical_norm == requested_norm:
            return row["id"]

        try:
            aliases = json.loads(row["aliases"] or "[]")
        except Exception:
            aliases = []

        for alias in aliases:
            if not alias:
                continue
            if er.normalize_name(str(alias)) == requested_norm:
                return row["id"]

        score = er.jaro_winkler(requested_norm, canonical_norm)
        if score > best_match_score:
            best_match_id = row["id"]
            best_match_score = score

        for alias in aliases:
            alias_norm = er.normalize_name(str(alias))
            alias_score = er.jaro_winkler(requested_norm, alias_norm)
            if alias_score > best_match_score:
                best_match_id = row["id"]
                best_match_score = alias_score

    if best_match_id and best_match_score >= 0.92:
        return best_match_id

    vendor_entity_id = er.generate_entity_id(vendor_name, {})
    company_entity = er.ResolvedEntity(
        id=vendor_entity_id,
        canonical_name=vendor_name,
        entity_type="company",
        aliases=[],
        identifiers={},
        country="",
        sources=["cyber_graph_ingest"],
        confidence=0.7,
        last_updated=datetime.now().isoformat(),
    )
    conn.execute("""
        INSERT INTO kg_entities
            (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, risk_level, sanctions_exposure, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            canonical_name = excluded.canonical_name,
            entity_type = excluded.entity_type,
            confidence = MAX(excluded.confidence, kg_entities.confidence),
            last_updated = excluded.last_updated
    """, (
        company_entity.id,
        company_entity.canonical_name,
        company_entity.entity_type,
        json.dumps(company_entity.aliases),
        json.dumps(company_entity.identifiers),
        company_entity.country,
        json.dumps(company_entity.sources),
        company_entity.confidence,
        "unknown",
        0.0,
        company_entity.last_updated,
    ))
    return vendor_entity_id


def _upsert_typed_entity(
    conn,
    entity_id: str,
    canonical_name: str,
    entity_type: str,
    *,
    confidence: float = 0.7,
    risk_level: str = "unknown",
    country: str = "",
    sources: list[str] | None = None,
    identifiers: dict[str, Any] | None = None,
) -> None:
    """Create or refresh a typed graph entity without relying on type-blind IDs."""
    sources = sources or []
    identifiers = identifiers or {}
    conn.execute(
        """
        INSERT INTO kg_entities
            (id, canonical_name, entity_type, aliases, identifiers, country, sources, confidence, risk_level, sanctions_exposure, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            canonical_name = COALESCE(NULLIF(excluded.canonical_name, ''), kg_entities.canonical_name),
            entity_type = excluded.entity_type,
            country = CASE
                WHEN excluded.country IS NOT NULL AND excluded.country != '' THEN excluded.country
                ELSE kg_entities.country
            END,
            confidence = MAX(excluded.confidence, kg_entities.confidence),
            risk_level = CASE
                WHEN excluded.risk_level IS NOT NULL AND excluded.risk_level != '' AND excluded.risk_level != 'unknown'
                    THEN excluded.risk_level
                ELSE kg_entities.risk_level
            END,
            sources = CASE
                WHEN excluded.sources IS NOT NULL AND excluded.sources != '[]' THEN excluded.sources
                ELSE kg_entities.sources
            END,
            last_updated = excluded.last_updated
        """,
        (
            entity_id,
            canonical_name,
            entity_type,
            json.dumps([]),
            json.dumps(identifiers),
            country or "",
            json.dumps(sorted(set(sources))),
            float(confidence or 0.0),
            (risk_level or "unknown").lower(),
            0.0,
            datetime.now().isoformat(),
        ),
    )


def _create_relationship(
    conn,
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    *,
    confidence: float,
    data_source: str,
    evidence: str = "",
) -> bool:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO kg_relationships
            (source_entity_id, target_entity_id, rel_type, confidence, data_source, evidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_entity_id,
            target_entity_id,
            rel_type,
            float(confidence or 0.0),
            data_source,
            evidence,
        ),
    )
    return cursor.rowcount > 0


def _make_country_id(country_code: str) -> str:
    return f"country:{(country_code or '').strip().upper()}"


def _make_person_id(person_name: str) -> str:
    normalized = (person_name or "").strip().upper()
    hash_val = hashlib.md5(normalized.encode()).hexdigest()[:12]
    return f"person:{hash_val}"


def _resolve_beneficial_owner_node(
    conn,
    owner_name: str,
    owner_type: str,
    *,
    confidence: float,
    data_source: str,
    country: str = "",
) -> tuple[str, str]:
    normalized_type = (owner_type or "company").strip().lower()
    if normalized_type == "holding_company":
        entity_id = _make_holding_company_id(owner_name)
        _upsert_typed_entity(
            conn,
            entity_id,
            owner_name,
            "holding_company",
            confidence=confidence,
            country=country,
            sources=[data_source],
        )
        return entity_id, "holding_company"

    if normalized_type == "country":
        entity_id = _make_country_id(owner_name)
        _upsert_typed_entity(
            conn,
            entity_id,
            (owner_name or "").strip().upper(),
            "country",
            confidence=1.0,
            country=(owner_name or "").strip().upper(),
            sources=[data_source],
        )
        return entity_id, "country"

    if normalized_type == "person":
        entity_id = _make_person_id(owner_name)
        _upsert_typed_entity(
            conn,
            entity_id,
            owner_name,
            "person",
            confidence=confidence,
            country=country,
            sources=[data_source],
        )
        return entity_id, "person"

    entity_id = _resolve_vendor_company_entity_id(conn, owner_name)
    _upsert_typed_entity(
        conn,
        entity_id,
        owner_name,
        "company",
        confidence=confidence,
        country=country,
        sources=[data_source],
    )
    return entity_id, "company"


def _link_entities_to_case(case_id: str, entity_ids: set[str]) -> int:
    if not case_id or not entity_ids:
        return 0

    linked = 0
    with get_kg_conn() as conn:
        for entity_id in entity_ids:
            existing = conn.execute(
                "SELECT 1 FROM kg_entity_vendors WHERE entity_id = ? AND vendor_id = ?",
                (entity_id, case_id),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO kg_entity_vendors (entity_id, vendor_id, linked_at)
                VALUES (?, ?, ?)
                """,
                (entity_id, case_id, datetime.now().isoformat()),
            )
            linked += 1
    return linked


# ---------------------------------------------------------------------------
# Entity Ingest Functions
# ---------------------------------------------------------------------------

def ingest_cve_findings(
    case_id: str,
    vendor_name: str,
    enrichment_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Ingest CVE findings from enrichment results into the knowledge graph.

    Creates CVE entities and relationships linking them to vendors and products.
    Assigns risk levels based on CVSS scores.

    Args:
        case_id: Case ID for context
        vendor_name: Vendor/company name
        enrichment_findings: List of findings from cisa_kev.py or similar

    Returns:
        Summary dict with created_cves, created_relationships, errors
    """
    if not HAS_KG:
        return {
            "status": "skipped",
            "reason": "knowledge_graph module not available",
            "created_cves": 0,
            "created_relationships": 0,
            "errors": [],
        }

    summary = {
        "case_id": case_id,
        "vendor_name": vendor_name,
        "created_cves": 0,
        "created_relationships": 0,
        "created_products": 0,
        "errors": [],
    }

    if not enrichment_findings:
        return summary

    try:
        init_kg_db()
    except Exception as e:
        summary["errors"].append(f"Failed to init KG DB: {str(e)}")
        return summary

    with get_kg_conn() as conn:
        # Extract CVE metadata from findings
        cves_to_ingest: list[dict[str, Any]] = []

        for finding in enrichment_findings:
            if not isinstance(finding, dict):
                continue

            # Look for CVE ID in finding title or detail
            title = str(finding.get("title") or "")
            detail = str(finding.get("detail") or "")
            cve_id = None

            # Try to extract CVE-XXXX-XXXXX pattern
            import re
            match = re.search(r"CVE-\d{4}-\d{4,7}", title + " " + detail)
            if match:
                cve_id = match.group(0)

            if not cve_id:
                continue

            severity = finding.get("severity", "medium")
            confidence = finding.get("confidence", 0.7)

            cves_to_ingest.append({
                "cve_id": cve_id,
                "title": title,
                "detail": detail,
                "severity": severity,
                "confidence": confidence,
            })

        # Insert CVE entities
        for cve_data in cves_to_ingest:
            cve_id = _make_cve_id(cve_data["cve_id"])
            severity = cve_data.get("severity", "medium").lower()

            # Assign risk_level based on severity
            # In real scenario, would use CVSS; here we use finding severity
            risk_level_map = {
                "critical": "critical",
                "high": "high",
                "medium": "medium",
                "low": "low",
                "info": "low",
            }
            risk_level = risk_level_map.get(severity, "unknown")

            try:
                conn.execute("""
                    INSERT INTO kg_entities
                        (id, canonical_name, entity_type, country, confidence,
                         risk_level, sanctions_exposure, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        risk_level = MAX(excluded.risk_level, risk_level),
                        last_updated = excluded.last_updated,
                        confidence = MAX(excluded.confidence, confidence)
                """, (
                    cve_id,
                    cve_data["cve_id"],
                    "cve",
                    "",
                    cve_data.get("confidence", 0.7),
                    risk_level,
                    0.0,
                    datetime.now().isoformat(),
                ))
                summary["created_cves"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to insert CVE {cve_data['cve_id']}: {str(e)}")
                continue

            # Create relationship: vendor -> has_vulnerability -> CVE
            vendor_entity_id = _resolve_vendor_company_entity_id(conn, vendor_name)
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO kg_relationships
                        (source_entity_id, target_entity_id, rel_type, confidence, data_source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    vendor_entity_id,
                    cve_id,
                    "has_vulnerability",
                    cve_data.get("confidence", 0.7),
                    "cyber_graph_ingest",
                ))
                summary["created_relationships"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to create relationship for {cve_data['cve_id']}: {str(e)}")

    return summary


def ingest_nvd_overlay(
    case_id: str,
    vendor_name: str,
    nvd_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Ingest NVD overlay summary data into the knowledge graph.

    Creates product entities and links them to CVEs with risk propagation.

    Args:
        case_id: Case ID for context
        vendor_name: Vendor/company name
        nvd_summary: Summary dict from nvd_overlay.py

    Returns:
        Summary dict with created resources and errors
    """
    if not HAS_KG:
        return {
            "status": "skipped",
            "reason": "knowledge_graph module not available",
            "created_products": 0,
            "created_relationships": 0,
            "errors": [],
        }

    summary = {
        "case_id": case_id,
        "vendor_name": vendor_name,
        "created_products": 0,
        "created_relationships": 0,
        "errors": [],
    }

    if not nvd_summary or not isinstance(nvd_summary, dict):
        return summary

    try:
        init_kg_db()
    except Exception as e:
        summary["errors"].append(f"Failed to init KG DB: {str(e)}")
        return summary

    product_terms = nvd_summary.get("product_terms") or []
    high_count = nvd_summary.get("high_or_critical_cve_count") or 0
    critical_count = nvd_summary.get("critical_cve_count") or 0
    kev_count = nvd_summary.get("kev_flagged_cve_count") or 0

    with get_kg_conn() as conn:
        vendor_entity_id = _resolve_vendor_company_entity_id(conn, vendor_name)

        # Ensure vendor entity exists with updated vulnerability exposure
        vendor_risk_level = "high" if (critical_count > 0 or kev_count > 0) else "medium" if high_count > 0 else "low"
        vendor_sanctions_exposure = min(1.0, (critical_count * 0.3 + high_count * 0.15 + kev_count * 0.4) / 10.0)

        try:
            conn.execute("""
                INSERT INTO kg_entities
                    (id, canonical_name, entity_type, confidence, risk_level, sanctions_exposure, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    risk_level = MAX(excluded.risk_level, risk_level),
                    sanctions_exposure = MAX(excluded.sanctions_exposure, sanctions_exposure),
                    last_updated = excluded.last_updated
            """, (
                vendor_entity_id,
                vendor_name,
                "company",
                0.8,
                vendor_risk_level,
                vendor_sanctions_exposure,
                datetime.now().isoformat(),
            ))
        except Exception as e:
            summary["errors"].append(f"Failed to update vendor entity: {str(e)}")

        # Create product entities
        for product_term in product_terms:
            if not product_term or not isinstance(product_term, str):
                continue

            product_id = _make_product_id(vendor_name, product_term)

            # Assign risk level to product based on exposure counts
            product_risk_level = "high" if (critical_count > 0 or kev_count > 0) else "medium" if high_count > 0 else "low"

            try:
                conn.execute("""
                    INSERT INTO kg_entities
                        (id, canonical_name, entity_type, confidence, risk_level, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        risk_level = MAX(excluded.risk_level, risk_level),
                        last_updated = excluded.last_updated
                """, (
                    product_id,
                    product_term,
                    "product",
                    0.7,
                    product_risk_level,
                    datetime.now().isoformat(),
                ))
                summary["created_products"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to insert product {product_term}: {str(e)}")
                continue

            # Create relationship: vendor -> uses_product -> product
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO kg_relationships
                        (source_entity_id, target_entity_id, rel_type, confidence, data_source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    vendor_entity_id,
                    product_id,
                    "uses_product",
                    0.8,
                    "cyber_graph_ingest",
                ))
                summary["created_relationships"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to create uses_product relationship: {str(e)}")

    return summary


def ingest_component_supply_chain(
    case_id: str,
    vendor_name: str,
    component_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    Ingest component-path findings into the knowledge graph.

    This models the critical subsystem infiltration chain directly:
      company -> component -> subsystem -> ownership path
    """
    if not HAS_KG:
        return {
            "status": "skipped",
            "reason": "knowledge_graph module not available",
            "created_entities": 0,
            "created_relationships": 0,
            "linked_entities": 0,
            "errors": [],
        }

    summary = {
        "case_id": case_id,
        "vendor_name": vendor_name,
        "created_entities": 0,
        "created_relationships": 0,
        "created_components": 0,
        "created_subsystems": 0,
        "created_holding_companies": 0,
        "linked_entities": 0,
        "errors": [],
    }

    if not component_records:
        return summary

    try:
        init_kg_db()
    except Exception as exc:
        summary["errors"].append(f"Failed to init KG DB: {exc}")
        return summary

    linked_entity_ids: set[str] = set()
    data_source_default = "component_supply_chain_ingest"

    with get_kg_conn() as conn:
        vendor_entity_id = _resolve_vendor_company_entity_id(conn, vendor_name)
        _upsert_typed_entity(
            conn,
            vendor_entity_id,
            vendor_name,
            "company",
            confidence=0.8,
            sources=[data_source_default],
        )
        linked_entity_ids.add(vendor_entity_id)

        for record in component_records:
            if not isinstance(record, dict):
                continue

            component_name = str(record.get("component_name") or record.get("component") or "").strip()
            subsystem_name = str(record.get("subsystem_name") or record.get("subsystem") or "").strip()
            platform_name = str(record.get("platform_name") or record.get("platform") or "").strip()
            owner_name = str(record.get("owner_name") or "").strip()
            owner_type = str(record.get("owner_type") or "holding_company").strip().lower()
            beneficial_owner_name = str(record.get("beneficial_owner_name") or "").strip()
            beneficial_owner_type = str(record.get("beneficial_owner_type") or "company").strip().lower()
            country = str(record.get("country") or "").strip().upper()
            data_source = str(record.get("data_source") or data_source_default).strip()
            evidence = str(record.get("evidence") or "").strip()
            confidence = float(record.get("confidence") or 0.82)
            risk_level = str(record.get("risk_level") or "unknown").strip().lower()

            if not any((component_name, subsystem_name, owner_name, beneficial_owner_name)):
                continue

            component_id = ""
            if component_name:
                component_id = _make_component_id(vendor_name, component_name)
                existed = conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (component_id,)).fetchone()
                _upsert_typed_entity(
                    conn,
                    component_id,
                    component_name,
                    "component",
                    confidence=confidence,
                    risk_level=risk_level,
                    country=country,
                    sources=[data_source],
                )
                if not existed:
                    summary["created_entities"] += 1
                    summary["created_components"] += 1
                linked_entity_ids.add(component_id)
                if _create_relationship(
                    conn,
                    vendor_entity_id,
                    component_id,
                    "supplies_component",
                    confidence=confidence,
                    data_source=data_source,
                    evidence=evidence,
                ):
                    summary["created_relationships"] += 1

            subsystem_id = ""
            if subsystem_name:
                subsystem_label = f"{platform_name} / {subsystem_name}" if platform_name else subsystem_name
                subsystem_id = _make_subsystem_id(subsystem_name, platform_name)
                existed = conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (subsystem_id,)).fetchone()
                _upsert_typed_entity(
                    conn,
                    subsystem_id,
                    subsystem_label,
                    "subsystem",
                    confidence=confidence,
                    risk_level=risk_level,
                    sources=[data_source],
                )
                if not existed:
                    summary["created_entities"] += 1
                    summary["created_subsystems"] += 1
                linked_entity_ids.add(subsystem_id)
                if _create_relationship(
                    conn,
                    vendor_entity_id,
                    subsystem_id,
                    "supplies_component_to",
                    confidence=confidence,
                    data_source=data_source,
                    evidence=evidence,
                ):
                    summary["created_relationships"] += 1

            if component_id and subsystem_id:
                if _create_relationship(
                    conn,
                    component_id,
                    subsystem_id,
                    "integrated_into",
                    confidence=max(confidence, 0.85),
                    data_source=data_source,
                    evidence=evidence,
                ):
                    summary["created_relationships"] += 1

            holding_company_id = ""
            if owner_name:
                owner_id = ""
                if owner_type == "holding_company":
                    owner_id = _make_holding_company_id(owner_name)
                existed = conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (owner_id,)).fetchone() if owner_id else None
                resolved_owner_id, resolved_owner_type = _resolve_beneficial_owner_node(
                    conn,
                    owner_name,
                    owner_type,
                    confidence=max(confidence, 0.78),
                    data_source=data_source,
                    country=country,
                )
                if owner_id and not existed and resolved_owner_type == "holding_company":
                    summary["created_entities"] += 1
                    summary["created_holding_companies"] += 1
                linked_entity_ids.add(resolved_owner_id)
                if _create_relationship(
                    conn,
                    vendor_entity_id,
                    resolved_owner_id,
                    "owned_by",
                    confidence=max(confidence, 0.8),
                    data_source=data_source,
                    evidence=evidence,
                ):
                    summary["created_relationships"] += 1
                holding_company_id = resolved_owner_id

            if beneficial_owner_name:
                beneficial_id = ""
                if beneficial_owner_type == "holding_company":
                    beneficial_id = _make_holding_company_id(beneficial_owner_name)
                elif beneficial_owner_type == "country":
                    beneficial_id = _make_country_id(beneficial_owner_name)
                elif beneficial_owner_type == "person":
                    beneficial_id = _make_person_id(beneficial_owner_name)
                existed = conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (beneficial_id,)).fetchone() if beneficial_id else None
                resolved_beneficial_id, resolved_type = _resolve_beneficial_owner_node(
                    conn,
                    beneficial_owner_name,
                    beneficial_owner_type,
                    confidence=max(confidence, 0.84),
                    data_source=data_source,
                    country=country,
                )
                if beneficial_id and not existed and resolved_type == "holding_company":
                    summary["created_entities"] += 1
                    summary["created_holding_companies"] += 1
                linked_entity_ids.add(resolved_beneficial_id)
                if _create_relationship(
                    conn,
                    holding_company_id or vendor_entity_id,
                    resolved_beneficial_id,
                    "beneficially_owned_by",
                    confidence=max(confidence, 0.86),
                    data_source=data_source,
                    evidence=evidence,
                ):
                    summary["created_relationships"] += 1

    try:
        summary["linked_entities"] = _link_entities_to_case(case_id, linked_entity_ids)
    except Exception as exc:
        summary["errors"].append(f"Failed to link component graph to case: {exc}")

    return summary


def build_cyber_subgraph(case_id: str, vendor_name: str = "") -> dict[str, Any]:
    """
    Extract the cyber-relevant portion of the knowledge graph for a case.

    Returns CVE, product, and KEV entities plus their relationships for
    visualization and analysis.

    Args:
        case_id: Case ID
        vendor_name: Optional vendor name to filter by

    Returns:
        Dict with entities, relationships, summary stats
    """
    if not HAS_KG:
        return {
            "status": "skipped",
            "reason": "knowledge_graph module not available",
            "entities": [],
            "relationships": [],
            "summary": {},
        }

    try:
        init_kg_db()
    except Exception:
        return {
            "status": "error",
            "entities": [],
            "relationships": [],
            "summary": {},
        }

    entities = []
    relationships = []
    stats = {
        "total_cves": 0,
        "critical_cves": 0,
        "high_cves": 0,
        "total_products": 0,
        "total_components": 0,
        "total_subsystems": 0,
        "services": 0,
        "telecom_providers": 0,
        "facilities": 0,
        "shipment_routes": 0,
        "holding_companies": 0,
        "kev_entries": 0,
    }

    with get_kg_conn() as conn:
        # Get cyber-related entities
        query = """
            SELECT id, canonical_name, entity_type, confidence, risk_level, sanctions_exposure
            FROM kg_entities
            WHERE entity_type IN ('cve', 'product', 'kev_entry', 'company', 'component', 'subsystem', 'holding_company', 'service', 'telecom_provider', 'facility', 'shipment_route')
        """
        params: list[Any] = []

        if vendor_name:
            query += " AND (canonical_name LIKE ? OR id LIKE ?)"
            params = [f"%{vendor_name}%", f"%{vendor_name.lower()}%"]

        cursor = conn.execute(query, params)
        for row in cursor.fetchall():
            entity = {
                "id": row[0],
                "name": row[1],
                "type": row[2],
                "confidence": row[3],
                "risk_level": row[4],
                "sanctions_exposure": row[5],
            }
            entities.append(entity)

            # Update stats
            if row[2] == "cve":
                stats["total_cves"] += 1
                if row[4] == "critical":
                    stats["critical_cves"] += 1
                elif row[4] == "high":
                    stats["high_cves"] += 1
            elif row[2] == "product":
                stats["total_products"] += 1
            elif row[2] == "component":
                stats["total_components"] += 1
            elif row[2] == "subsystem":
                stats["total_subsystems"] += 1
            elif row[2] == "holding_company":
                stats["holding_companies"] += 1
            elif row[2] == "service":
                stats["services"] += 1
            elif row[2] == "telecom_provider":
                stats["telecom_providers"] += 1
            elif row[2] == "facility":
                stats["facilities"] += 1
            elif row[2] == "shipment_route":
                stats["shipment_routes"] += 1
            elif row[2] == "kev_entry":
                stats["kev_entries"] += 1

        # Get relationships between cyber entities
        entity_ids = [e["id"] for e in entities]
        if entity_ids:
            placeholders = ",".join(["?"] * len(entity_ids))
            rel_query = f"""
                SELECT source_entity_id, target_entity_id, rel_type, confidence
                FROM kg_relationships
                WHERE source_entity_id IN ({placeholders})
                   OR target_entity_id IN ({placeholders})
            """
            rel_params = entity_ids + entity_ids

            cursor = conn.execute(rel_query, rel_params)
            for row in cursor.fetchall():
                rel = {
                    "source": row[0],
                    "target": row[1],
                    "type": row[2],
                    "confidence": row[3],
                }
                relationships.append(rel)

    return {
        "case_id": case_id,
        "vendor_name": vendor_name,
        "status": "success",
        "entities": entities,
        "relationships": relationships,
        "summary": stats,
    }
