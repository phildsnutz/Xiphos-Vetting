"""
AXIOM Agent -- Agentic Intelligence Search Orchestrator

Tier 2 of the AXIOM (Automated eXtraction of Intelligence from Open Media)
collection system. Orchestrates iterative, LLM-driven search loops that
dynamically adjust queries based on discovered intelligence.

Architecture:
  1. Initial broad sweep via careers_scraper.py (Tier 1)
  2. LLM analyzes results, extracts entities, identifies leads
  3. LLM generates targeted follow-up queries
  4. Follow-up collection via scraper + web search
  5. LLM synthesizes all findings into structured intelligence
  6. Output: KG-ready entities, relationships, and evidence chains

The agent implements an OODA loop (Observe-Orient-Decide-Act) applied to OSINT:
  - Observe: Run scraper against target
  - Orient: LLM analyzes results in context of mission
  - Decide: LLM generates follow-up queries or terminates
  - Act: Execute follow-up collection

This is fundamentally different from a static scraper pipeline because the
LLM can pivot based on what it discovers, follow threads of intelligence,
and make judgments about what's worth pursuing.
"""

import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 5          # Maximum OODA loops before forced termination
MAX_FOLLOW_UPS_PER_ITER = 3 # Max follow-up queries per iteration
SCRAPE_DELAY = 2.0          # Seconds between scraper calls
LLM_TIMEOUT = 30            # Seconds for LLM API calls
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SearchTarget:
    """Target specification for an AXIOM agent run."""
    prime_contractor: str
    contract_name: str = ""
    vehicle_name: str = ""
    installation: str = ""
    website: str = ""
    known_subs: list[str] = field(default_factory=list)
    context: str = ""  # Free-text mission context


@dataclass
class DiscoveredEntity:
    """An entity discovered during the search."""
    name: str
    entity_type: str  # company, person, installation, contract_vehicle
    confidence: float = 0.5
    attributes: dict = field(default_factory=dict)
    source_queries: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class DiscoveredRelationship:
    """A relationship discovered during the search."""
    source_entity: str
    target_entity: str
    rel_type: str  # subcontractor_of, teamed_with, performed_at, etc.
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)


@dataclass
class SearchIteration:
    """Record of a single OODA loop iteration."""
    iteration: int
    queries_executed: list[str] = field(default_factory=list)
    raw_findings_count: int = 0
    entities_discovered: list[str] = field(default_factory=list)
    follow_up_queries: list[str] = field(default_factory=list)
    llm_reasoning: str = ""
    elapsed_ms: int = 0


@dataclass
class AgentResult:
    """Complete result from an AXIOM agent run."""
    target: SearchTarget
    entities: list[DiscoveredEntity] = field(default_factory=list)
    relationships: list[DiscoveredRelationship] = field(default_factory=list)
    iterations: list[SearchIteration] = field(default_factory=list)
    total_queries: int = 0
    total_findings: int = 0
    intelligence_gaps: list[dict] = field(default_factory=list)
    advisory_opportunities: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, system: str = "", provider: str = DEFAULT_PROVIDER,
              model: str = DEFAULT_MODEL, api_key: str = "",
              max_tokens: int = 4096) -> str:
    """
    Call LLM provider via raw HTTP (matching existing Helios ai_analysis.py pattern).
    Returns the text response or empty string on failure.
    """
    if not api_key:
        logger.warning("axiom_agent: no API key provided for %s", provider)
        return ""

    try:
        if provider == "anthropic":
            return _call_anthropic(prompt, system, model, api_key, max_tokens)
        elif provider == "openai":
            return _call_openai(prompt, system, model, api_key, max_tokens)
        else:
            logger.error("axiom_agent: unsupported provider '%s'", provider)
            return ""
    except Exception as e:
        logger.exception("axiom_agent: LLM call failed: %s", e)
        return ""


def _call_anthropic(prompt: str, system: str, model: str, api_key: str,
                    max_tokens: int) -> str:
    """Call Anthropic Claude API."""
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


def _call_openai(prompt: str, system: str, model: str, api_key: str,
                 max_tokens: int) -> str:
    """Call OpenAI API."""
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


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are AXIOM, an intelligence analyst specializing in government contract 
vehicle analysis and subcontractor identification. You analyze job postings, company data, 
and public records to map teaming relationships in the defense/intelligence community.

