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
import os
import re
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from ai_lane_routing import build_runtime_chain_for_lane, get_lane_policy

logger = logging.getLogger(__name__)

# Connector registry for OODA loop
try:
    from osint.connector_registry import CONNECTOR_REGISTRY, ACTIVE_CONNECTOR_ORDER
except ImportError:
    CONNECTOR_REGISTRY = {}
    ACTIVE_CONNECTOR_ORDER = []

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 5          # Maximum OODA loops before forced termination
MAX_FOLLOW_UPS_PER_ITER = 3 # Max follow-up queries per iteration
SCRAPE_DELAY = 2.0          # Seconds between scraper calls
LLM_TIMEOUT = 30            # Seconds for LLM API calls
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"

_ENV_PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

_FALLBACK_PROVIDER_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "gemini": "gemini-1.5-pro",
}


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
    connector_calls: list[dict] = field(default_factory=list)  # Track connector executions
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
    total_connector_calls: int = 0  # Track total connector executions
    intelligence_gaps: list[dict] = field(default_factory=list)
    advisory_opportunities: list[dict] = field(default_factory=list)
    vehicle_mode_support: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    runtime: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LaneExecutionProfile:
    """Execution profile that keeps broad collection and tactical pressure distinct."""
    use_initial_scraper: bool = True
    use_follow_up_search: bool = True
    reuse_connector_findings: bool = False
    scrape_delay_seconds: float = SCRAPE_DELAY
    connector_delay_seconds: float = 1.0
    max_iterations: int = MAX_ITERATIONS
    max_follow_up_queries: int = MAX_FOLLOW_UPS_PER_ITER
    max_connector_requests_per_iteration: int = 6
    max_parallel_connector_requests: int = 1
    llm_max_tokens: int = 4096
    raw_findings_limit: int = 20
    second_pass_raw_findings_limit: int = 10
    allow_follow_up_queries: bool = True
    allowed_connectors: tuple[str, ...] = ()
    prefetch_connector_plan: bool = False
    tactical_focus: str = ""
    tactical_instruction: str = ""


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

def _default_model_for_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower() or DEFAULT_PROVIDER
    try:
        from ai_analysis import PROVIDERS

        config = PROVIDERS.get(normalized)
        if config and getattr(config, "default_model", ""):
            return config.default_model
    except Exception:
        pass
    return _FALLBACK_PROVIDER_MODELS.get(normalized, DEFAULT_MODEL)


def _env_api_key_for_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    for env_var in _ENV_PROVIDER_KEYS.get(normalized, ()):
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return ""


