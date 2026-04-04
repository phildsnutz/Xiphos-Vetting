"""
AXIOM Gap Filler -- The Wise Case Officer Pattern

Tier 2.5 of the AXIOM collection system. When the intelligence pipeline identifies
gaps (unfilled OSINT data points), AXIOM gets first look at each gap and attempts
to fill it using 2-5 creative, unconventional approaches before declaring it unfillable.

Core Philosophy:
  - Think like an experienced intelligence case officer, not a search engine
  - Consider indirect indicators (hiring patterns, press releases, regulatory filings)
  - Query the knowledge graph for 2nd and 3rd order connections
  - Use pattern matching from similar vehicles/programs
  - Build institutional wisdom over time; learn to prioritize effective approaches
  - After each attempt, reflect on what worked and WHY

The Approach Library includes:
  - lateral_entity_search: Alternate names, DBAs, subsidiaries
  - graph_pattern_inference: Entities connected to known associates
  - proxy_indicator_hunt: Job postings, press releases, subaward data, SBA filings
  - cross_vehicle_correlation: Check related vehicles for data gaps
  - temporal_backtrack: Search older data for historical relationships
  - ownership_chain_walk: Walk parent -> subsidiary ownership graph
  - regulatory_filing_mine: SEC, SAM.gov, FPDS, SBA indirect evidence
  - adversarial_media_scan: News/GDELT for entity + key terms

Wisdom Memory:
  - Persistent JSON file (axiom_wisdom.json) stores lessons learned
  - Before selecting approaches, consult wisdom to prioritize high-success methods
  - After each attempt, write back lessons for future decisions
  - Wisdom improves case officer judgment over time without requiring ML retraining
"""

import json
import logging
import time
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List
from pathlib import Path

from axiom_agent import (
    run_agent, SearchTarget, AgentResult, DiscoveredEntity, DiscoveredRelationship,
    _call_llm, _run_connector, DEFAULT_PROVIDER, DEFAULT_MODEL, SYSTEM_PROMPT, MAX_ITERATIONS
)
from knowledge_graph import get_kg_conn, get_entity_network, find_shortest_path
try:
    from graph_ingest import get_vendor_graph_summary
except ImportError:
    get_vendor_graph_summary = None
import db

logger = logging.getLogger(__name__)

# Wisdom memory file location
WISDOM_FILE = Path(__file__).parent / "axiom_wisdom.json"

# Gap type classifications
GAP_TYPES = {
    "subcontractor_identity",
    "ownership_chain",
    "contract_history",
    "personnel",
    "facility",
    "cyber_posture",
    "financial",
    "teaming_partner",
    "supply_chain",
    "operational_location"
}

# Advisory value estimation (in USD)
ADVISORY_VALUE_ESTIMATES = {
    "subcontractor_identity": (15000, 35000),
    "ownership_chain": (10000, 25000),
    "contract_history": (20000, 45000),
    "personnel": (5000, 15000),
    "facility": (10000, 30000),
    "cyber_posture": (15000, 40000),
    "teaming_partner": (8000, 20000),
    "supply_chain": (12000, 28000),
    "operational_location": (10000, 25000),
}

