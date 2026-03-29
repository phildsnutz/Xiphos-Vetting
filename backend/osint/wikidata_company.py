"""
Wikidata Company Intelligence Connector

Free SPARQL endpoint, no auth required.
Discovers company metadata: founding year, headquarters, industry, stock exchange,
number of employees, parent company, and subsidiaries via Wikidata.

Source: https://query.wikidata.org/
"""

import requests
from datetime import datetime
from . import EnrichmentResult, Finding

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
TIMEOUT = 15

QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?foundedYear ?hqLabel ?industryLabel ?exchangeLabel
       ?employees ?parentLabel ?countryLabel ?websiteUrl
WHERE {{
  ?item rdfs:label "{vendor_name}"@en .
  ?item wdt:P31/wdt:P279* wd:Q4830453 .  # instance of business enterprise
  OPTIONAL {{ ?item wdt:P571 ?founded . BIND(YEAR(?founded) AS ?foundedYear) }}
  OPTIONAL {{ ?item wdt:P159 ?hq . }}
  OPTIONAL {{ ?item wdt:P452 ?industry . }}
  OPTIONAL {{ ?item wdt:P414 ?exchange . }}
  OPTIONAL {{ ?item wdt:P1128 ?employees . }}
  OPTIONAL {{ ?item wdt:P749 ?parent . }}
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{ ?item wdt:P856 ?websiteUrl . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 5
"""


def _wikidata_url(entity_id: str) -> str:
    return f"https://www.wikidata.org/wiki/{entity_id}" if entity_id else ""


def _ownership_relationship(
    *,
    vendor_name: str,
    vendor_country: str,
    wikidata_id: str,
    parent_name: str,
    evidence: str,
) -> dict:
    return {
        "type": "owned_by",
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {"wikidata_id": wikidata_id} if wikidata_id else {},
        "target_entity": parent_name,
        "target_entity_type": "holding_company",
        "target_identifiers": {},
        "country": vendor_country,
        "data_source": "wikidata_company",
        "confidence": 0.68,
        "evidence": evidence,
        "observed_at": datetime.utcnow().isoformat() + "Z",
        "artifact_ref": f"wikidata://{wikidata_id}" if wikidata_id else "",
        "evidence_url": _wikidata_url(wikidata_id),
        "evidence_title": "Wikidata parent-company relationship",
        "structured_fields": {
            "standards": ["Wikidata"],
            "relationship_scope": "parent_company",
            "wikidata_id": wikidata_id,
        },
        "source_class": "public_connector",
        "authority_level": "third_party_public",
        "access_model": "public_api",
    }


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="wikidata_company", vendor_name=vendor_name)
    start = datetime.now()

    try:
        # Try exact match first, then simplified name
        names_to_try = [vendor_name]
        # Add simplified version (remove common suffixes)
        simplified = vendor_name
        for suffix in [" Inc", " Inc.", " LLC", " Corp", " Corp.", " Ltd", " Ltd.", " plc", " SA", " AG", " GmbH", " Co.", " Company"]:
            simplified = simplified.replace(suffix, "")
        if simplified != vendor_name:
            names_to_try.append(simplified.strip())

        entity = None
        for name in names_to_try:
            query = QUERY_TEMPLATE.format(vendor_name=name.replace('"', '\\"'))
            resp = requests.get(SPARQL_ENDPOINT, params={"query": query, "format": "json"}, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
                if bindings:
                    entity = bindings[0]
                    break

        if entity:
            label = entity.get("itemLabel", {}).get("value", vendor_name)
            founded = entity.get("foundedYear", {}).get("value", "")
            hq = entity.get("hqLabel", {}).get("value", "")
            industry = entity.get("industryLabel", {}).get("value", "")
            exchange = entity.get("exchangeLabel", {}).get("value", "")
            employees = entity.get("employees", {}).get("value", "")
            parent = entity.get("parentLabel", {}).get("value", "")
            entity_country = entity.get("countryLabel", {}).get("value", "")
            website = entity.get("websiteUrl", {}).get("value", "")
            wikidata_id = entity.get("item", {}).get("value", "").split("/")[-1]

            if wikidata_id:
                result.identifiers["wikidata_id"] = wikidata_id
            if founded:
                result.identifiers["incorporation_date"] = founded
            if exchange:
                result.identifiers["stock_exchange"] = exchange
                result.identifiers["publicly_traded"] = True
            if employees:
                result.identifiers["employee_count"] = employees
            if website:
                result.identifiers["website"] = website

            detail_parts = [f"Entity: {label}"]
            if founded:
                detail_parts.append(f"Founded: {founded}")
            if hq:
                detail_parts.append(f"HQ: {hq}")
            if industry:
                detail_parts.append(f"Industry: {industry}")
            if exchange:
                detail_parts.append(f"Exchange: {exchange}")
            if employees:
                detail_parts.append(f"Employees: {employees}")
            if parent:
                detail_parts.append(f"Parent: {parent}")
            if entity_country:
                detail_parts.append(f"Country: {entity_country}")

            result.findings.append(Finding(
                source="wikidata_company", category="identity",
                title=f"Wikidata: {label} identified",
                detail=" | ".join(detail_parts),
                severity="info", confidence=0.75,
                url=_wikidata_url(wikidata_id),
            ))

            if parent:
                result.relationships.append({
                    **_ownership_relationship(
                        vendor_name=vendor_name,
                        vendor_country=entity_country or country,
                        wikidata_id=wikidata_id,
                        parent_name=parent,
                        evidence=f"Wikidata identifies {parent} as the parent company of {label}.",
                    ),
                    "raw_data": {
                        "parent_name": parent,
                        "wikidata_id": wikidata_id,
                    },
                })
                result.findings.append(Finding(
                    source="wikidata_company", category="ownership",
                    title=f"Parent company: {parent}",
                    detail=f"Wikidata identifies {parent} as the parent company of {label}.",
                    severity="info", confidence=0.7,
                ))
        else:
            result.findings.append(Finding(
                source="wikidata_company", category="identity",
                title=f"Wikidata: No structured data found for '{vendor_name}'",
                detail="Entity not found in Wikidata as a business enterprise. May be a subsidiary or use a different registered name.",
                severity="info", confidence=0.5,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