def resolve_runtime_ai_credentials(
    *,
    user_id: str = "",
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    api_key: str = "",
    provider_locked: bool = False,
    model_locked: bool = False,
    lane_id: str = "mission_command",
) -> tuple[str, str, str]:
    """Resolve runtime LLM credentials from explicit args, stored config, then env fallback."""
    resolved_provider = str(provider or DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    resolved_model = str(model or "").strip() or _default_model_for_provider(resolved_provider)
    resolved_api_key = str(api_key or "").strip()
    lane_policy = get_lane_policy(lane_id)
    lane_primary = dict(lane_policy.get("primary") or {})

    if not provider_locked and str(provider or "").strip() in {"", DEFAULT_PROVIDER}:
        resolved_provider = str(lane_primary.get("provider") or resolved_provider).strip().lower() or resolved_provider
    if not model_locked and str(model or "").strip() in {"", DEFAULT_MODEL}:
        resolved_model = str(lane_primary.get("model") or resolved_model).strip() or resolved_model

    if resolved_api_key:
        return resolved_provider, resolved_model, resolved_api_key

    # Explicit provider overrides must be able to bind directly to env-backed keys
    # without being silently rewritten by lane defaults or stored org config.
    if provider_locked:
        env_key = _env_api_key_for_provider(resolved_provider)
        if env_key:
            return resolved_provider, resolved_model, env_key

    if user_id:
        try:
            from ai_analysis import get_ai_config

            config = get_ai_config(user_id)
            if config and config.get("api_key"):
                config_provider = str(config.get("provider") or resolved_provider).strip().lower() or resolved_provider
                if provider_locked and config_provider != resolved_provider:
                    config = None
                else:
                    config_model = str(config.get("model") or resolved_model).strip() or resolved_model
                    return (
                        resolved_provider if provider_locked else config_provider,
                        resolved_model if model_locked else config_model,
                        str(config.get("api_key") or "").strip(),
                    )
        except Exception as e:
            logger.warning("axiom_agent: could not retrieve AI config: %s", e)

    for idx, candidate in enumerate(build_runtime_chain_for_lane(lane_id)):
        fallback_provider = str(candidate.get("provider") or "").strip().lower()
        if not fallback_provider:
            continue
        fallback_model = str(candidate.get("model") or "").strip() or _default_model_for_provider(fallback_provider)
        if provider_locked and fallback_provider != resolved_provider:
            continue
        if model_locked and fallback_provider == resolved_provider and resolved_model:
            fallback_model = resolved_model
        fallback_key = _env_api_key_for_provider(fallback_provider)
        if not fallback_key:
            continue
        return fallback_provider, fallback_model, fallback_key

    if not provider_locked:
        for fallback_provider in _ENV_PROVIDER_KEYS:
            if fallback_provider == resolved_provider:
                continue
            fallback_key = _env_api_key_for_provider(fallback_provider)
            if not fallback_key:
                continue
            fallback_model = (
                resolved_model
                if model_locked and resolved_model
                else _default_model_for_provider(fallback_provider)
            )
            return fallback_provider, fallback_model, fallback_key

    return resolved_provider, resolved_model, ""

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

def _build_system_prompt_with_connectors() -> str:
    """Build system prompt that includes available connectors."""
    base = """You are AXIOM, an intelligence analyst specializing in government contract
vehicle analysis and subcontractor identification. You analyze job postings, company data,
and public records to map teaming relationships in the defense/intelligence community.

You operate in an iterative search loop. Each iteration:
1. You receive raw findings from web scraping
2. You extract entities and relationships
3. You decide what follow-up searches would yield the highest intelligence value
4. You may request targeted connector enrichments to fill intelligence gaps
5. You either generate follow-up queries or declare the search complete

Your outputs must be valid JSON matching the schema provided in each prompt.
Be precise with entity names (use official company names, not abbreviations).
Confidence scores: 0.3=speculative, 0.5=possible, 0.7=probable, 0.85=likely, 0.95=confirmed.

CONNECTOR CAPABILITIES:
You have access to the following OSINT connectors that can be invoked within your analysis loop
to enrich vendor intelligence. Request a connector by including a JSON object in your response with:
  "connector_requests": [
    {"name": "connector_name", "vendor_name": "company name", "parameters": {...}}
  ]

Available connectors by category:

GOVERNMENT & CONTRACTS (9):
  - sam_gov: US federal SAM.gov entity registration, UEI, CAGE, exclusions
  - sam_subaward_reporting: SAM.gov subcontract/subaward reporting data
  - usaspending: Federal spending and award history
  - fpds_contracts: Federal procurement contract history
  - sbir_awards: SBIR/STTR award history
  - dla_cage: Defense Logistics Agency CAGE registry
  - fara: DOJ Foreign Agents Registration Act filings
  - fedramp_marketplace: FedRAMP authorization and cloud service posture
  - piee_sprs: DoD supplier performance and cyber posture (authenticated)

SANCTIONS & RESTRICTED PARTIES (8):
  - ofac_sdn: Treasury Specially Designated Nationals
  - trade_csl: Commerce Dept Consolidated Screening List (13 lists)
  - un_sanctions: UN Security Council sanctions
  - eu_sanctions: European Commission sanctions
  - uk_hmt_sanctions: UK HM Treasury sanctions
  - opensanctions_pep: Politically exposed person screening
  - worldbank_debarred: World Bank/IDB/ADB debarments
  - dod_sam_exclusions: DoD SAM exclusions and EPLS checks

OWNERSHIP & CORPORATE (9):
  - sec_edgar: SEC filings, ownership, subsidiaries
  - gleif_lei: Legal Entity Identifiers, parent chains
  - opencorporates: Global corporate registry, officers
  - uk_companies_house: UK beneficial ownership register
  - corporations_canada: Canadian federal corporations
  - australia_abn_asic: Australian Business Register and ASIC
  - singapore_acra: Singapore entity profile
  - new_zealand_companies_office: NZ Companies Register
  - wikidata_company: Public knowledge graph company metadata

FINANCIAL & COMPLIANCE (8):
  - sec_xbrl: Structured SEC financial data
  - fdic_bankfind: FDIC bank regulatory data
  - epa_echo: EPA enforcement and compliance history
  - osha_safety: OSHA workplace safety records
  - cisa_kev: Known Exploited Vulnerabilities catalog
  - nvd_overlay: NIST NVD product and vulnerability overlay
  - osv_dev: Open source package vulnerability lookups
  - deps_dev: Open source package and advisory metadata

LITIGATION & ADVERSE MEDIA (4):
  - courtlistener: Federal/state court litigation records
  - recap_courts: Federal litigation archive and dockets
  - gdelt_media: Adverse media monitoring via GDELT
  - google_news: Real-time public news coverage

INTERNATIONAL REGISTRIES (5):
  - france_inpi_rne: French entity identity corroboration
  - netherlands_kvk: Dutch Chamber of Commerce
  - norway_brreg: Norwegian organization data
  - icij_offshore: Panama/Paradise/Pandora Papers
  - foci_artifact_upload: Customer FOCI artifact upload

Example connector request in your response:
  "connector_requests": [
    {
      "name": "sam_gov",
      "vendor_name": "SMX Technologies Inc",
      "parameters": {"country": "US"}
    },
    {
      "name": "fpds_contracts",
      "vendor_name": "SMX Technologies Inc",
      "parameters": {}
    }
  ]

Use connectors strategically to confirm suspected subcontractors, verify government relationships,
or fill critical intelligence gaps."""

    return base

SYSTEM_PROMPT = _build_system_prompt_with_connectors()


def _build_tactical_system_prompt(lane_profile: LaneExecutionProfile) -> str:
    connector_lines = "\n".join(f"- {name}" for name in (lane_profile.allowed_connectors or ()))
    return f"""You are AXIOM mission command.

This lane is tactical pressure, not broad exploration.
Return valid JSON only.
Use only the allowed connectors below when evidence is still thin:
{connector_lines}

Rules:
- Keep reasoning concise and decision-oriented.
- Prefer explicit abstention over speculative structure.
- Convert only strong connector-backed or graph-backed evidence into entities and relationships.
- If the pressure picture is good enough, close the search instead of asking for more work."""


def _build_system_prompt_for_lane(lane_profile: LaneExecutionProfile) -> str:
    if lane_profile.allowed_connectors:
        return _build_tactical_system_prompt(lane_profile)
    return SYSTEM_PROMPT


def _support_relationship_digest(relationships: list[dict]) -> list[dict]:
    digested: list[dict] = []
    for relationship in relationships[:6]:
        if not isinstance(relationship, dict):
            continue
        digested.append(
            {
                "rel_type": str(relationship.get("rel_type") or ""),
                "source": str(relationship.get("source_name") or ""),
                "target": str(relationship.get("target_name") or ""),
                "summary": str(relationship.get("evidence_summary") or relationship.get("evidence") or ""),
                "connector": str(relationship.get("data_source") or ""),
            }
        )
    return digested


def _support_event_digest(events: list[dict]) -> list[dict]:
    digested: list[dict] = []
    for event in events[:4]:
        if not isinstance(event, dict):
            continue
        digested.append(
            {
                "title": str(event.get("title") or event.get("subject") or "Observed event"),
                "status": str(event.get("status") or ""),
                "connector": str(event.get("connector") or ""),
                "assessment": str(event.get("assessment") or ""),
            }
        )
    return digested


def _support_finding_digest(findings: list[dict]) -> list[dict]:
    digested: list[dict] = []
    for finding in findings[:4]:
        if not isinstance(finding, dict):
            continue
        digested.append(
            {
                "title": str(finding.get("title") or ""),
                "detail": str(finding.get("detail") or ""),
                "source": str(finding.get("source") or ""),
                "severity": str(finding.get("severity") or ""),
            }
        )
    return digested


def _build_vehicle_mode_support(target: SearchTarget) -> dict:
    if not str(target.vehicle_name or "").strip():
        return {}

    state_contract = {
        "graph_facts": "Observed graph relationships and provenance-backed edges only.",
        "support_evidence": "Vehicle-scoped archive, notice, and protest support that is useful but not graph truth.",
        "predictions": "Forward-looking teaming and capture judgments only.",
        "unknowns": "Conflicts or missing evidence that should lower confidence.",
    }

    teaming_builder = globals().get("build_teaming_intelligence")
    if teaming_builder is None:
        try:
            from teaming_intelligence import build_teaming_intelligence as teaming_builder
        except Exception:
            teaming_builder = None

    support_builder = globals().get("build_vehicle_intelligence_support")
    if support_builder is None:
        try:
            from vehicle_intel_support import build_vehicle_intelligence_support as support_builder
        except Exception:
            support_builder = None

    support_bundle = None
    if support_builder is not None:
        try:
            support_bundle = support_builder(
                vehicle_name=target.vehicle_name,
                vendor={
                    "id": "",
                    "name": target.prime_contractor,
                    "vendor_input": {
                        "seed_metadata": {
                            "contract_vehicle_name": target.vehicle_name,
                        }
                    },
                },
            )
        except Exception:
            support_bundle = None

    observed_vendors = [{"vendor_name": target.prime_contractor, "role": "prime"}]
    observed_vendors.extend({"vendor_name": name, "role": "subcontractor"} for name in target.known_subs[:4])
    if isinstance(support_bundle, dict):
        observed_vendors.extend(
            dict(row)
            for row in (support_bundle.get("observed_vendors") or [])
            if isinstance(row, dict)
        )

    deduped_observed: dict[str, dict] = {}
    for row in observed_vendors:
        vendor_name = str(row.get("vendor_name") or "").strip()
        if not vendor_name:
            continue
        key = vendor_name.upper()
        existing = deduped_observed.get(key)
        try:
            candidate_amount = float(row.get("award_amount") or 0.0)
        except (TypeError, ValueError):
            candidate_amount = 0.0
        if existing is None:
            deduped_observed[key] = {
                "vendor_name": vendor_name,
                "role": str(row.get("role") or "prime"),
                "award_amount": candidate_amount,
            }
            continue
        if existing["role"] != str(row.get("role") or "prime"):
            existing["role"] = "prime+sub"
        if candidate_amount > existing["award_amount"]:
            existing["award_amount"] = candidate_amount

    teaming_report = None
    if teaming_builder is not None:
        try:
            teaming_report = teaming_builder(
                vehicle_name=target.vehicle_name,
                observed_vendors=list(deduped_observed.values()),
            )
        except Exception:
            teaming_report = None

    graph_facts = []
    predictions: list[str] = []
    unknowns: list[str] = []
    if isinstance(teaming_report, dict):
        for signal in teaming_report.get("observed_signals") or []:
            if not isinstance(signal, dict):
                continue
            graph_facts.append(
                {
                    "source": str(signal.get("source") or ""),
                    "target": str(signal.get("target") or ""),
                    "rel_type": str(signal.get("rel_type") or ""),
                    "connector": str(signal.get("connector") or ""),
                    "snippet": str(signal.get("snippet") or ""),
                }
            )
        predictions.extend(str(item) for item in (teaming_report.get("top_conclusions") or [])[:4] if str(item or "").strip())
        if not teaming_report.get("supported", True):
            unknowns.append(str(teaming_report.get("message") or "Vehicle teaming intelligence is not yet supported for this vehicle scope."))

    support_evidence = {
        "connectors_run": int((support_bundle or {}).get("connectors_run") or 0),
        "connectors_with_data": int((support_bundle or {}).get("connectors_with_data") or 0),
        "observed_vendors": list(deduped_observed.values())[:8],
        "relationships": _support_relationship_digest((support_bundle or {}).get("relationships") or []),
        "events": _support_event_digest((support_bundle or {}).get("events") or []),
        "findings": _support_finding_digest((support_bundle or {}).get("findings") or []),
    }

    if not graph_facts:
        unknowns.append("No graph-backed vehicle facts are attached strongly enough to drive the thread yet.")
    if support_evidence["connectors_with_data"] == 0:
        unknowns.append("No vehicle-scoped support evidence is attached yet.")
    if not support_evidence["events"]:
        unknowns.append("No protest or litigation signal is attached to this vehicle yet.")
    if not support_evidence["relationships"]:
        unknowns.append("No lineage or notice-derived relationship signal is attached to this vehicle yet.")

    return {
        "vehicle_name": target.vehicle_name,
        "state_contract": state_contract,
        "graph_facts": graph_facts[:6],
        "support_evidence": support_evidence,
        "predictions": predictions[:4],
        "unknowns": unknowns[:5],
    }


def _build_analysis_prompt(target: SearchTarget, raw_findings: list[dict],
                           iteration: int, previous_entities: list[str],
                           lane_profile: LaneExecutionProfile,
                           vehicle_mode_support: dict | None = None) -> str:
    """Build the LLM prompt for analyzing scraper results and requesting connectors."""
    findings_limit = (
        lane_profile.second_pass_raw_findings_limit
        if iteration > 1
        else lane_profile.raw_findings_limit
    )
    findings_slice = raw_findings[:findings_limit]
    previous_entities_slice = previous_entities[:8]
    vehicle_support_block = ""
    if vehicle_mode_support:
        vehicle_support_block = f"""

VEHICLE MODE SUPPORT (Aegis contract-vehicle context):
Treat the four blocks below as separate truth states. Do not silently merge them.

GRAPH_FACTS:
{json.dumps(vehicle_mode_support.get("graph_facts") or [], indent=2, default=str)}

SUPPORT_EVIDENCE:
{json.dumps(vehicle_mode_support.get("support_evidence") or {}, indent=2, default=str)}

PREDICTIONS:
{json.dumps(vehicle_mode_support.get("predictions") or [], indent=2, default=str)}

UNKNOWNS:
{json.dumps(vehicle_mode_support.get("unknowns") or [], indent=2, default=str)}

Rules:
- support_evidence can strengthen or weaken a hypothesis, but it is not graph fact
- predictions stay forward-looking unless independently confirmed
- if support_evidence conflicts with graph_facts, say so explicitly and lower confidence
"""
    lane_mode_block = ""
    if lane_profile.allowed_connectors:
        connector_lines = "\n".join(f"- {name}" for name in lane_profile.allowed_connectors)
        if iteration > 1:
            return f"""FINAL TACTICAL SYNTHESIS PASS

TARGET:
- Prime Contractor: {target.prime_contractor}
- Focus: {lane_profile.tactical_focus or 'tactical_pressure'}
- Context: {target.context or 'General contract vehicle intelligence'}
- Pressure instruction: {lane_profile.tactical_instruction or 'Close the pressure picture honestly.'}
{vehicle_support_block}

KNOWN ENTITIES: {', '.join(previous_entities_slice) if previous_entities_slice else 'None yet'}

CONNECTOR FINDINGS ({len(findings_slice)} items):
{json.dumps(findings_slice, indent=2, default=str)}

Return valid JSON:
{{
  "entities": [],
  "relationships": [],
  "connector_requests": [],
  "follow_up_queries": [],
  "reasoning": "Brief tactical readout of what holds and what stays thin",
  "intelligence_gaps": [],
  "search_complete": true
}}

Rules:
- Do not request more connectors.
- Do not generate follow-up queries.
- Keep reasoning under 70 words.
- Convert only strong evidence into structure.
- Ignore routine CDN, hosting, or generic service dependencies unless they materially change control-path or procurement posture.
- If ownership, control-path, teammate, or vehicle specifics stay weak, say so in intelligence_gaps instead of bluffing."""
        lane_mode_block = f"""

TACTICAL LANE CONSTRAINTS:
- Broad careers-style search is not available in this lane.
- Only the connectors below can run:
{connector_lines}
- Request at most {lane_profile.max_connector_requests_per_iteration} connectors this iteration.
- {"Do not generate follow-up web-search queries in this lane." if not lane_profile.allow_follow_up_queries else f"Generate at most {lane_profile.max_follow_up_queries} follow-up queries."}
- Close the search as soon as connector evidence is good enough to state what holds and what stays thin.
- Focus: {lane_profile.tactical_focus or 'tactical_pressure'}
- Pressure instruction: {lane_profile.tactical_instruction or 'Close the pressure picture honestly.'}
"""

    prompt_intro = "Analyze the following job board scraping results and connector findings for intelligence value."
    if lane_profile.allowed_connectors:
        prompt_intro = "Run a tactical pressure pass over the following evidence and decide the minimum next moves."

    return f"""{prompt_intro}

TARGET:
- Prime Contractor: {target.prime_contractor}
- Contract/Vehicle: {target.contract_name or target.vehicle_name or 'Not specified'}
- Installation: {target.installation or 'Not specified'}
- Known Subcontractors: {', '.join(target.known_subs) if target.known_subs else 'None'}
- Context: {target.context or 'General contract vehicle intelligence'}
{vehicle_support_block}
{lane_mode_block}

ITERATION: {iteration} of {lane_profile.max_iterations}
PREVIOUSLY DISCOVERED ENTITIES: {', '.join(previous_entities_slice) if previous_entities_slice else 'None yet'}

RAW FINDINGS ({len(findings_slice)} items):
{json.dumps(findings_slice, indent=2, default=str)}

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
  "connector_requests": [
    {{
      "name": "connector_name_from_list",
      "vendor_name": "Company Name",
      "parameters": {{"country": "US"}}
    }}
  ],
  "follow_up_queries": [
    "search query string that would yield high intelligence value"
  ],
  "reasoning": "Brief explanation of what you found and why you recommend the next pressure move",
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

CONNECTOR USAGE GUIDANCE:
Request connectors (via connector_requests array) when:
- You need to verify a company exists and find its official identifiers (sam_gov, sec_edgar, opencorporates)
- You need to confirm contract history or subcontract awards (fpds_contracts, usaspending, sam_subaward_reporting)
- You need to screen for sanctions, debarment, or exclusions (ofac_sdn, trade_csl, worldbank_debarred)
- You need to find ownership, parent companies, or subsidiaries (sec_edgar, gleif_lei, opencorporates)
- You need litigation or regulatory history (courtlistener, epa_echo, osha_safety)

Generate 0-{lane_profile.max_follow_up_queries} follow-up queries. Each should be specific and different from previous queries.
Focus follow-ups on: confirming suspected subs, finding additional subs, attributing positions to specific vehicles, identifying teaming partners.
Use connectors strategically to confirm key suspected entities before exhausting career site scraping."""


def _dedupe_connector_names(names: list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in names:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return tuple(ordered)


def _classify_mission_command_focus(target: SearchTarget) -> str:
    context = " ".join(
        filter(
            None,
            [
                str(target.context or ""),
                str(target.contract_name or ""),
                str(target.vehicle_name or ""),
            ],
        )
    ).lower()

    ownership = any(keyword in context for keyword in ("ownership", "owner", "control", "parent", "beneficial", "foci"))
    procurement = any(keyword in context for keyword in ("vehicle", "prime", "procurement", "customer", "subcontract", "teammate"))
    adverse = any(keyword in context for keyword in ("adverse", "litigation", "protest", "suit", "court"))

    if ownership and procurement:
        return "ownership_procurement"
    if ownership:
        return "ownership_control"
    if procurement:
        return "procurement_posture"
    if adverse:
        return "adverse_pressure"
    return "general_pressure"


def _mission_command_settings(target: SearchTarget) -> dict:
    focus = _classify_mission_command_focus(target)
    connectors_by_focus = {
        "ownership_control": [
            "public_search_ownership",
            "sec_edgar",
            "gleif_lei",
            "public_html_ownership",
            "sam_gov",
        ],
        "procurement_posture": [
            "fpds_contracts",
            "usaspending",
            "sam_subaward_reporting",
            "sam_gov",
        ],
        "ownership_procurement": [
            "public_search_ownership",
            "sec_edgar",
            "fpds_contracts",
            "sam_gov",
            "gleif_lei",
        ],
        "adverse_pressure": [
            "courtlistener",
            "epa_echo",
            "osha_safety",
            "sam_gov",
        ],
        "general_pressure": [
            "public_search_ownership",
            "fpds_contracts",
            "sam_subaward_reporting",
            "sam_gov",
            "usaspending",
        ],
    }
    instructions = {
        "ownership_control": "Prioritize who controls the entity, whether control-path confidence is real, and where ownership must stay unresolved.",
        "procurement_posture": "Prioritize prime posture, vehicle relevance, customer concentration, and teammate/sub visibility without overclaiming.",
        "ownership_procurement": "Prioritize control-path clarity first, then procurement posture. Do not trade ownership honesty for extra contract color.",
        "adverse_pressure": "Prioritize adverse records that materially change risk posture. Ignore generic negative noise.",
        "general_pressure": "Prioritize teammate visibility, vehicle posture, ownership walls, and prime-vs-sub reality for thinner mid-market cases. Keep weak edges explicit instead of defaulting to generic procurement color.",
    }
    connector_budget = 4 if focus == "general_pressure" else 3 if focus == "ownership_procurement" else 2
    return {
        "focus": focus,
        "allowed_connectors": _dedupe_connector_names(connectors_by_focus.get(focus, connectors_by_focus["general_pressure"]))[:7],
        "max_connector_requests_per_iteration": connector_budget,
        "tactical_instruction": instructions.get(focus, instructions["general_pressure"]),
    }


def _build_prefetched_connector_requests(
    target: SearchTarget,
    lane_profile: LaneExecutionProfile,
) -> list[dict]:
    requests: list[dict] = []
    for connector_name in (lane_profile.allowed_connectors or ())[: lane_profile.max_connector_requests_per_iteration]:
        params: dict = {}
        if connector_name == "sam_gov":
            params["country"] = "US"
        requests.append(
            {
                "name": connector_name,
                "vendor_name": target.prime_contractor,
                "parameters": params,
            }
        )
    return requests


_ROUTINE_DEPENDENCY_NAMES = (
    "CLOUDFLARE",
    "AKAMAI",
    "FASTLY",
    "AMAZON WEB SERVICES",
    "AWS",
    "MICROSOFT AZURE",
    "GOOGLE CLOUD",
    "GCP",
)


def _is_routine_dependency_entity_name(name: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()
    if not normalized:
        return False
    return any(token in normalized for token in _ROUTINE_DEPENDENCY_NAMES)


def _should_suppress_tactical_relationship(
    relationship: DiscoveredRelationship,
    lane_profile: LaneExecutionProfile,
) -> bool:
    if lane_profile.tactical_focus not in {"ownership_control", "ownership_procurement"}:
        return False
    if relationship.rel_type in {"related_entity", "depends_on_service", "depends_on_network"}:
        return _is_routine_dependency_entity_name(relationship.source_entity) or _is_routine_dependency_entity_name(relationship.target_entity)
    return False


def _prune_relationships_for_lane(
    relationships: list[DiscoveredRelationship],
    lane_profile: LaneExecutionProfile,
) -> list[DiscoveredRelationship]:
    if lane_profile.tactical_focus not in {"ownership_control", "ownership_procurement", "procurement_posture"}:
        return relationships

    priority = {
        "owned_by": 0,
        "beneficially_owned_by": 0,
        "backed_by": 1,
        "parent_of": 1,
        "subsidiary_of": 2,
        "contracts_with": 3,
        "former_name": 4,
    }
    per_type_limits = {
        "subsidiary_of": 8,
        "contracts_with": 4,
        "former_name": 2,
    }
    kept: list[DiscoveredRelationship] = []
    counts: dict[str, int] = {}
    ordered = sorted(
        relationships,
        key=lambda rel: (
            priority.get(rel.rel_type, 9),
            -float(rel.confidence or 0.0),
            rel.source_entity,
            rel.target_entity,
        ),
    )
    for relationship in ordered:
        rel_type = relationship.rel_type
        if counts.get(rel_type, 0) >= per_type_limits.get(rel_type, 999):
            continue
        kept.append(relationship)
        counts[rel_type] = counts.get(rel_type, 0) + 1
        if len(kept) >= 16:
            break
    return kept


def _build_lane_execution_profile(lane_id: str) -> LaneExecutionProfile:
    normalized = str(lane_id or "").strip().lower()
    if normalized == "mission_command":
        return LaneExecutionProfile(
            use_initial_scraper=False,
            use_follow_up_search=False,
            reuse_connector_findings=True,
            scrape_delay_seconds=0.0,
            connector_delay_seconds=0.0,
            max_iterations=2,
            max_follow_up_queries=0,
            max_connector_requests_per_iteration=2,
            max_parallel_connector_requests=3,
            llm_max_tokens=2200,
            raw_findings_limit=12,
            second_pass_raw_findings_limit=8,
            allow_follow_up_queries=False,
            prefetch_connector_plan=True,
        )
    return LaneExecutionProfile()


def _build_tactical_seed_findings(target: SearchTarget, lane_id: str) -> list[dict]:
    return [
        {
            "category": "tactical_seed",
            "title": f"{target.prime_contractor} tactical pressure seed",
            "detail": (
                f"{lane_id} is running in tactical mode. Broad careers-style search is intentionally skipped. "
                "Work from connector evidence, graph context, and the named pressure thread."
            ),
            "severity": "info",
            "confidence": 0.58,
            "source": f"lane:{lane_id}",
        }
    ]


def _filter_connector_requests(
    connector_requests: list[dict],
    lane_profile: LaneExecutionProfile,
) -> list[dict]:
    allowed = set(lane_profile.allowed_connectors or ())
    filtered: list[dict] = []
    for conn_req in connector_requests:
        if not isinstance(conn_req, dict):
            continue
        name = str(conn_req.get("name") or "").strip()
        if not name:
            continue
        if allowed and name not in allowed:
            logger.info("axiom_agent: skipping connector '%s' outside tactical window", name)
            continue
        filtered.append(conn_req)
        if len(filtered) >= lane_profile.max_connector_requests_per_iteration:
            break
    return filtered


def _execute_connector_request(
    conn_req: dict,
) -> dict:
    conn_name = str(conn_req.get("name") or "").strip()
    vendor = str(conn_req.get("vendor_name") or "").strip()
    params = conn_req.get("parameters", {})
    if not conn_name or not vendor:
        return {
            "success": False,
            "connector_name": conn_name or "unknown",
            "vendor_name": vendor or "unknown",
            "error": "Incomplete connector request",
        }
    logger.info(
        "axiom_agent: executing connector '%s' for vendor '%s'",
        conn_name, vendor
    )
    return _run_connector(conn_name, vendor, **params)


def _execute_connector_requests(
    connector_requests: list[dict],
    lane_profile: LaneExecutionProfile,
) -> list[dict]:
    if not connector_requests:
        return []
    if lane_profile.max_parallel_connector_requests <= 1 or len(connector_requests) <= 1:
        return [_execute_connector_request(conn_req) for conn_req in connector_requests]

    results: list[dict | None] = [None] * len(connector_requests)
    max_workers = min(lane_profile.max_parallel_connector_requests, len(connector_requests))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="axiom-connector") as executor:
        future_to_index = {
            executor.submit(_execute_connector_request, conn_req): idx
            for idx, conn_req in enumerate(connector_requests)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            conn_req = connector_requests[idx]
            try:
                results[idx] = future.result()
            except Exception as exc:
                results[idx] = {
                    "success": False,
                    "connector_name": str(conn_req.get("name") or "unknown"),
                    "vendor_name": str(conn_req.get("vendor_name") or "unknown"),
                    "error": str(exc),
                }
    return [result or {} for result in results]


def _build_connector_summary_finding(conn_result: dict) -> dict | None:
    connector_name = str(conn_result.get("connector_name") or "").strip()
    if not connector_name:
        return None
    findings = conn_result.get("findings") or []
    relationship_count = int(conn_result.get("relationship_count") or 0)
    identifiers = dict(conn_result.get("identifiers") or {})
    structured_fields = dict(conn_result.get("structured_fields") or {})
    finding_titles = [
        str(item.get("title") or "").strip()
        for item in findings
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ][:3]
    fragments: list[str] = []
    if findings:
        fragments.append(f"{len(findings)} finding(s)")
    if relationship_count:
        fragments.append(f"{relationship_count} relationship(s)")
    if identifiers:
        fragments.append(f"identifiers: {', '.join(sorted(identifiers.keys())[:5])}")
    top_customers = [str(item).strip() for item in (structured_fields.get("top_customers") or []) if str(item).strip()]
    if top_customers:
        fragments.append(f"top customers: {', '.join(top_customers[:3])}")
    dod_customers = [str(item).strip() for item in (structured_fields.get("dod_customers") or []) if str(item).strip()]
    if dod_customers:
        fragments.append(f"DoD customers: {', '.join(dod_customers[:3])}")
    beneficial_owner_count = structured_fields.get("beneficial_ownership_filing_count")
    if beneficial_owner_count not in (None, "", [], {}):
        fragments.append(f"beneficial ownership filings: {beneficial_owner_count}")
    insider_filing_count = structured_fields.get("insider_filing_count")
    if insider_filing_count not in (None, "", [], {}):
        fragments.append(f"insider filings: {insider_filing_count}")
    subsidiary_count = structured_fields.get("subsidiary_count")
    if subsidiary_count not in (None, "", [], {}):
        fragments.append(f"subsidiaries: {subsidiary_count}")
    largest_award = structured_fields.get("largest_award") or {}
    if isinstance(largest_award, dict):
        largest_award_agency = str(largest_award.get("agency") or "").strip()
        largest_award_value = largest_award.get("amount")
        if largest_award_agency and largest_award_value not in (None, "", [], {}):
            try:
                fragments.append(f"largest award: ${float(largest_award_value):,.0f} from {largest_award_agency}")
            except Exception:
                fragments.append(f"largest award: {largest_award_value} from {largest_award_agency}")
    if structured_fields:
        fragments.append(f"structured: {', '.join(sorted(structured_fields.keys())[:5])}")
    if finding_titles:
        fragments.append(f"highlights: {'; '.join(finding_titles)}")
    if not fragments:
        fragments.append("connector ran but returned thin evidence")
    return {
        "category": "connector_summary",
        "title": f"{connector_name} tactical summary",
        "detail": ". ".join(fragments),
        "source": f"connector:{connector_name}",
        "severity": "info",
        "confidence": 0.7 if conn_result.get("has_data") else 0.5,
        "connector_source": connector_name,
    }


def _merge_entity_attributes(existing: dict, updates: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (updates or {}).items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if isinstance(current, list) or isinstance(value, list):
            current_list = current if isinstance(current, list) else ([current] if current not in (None, "", [], {}) else [])
            value_list = value if isinstance(value, list) else [value]
            merged[key] = list(dict.fromkeys([item for item in current_list + value_list if item not in (None, "", [], {})]))
            continue
        if current in (None, "", [], {}):
            merged[key] = value
    return merged


def _select_target_structured_fields(structured_fields: dict) -> dict:
    allowed_keys = {
        "beneficial_ownership_filing_count",
        "most_recent_beneficial_ownership_filing",
        "insider_filing_count",
        "recent_insider_filing_count",
        "subsidiary_count",
        "top_customers",
        "dod_customers",
        "largest_award",
    }
    selected: dict = {}
    for key in allowed_keys:
        value = structured_fields.get(key)
        if value in (None, "", [], {}):
            continue
        selected[key] = value
    return selected


def _normalize_connector_relationship(
    relationship: dict,
    *,
    vendor_name: str,
) -> DiscoveredRelationship | None:
    if not isinstance(relationship, dict):
        return None
    rel_type = str(relationship.get("rel_type") or relationship.get("type") or "related_entity").strip() or "related_entity"
    source_entity = str(relationship.get("source_entity") or relationship.get("source_name") or "").strip()
    target_entity = str(
        relationship.get("target_entity")
        or relationship.get("target_name")
        or relationship.get("entity")
        or relationship.get("former_name")
        or ""
    ).strip()

    if rel_type == "former_name_match":
        rel_type = "former_name"

    if not source_entity:
        if rel_type == "subsidiary_of" and target_entity:
            source_entity = target_entity
            target_entity = vendor_name
        elif target_entity:
            source_entity = vendor_name

    if not source_entity or not target_entity:
        return None

    evidence = [
        text
        for text in (
            str(relationship.get("evidence_summary") or "").strip(),
            str(relationship.get("evidence") or "").strip(),
            str(relationship.get("snippet") or "").strip(),
            str(relationship.get("detail") or "").strip(),
        )
        if text
    ]
    if not evidence:
        evidence = [f"Connector returned a {rel_type} relationship."]

    attributes = {}
    structured_fields = relationship.get("structured_fields")
    if isinstance(structured_fields, dict) and structured_fields:
        attributes = _merge_entity_attributes(attributes, structured_fields)
    for key in ("data_source", "jurisdiction", "sec_role", "filing_date", "form_type", "evidence_title"):
        value = relationship.get(key)
        if value not in (None, "", [], {}):
            attributes[key] = value

    return DiscoveredRelationship(
        source_entity=source_entity,
        target_entity=target_entity,
        rel_type=rel_type,
        confidence=float(relationship.get("confidence") or 0.72),
        evidence=evidence,
        attributes=attributes,
    )


# ---------------------------------------------------------------------------
# Connector integration
# ---------------------------------------------------------------------------

def _run_connector(connector_name: str, vendor_name: str, **kwargs) -> dict:
    """
    Dynamically import and execute a registered connector.

    Args:
        connector_name: Key from CONNECTOR_REGISTRY (e.g., "sam_gov")
        vendor_name: Target vendor/company name
        **kwargs: Additional parameters for the connector (country, ids, etc.)

    Returns:
        Dict with keys:
          - success (bool): Whether connector executed without error
          - connector_name (str): The connector that was called
          - vendor_name (str): The vendor queried
          - findings_count (int): Number of findings returned
          - findings (list): Simplified finding dicts for LLM consumption
          - identifiers (dict): Any discovered identifiers (UEI, CIK, LEI, etc.)
          - error (str): Error message if connector failed
          - elapsed_ms (int): Execution time
    """
    result = {
        "success": False,
        "connector_name": connector_name,
        "vendor_name": vendor_name,
        "findings_count": 0,
        "findings": [],
        "has_data": False,
        "identifiers": {},
        "relationship_count": 0,
        "relationships": [],
        "structured_fields": {},
        "error": "",
        "elapsed_ms": 0,
    }

    # Verify connector is registered
    if connector_name not in CONNECTOR_REGISTRY:
        result["error"] = f"Unknown connector: {connector_name}. Available: {', '.join(ACTIVE_CONNECTOR_ORDER)}"
        return result

    try:
        start = datetime.now(timezone.utc)

        # Dynamically import connector module
        module_name = f"osint.{connector_name}"
        module = __import__(module_name, fromlist=["enrich"])
        enrich_func = getattr(module, "enrich", None)

        if not enrich_func:
            result["error"] = f"Connector {connector_name} has no enrich() function"
            return result

        # Call the connector with standard interface
        enrichment = enrich_func(vendor_name=vendor_name, **kwargs)

        # Convert EnrichmentResult to simplified findings for LLM
        findings = []
        for f in enrichment.findings:
            findings.append({
                "source": f.source,
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "severity": f.severity,
                "confidence": f.confidence,
                "url": f.url,
            })

        result["success"] = True
        result["findings_count"] = len(findings)
        result["findings"] = findings
        result["identifiers"] = enrichment.identifiers or {}
        result["relationship_count"] = len(getattr(enrichment, "relationships", []) or [])
        result["relationships"] = [
            dict(rel)
            for rel in (getattr(enrichment, "relationships", []) or [])
            if isinstance(rel, dict)
        ]
        result["structured_fields"] = dict(getattr(enrichment, "structured_fields", {}) or {})
        result["has_data"] = bool(
            findings
            or result["relationship_count"]
            or result["identifiers"]
            or result["structured_fields"]
        )
        result["elapsed_ms"] = int(
            (datetime.now(timezone.utc) - start).total_seconds() * 1000
        )

        logger.info(
            "axiom_agent: connector '%s' for '%s' returned %d findings in %dms",
            connector_name, vendor_name, len(findings), result["elapsed_ms"],
        )

    except ImportError as e:
        result["error"] = f"Failed to import connector module {connector_name}: {e}"
        logger.warning("axiom_agent: %s", result["error"])
    except AttributeError as e:
        result["error"] = f"Connector {connector_name} missing required interface: {e}"
        logger.warning("axiom_agent: %s", result["error"])
    except Exception as e:
        result["error"] = f"Connector {connector_name} failed: {e}"
        logger.exception("axiom_agent: connector execution error: %s", e)

    return result


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


def _parse_connector_requests(llm_response: str) -> list[dict]:
    """
    Extract connector requests from LLM response JSON.

    The LLM may include a "connector_requests" array in its JSON response:
      "connector_requests": [
        {"name": "sam_gov", "vendor_name": "Company Inc", "parameters": {...}},
        ...
      ]

    Returns:
        List of connector request dicts, or empty list if none found.
    """
    requests = []
    try:
        # Handle markdown code blocks
        clean_response = llm_response.strip()
        if clean_response.startswith("```"):
            clean_response = clean_response.split("\n", 1)[1]
            if clean_response.endswith("```"):
                clean_response = clean_response[:-3]
            clean_response = clean_response.strip()

        data = json.loads(clean_response)
        requests = data.get("connector_requests", [])
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return requests


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
              model: str = DEFAULT_MODEL, user_id: str = "",
              provider_locked: bool = False, model_locked: bool = False,
              lane_id: str = "mission_command") -> AgentResult:
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
    requested_provider = str(provider or "").strip().lower() or None
    requested_model = str(model or "").strip() or None

    provider, model, api_key = resolve_runtime_ai_credentials(
        user_id=user_id,
        provider=provider,
        model=model,
        api_key=api_key,
        provider_locked=provider_locked,
        model_locked=model_locked,
        lane_id=lane_id,
    )
    result.runtime = {
        "lane_id": lane_id,
        "provider_requested": requested_provider,
        "model_requested": requested_model,
        "provider_used": provider,
        "model_used": model,
        "provider_backed": bool(api_key),
        "fallback_active": False,
    }

    if not api_key:
        result.error = "No API key available. Configure AI provider in settings or pass api_key."
        result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return result

    all_entities: dict[str, DiscoveredEntity] = {}
    all_relationships: list[DiscoveredRelationship] = []
    all_findings: list[dict] = []
    carry_forward_findings: list[dict] = []
    target_identifier_attrs: dict = {}
    target_structured_attrs: dict = {}
    target_support_evidence: list[str] = []
    lane_profile = _build_lane_execution_profile(lane_id)
    if lane_id == "mission_command":
        mission_settings = _mission_command_settings(target)
        lane_profile = LaneExecutionProfile(
            **{
                **lane_profile.__dict__,
                "allowed_connectors": mission_settings["allowed_connectors"],
                "max_connector_requests_per_iteration": mission_settings["max_connector_requests_per_iteration"],
                "tactical_focus": mission_settings["focus"],
                "tactical_instruction": mission_settings["tactical_instruction"],
            }
        )
    vehicle_mode_support = _build_vehicle_mode_support(target)
    result.vehicle_mode_support = vehicle_mode_support

    try:
        for iteration in range(1, lane_profile.max_iterations + 1):
            iter_start = datetime.now(timezone.utc)
            iter_record = SearchIteration(iteration=iteration)
            current_carry_findings = list(carry_forward_findings)
            carry_forward_findings = []

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
                if not queries and not (lane_profile.reuse_connector_findings and current_carry_findings):
                    logger.info("axiom_agent: no follow-up queries, terminating at iteration %d", iteration)
                    break

            # Execute queries
            iter_findings: list[dict] = []
            if iteration == 1 and not lane_profile.use_initial_scraper:
                iter_findings.extend(_build_tactical_seed_findings(target, lane_id))
            elif iteration > 1 and not lane_profile.use_follow_up_search:
                iter_findings.extend(current_carry_findings)
            else:
                for query in queries[:MAX_FOLLOW_UPS_PER_ITER + 1]:
                    logger.info("axiom_agent: iteration %d, query: '%s'", iteration, query)
                    iter_record.queries_executed.append(query)

                    if iteration == 1:
                        findings = _run_scraper(query, target)
                    else:
                        findings = _run_web_search(query)

                    iter_findings.extend(findings)
                    if lane_profile.scrape_delay_seconds > 0:
                        time.sleep(lane_profile.scrape_delay_seconds)

            iter_record.raw_findings_count = len(iter_findings)
            all_findings.extend(iter_findings)
            result.total_findings += len(iter_findings)
            result.total_queries += len(iter_record.queries_executed)

            if not iter_findings and iteration > 1:
                logger.info("axiom_agent: no findings in iteration %d, terminating", iteration)
                iter_record.llm_reasoning = "No new findings from follow-up queries. Search exhausted."
                result.iterations.append(iter_record)
                break

            # LLM analysis or deterministic tactical connector seed
            if lane_profile.prefetch_connector_plan and iteration == 1:
                analysis = {
                    "entities": [],
                    "relationships": [],
                    "connector_requests": _build_prefetched_connector_requests(target, lane_profile),
                    "follow_up_queries": [],
                    "reasoning": (
                        f"Using prefetched {lane_profile.tactical_focus or 'tactical'} connector plan "
                        "before the final synthesis pass."
                    ),
                    "intelligence_gaps": [],
                    "search_complete": False,
                }
            else:
                previous_entity_names = list(all_entities.keys())
                analysis_prompt = _build_analysis_prompt(
                    target, iter_findings, iteration, previous_entity_names, lane_profile, vehicle_mode_support
                )

                llm_response = _call_llm(
                    prompt=analysis_prompt,
                    system=_build_system_prompt_for_lane(lane_profile),
                    provider=provider,
                    model=model,
                    api_key=api_key,
                    max_tokens=lane_profile.llm_max_tokens,
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

            # Execute connector requests if present
            connector_requests = _filter_connector_requests(
                []
                if lane_profile.allowed_connectors and iteration > 1
                else analysis.get("connector_requests", []),
                lane_profile,
            )
            connector_follow_on_findings: list[dict] = []
            connector_summary_findings: list[dict] = []
            for conn_req, conn_result in zip(
                connector_requests,
                _execute_connector_requests(connector_requests, lane_profile),
            ):
                try:
                    conn_name = conn_req.get("name", "")
                    vendor = conn_req.get("vendor_name", "")

                    if not conn_name or not vendor:
                        logger.warning(
                            "axiom_agent: incomplete connector request: name=%s, vendor=%s",
                            conn_name, vendor
                        )
                        continue

                    iter_record.connector_calls.append(conn_result)
                    result.total_connector_calls += 1

                    # Add connector findings to iteration findings
                    if conn_result["success"]:
                        target_identifier_attrs = _merge_entity_attributes(
                            target_identifier_attrs,
                            dict(conn_result.get("identifiers") or {}),
                        )
                        target_structured_attrs = _merge_entity_attributes(
                            target_structured_attrs,
                            _select_target_structured_fields(dict(conn_result.get("structured_fields") or {})),
                        )
                        summary_finding = _build_connector_summary_finding(conn_result)
                        if summary_finding:
                            iter_findings.append(summary_finding)
                            connector_summary_findings.append(summary_finding)
                            detail = str(summary_finding.get("detail") or "").strip()
                            if detail:
                                target_support_evidence.append(f"{conn_name}: {detail}")
                        for finding in conn_result["findings"]:
                            finding_payload = {
                                "category": finding.get("category", "connector_finding"),
                                "title": finding.get("title", ""),
                                "detail": finding.get("detail", ""),
                                "source": f"connector:{conn_name}",
                                "severity": finding.get("severity", "info"),
                                "confidence": finding.get("confidence", 0.5),
                                "url": finding.get("url", ""),
                                "connector_source": conn_name,
                            }
                            iter_findings.append(finding_payload)
                            connector_follow_on_findings.append(finding_payload)
                        result.total_findings += len(conn_result.get("findings", []) or [])

                        if conn_result.get("relationship_count", 0) > 0:
                            connector_follow_on_findings.append(
                                {
                                    "category": "connector_relationships",
                                    "title": f"{conn_name} returned structured relationships",
                                    "detail": (
                                        f"{conn_result.get('relationship_count', 0)} structured relationships "
                                        f"returned for {vendor}."
                                    ),
                                    "source": f"connector:{conn_name}",
                                    "severity": "info",
                                    "confidence": 0.7,
                                    "connector_source": conn_name,
                                }
                            )

                        for relationship in conn_result.get("relationships", []) or []:
                            discovered_relationship = _normalize_connector_relationship(
                                relationship,
                                vendor_name=vendor,
                            )
                            if discovered_relationship is None:
                                continue
                            if _should_suppress_tactical_relationship(discovered_relationship, lane_profile):
                                continue

                            all_relationships.append(discovered_relationship)

                            for entity_name in (
                                discovered_relationship.source_entity,
                                discovered_relationship.target_entity,
                            ):
                                if entity_name in all_entities:
                                    continue
                                if (
                                    lane_profile.tactical_focus in {"ownership_control", "ownership_procurement"}
                                    and _is_routine_dependency_entity_name(entity_name)
                                ):
                                    continue
                                all_entities[entity_name] = DiscoveredEntity(
                                    name=entity_name,
                                    entity_type="company",
                                    confidence=float(relationship.get("confidence") or 0.68),
                                    source_queries=list(queries),
                                    evidence=[f"Connector {conn_name} returned a structured relationship touching this entity."],
                                )
                        if lane_profile.connector_delay_seconds > 0 and lane_profile.max_parallel_connector_requests <= 1:
                            time.sleep(lane_profile.connector_delay_seconds)
                    else:
                        logger.warning(
                            "axiom_agent: connector '%s' failed: %s",
                            conn_name, conn_result.get("error", "unknown error")
                        )

                except Exception as e:
                    logger.exception(
                        "axiom_agent: error executing connector request: %s", e
                    )
                    iter_record.connector_calls.append({
                        "success": False,
                        "connector_name": conn_req.get("name", "unknown"),
                        "vendor_name": conn_req.get("vendor_name", "unknown"),
                        "error": str(e),
                    })

            # Process discovered entities
            for ent_data in analysis.get("entities", []):
                name = ent_data.get("name", "").strip()
                if not name:
                    continue
                if (
                    lane_profile.tactical_focus in {"ownership_control", "ownership_procurement"}
                    and _is_routine_dependency_entity_name(name)
                ):
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
                if rel.source_entity and rel.target_entity and not _should_suppress_tactical_relationship(rel, lane_profile):
                    all_relationships.append(rel)

            # Process intelligence gaps
            for gap_data in analysis.get("intelligence_gaps", []):
                if isinstance(gap_data, dict):
                    gap_text = str(gap_data.get("gap", "")).strip()
                    gap_type = str(gap_data.get("gap_type", "")).strip() or "gap"
                    fillable_by = str(gap_data.get("fillable_by", "automated_search")).strip() or "automated_search"
                    priority = str(gap_data.get("priority", "medium")).strip() or "medium"
                    try:
                        confidence = float(gap_data.get("confidence", 0) or 0)
                    except (TypeError, ValueError):
                        confidence = 0.0
                else:
                    gap_text = str(gap_data or "").strip()
                    gap_type = "gap"
                    fillable_by = "automated_search"
                    priority = "medium"
                    confidence = 0.0
                if not gap_text:
                    continue
                gap = {
                    "gap": gap_text,
                    "gap_type": gap_type,
                    "description": gap_text,
                    "confidence": max(confidence, 0.0),
                    "fillable_by": fillable_by,
                    "priority": priority,
                    "iteration_discovered": iteration,
                }
                result.intelligence_gaps.append(gap)

                # Flag advisory opportunities (gaps fillable by HUMINT/consulting)
                if fillable_by == "advisory_services":
                    result.advisory_opportunities.append({
                        "gap": gap_text,
                        "priority": priority,
                        "value_proposition": (
                            f"Automated collection cannot determine: {gap_text}. "
                            f"Xiphos advisory services can fill this gap through network intelligence."
                        ),
                    })

            # Store follow-up queries and reasoning
            follow_up_queries = analysis.get("follow_up_queries", []) if lane_profile.allow_follow_up_queries else []
            iter_record.follow_up_queries = [
                str(item).strip()
                for item in follow_up_queries[: lane_profile.max_follow_up_queries]
                if str(item).strip()
            ]
            iter_record.llm_reasoning = analysis.get("reasoning", "")
            iter_record.elapsed_ms = int(
                (datetime.now(timezone.utc) - iter_start).total_seconds() * 1000
            )
            if lane_profile.reuse_connector_findings:
                carry_forward_findings = (connector_summary_findings + connector_follow_on_findings)[:20]
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
    target_name = str(target.prime_contractor or "").strip()
    if target_name and result.total_connector_calls > 0:
        target_entity = all_entities.get(target_name)
        target_confidence = 0.92 if target_identifier_attrs else 0.72
        target_attributes = _merge_entity_attributes(
            getattr(target_entity, "attributes", {}),
            target_identifier_attrs,
        )
        target_attributes = _merge_entity_attributes(target_attributes, target_structured_attrs)
        if target.vehicle_name:
            target_attributes = _merge_entity_attributes(target_attributes, {"vehicle_name": target.vehicle_name})
        target_evidence = list(
            dict.fromkeys((getattr(target_entity, "evidence", []) or []) + target_support_evidence)
        )[:6]
        if not target_evidence:
            target_evidence = ["Target anchored by tactical connector evidence."]
        if target_entity:
            target_entity.confidence = max(target_entity.confidence, target_confidence)
            target_entity.attributes = target_attributes
            target_entity.evidence = target_evidence
        else:
            all_entities[target_name] = DiscoveredEntity(
                name=target_name,
                entity_type="company",
                confidence=target_confidence,
                attributes=target_attributes,
                source_queries=[target_name],
                evidence=target_evidence,
            )
    result.entities = list(all_entities.values())
    deduped_relationships: dict[tuple[str, str, str], DiscoveredRelationship] = {}
    for relationship in all_relationships:
        key = (
            relationship.source_entity.strip().lower(),
            relationship.target_entity.strip().lower(),
            relationship.rel_type.strip().lower(),
        )
        existing = deduped_relationships.get(key)
        if existing is None or relationship.confidence > existing.confidence:
            deduped_relationships[key] = relationship
    result.relationships = _prune_relationships_for_lane(
        list(deduped_relationships.values()),
        lane_profile,
    )
    result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    logger.info(
        "axiom_agent: complete. %d entities, %d relationships, %d gaps, %d advisory opportunities, "
        "%d iterations, %d connector calls, %dms",
        len(result.entities), len(result.relationships),
        len(result.intelligence_gaps), len(result.advisory_opportunities),
        len(result.iterations), result.total_connector_calls, result.elapsed_ms,
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
            entity_ids_by_name: dict[str, str] = {}

            def _upsert_entity_record(
                *,
                entity_id: str,
                canonical_name: str,
                entity_type: str,
                identifiers: dict | None = None,
                sources: list[str] | None = None,
                confidence: float = 0.5,
            ) -> None:
                conn.execute("""
                    INSERT INTO kg_entities (id, canonical_name, entity_type,
                        aliases, identifiers, sources, confidence, risk_level, last_updated, created_at)
                    VALUES (?, ?, ?, '[]', ?, ?, ?, 'unknown', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        confidence = max(kg_entities.confidence, excluded.confidence),
                        sources = excluded.sources,
                        last_updated = excluded.last_updated
                """, (
                    entity_id,
                    canonical_name,
                    entity_type,
                    json.dumps(identifiers or {}),
                    json.dumps(sources or ["axiom_agent"]),
                    confidence,
                    now,
                    now,
                ))

            def _ensure_entity_id(name: str, fallback_type: str = "company") -> str:
                normalized = str(name or "").strip()
                existing_id = entity_ids_by_name.get(normalized.lower())
                if existing_id:
                    return existing_id
                entity_id = _stable_hash(normalized, fallback_type, prefix="axiom")
                _upsert_entity_record(
                    entity_id=entity_id,
                    canonical_name=normalized,
                    entity_type=fallback_type,
                    confidence=0.5,
                )
                entity_ids_by_name[normalized.lower()] = entity_id
                summary["entities_created"] += 1
                return entity_id

            for entity in agent_result.entities:
                entity_id = _stable_hash(
                    entity.name, entity.entity_type,
                    prefix="axiom"
                )

                # Upsert entity
                if hasattr(conn, 'execute'):
                    try:
                        _upsert_entity_record(
                            entity_id=entity_id,
                            canonical_name=entity.name,
                            entity_type=entity.entity_type,
                            identifiers=entity.attributes,
                            confidence=entity.confidence,
                        )
                        entity_ids_by_name[entity.name.strip().lower()] = entity_id
                        summary["entities_created"] += 1
                    except Exception as e:
                        logger.warning("axiom_agent: entity upsert failed for '%s': %s", entity.name, e)

            for rel in agent_result.relationships:
                source_id = _ensure_entity_id(rel.source_entity, "company")
                target_id = _ensure_entity_id(rel.target_entity, "company")

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
          f"{len(result.intelligence_gaps)} gaps, {len(result.advisory_opportunities)} advisory opportunities, "
          f"{result.total_connector_calls} connector calls")


if __name__ == "__main__":
    main()