You operate in an iterative search loop. Each iteration:
1. You receive raw findings from web scraping
2. You extract entities and relationships
3. You decide what follow-up searches would yield the highest intelligence value
4. You either generate follow-up queries or declare the search complete

Your outputs must be valid JSON matching the schema provided in each prompt.
Be precise with entity names (use official company names, not abbreviations).
Confidence scores: 0.3=speculative, 0.5=possible, 0.7=probable, 0.85=likely, 0.95=confirmed."""


def _build_analysis_prompt(target: SearchTarget, raw_findings: list[dict],
                           iteration: int, previous_entities: list[str]) -> str:
    """Build the LLM prompt for analyzing scraper results."""
    return f"""Analyze the following job board scraping results for intelligence value.

TARGET:
- Prime Contractor: {target.prime_contractor}
- Contract/Vehicle: {target.contract_name or target.vehicle_name or 'Not specified'}
- Installation: {target.installation or 'Not specified'}
- Known Subcontractors: {', '.join(target.known_subs) if target.known_subs else 'None'}
- Context: {target.context or 'General contract vehicle intelligence'}

ITERATION: {iteration} of {MAX_ITERATIONS}
PREVIOUSLY DISCOVERED ENTITIES: {', '.join(previous_entities) if previous_entities else 'None yet'}

RAW FINDINGS ({len(raw_findings)} items):
{json.dumps(raw_findings[:20], indent=2, default=str)}

Respond with valid JSON:
{{
  "entities": [
    {{
      "name": "Company Name",
      "entity_type": "company|person|installation|contract_vehicle",
      "confidence": 0.0-1.0,
      "attributes": {{"role": "subcontractor|prime|partner", "clearance": "...", "location": "..."}},
      "evidence": ["brief description of supporting evidence"]
    }}
  ],
  "relationships": [
    {{
      "source_entity": "Entity A",
      "target_entity": "Entity B",
      "rel_type": "subcontractor_of|teamed_with|performed_at|competed_on|incumbent_on",
      "confidence": 0.0-1.0,
      "evidence": ["brief description"]
    }}
  ],
  "follow_up_queries": [
    "search query string that would yield high intelligence value"
  ],
  "reasoning": "Brief explanation of what you found and why you recommend these follow-ups",
  "intelligence_gaps": [
    {{
      "gap": "What information is missing",
      "fillable_by": "automated_search|advisory_services|foia|network_query",
      "priority": "high|medium|low"
    }}
  ],
  "search_complete": false
}}

Set search_complete to true ONLY when:
- Follow-up queries would be redundant (same entities keep appearing)
- The intelligence picture is sufficiently complete for the target
- Remaining gaps can only be filled through non-automated means