# Approach library: strategy patterns
APPROACH_LIBRARY = [
    {
        "name": "lateral_entity_search",
        "description": "Search for target entity under alternate names, DBAs, subsidiary names, historical names",
        "case_officer_reasoning": "The entity may have changed names, operates under a DBA, or is a subsidiary of a parent company. Cast the net wider."
    },
    {
        "name": "graph_pattern_inference",
        "description": "Query KG for entities connected to known associates. If A connects to B and C, check if B or C connect to the target.",
        "case_officer_reasoning": "Intelligence relationships often form through mutual connections. Secondary relationships often reveal what direct searches miss."
    },
    {
        "name": "proxy_indicator_hunt",
        "description": "Look for indirect evidence: job postings (hiring for clearances = contract indicator), press releases, subaward data, SBA filings",
        "case_officer_reasoning": "Companies often advertise their relationships before formal announcements. Operational requirements leak through hiring."
    },
    {
        "name": "cross_vehicle_correlation",
        "description": "Check if the same gap exists on related vehicles; if one vehicle has the data, trace it to others",
        "case_officer_reasoning": "Stable subcontractors often work across multiple related vehicles. What we know from one contract illuminates others."
    },
    {
        "name": "temporal_backtrack",
        "description": "Search older data sources for historical relationships. Data from 2 years ago may still reflect persistent relationships.",
        "case_officer_reasoning": "Defense supply chains are sticky. Yesterday's subcontractor is often today's. Look at archives and historical filings."
    },
    {
        "name": "ownership_chain_walk",
        "description": "Walk the ownership graph upward (parent -> subsidiary) and downward to find data at different corporate levels",
        "case_officer_reasoning": "If a subsidiary won't disclose, the parent company filings often will. Ownership data concentrates at the top."
    },
    {
        "name": "regulatory_filing_mine",
        "description": "Check SEC 10-Ks, 8-Ks, SAM.gov, FPDS, SBA subawards for data that indirectly fills the gap",
        "case_officer_reasoning": "Regulatory disclosures are legally binding. If a relationship involves government money, it's recorded somewhere."
    },
    {
        "name": "adversarial_media_scan",
        "description": "Search GDELT and news for entity + key intelligence terms that would indicate the relationship exists",
        "case_officer_reasoning": "What companies do together appears in news before formal announcements. Intelligence work generates paper trails."
    },
]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceGap:
    """A gap identified by the pipeline that needs filling."""
    gap_id: str
    description: str
    entity_name: str
    vehicle_name: str = ""
    gap_type: str = ""  # See GAP_TYPES
    priority: str = "medium"  # critical, high, medium, low
    original_classification: str = ""  # automated_search, network_query, foia, field_collection
    source_iteration: int = 0


@dataclass
class FillAttempt:
    """Record of a single attempt to fill a gap."""
    approach_name: str  # e.g., "lateral_entity_search"
    approach_reasoning: str  # Why the case officer chose this approach
    connectors_used: List[str] = field(default_factory=list)
    graph_queries_made: List[str] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    confidence_in_fill: float = 0.0  # 0.0 = nothing found, 1.0 = confirmed fill
    elapsed_ms: int = 0
    lesson_learned: str = ""  # What worked or didn't -- feeds wisdom memory


@dataclass
class GapFillResult:
    """Complete result of attempting to fill a gap."""
    gap: IntelligenceGap
    filled: bool = False
    fill_confidence: float = 0.0
    attempts: List[FillAttempt] = field(default_factory=list)
    final_classification: str = ""  # Reclassified: automated_search, network_query, foia, field_collection, filled
    advisory_value_estimate: float = 0.0  # Dollar estimate if this becomes advisory
    advisory_scope: str = ""  # Proposed scope for advisory engagement
    wisdom_entry: str = ""  # Lesson for wisdom memory
    elapsed_ms: int = 0


@dataclass
class WisdomEntry:
    """A lesson learned from gap-filling attempts."""
    entry_id: str
    gap_type: str  # What kind of gap was being filled
    approach_used: str  # Which approach was tried
    worked: bool  # Did it succeed?
    entity_type: str  # company, person, vehicle, etc.
    sector: str  # defense, intelligence, logistics, etc.
    lesson: str  # Natural language lesson
    confidence_impact: float  # How much this improved confidence
    timestamp: str


# ---------------------------------------------------------------------------
# Wisdom Memory Management
# ---------------------------------------------------------------------------

def load_wisdom() -> List[dict]:
    """Load the wisdom memory from disk."""
    if not WISDOM_FILE.exists():
        logger.info(f"No wisdom file found at {WISDOM_FILE}; starting with empty wisdom")
        return []
    
    try:
        with open(WISDOM_FILE, 'r') as f:
            wisdom = json.load(f)
            logger.info(f"Loaded {len(wisdom)} wisdom entries from {WISDOM_FILE}")
            return wisdom
    except Exception as e:
        logger.error(f"Failed to load wisdom from {WISDOM_FILE}: {e}")
        return []


def save_wisdom(entries: List[dict]) -> None:
    """Save wisdom entries to disk."""
    try:
        WISDOM_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WISDOM_FILE, 'w') as f:
            json.dump(entries, f, indent=2)
        logger.info(f"Saved {len(entries)} wisdom entries to {WISDOM_FILE}")
    except Exception as e:
        logger.error(f"Failed to save wisdom to {WISDOM_FILE}: {e}")


