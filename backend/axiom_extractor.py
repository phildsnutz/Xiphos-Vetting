"""
AXIOM Extractor -- LLM-Powered Intelligence Extraction

Extracts structured entities, relationships, and intelligence signals from
raw text content (scraped web pages, job postings, press releases, etc.)
using an LLM. Produces KG-ready output.

This module handles the "Orient" phase of the OODA loop: taking raw
observations and converting them into structured intelligence that can
be acted upon.

Extraction targets:
  - Company entities (subcontractors, primes, partners)
  - Person entities (key personnel, hiring managers)
  - Contract references (vehicle names, PIIDs, task orders)
  - Installation/location attribution
  - Clearance requirements (indicating classified work)
  - Teaming relationships
  - Technology/capability indicators
  - Temporal signals (hiring surges, position removals)
"""

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.1"
LLM_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExtractedEntity:
    """An entity extracted from raw content."""
    name: str
    entity_type: str  # company, person, installation, contract, technology
    confidence: float = 0.5
    context: str = ""  # surrounding text that references this entity
    attributes: dict = field(default_factory=dict)


@dataclass
class ExtractedRelationship:
    """A relationship extracted from raw content."""
    source: str
    target: str
    rel_type: str
    confidence: float = 0.5
    evidence_text: str = ""


@dataclass
class ExtractedSignal:
    """An intelligence signal extracted from raw content."""
    signal_type: str  # hiring_surge, position_removal, new_location, clearance_upgrade
    description: str
    confidence: float = 0.5
    entities_involved: list[str] = field(default_factory=list)
    temporal: str = ""  # when this signal was observed