Generate 0-{MAX_FOLLOW_UPS_PER_ITER} follow-up queries. Each should be specific and different from previous queries.
Focus follow-ups on: confirming suspected subs, finding additional subs, attributing positions to specific vehicles, identifying teaming partners."""


# ---------------------------------------------------------------------------
# Scraper integration
# ---------------------------------------------------------------------------

def _run_scraper(query: str, target: SearchTarget) -> list[dict]:
    """
    Run the careers_scraper against a query.
    Returns list of finding dicts from the EnrichmentResult.
    """
    try:
        from osint.careers_scraper import enrich
        result = enrich(
            vendor_name=query,
            contract_name=target.contract_name,
            vehicle_name=target.vehicle_name,
            installation=target.installation,
            website=target.website,
        )
        # Convert findings to simple dicts for LLM consumption
        findings = []
        for f in result.findings:
            findings.append({
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "severity": f.severity,
                "confidence": f.confidence,
                "raw_data": f.raw_data,
            })
        return findings
    except Exception as e:
        logger.exception("axiom_agent: scraper failed for query '%s': %s", query, e)
        return []


def _run_web_search(query: str) -> list[dict]:
    """
    Run a general web search for follow-up intelligence.
    Uses requests to search public sources. Returns simplified results.
    """
    import requests

    findings = []
    try:
        # Google Custom Search API (if configured) or fallback to scraping
        # For now, search ClearanceJobs directly with the follow-up query
        from osint.careers_scraper import _get_session, _scrape_clearancejobs
        session = _get_session()
        posts = _scrape_clearancejobs(session, query)
        for post in posts[:10]:
            findings.append({
                "category": "follow_up_search",
                "title": post.get("title", ""),
                "detail": post.get("description_snippet", ""),
                "company": post.get("company", ""),
                "location": post.get("location", ""),
                "clearance": post.get("clearance", ""),
                "contract_indicators": post.get("contract_indicators", []),
                "source": "clearancejobs_followup",
            })
    except Exception as e:
        logger.warning("axiom_agent: web search failed for '%s': %s", query, e)

    return findings


# ---------------------------------------------------------------------------
# Core agent loop
# ---------------------------------------------------------------------------

def run_agent(target: SearchTarget, api_key: str = "", provider: str = DEFAULT_PROVIDER,
              model: str = DEFAULT_MODEL, user_id: str = "") -> AgentResult:
    """
    Execute the AXIOM agentic search loop.

    This is the main entry point. It runs an iterative OODA loop:
    1. Initial broad sweep with careers_scraper
    2. LLM analysis of results
    3. Follow-up queries generated by LLM
    4. Repeat until search_complete or MAX_ITERATIONS

    Args:
        target: SearchTarget with prime contractor and context
        api_key: LLM provider API key (or retrieved from ai_config if user_id provided)
        provider: LLM provider name (anthropic, openai)
        model: Model identifier
        user_id: Optional user ID to retrieve stored API key

    Returns:
        AgentResult with all discovered entities, relationships, and gaps
    """
    result = AgentResult(target=target)
    start = datetime.now(timezone.utc)

    # Resolve API key
    if not api_key and user_id:
        try:
            from ai_analysis import get_ai_config
            config = get_ai_config(user_id)
            if config:
                api_key = config.get("api_key", "")
                provider = config.get("provider", provider)
                model = config.get("model", model)
        except Exception as e:
            logger.warning("axiom_agent: could not retrieve AI config: %s", e)

    if not api_key:
        result.error = "No API key available. Configure AI provider in settings or pass api_key."
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    all_entities: dict[str, DiscoveredEntity] = {}
    all_relationships: list[DiscoveredRelationship] = []
    all_findings: list[dict] = []

    try:
        for iteration in range(1, MAX_ITERATIONS + 1):
            iter_start = datetime.now(timezone.utc)
            iter_record = SearchIteration(iteration=iteration)

            # Determine queries for this iteration
            if iteration == 1:
                # Initial broad sweep
                queries = [target.prime_contractor]
                if target.contract_name:
                    queries.append(f"{target.prime_contractor} {target.contract_name}")
                if target.installation:
                    queries.append(f"{target.prime_contractor} {target.installation}")
            else:
                # Use LLM-generated follow-up queries from previous iteration
                prev_iter = result.iterations[-1] if result.iterations else None
                queries = prev_iter.follow_up_queries if prev_iter else []
                if not queries:
                    logger.info("axiom_agent: no follow-up queries, terminating at iteration %d", iteration)
                    break

            # Execute queries
            iter_findings = []
            for query in queries[:MAX_FOLLOW_UPS_PER_ITER + 1]:
                logger.info("axiom_agent: iteration %d, query: '%s'", iteration, query)
                iter_record.queries_executed.append(query)

                if iteration == 1:
                    findings = _run_scraper(query, target)
                else:
                    findings = _run_web_search(query)

                iter_findings.extend(findings)
                time.sleep(SCRAPE_DELAY)

            iter_record.raw_findings_count = len(iter_findings)
            all_findings.extend(iter_findings)
            result.total_findings += len(iter_findings)
            result.total_queries += len(queries)

            if not iter_findings and iteration > 1:
                logger.info("axiom_agent: no findings in iteration %d, terminating", iteration)
                iter_record.llm_reasoning = "No new findings from follow-up queries. Search exhausted."
                result.iterations.append(iter_record)
                break

            # LLM analysis
            previous_entity_names = list(all_entities.keys())
            analysis_prompt = _build_analysis_prompt(
                target, iter_findings, iteration, previous_entity_names
            )

            llm_response = _call_llm(
                prompt=analysis_prompt,
                system=SYSTEM_PROMPT,
                provider=provider,
                model=model,
                api_key=api_key,
            )

            if not llm_response:
                iter_record.llm_reasoning = "LLM call failed or returned empty response."
                result.iterations.append(iter_record)
                continue

            # Parse LLM response
            try:
                # Handle potential markdown code blocks in response
                clean_response = llm_response.strip()
                if clean_response.startswith("```"):
                    clean_response = clean_response.split("\n", 1)[1]
                    if clean_response.endswith("```"):
                        clean_response = clean_response[:-3]
                    clean_response = clean_response.strip()

                analysis = json.loads(clean_response)
            except json.JSONDecodeError as e:
                logger.warning("axiom_agent: failed to parse LLM response: %s", e)
                iter_record.llm_reasoning = f"LLM response parse error: {e}"
                result.iterations.append(iter_record)
                continue

            # Process discovered entities
            for ent_data in analysis.get("entities", []):
                name = ent_data.get("name", "").strip()
                if not name:
                    continue

                if name in all_entities:
                    # Update existing entity with higher confidence
                    existing = all_entities[name]
                    existing.confidence = max(existing.confidence, ent_data.get("confidence", 0.5))
                    existing.source_queries.extend(queries)
                    existing.evidence.extend(ent_data.get("evidence", []))
                else:
                    all_entities[name] = DiscoveredEntity(
                        name=name,
                        entity_type=ent_data.get("entity_type", "company"),
                        confidence=ent_data.get("confidence", 0.5),
                        attributes=ent_data.get("attributes", {}),
                        source_queries=list(queries),
                        evidence=ent_data.get("evidence", []),
                    )
                iter_record.entities_discovered.append(name)

            # Process discovered relationships
            for rel_data in analysis.get("relationships", []):
                rel = DiscoveredRelationship(
                    source_entity=rel_data.get("source_entity", ""),
                    target_entity=rel_data.get("target_entity", ""),
                    rel_type=rel_data.get("rel_type", "related_entity"),
                    confidence=rel_data.get("confidence", 0.5),
                    evidence=rel_data.get("evidence", []),
                )
                if rel.source_entity and rel.target_entity:
                    all_relationships.append(rel)

            # Process intelligence gaps
            for gap_data in analysis.get("intelligence_gaps", []):
                gap = {
                    "gap": gap_data.get("gap", ""),
                    "fillable_by": gap_data.get("fillable_by", "automated_search"),
                    "priority": gap_data.get("priority", "medium"),
                    "iteration_discovered": iteration,
                }
                result.intelligence_gaps.append(gap)

                # Flag advisory opportunities (gaps fillable by HUMINT/consulting)
                if gap_data.get("fillable_by") == "advisory_services":
                    result.advisory_opportunities.append({
                        "gap": gap_data.get("gap", ""),
                        "priority": gap_data.get("priority", "medium"),
                        "value_proposition": (
                            f"Automated collection cannot determine: {gap_data.get('gap', '')}. "
                            f"Xiphos advisory services can fill this gap through network intelligence."
                        ),
                    })

            # Store follow-up queries and reasoning
            iter_record.follow_up_queries = analysis.get("follow_up_queries", [])
            iter_record.llm_reasoning = analysis.get("reasoning", "")
            iter_record.elapsed_ms = int(
                (datetime.now(timezone.utc) - iter_start).total_seconds() * 1000
            )
            result.iterations.append(iter_record)

            # Check termination
            if analysis.get("search_complete", False):
                logger.info("axiom_agent: LLM declared search complete at iteration %d", iteration)
                break

            logger.info(
                "axiom_agent: iteration %d complete. %d entities, %d relationships, %d follow-ups",
                iteration, len(all_entities), len(all_relationships),
                len(iter_record.follow_up_queries),
            )

    except Exception as e:
        logger.exception("axiom_agent: unexpected error: %s", e)
        result.error = str(e)

    # Finalize result
    result.entities = list(all_entities.values())
    result.relationships = all_relationships
    result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    logger.info(
        "axiom_agent: complete. %d entities, %d relationships, %d gaps, %d advisory opportunities, %d iterations, %dms",
        len(result.entities), len(result.relationships),
        len(result.intelligence_gaps), len(result.advisory_opportunities),
        len(result.iterations), result.elapsed_ms,
    )

    return result


# ---------------------------------------------------------------------------
# KG ingestion helper
# ---------------------------------------------------------------------------

def ingest_agent_result(agent_result: AgentResult, vendor_id: str = "") -> dict:
    """
    Ingest an AgentResult into the Helios Knowledge Graph.

    Creates entities, relationships, claims, and evidence records from
    the agent's discoveries. Returns summary of what was ingested.

    Args:
        agent_result: Completed AgentResult from run_agent()
        vendor_id: Optional vendor ID to link discoveries to

    Returns:
        Dict with counts of entities/relationships/claims created
    """
    summary = {
        "entities_created": 0,
        "relationships_created": 0,
        "claims_created": 0,
        "evidence_created": 0,
    }

    try:
        from knowledge_graph import get_kg_conn, _stable_hash, _utc_now

        with get_kg_conn() as conn:
            now = _utc_now()

            for entity in agent_result.entities:
                entity_id = _stable_hash(
                    entity.name, entity.entity_type,
                    prefix="axiom"
                )

                # Upsert entity
                if hasattr(conn, 'execute'):
                    try:
                        conn.execute("""
                            INSERT INTO kg_entities (id, canonical_name, entity_type,
                                aliases, identifiers, sources, confidence, risk_level, last_updated)
                            VALUES (?, ?, ?, '[]', ?, ?, ?, 'unknown', ?)
                            ON CONFLICT(id) DO UPDATE SET
                                confidence = MAX(kg_entities.confidence, excluded.confidence),
                                sources = excluded.sources,
                                last_updated = excluded.last_updated
                        """, (
                            entity_id, entity.name, entity.entity_type,
                            json.dumps(entity.attributes),
                            json.dumps(["axiom_agent"]),
                            entity.confidence, now,
                        ))
                        summary["entities_created"] += 1
                    except Exception as e:
                        logger.warning("axiom_agent: entity upsert failed for '%s': %s", entity.name, e)

            for rel in agent_result.relationships:
                source_id = _stable_hash(rel.source_entity, "company", prefix="axiom")
                target_id = _stable_hash(rel.target_entity, "company", prefix="axiom")

                try:
                    conn.execute("""
                        INSERT INTO kg_relationships (source_entity_id, target_entity_id,
                            rel_type, confidence, data_source, evidence, created_at)
                        VALUES (?, ?, ?, ?, 'axiom_agent', ?, ?)
                    """, (
                        source_id, target_id, rel.rel_type,
                        rel.confidence, json.dumps(rel.evidence), now,
                    ))
                    summary["relationships_created"] += 1
                except Exception as e:
                    logger.warning("axiom_agent: relationship insert failed: %s", e)

            if hasattr(conn, 'commit'):
                conn.commit()

    except Exception as e:
        logger.exception("axiom_agent: KG ingestion failed: %s", e)

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for standalone AXIOM agent runs."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="AXIOM Agentic Intelligence Search")
    parser.add_argument("prime", help="Prime contractor name")
    parser.add_argument("--contract", default="", help="Contract name")
    parser.add_argument("--vehicle", default="", help="Vehicle name (OASIS, ASTRO, etc.)")
    parser.add_argument("--installation", default="", help="Installation (Camp Smith, etc.)")
    parser.add_argument("--website", default="", help="Company website URL")
    parser.add_argument("--known-subs", nargs="*", default=[], help="Known subcontractor names")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="LLM provider")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model")
    parser.add_argument("--api-key", default="", help="LLM API key (or set env var)")
    parser.add_argument("--output", default="", help="Output JSON file path")
    parser.add_argument("--ingest", action="store_true", help="Ingest results into KG")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")

    target = SearchTarget(
        prime_contractor=args.prime,
        contract_name=args.contract,
        vehicle_name=args.vehicle,
        installation=args.installation,
        website=args.website,
        known_subs=args.known_subs,
    )

    result = run_agent(target, api_key=api_key, provider=args.provider, model=args.model)

    # Output
    output_data = result.to_dict()
    if args.output:
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"Results written to {args.output}")
    else:
        print(json.dumps(output_data, indent=2, default=str))

    # KG ingestion
    if args.ingest:
        summary = ingest_agent_result(result)
        print(f"KG Ingestion: {summary}")

    print(f"\nSummary: {len(result.entities)} entities, {len(result.relationships)} relationships, "
          f"{len(result.intelligence_gaps)} gaps, {len(result.advisory_opportunities)} advisory opportunities")


if __name__ == "__main__":
    main()