def consult_wisdom(gap: IntelligenceGap, wisdom: List[dict]) -> List[str]:
    """
    Given a gap, return prioritized list of approaches based on historical success.
    Approaches that have succeeded for similar gaps are ranked first.
    """
    if not wisdom:
        # No wisdom yet; return approaches in default order
        return [a["name"] for a in APPROACH_LIBRARY]
    
    # Score each approach based on success rate for this gap type
    approach_scores = {}
    for approach in APPROACH_LIBRARY:
        approach_name = approach["name"]
        
        # Find wisdom entries for this approach + gap type
        relevant_entries = [
            w for w in wisdom
            if w.get("approach_used") == approach_name and w.get("gap_type") == gap.gap_type
        ]
        
        if not relevant_entries:
            # No history; neutral score
            approach_scores[approach_name] = 0.5
        else:
            # Calculate success rate
            successes = len([w for w in relevant_entries if w.get("worked")])
            success_rate = successes / len(relevant_entries)
            
            # Weight by recency: recent entries count more
            now = datetime.now(timezone.utc).timestamp()
            avg_recency = 0
            for w in relevant_entries:
                try:
                    entry_time = datetime.fromisoformat(w.get("timestamp", "")).timestamp()
                    age_days = (now - entry_time) / 86400
                    recency = max(0, 1 - (age_days / 365))  # Decay over 1 year
                    avg_recency += recency
                except:
                    pass
            
            avg_recency = avg_recency / len(relevant_entries) if relevant_entries else 0.5
            approach_scores[approach_name] = success_rate * 0.7 + avg_recency * 0.3
    
    # Return approaches sorted by score (highest first)
    sorted_approaches = sorted(
        approach_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return [name for name, score in sorted_approaches]


# ---------------------------------------------------------------------------
# Advisory Value Estimation
# ---------------------------------------------------------------------------

def estimate_advisory_value(gap: IntelligenceGap) -> tuple[float, str]:
    """
    Estimate the dollar value of an advisory engagement if this gap becomes
    an advisory scope item.
    
    Returns: (mid_point_estimate, scope_description)
    """
    gap_type = gap.gap_type
    
    if gap_type not in ADVISORY_VALUE_ESTIMATES:
        # Default estimate
        return (15000, f"Intelligence assessment of {gap.gap_type}")
    
    low, high = ADVISORY_VALUE_ESTIMATES[gap_type]
    mid_point = (low + high) / 2
    
    # Build scope description
    scope_map = {
        "subcontractor_identity": f"Identify and profile subcontractors on {gap.vehicle_name}",
        "ownership_chain": f"Map ownership chain and beneficial owners of {gap.entity_name}",
        "contract_history": f"Trace contract history and vehicle evolution for {gap.vehicle_name}",
        "personnel": f"Profile key personnel and organizational structure of {gap.entity_name}",
        "facility": f"Intelligence assessment of facility operations at {gap.description}",
        "cyber_posture": f"Cyber posture and infrastructure assessment of {gap.entity_name}",
        "teaming_partner": f"Identify and validate teaming partners for {gap.vehicle_name}",
        "supply_chain": f"Map supply chain and vendor relationships for {gap.vehicle_name}",
        "operational_location": f"Operational location analysis and facility footprint for {gap.entity_name}",
    }
    
    scope = scope_map.get(gap_type, f"Intelligence assessment: {gap.description}")
    
    return (mid_point, scope)


# ---------------------------------------------------------------------------
# LLM-Driven Case Officer Logic
# ---------------------------------------------------------------------------

def _get_case_officer_system_prompt() -> str:
    """
    Generate the system prompt that instructs the LLM to think like a wise,
    experienced intelligence case officer rather than a search engine.
    """
    return """You are a wise, experienced intelligence case officer with 20+ years of HUMINT and OSINT
collection experience. You have deep knowledge of defense contractors, supply chains, and how intelligence
relationships form and persist.

Your core mission: Fill intelligence gaps using creative, unconventional approaches.

Key behaviors:
1. THINK LATERALLY: Consider indirect indicators. A company hiring for TS/SCI at a specific location
   is often a signal they're a subcontractor on a contract there.

2. QUERY THE NETWORK: The knowledge graph contains 2nd and 3rd order connections. If A works with B
   and C, and you need data on D, check if B or C connect to D. Intelligence relationships form through
   mutual acquaintances.

3. USE PROXY DATA: If you can't find the direct answer, look at subaward reports, SBA filings, joint
   ventures, press releases, regulatory disclosures. The data exists somewhere; you must find where.

4. PATTERN MATCH: If LEIA has subcontractors X and Y, check if C3PO (a similar vehicle) has the same
   ones. Stable relationships persist across multiple vehicles.

5. RESPECT TIME DECAY: Data from 2 years ago may still be valid for persistent relationships. Defense
   supply chains are sticky. Look at archives, historical filings, old news.

6. WALK THE OWNERSHIP CHAIN: If a subsidiary won't disclose, the parent company will. Ownership data
   concentrates at the top of the organizational hierarchy.

7. REFLECT AND LEARN: After each attempt, analyze what worked and why. Build institutional wisdom.
   Document your lessons so future case officers can learn from your experience.

You are not trying to be smarter or faster. You are trying to become WISER by learning from patterns,
successes, and failures. Your goal is to help the human analyst make better decisions."""


def _run_gap_filling_iteration(
    gap: IntelligenceGap,
    approach: dict,
    wisdom: List[dict],
    api_key: str,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
) -> FillAttempt:
    """
    Execute a single gap-filling iteration using the selected approach.
    
    Flow:
    1. Consult wisdom for relevant lessons
    2. Query KG for related entity network
    3. Ask LLM to reason about the approach and execute it
    4. Collect findings and score confidence
    5. Reflect on what worked
    6. Record lesson for wisdom
    """
    attempt = FillAttempt(
        approach_name=approach["name"],
        approach_reasoning=approach["case_officer_reasoning"]
    )
    
    start_time = time.time()
    
    try:
        # Step 1: Build context about the entity from KG
        kg_context = ""
        try:
            kg_conn = get_kg_conn()
            # Get summary of vendor graph if available
            graph_summary = get_vendor_graph_summary(kg_conn, gap.entity_name) if callable(get_vendor_graph_summary) else None
            if graph_summary:
                kg_context = f"Knowledge Graph Context:\n{json.dumps(graph_summary, indent=2)}\n\n"
        except Exception as e:
            logger.warning(f"Could not fetch KG context for {gap.entity_name}: {e}")
        
        # Step 2: Look up relevant wisdom
        relevant_wisdom = [
            w for w in wisdom
            if w.get("approach_used") == approach["name"]
        ]
        wisdom_summary = ""
        if relevant_wisdom:
            wisdom_summary = "Historical Lessons for this Approach:\n"
            for w in relevant_wisdom[:3]:  # Top 3 most relevant
                status = "WORKED" if w.get("worked") else "DIDN'T WORK"
                wisdom_summary += f"  - {status}: {w.get('lesson')}\n"
            wisdom_summary += "\n"
        
        # Step 3: Build the case officer prompt
        prompt = f"""
Intelligence Gap to Fill:
  Gap ID: {gap.gap_id}
  Description: {gap.description}
  Entity: {gap.entity_name}
  Vehicle: {gap.vehicle_name}
  Gap Type: {gap.gap_type}
  Priority: {gap.priority}

Approach to Try: {approach['name']}
  Description: {approach['description']}
  Reasoning: {approach['case_officer_reasoning']}

{wisdom_summary}
{kg_context}

Your Task:
1. Analyze whether this approach is likely to work for this specific gap
2. If pursuing, describe what connectors, searches, or queries you would execute
3. Based on your case officer judgment, rate the confidence that this approach will fill the gap (0-1)
4. List any findings or evidence that might fill the gap
5. Explain what you learned about this gap type and approach combination

Respond in JSON format:
{{
  "will_pursue": true/false,
  "reasoning": "Why or why not pursue this approach",
  "connectors_to_try": ["connector1", "connector2"],
  "queries": ["query1", "query2"],
  "findings": [
    {{"source": "connector_or_search", "evidence": "what was found", "confidence": 0.8}}
  ],
  "confidence_in_fill": 0.0 to 1.0,
  "lesson_learned": "What did you learn about filling {gap.gap_type} gaps?",
  "next_approach_if_fails": "name of next approach to try"
}}
"""
        
        # Step 4: Call LLM
        response_text = _call_llm(
            prompt=prompt,
            system=_get_case_officer_system_prompt(),
            provider=provider,
            model=model,
            api_key=api_key
        )
        
        # Step 5: Parse response
        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response = json.loads(json_match.group())
            else:
                response = {}
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON; treating as unsuccessful attempt")
            response = {}
        
        # Step 6: Execute connectors if indicated
        if response.get("will_pursue"):
            for connector_name in response.get("connectors_to_try", []):
                try:
                    result = _run_connector(
                        connector_name,
                        gap.entity_name,
                        vehicle=gap.vehicle_name,
                        context=gap.description
                    )
                    if result:
                        attempt.connectors_used.append(connector_name)
                        attempt.findings.append({
                            "source": connector_name,
                            "data": result,
                            "confidence": response.get("confidence_in_fill", 0.5)
                        })
                except Exception as e:
                    logger.warning(f"Connector {connector_name} failed: {e}")
        
        # Step 7: Extract findings and confidence
        attempt.findings = response.get("findings", [])
        attempt.confidence_in_fill = response.get("confidence_in_fill", 0.0)
        attempt.lesson_learned = response.get("lesson_learned", "")
        
    except Exception as e:
        logger.error(f"Error during gap-filling iteration for {gap.gap_id}: {e}")
        attempt.lesson_learned = f"Attempt failed with error: {str(e)}"
    
    attempt.elapsed_ms = int((time.time() - start_time) * 1000)
    return attempt


def fill_single_gap(
    gap: IntelligenceGap,
    api_key: str,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    max_attempts: int = 3,
    wisdom: List[dict] = None,
) -> GapFillResult:
    """
    Fill a single intelligence gap with 2-5 approach attempts.
    
    Flow:
    1. Load wisdom
    2. Consult wisdom to get prioritized approach list
    3. For each attempt (up to max_attempts):
       a. Select next approach from prioritized list
       b. Execute iteration
       c. If confidence >= 0.7, mark filled and stop
       d. If confidence < 0.7 and attempts remain, try next approach
    4. After all attempts:
       a. Generate final classification
       b. Estimate advisory value if not filled
       c. Create wisdom entry
    """
    if wisdom is None:
        wisdom = load_wisdom()
    
    result = GapFillResult(gap=gap)
    start_time = time.time()
    
    try:
        # Get prioritized approach list
        prioritized_approaches = consult_wisdom(gap, wisdom)
        approach_objs = {a["name"]: a for a in APPROACH_LIBRARY}
        
        # Execute up to max_attempts
        for attempt_num in range(max_attempts):
            if attempt_num >= len(prioritized_approaches):
                break
            
            approach_name = prioritized_approaches[attempt_num]
            approach = approach_objs.get(approach_name, APPROACH_LIBRARY[0])
            
            logger.info(f"Gap {gap.gap_id}: Attempt {attempt_num + 1}/{max_attempts}, approach={approach_name}")
            
            # Execute iteration
            attempt = _run_gap_filling_iteration(
                gap=gap,
                approach=approach,
                wisdom=wisdom,
                api_key=api_key,
                provider=provider,
                model=model
            )
            
            result.attempts.append(attempt)
            
            # Check if gap is filled
            if attempt.confidence_in_fill >= 0.7:
                result.filled = True
                result.fill_confidence = attempt.confidence_in_fill
                result.final_classification = "filled"
                result.wisdom_entry = f"Successfully filled {gap.gap_type} using {approach_name}. {attempt.lesson_learned}"
                logger.info(f"Gap {gap.gap_id} filled with confidence {attempt.confidence_in_fill}")
                break
        
        # If not filled, estimate advisory value
        if not result.filled:
            estimate, scope = estimate_advisory_value(gap)
            result.advisory_value_estimate = estimate
            result.advisory_scope = scope
            result.final_classification = gap.original_classification or "network_query"
            
            # Compile lessons for wisdom
            lessons = [a.lesson_learned for a in result.attempts if a.lesson_learned]
            result.wisdom_entry = f"Could not fill {gap.gap_type}. Lessons: {'; '.join(lessons)}"
            
            logger.info(f"Gap {gap.gap_id} not filled; estimated advisory value: ${estimate:,.0f}")
        
        # Update times
        result.elapsed_ms = int((time.time() - start_time) * 1000)
        
        # Add to wisdom
        for attempt in result.attempts:
            wisdom_entry = {
                "entry_id": f"{gap.gap_id}_{attempt.approach_name}_{int(time.time())}",
                "gap_type": gap.gap_type,
                "approach_used": attempt.approach_name,
                "worked": attempt.confidence_in_fill >= 0.7,
                "entity_type": "company",  # TODO: infer from gap context
                "sector": "defense",  # TODO: infer from vehicle/entity
                "lesson": attempt.lesson_learned,
                "confidence_impact": attempt.confidence_in_fill,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            wisdom.append(wisdom_entry)
        
        # Save updated wisdom
        save_wisdom(wisdom)
    
    except Exception as e:
        logger.error(f"Exception filling gap {gap.gap_id}: {e}")
        result.final_classification = "error"
        result.wisdom_entry = f"Gap filling error: {str(e)}"
    
    return result


def fill_gaps(
    gaps: List[IntelligenceGap],
    api_key: str = "",
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    user_id: str = "",
    max_attempts_per_gap: int = 3,
) -> List[GapFillResult]:
    """
    Attempt to fill a list of intelligence gaps using the Wise Case Officer pattern.
    
    Returns results for each gap, including whether it was filled, how, and lessons learned.
    """
    logger.info(f"Starting gap filling for {len(gaps)} gaps, max_attempts={max_attempts_per_gap}")
    
    # Load wisdom once at start
    wisdom = load_wisdom()
    
    results = []
    for gap in gaps:
        try:
            result = fill_single_gap(
                gap=gap,
                api_key=api_key,
                provider=provider,
                model=model,
                max_attempts=max_attempts_per_gap,
                wisdom=wisdom
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to fill gap {gap.gap_id}: {e}")
            result = GapFillResult(
                gap=gap,
                final_classification="error",
                wisdom_entry=f"Error: {str(e)}"
            )
            results.append(result)
    
    # Summary
    filled_count = len([r for r in results if r.filled])
    total_advisory_value = sum([r.advisory_value_estimate for r in results if not r.filled])
    
    logger.info(
        f"Gap filling complete: {filled_count}/{len(gaps)} filled, "
        f"${total_advisory_value:,.0f} potential advisory value"
    )
    
    return results


# ---------------------------------------------------------------------------
# Integration with Helios Pipeline
# ---------------------------------------------------------------------------

def ingest_gap_fill_results(results: List[GapFillResult], case_id: str = "") -> dict:
    """
    Ingest gap-fill results into Helios database and KG.
    
    For filled gaps, add entities/relationships to KG.
    For unfilled gaps, create advisory opportunities.
    
    Returns summary dict.
    """
    summary = {
        "case_id": case_id,
        "total_gaps": len(results),
        "filled": 0,
        "unfilled": 0,
        "advisory_opportunities": [],
        "kg_entities_added": 0,
        "kg_relationships_added": 0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        for result in results:
            if result.filled:
                summary["filled"] += 1
                # TODO: Ingest filled entities/relationships into KG
            else:
                summary["unfilled"] += 1
                # Create advisory opportunity
                advisory = {
                    "gap_id": result.gap.gap_id,
                    "description": result.gap.description,
                    "entity": result.gap.entity_name,
                    "vehicle": result.gap.vehicle_name,
                    "gap_type": result.gap.gap_type,
                    "estimated_value": result.advisory_value_estimate,
                    "scope": result.advisory_scope,
                    "case_id": case_id
                }
                summary["advisory_opportunities"].append(advisory)
    
    except Exception as e:
        logger.error(f"Error ingesting gap-fill results: {e}")
    
    return summary


# ---------------------------------------------------------------------------
# Main / Testing
# ---------------------------------------------------------------------------

def main():
    """Test the gap filler with sample gaps."""
    logging.basicConfig(level=logging.INFO)
    
    # Sample gaps for testing
    sample_gaps = [
        IntelligenceGap(
            gap_id="GAP-001",
            description="Unknown subcontractors on LEIA contract vehicle",
            entity_name="LEIA Program Office",
            vehicle_name="LEIA (Logistics Excellence Intelligence Architecture)",
            gap_type="subcontractor_identity",
            priority="high",
            original_classification="network_query"
        ),
        IntelligenceGap(
            gap_id="GAP-002",
            description="Beneficial ownership structure unclear for TechDefense Corp",
            entity_name="TechDefense Corp",
            vehicle_name="C3PO (Cyber Command Protection Operations)",
            gap_type="ownership_chain",
            priority="critical",
            original_classification="automated_search"
        ),
    ]
    
    # Run gap filler
    # results = fill_gaps(sample_gaps, api_key="<your-api-key>")
    
    # Print results
    # for result in results:
    #     print(f"\n{result.gap.gap_id}:")
    #     print(f"  Filled: {result.filled}")
    #     print(f"  Confidence: {result.fill_confidence:.2f}")
    #     print(f"  Attempts: {len(result.attempts)}")
    #     if not result.filled:
    #         print(f"  Advisory Value: ${result.advisory_value_estimate:,.0f}")


if __name__ == "__main__":
    main()