@dataclass
class ExtractionResult:
    """Complete extraction result from a piece of content."""
    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)
    signals: list[ExtractedSignal] = field(default_factory=list)
    contract_references: list[dict] = field(default_factory=list)
    advisory_flags: list[dict] = field(default_factory=list)
    raw_llm_output: str = ""
    elapsed_ms: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# LLM calls (matching ai_analysis.py pattern)
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, system: str, provider: str, model: str,
              api_key: str, max_tokens: int = 4096) -> str:
    """Call LLM provider. Returns text response or empty string."""
    try:
        if provider == "anthropic":
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                payload["system"] = system

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("content", [{}])[0].get("text", "")

        elif provider == "openai":
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        else:
            logger.error("axiom_extractor: unsupported provider '%s'", provider)
            return ""
    except Exception as e:
        logger.exception("axiom_extractor: LLM call failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Extraction prompts
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = """You are an intelligence extraction engine. Given raw text content 
(job postings, press releases, web pages), you extract structured intelligence about 
government contracting relationships, company teaming arrangements, and workforce patterns.

Output ONLY valid JSON. Be precise with company names. 
Confidence: 0.3=speculative, 0.5=possible, 0.7=probable, 0.85=likely, 0.95=confirmed."""


def _build_extraction_prompt(content: str, context: str = "",
                              focus_entities: list[str] = None) -> str:
    """Build extraction prompt for a piece of content."""
    focus = ""
    if focus_entities:
        focus = f"\nFOCUS ON THESE ENTITIES: {', '.join(focus_entities)}"

    return f"""Extract intelligence from this content.{focus}

CONTEXT: {context or 'Government contract intelligence gathering'}

CONTENT:
{content[:8000]}

Respond with valid JSON:
{{
  "entities": [
    {{
      "name": "Official Entity Name",
      "entity_type": "company|person|installation|contract|technology",
      "confidence": 0.0-1.0,
      "context": "brief surrounding context",
      "attributes": {{}}
    }}
  ],
  "relationships": [
    {{
      "source": "Entity A",
      "target": "Entity B",
      "rel_type": "subcontractor_of|teamed_with|performed_at|awarded_under|incumbent_on|hired_by",
      "confidence": 0.0-1.0,
      "evidence_text": "brief supporting text"
    }}
  ],
  "signals": [
    {{
      "signal_type": "hiring_surge|position_removal|new_location|clearance_upgrade|recompete_indicator|teaming_shift",
      "description": "what this signal indicates",
      "confidence": 0.0-1.0,
      "entities_involved": ["entity names"],
      "temporal": "when observed or relevant timeframe"
    }}
  ],
  "contract_references": [
    {{
      "name": "contract or vehicle name",
      "piid": "if found",
      "vehicle": "OASIS/ASTRO/Alliant/etc if identified",
      "agency": "contracting agency if identified"
    }}
  ],
  "advisory_flags": [
    {{
      "flag": "what automated extraction cannot determine",
      "recommended_action": "how a human analyst could resolve this",
      "value": "why this matters for capture intelligence"
    }}
  ]
}}"""


def _build_batch_extraction_prompt(items: list[dict], context: str = "") -> str:
    """Build extraction prompt for a batch of job postings."""
    formatted_items = []
    for i, item in enumerate(items[:15]):
        formatted_items.append(
            f"[{i+1}] Title: {item.get('title', 'Unknown')}\n"
            f"    Company: {item.get('company', 'Unknown')}\n"
            f"    Location: {item.get('location', 'Unknown')}\n"
            f"    Clearance: {item.get('clearance', 'Not specified')}\n"
            f"    Snippet: {item.get('description_snippet', '')[:300]}\n"
            f"    Indicators: {', '.join(item.get('contract_indicators', []))}"
        )

    return f"""Extract intelligence from these {len(formatted_items)} job postings.

CONTEXT: {context or 'Subcontractor identification for government contract vehicle'}

JOB POSTINGS:
{chr(10).join(formatted_items)}

Respond with valid JSON:
{{
  "entities": [
    {{
      "name": "Company Name (use official name, not abbreviation)",
      "entity_type": "company",
      "confidence": 0.0-1.0,
      "context": "role in contract ecosystem",
      "attributes": {{
        "role": "subcontractor|prime|staffing_partner",
        "positions_count": 0,
        "primary_location": "",
        "clearance_level": "",
        "capability_indicators": []
      }}
    }}
  ],
  "relationships": [
    {{
      "source": "Subcontractor Name",
      "target": "Prime Name",
      "rel_type": "subcontractor_of|teamed_with|staffing_partner_of",
      "confidence": 0.0-1.0,
      "evidence_text": "e.g. '3 positions referencing LEIA contract at Camp Smith'"
    }}
  ],
  "signals": [
    {{
      "signal_type": "hiring_surge|capability_expansion|geographic_expansion",
      "description": "what pattern is observable across these postings",
      "confidence": 0.0-1.0,
      "entities_involved": [],
      "temporal": ""
    }}
  ],
  "contract_references": [],
  "advisory_flags": [
    {{
      "flag": "what can't be determined from job postings alone",
      "recommended_action": "specific human intelligence action",
      "value": "capture intelligence value"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Public extraction functions
# ---------------------------------------------------------------------------

def extract_from_text(content: str, context: str = "",
                      focus_entities: list[str] = None,
                      api_key: str = "", provider: str = DEFAULT_PROVIDER,
                      model: str = DEFAULT_MODEL) -> ExtractionResult:
    """
    Extract intelligence from raw text content.

    Args:
        content: Raw text (HTML stripped, job posting text, press release, etc.)
        context: Mission context for the extraction
        focus_entities: Optional list of entity names to focus on
        api_key: LLM provider API key
        provider: LLM provider name
        model: Model identifier

    Returns:
        ExtractionResult with structured intelligence
    """
    result = ExtractionResult()
    start = datetime.now(timezone.utc)

    if not api_key:
        result.error = "No API key provided"
        return result

    prompt = _build_extraction_prompt(content, context, focus_entities)
    llm_output = _call_llm(prompt, EXTRACTION_SYSTEM, provider, model, api_key)
    result.raw_llm_output = llm_output

    if not llm_output:
        result.error = "LLM returned empty response"
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    try:
        clean = llm_output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        result.error = f"JSON parse error: {e}"
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    # Process entities
    for ent in parsed.get("entities", []):
        result.entities.append(ExtractedEntity(
            name=ent.get("name", ""),
            entity_type=ent.get("entity_type", "company"),
            confidence=ent.get("confidence", 0.5),
            context=ent.get("context", ""),
            attributes=ent.get("attributes", {}),
        ))

    # Process relationships
    for rel in parsed.get("relationships", []):
        result.relationships.append(ExtractedRelationship(
            source=rel.get("source", ""),
            target=rel.get("target", ""),
            rel_type=rel.get("rel_type", "related_entity"),
            confidence=rel.get("confidence", 0.5),
            evidence_text=rel.get("evidence_text", ""),
        ))

    # Process signals
    for sig in parsed.get("signals", []):
        result.signals.append(ExtractedSignal(
            signal_type=sig.get("signal_type", ""),
            description=sig.get("description", ""),
            confidence=sig.get("confidence", 0.5),
            entities_involved=sig.get("entities_involved", []),
            temporal=sig.get("temporal", ""),
        ))

    # Contract references and advisory flags
    result.contract_references = parsed.get("contract_references", [])
    result.advisory_flags = parsed.get("advisory_flags", [])

    result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return result


def extract_from_job_postings(postings: list[dict], context: str = "",
                               api_key: str = "", provider: str = DEFAULT_PROVIDER,
                               model: str = DEFAULT_MODEL) -> ExtractionResult:
    """
    Extract intelligence from a batch of job postings.

    Optimized for the output format of careers_scraper.py. Takes the raw_data
    from scraper findings and extracts structured intelligence.

    Args:
        postings: List of job posting dicts from careers_scraper
        context: Mission context
        api_key: LLM provider API key
        provider: LLM provider name
        model: Model identifier

    Returns:
        ExtractionResult with structured intelligence
    """
    result = ExtractionResult()
    start = datetime.now(timezone.utc)

    if not api_key:
        result.error = "No API key provided"
        return result

    if not postings:
        result.error = "No postings provided"
        return result

    prompt = _build_batch_extraction_prompt(postings, context)
    llm_output = _call_llm(prompt, EXTRACTION_SYSTEM, provider, model, api_key)
    result.raw_llm_output = llm_output

    if not llm_output:
        result.error = "LLM returned empty response"
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    try:
        clean = llm_output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        result.error = f"JSON parse error: {e}"
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    for ent in parsed.get("entities", []):
        result.entities.append(ExtractedEntity(
            name=ent.get("name", ""),
            entity_type=ent.get("entity_type", "company"),
            confidence=ent.get("confidence", 0.5),
            context=ent.get("context", ""),
            attributes=ent.get("attributes", {}),
        ))

    for rel in parsed.get("relationships", []):
        result.relationships.append(ExtractedRelationship(
            source=rel.get("source", ""),
            target=rel.get("target", ""),
            rel_type=rel.get("rel_type", "related_entity"),
            confidence=rel.get("confidence", 0.5),
            evidence_text=rel.get("evidence_text", ""),
        ))

    for sig in parsed.get("signals", []):
        result.signals.append(ExtractedSignal(
            signal_type=sig.get("signal_type", ""),
            description=sig.get("description", ""),
            confidence=sig.get("confidence", 0.5),
            entities_involved=sig.get("entities_involved", []),
            temporal=sig.get("temporal", ""),
        ))

    result.contract_references = parsed.get("contract_references", [])
    result.advisory_flags = parsed.get("advisory_flags", [])

    result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return result
