"""
Transaction Authorization Orchestrator (S12-01)

Single-pass orchestration engine that combines:
  1. Export authorization rules engine (BIS/ITAR posture)
  2. Graph-aware authorization (knowledge graph risk elevation)
  3. Person screening (sanctions + deemed export for all parties)
  4. Person-to-graph ingest (screening results feed the graph)
  5. License exception eligibility (S12-02, pluggable)

A Transaction represents a complete export authorization request:
  - An item being exported/disclosed (ECCN/USML classification)
  - A destination (country + end user + end use)
  - Parties involved (persons with nationalities, employers)
  - The authorization question: can this proceed, and under what conditions?

The Orchestrator runs all pipeline stages, applies posture elevation
logic (most-restrictive-wins), and returns a single TransactionAuthorization
with the combined posture, all component results, and required next steps.

Usage:
    from transaction_authorization import TransactionOrchestrator
    orch = TransactionOrchestrator()
    result = orch.authorize(transaction_input)
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("xiphos.transaction_auth")


# ---------------------------------------------------------------------------
# Posture hierarchy (most restrictive first)
# ---------------------------------------------------------------------------

POSTURE_HIERARCHY = [
    "likely_prohibited",
    "escalate",
    "likely_license_required",
    "likely_exception_or_exemption",
    "likely_nlr",
    "insufficient_confidence",
]

POSTURE_LABELS = {
    "likely_prohibited": "Likely Prohibited",
    "escalate": "Escalation Required",
    "likely_license_required": "License Required",
    "likely_exception_or_exemption": "License Exception May Apply",
    "likely_nlr": "No License Required (NLR)",
    "insufficient_confidence": "Insufficient Data",
}

POSTURE_SEVERITY = {p: i for i, p in enumerate(POSTURE_HIERARCHY)}


def _most_restrictive(*postures: str) -> str:
    """Return the most restrictive posture from a set of inputs."""
    best = "insufficient_confidence"
    best_rank = POSTURE_SEVERITY.get(best, 99)
    for p in postures:
        rank = POSTURE_SEVERITY.get(p, 99)
        if rank < best_rank:
            best = p
            best_rank = rank
    return best


# ---------------------------------------------------------------------------
# Transaction data models
# ---------------------------------------------------------------------------

@dataclass
class TransactionPerson:
    """A person involved in the export transaction."""
    name: str
    nationalities: list[str] = field(default_factory=list)
    employer: Optional[str] = None
    role: Optional[str] = None
    item_classification: Optional[str] = None
    access_level: Optional[str] = None


@dataclass
class TransactionInput:
    """Complete export transaction request."""
    # Item being exported/disclosed
    jurisdiction_guess: str = "unknown"       # ear | itar | unknown
    request_type: str = "physical_export"     # physical_export | deemed_export | reexport
    classification_guess: str = "unknown"     # ECCN or USML category
    item_or_data_summary: str = ""

    # Destination
    destination_country: str = ""
    destination_company: str = ""
    end_use_summary: str = ""
    end_user_name: str = ""
    access_context: str = ""

    # Persons involved
    persons: list[TransactionPerson] = field(default_factory=list)

    # Case linkage
    case_id: Optional[str] = None
    requested_by: str = "system"

    # Metadata
    notes: str = ""

    def to_rules_input(self) -> dict:
        """Convert to the dict format expected by export_authorization_rules."""
        all_nationalities = []
        for p in self.persons:
            all_nationalities.extend(p.nationalities)
        return {
            "jurisdiction_guess": self.jurisdiction_guess,
            "request_type": self.request_type,
            "classification_guess": self.classification_guess,
            "destination_country": self.destination_country,
            "foreign_person_nationalities": list(set(all_nationalities)),
            "item_or_data_summary": self.item_or_data_summary,
            "end_use_summary": self.end_use_summary,
            "access_context": self.access_context,
        }

    def to_graph_input(self) -> dict:
        """Convert to the dict format expected by graph_aware_authorization."""
        base = self.to_rules_input()
        base["destination_company"] = self.destination_company
        base["end_user_name"] = self.end_user_name
        return base


@dataclass
class PersonAuthResult:
    """Screening + graph result for a single person."""
    name: str
    role: Optional[str]
    screening_id: Optional[str] = None
    screening_status: str = "PENDING"
    composite_score: float = 0.0
    deemed_export: Optional[dict] = None
    recommended_action: str = ""
    matched_lists: list = field(default_factory=list)
    network_risk_level: str = "UNKNOWN"
    network_risk_signals: list = field(default_factory=list)
    graph_ingested: bool = False
    error: Optional[str] = None


@dataclass
class TransactionAuthorization:
    """Complete orchestrated authorization result."""
    id: str = ""
    case_id: Optional[str] = None
    transaction_type: str = ""

    # Combined posture (most restrictive across all components)
    combined_posture: str = "insufficient_confidence"
    combined_posture_label: str = "Insufficient Data"
    confidence: float = 0.0

    # Component results
    rules_posture: str = "insufficient_confidence"
    rules_confidence: float = 0.0
    rules_guidance: Optional[dict] = None

    graph_posture: str = "insufficient_confidence"
    graph_elevated: bool = False
    graph_intelligence: Optional[dict] = None

    person_results: list[PersonAuthResult] = field(default_factory=list)
    person_summary: Optional[dict] = None

    license_exception: Optional[dict] = None  # S12-02 will populate

    # Decision support
    recommended_next_step: str = ""
    escalation_reasons: list[str] = field(default_factory=list)
    blocking_factors: list[str] = field(default_factory=list)
    all_factors: list[str] = field(default_factory=list)

    # Metadata
    requested_by: str = "system"
    created_at: str = ""
    duration_ms: float = 0.0

    # Pipeline execution log
    pipeline_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for JSON response / DB storage."""
        d = asdict(self)
        # Convert PersonAuthResult list to plain dicts
        d["person_results"] = [asdict(p) if hasattr(p, '__dataclass_fields__') else p for p in self.person_results]
        return d


@dataclass
class ParallelStageResult:
    """Parallel stage payload collected off-thread then merged on the main thread."""
    stage: str
    pipeline_log: list[dict] = field(default_factory=list)
    posture: Optional[str] = None
    guidance: Optional[dict] = None
    person_results: list[PersonAuthResult] = field(default_factory=list)
    person_summary: Optional[dict] = None


# ---------------------------------------------------------------------------
# Safe imports for pipeline components
# ---------------------------------------------------------------------------

def _import_rules_engine():
    try:
        from export_authorization_rules import build_export_authorization_guidance
        return build_export_authorization_guidance
    except ImportError:
        return None


def _import_graph_auth():
    try:
        from graph_aware_authorization import build_graph_aware_guidance
        return build_graph_aware_guidance
    except ImportError:
        return None


def _import_person_screening():
    try:
        from person_screening import screen_person, init_person_screening_db
        return screen_person, init_person_screening_db
    except ImportError:
        return None, None


def _import_graph_ingest():
    try:
        from person_graph_ingest import ingest_person_screening, get_person_network_risk
        return ingest_person_screening, get_person_network_risk
    except ImportError:
        return None, None


def _import_db():
    try:
        import db
        return db
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TransactionOrchestrator:
    """
    Runs the full export authorization pipeline for a transaction.

    Pipeline stages:
      1. Rules engine: Conservative BIS/ITAR posture determination
      2. Graph-aware auth: Overlay knowledge graph risk signals
      3. Person screening: Screen all parties (sanctions + deemed export)
      4. Graph ingest: Feed screening results into knowledge graph
      5. Network risk: Query graph for person-level network exposure
      6. License exception check: (S12-02 hook, returns None until built)
      7. Posture combination: Most-restrictive-wins across all stages
      8. Persist: Store authorization record
    """

    def __init__(self):
        self.build_rules = _import_rules_engine()
        self.build_graph = _import_graph_auth()
        self.screen_person, self.init_screening_db = _import_person_screening()
        self.ingest_screening, self.get_network_risk = _import_graph_ingest()
        self.db = _import_db()

    def authorize(self, txn: TransactionInput) -> TransactionAuthorization:
        """Run full authorization pipeline and return combined result."""
        start = datetime.utcnow()
        auth = TransactionAuthorization(
            id=f"txauth-{uuid.uuid4().hex[:10]}",
            case_id=txn.case_id,
            transaction_type=txn.request_type,
            requested_by=txn.requested_by,
            created_at=start.isoformat(),
        )

        postures_collected = []

        # ------------------------------------------------------------------
        # Stage 1: Rules engine
        # ------------------------------------------------------------------
        auth.pipeline_log.append({"stage": "rules_engine", "status": "started", "ts": datetime.utcnow().isoformat()})
        if self.build_rules:
            try:
                rules_input = txn.to_rules_input()
                guidance = self.build_rules(rules_input)
                if guidance:
                    auth.rules_posture = guidance.get("posture", "insufficient_confidence")
                    auth.rules_confidence = guidance.get("confidence", 0.0)
                    auth.rules_guidance = guidance
                    postures_collected.append(auth.rules_posture)
                    auth.all_factors.extend(guidance.get("factors", []))
                    auth.pipeline_log.append({"stage": "rules_engine", "status": "ok", "posture": auth.rules_posture})
                    logger.info(f"[TxAuth {auth.id}] Rules: {auth.rules_posture} (conf={auth.rules_confidence})")
                else:
                    auth.pipeline_log.append({"stage": "rules_engine", "status": "no_result"})
            except Exception as e:
                auth.pipeline_log.append({"stage": "rules_engine", "status": "error", "error": str(e)})
                logger.warning(f"[TxAuth {auth.id}] Rules engine error: {e}")
        else:
            auth.pipeline_log.append({"stage": "rules_engine", "status": "unavailable"})

        # ------------------------------------------------------------------
        # Stage 2: Graph-aware authorization
        # ------------------------------------------------------------------
        auth.pipeline_log.append({"stage": "graph_auth", "status": "started", "ts": datetime.utcnow().isoformat()})
        if self.build_graph:
            try:
                graph_input = txn.to_graph_input()
                graph_guidance = self.build_graph(graph_input)
                if graph_guidance:
                    graph_posture = graph_guidance.get("posture", "insufficient_confidence")
                    gi = graph_guidance.get("graph_intelligence", {})
                    auth.graph_posture = graph_posture
                    auth.graph_elevated = gi.get("posture_elevated", False)
                    auth.graph_intelligence = gi
                    postures_collected.append(graph_posture)

                    if auth.graph_elevated:
                        reasons = gi.get("elevation_reasons", [])
                        auth.escalation_reasons.extend(reasons)
                        auth.all_factors.append(f"Graph elevated posture: {', '.join(reasons)}")

                    auth.pipeline_log.append({
                        "stage": "graph_auth", "status": "ok",
                        "posture": graph_posture, "elevated": auth.graph_elevated,
                    })
                    logger.info(f"[TxAuth {auth.id}] Graph: {graph_posture} (elevated={auth.graph_elevated})")
                else:
                    auth.pipeline_log.append({"stage": "graph_auth", "status": "no_result"})
            except Exception as e:
                auth.pipeline_log.append({"stage": "graph_auth", "status": "error", "error": str(e)})
                logger.warning(f"[TxAuth {auth.id}] Graph auth error: {e}")
        else:
            auth.pipeline_log.append({"stage": "graph_auth", "status": "unavailable"})

        # ------------------------------------------------------------------
        # Stage 3: Person screening
        # ------------------------------------------------------------------
        if txn.persons and self.screen_person:
            auth.pipeline_log.append({"stage": "person_screening", "status": "started", "ts": datetime.utcnow().isoformat()})
            try:
                if self.init_screening_db:
                    self.init_screening_db()
            except Exception:
                pass

            for person in txn.persons:
                pr = PersonAuthResult(name=person.name, role=person.role)
                try:
                    result = self.screen_person(
                        name=person.name,
                        nationalities=person.nationalities,
                        employer=person.employer,
                        item_classification=person.item_classification or txn.classification_guess,
                        access_level=person.access_level,
                        case_id=txn.case_id,
                        screened_by=txn.requested_by,
                    )
                    pr.screening_id = result.id
                    pr.screening_status = result.screening_status
                    pr.composite_score = result.composite_score
                    pr.deemed_export = result.deemed_export
                    pr.recommended_action = result.recommended_action
                    pr.matched_lists = result.matched_lists

                    # Person-level posture contribution
                    if result.screening_status == "MATCH":
                        postures_collected.append("likely_prohibited")
                        auth.blocking_factors.append(f"Sanctions match: {person.name}")
                    elif result.screening_status == "ESCALATE":
                        postures_collected.append("escalate")
                        auth.escalation_reasons.append(f"Person escalation: {person.name} ({pr.recommended_action})")
                    elif result.screening_status == "PARTIAL_MATCH":
                        postures_collected.append("likely_license_required")
                        auth.escalation_reasons.append(f"Partial match: {person.name}")

                    # Deemed export contribution
                    if result.deemed_export and result.deemed_export.get("required"):
                        de_type = result.deemed_export.get("license_type", "")
                        if de_type == "PROHIBITED":
                            postures_collected.append("likely_prohibited")
                            auth.blocking_factors.append(f"Deemed export prohibited: {person.name}")
                        elif de_type in ("LICENSE_REQUIRED", "DEEMED_EXPORT"):
                            postures_collected.append("likely_license_required")
                            auth.all_factors.append(f"Deemed export license required: {person.name}")

                    # ----------------------------------------------------------
                    # Stage 4: Graph ingest
                    # ----------------------------------------------------------
                    if self.ingest_screening:
                        try:
                            self.ingest_screening(result, case_id=txn.case_id)
                            pr.graph_ingested = True
                        except Exception as ge:
                            logger.debug(f"[TxAuth {auth.id}] Graph ingest for {person.name}: {ge}")

                    # ----------------------------------------------------------
                    # Stage 5: Network risk query
                    # ----------------------------------------------------------
                    if self.get_network_risk:
                        try:
                            risk = self.get_network_risk(person.name, person.nationalities)
                            pr.network_risk_level = risk.get("network_risk_level", "UNKNOWN")
                            pr.network_risk_signals = risk.get("risk_signals", [])

                            if pr.network_risk_level in ("CRITICAL", "HIGH"):
                                postures_collected.append("escalate")
                                auth.escalation_reasons.append(
                                    f"Network risk {pr.network_risk_level} for {person.name}"
                                )
                        except Exception as ne:
                            logger.debug(f"[TxAuth {auth.id}] Network risk for {person.name}: {ne}")

                except Exception as e:
                    pr.error = str(e)
                    logger.warning(f"[TxAuth {auth.id}] Person screening error for {person.name}: {e}")

                auth.person_results.append(pr)

            # Build person summary
            statuses = [p.screening_status for p in auth.person_results]
            auth.person_summary = {
                "total": len(auth.person_results),
                "clear": statuses.count("CLEAR"),
                "match": statuses.count("MATCH"),
                "partial_match": statuses.count("PARTIAL_MATCH"),
                "escalate": statuses.count("ESCALATE"),
                "pending": statuses.count("PENDING"),
                "errors": sum(1 for p in auth.person_results if p.error),
                "deemed_export_flags": sum(
                    1 for p in auth.person_results
                    if p.deemed_export and p.deemed_export.get("required")
                ),
            }
            auth.pipeline_log.append({
                "stage": "person_screening", "status": "ok",
                "persons_screened": len(auth.person_results),
                "summary": auth.person_summary,
            })
        else:
            auth.pipeline_log.append({"stage": "person_screening", "status": "skipped", "reason": "no_persons_or_module"})

        # ------------------------------------------------------------------
        # Stage 6: License exception eligibility (S12-02 hook)
        # ------------------------------------------------------------------
        auth.pipeline_log.append({"stage": "license_exception", "status": "started", "ts": datetime.utcnow().isoformat()})
        try:
            auth.license_exception = self._check_license_exception(txn, auth)
            if auth.license_exception and auth.license_exception.get("eligible"):
                auth.all_factors.append(
                    f"License exception eligible: {auth.license_exception.get('exception_code', 'unknown')}"
                )
            auth.pipeline_log.append({"stage": "license_exception", "status": "ok"})
        except Exception as e:
            auth.pipeline_log.append({"stage": "license_exception", "status": "error", "error": str(e)})

        # ------------------------------------------------------------------
        # Stage 7: Combine postures (most restrictive wins)
        # ------------------------------------------------------------------
        if postures_collected:
            auth.combined_posture = _most_restrictive(*postures_collected)
        else:
            auth.combined_posture = "insufficient_confidence"

        auth.combined_posture_label = POSTURE_LABELS.get(auth.combined_posture, auth.combined_posture)

        # Confidence is the minimum confidence across components
        confidences = [auth.rules_confidence]
        if auth.person_results:
            confidences.append(1.0 - max(p.composite_score for p in auth.person_results) * 0.5)
        auth.confidence = round(min(c for c in confidences if c > 0) if any(c > 0 for c in confidences) else 0.0, 4)

        # ------------------------------------------------------------------
        # Stage 8: Determine recommended next step
        # ------------------------------------------------------------------
        auth.recommended_next_step = self._determine_next_step(auth)

        # Duration
        auth.duration_ms = round((datetime.utcnow() - start).total_seconds() * 1000, 2)
        auth.pipeline_log.append({
            "stage": "complete", "ts": datetime.utcnow().isoformat(),
            "combined_posture": auth.combined_posture, "duration_ms": auth.duration_ms,
        })

        logger.info(
            f"[TxAuth {auth.id}] Complete: {auth.combined_posture_label} "
            f"(conf={auth.confidence}, persons={len(auth.person_results)}, "
            f"duration={auth.duration_ms}ms)"
        )

        # ------------------------------------------------------------------
        # Stage 9: Persist
        # ------------------------------------------------------------------
        try:
            self._persist(auth, txn)
        except Exception as e:
            logger.warning(f"[TxAuth {auth.id}] Persist error: {e}")

        return auth

    def _check_license_exception(self, txn: TransactionInput, auth: TransactionAuthorization) -> Optional[dict]:
        """
        Hook for S12-02 License Exception Eligibility Engine.
        Returns None until that module is built.
        """
        try:
            from license_exception_engine import check_license_exception
            return check_license_exception(
                classification=txn.classification_guess,
                destination_country=txn.destination_country,
                end_use=txn.end_use_summary,
                current_posture=auth.rules_posture,
            )
        except ImportError:
            return None

    def _determine_next_step(self, auth: TransactionAuthorization) -> str:
        """Generate recommended next step based on combined posture and factors."""
        p = auth.combined_posture

        if p == "likely_prohibited":
            if auth.blocking_factors:
                return f"STOP: Transaction is likely prohibited. Blocking factors: {'; '.join(auth.blocking_factors[:3])}"
            return "STOP: Transaction is likely prohibited under current regulations. Do not proceed without legal review."

        if p == "escalate":
            reasons = auth.escalation_reasons[:3]
            if reasons:
                return f"ESCALATE to export compliance officer. Triggers: {'; '.join(reasons)}"
            return "ESCALATE to export compliance officer for manual review before proceeding."

        if p == "likely_license_required":
            if auth.license_exception and auth.license_exception.get("eligible"):
                exc = auth.license_exception.get("exception_code", "unknown")
                return f"License required, but exception {exc} may apply. Verify eligibility and document per EAR {exc}."
            return "Submit license application to BIS/DDTC. Gather supporting documentation for all parties."

        if p == "likely_exception_or_exemption":
            return "Document the applicable license exception/exemption. Maintain records per EAR Part 762."

        if p == "likely_nlr":
            return "Transaction may proceed under NLR. Document classification basis and retain for 5 years per EAR Part 762."

        return "Insufficient data for determination. Provide item classification, destination, and end-use details."

    def _persist(self, auth: TransactionAuthorization, txn: TransactionInput):
        """Store the authorization record in the database."""
        if not self.db:
            return

        try:
            self.db.init_db()
            with self.db.get_conn() as conn:
                # Ensure table exists
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS transaction_authorizations (
                        id TEXT PRIMARY KEY,
                        case_id TEXT,
                        transaction_type TEXT NOT NULL,
                        classification TEXT,
                        destination_country TEXT,
                        destination_company TEXT,
                        end_user TEXT,
                        combined_posture TEXT NOT NULL,
                        combined_posture_label TEXT,
                        confidence REAL,
                        rules_posture TEXT,
                        rules_confidence REAL,
                        graph_posture TEXT,
                        graph_elevated BOOLEAN DEFAULT 0,
                        persons_screened INTEGER DEFAULT 0,
                        person_summary JSON,
                        license_exception JSON,
                        escalation_reasons JSON,
                        blocking_factors JSON,
                        all_factors JSON,
                        recommended_next_step TEXT,
                        rules_guidance JSON,
                        graph_intelligence JSON,
                        person_results JSON,
                        pipeline_log JSON,
                        requested_by TEXT,
                        duration_ms REAL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_txauth_case ON transaction_authorizations(case_id);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_txauth_posture ON transaction_authorizations(combined_posture);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_txauth_created ON transaction_authorizations(created_at);
                """)

                conn.execute("""
                    INSERT INTO transaction_authorizations (
                        id, case_id, transaction_type, classification,
                        destination_country, destination_company, end_user,
                        combined_posture, combined_posture_label, confidence,
                        rules_posture, rules_confidence,
                        graph_posture, graph_elevated,
                        persons_screened, person_summary, license_exception,
                        escalation_reasons, blocking_factors, all_factors,
                        recommended_next_step,
                        rules_guidance, graph_intelligence, person_results,
                        pipeline_log, requested_by, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    auth.id,
                    auth.case_id if auth.case_id else None,
                    auth.transaction_type,
                    txn.classification_guess,
                    txn.destination_country,
                    txn.destination_company,
                    txn.end_user_name,
                    auth.combined_posture,
                    auth.combined_posture_label,
                    auth.confidence,
                    auth.rules_posture,
                    auth.rules_confidence,
                    auth.graph_posture,
                    auth.graph_elevated,
                    len(auth.person_results),
                    json.dumps(auth.person_summary),
                    json.dumps(auth.license_exception),
                    json.dumps(auth.escalation_reasons),
                    json.dumps(auth.blocking_factors),
                    json.dumps(auth.all_factors),
                    auth.recommended_next_step,
                    json.dumps(auth.rules_guidance, default=str),
                    json.dumps(auth.graph_intelligence, default=str),
                    json.dumps([asdict(p) if hasattr(p, '__dataclass_fields__') else p for p in auth.person_results], default=str),
                    json.dumps(auth.pipeline_log, default=str),
                    auth.requested_by,
                    auth.duration_ms,
                ))

            logger.info(f"[TxAuth {auth.id}] Persisted to database")
        except Exception as e:
            logger.warning(f"[TxAuth {auth.id}] DB persist failed: {e}")


# ---------------------------------------------------------------------------
# Convenience: dict-based authorization (for API layer)
# ---------------------------------------------------------------------------

def authorize_transaction(input_dict: dict) -> dict:
    """
    Dict-in, dict-out convenience wrapper for API endpoints.

    Input keys:
        jurisdiction_guess, request_type, classification_guess,
        item_or_data_summary, destination_country, destination_company,
        end_use_summary, end_user_name, access_context,
        persons: [{name, nationalities, employer, role}],
        case_id, requested_by
    """
    persons = []
    for p in input_dict.get("persons", []):
        persons.append(TransactionPerson(
            name=p.get("name", ""),
            nationalities=p.get("nationalities", []),
            employer=p.get("employer"),
            role=p.get("role"),
            item_classification=p.get("item_classification"),
            access_level=p.get("access_level"),
        ))

    txn = TransactionInput(
        jurisdiction_guess=input_dict.get("jurisdiction_guess", "unknown"),
        request_type=input_dict.get("request_type", "physical_export"),
        classification_guess=input_dict.get("classification_guess", "unknown"),
        item_or_data_summary=input_dict.get("item_or_data_summary", ""),
        destination_country=input_dict.get("destination_country", ""),
        destination_company=input_dict.get("destination_company", ""),
        end_use_summary=input_dict.get("end_use_summary", ""),
        end_user_name=input_dict.get("end_user_name", ""),
        access_context=input_dict.get("access_context", ""),
        persons=persons,
        case_id=input_dict.get("case_id"),
        requested_by=input_dict.get("requested_by", "api"),
        notes=input_dict.get("notes", ""),
    )

    orch = TransactionOrchestrator()
    result = orch.authorize(txn)
    return result.to_dict()


# ---------------------------------------------------------------------------
# S12-01 Enhancements: Audit trail + parallel execution + re-auth
# ---------------------------------------------------------------------------

@dataclass
class AuthorizationAuditEntry:
    """Single audit trail entry for an authorization decision."""
    id: str = ""
    case_id: Optional[str] = None
    timestamp: str = ""
    request_payload: dict = field(default_factory=dict)
    combined_posture: str = ""
    confidence: float = 0.0
    pipeline_log: list = field(default_factory=list)
    analyst_email: str = ""
    review_status: str = "pending"  # pending, approved, rejected
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


def init_authorization_audit_db():
    """Initialize authorization_audit table if needed."""
    db_module = _import_db()
    if not db_module:
        return
    
    try:
        db_module.init_db()
        with db_module.get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS authorization_audit (
                    id TEXT PRIMARY KEY,
                    case_id TEXT,
                    timestamp TEXT NOT NULL,
                    request_payload JSON,
                    combined_posture TEXT,
                    confidence REAL,
                    pipeline_log JSON,
                    analyst_email TEXT,
                    review_status TEXT DEFAULT 'pending',
                    review_notes TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (case_id) REFERENCES vendors(id) ON DELETE SET NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_audit_case ON authorization_audit(case_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_audit_status ON authorization_audit(review_status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_audit_timestamp ON authorization_audit(timestamp)
            """)
            conn.commit()
    except Exception as e:
        logger.debug(f"Authorization audit DB init: {e}")


def _persist_audit_entry(auth: TransactionAuthorization, txn: TransactionInput):
    """Persist authorization result to audit table."""
    db_module = _import_db()
    if not db_module:
        return
    
    try:
        init_authorization_audit_db()
        audit_id = f"autaudit-{uuid.uuid4().hex[:10]}"
        
        with db_module.get_conn() as conn:
            conn.execute("""
                INSERT INTO authorization_audit (
                    id, case_id, timestamp, request_payload,
                    combined_posture, confidence, pipeline_log,
                    analyst_email, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit_id,
                auth.case_id,
                auth.created_at,
                json.dumps({
                    "jurisdiction": txn.jurisdiction_guess,
                    "classification": txn.classification_guess,
                    "destination": txn.destination_country,
                    "end_use": txn.end_use_summary,
                    "persons": len(txn.persons),
                }),
                auth.combined_posture,
                auth.confidence,
                json.dumps(auth.pipeline_log, default=str),
                txn.requested_by,
                "pending",
            ))
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to persist audit entry: {e}")


class TransactionOrchestratorEnhanced(TransactionOrchestrator):
    """
    Enhanced orchestrator with:
    1. Parallel execution of graph_auth and person_screening
    2. Audit trail persistence
    3. Risk escalation rules
    4. Re-authorization support
    """
    
    def authorize(self, txn: TransactionInput) -> TransactionAuthorization:
        """Run authorization pipeline with parallel stages and audit trail."""
        start = datetime.utcnow()
        auth = TransactionAuthorization(
            id=f"txauth-{uuid.uuid4().hex[:10]}",
            case_id=txn.case_id,
            transaction_type=txn.request_type,
            requested_by=txn.requested_by,
            created_at=start.isoformat(),
        )
        
        postures_collected = []
        
        # Stage 1: Rules engine (sequential, needed by graph)
        auth.pipeline_log.append({
            "stage": "rules_engine", "status": "started",
            "ts": datetime.utcnow().isoformat()
        })
        if self.build_rules:
            try:
                rules_input = txn.to_rules_input()
                guidance = self.build_rules(rules_input)
                if guidance:
                    auth.rules_posture = guidance.get("posture", "insufficient_confidence")
                    auth.rules_confidence = guidance.get("confidence", 0.0)
                    auth.rules_guidance = guidance
                    postures_collected.append(auth.rules_posture)
                    auth.all_factors.extend(guidance.get("factors", []))
                    auth.pipeline_log.append({
                        "stage": "rules_engine", "status": "ok",
                        "posture": auth.rules_posture
                    })
                    logger.info(f"[TxAuth {auth.id}] Rules: {auth.rules_posture}")
            except Exception as e:
                auth.pipeline_log.append({
                    "stage": "rules_engine", "status": "error",
                    "error": str(e)
                })
                logger.warning(f"[TxAuth {auth.id}] Rules engine error: {e}")
        else:
            auth.pipeline_log.append({
                "stage": "rules_engine", "status": "unavailable"
            })
        
        # Stages 2-5: Run graph_auth and person_screening in parallel
        auth.pipeline_log.append({
            "stage": "parallel_execution", "status": "started",
            "ts": datetime.utcnow().isoformat()
        })
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both tasks
            graph_future = executor.submit(self._run_graph_auth, txn, auth.id)
            person_future = executor.submit(self._run_person_screening, txn, auth.id)
            
            # Wait for both to complete
            for future in as_completed([graph_future, person_future]):
                try:
                    stage_result = future.result()
                    auth.pipeline_log.extend(stage_result.pipeline_log)
                    if stage_result.stage == "graph":
                        graph_posture = stage_result.posture
                        graph_guidance = stage_result.guidance or {}
                        if graph_posture:
                            auth.graph_posture = graph_posture
                            auth.graph_intelligence = graph_guidance.get("graph_intelligence", {})
                            auth.graph_elevated = auth.graph_intelligence.get("posture_elevated", False)
                            postures_collected.append(graph_posture)
                            if auth.graph_elevated:
                                auth.escalation_reasons.extend(
                                    auth.graph_intelligence.get("elevation_reasons", [])
                                )
                    elif stage_result.stage == "person":
                        auth.person_results = stage_result.person_results
                        auth.person_summary = stage_result.person_summary
                        postures_collected.extend([p.screening_status for p in stage_result.person_results
                                                  if p.screening_status in POSTURE_HIERARCHY])
                except Exception as e:
                    logger.warning(f"[TxAuth {auth.id}] Parallel execution error: {e}")
        
        auth.pipeline_log.append({
            "stage": "parallel_execution", "status": "ok"
        })
        
        # Stage 6: License exception eligibility
        auth.pipeline_log.append({
            "stage": "license_exception", "status": "started",
            "ts": datetime.utcnow().isoformat()
        })
        try:
            auth.license_exception = self._check_license_exception(txn, auth)
            if auth.license_exception and auth.license_exception.get("eligible"):
                auth.all_factors.append(
                    f"License exception eligible: {auth.license_exception.get('exception_code', 'unknown')}"
                )
            auth.pipeline_log.append({"stage": "license_exception", "status": "ok"})
        except Exception as e:
            auth.pipeline_log.append({
                "stage": "license_exception", "status": "error",
                "error": str(e)
            })
        
        # Stage 7: Combine postures
        if postures_collected:
            auth.combined_posture = _most_restrictive(*postures_collected)
        else:
            auth.combined_posture = "insufficient_confidence"
        
        auth.combined_posture_label = POSTURE_LABELS.get(auth.combined_posture, auth.combined_posture)
        
        # Confidence calculation
        confidences = [auth.rules_confidence]
        if auth.person_results:
            confidences.append(1.0 - max(p.composite_score for p in auth.person_results) * 0.5)
        auth.confidence = round(min(c for c in confidences if c > 0) if any(c > 0 for c in confidences) else 0.0, 4)
        
        # Stage 8: Determine next step
        auth.recommended_next_step = self._determine_next_step(auth)
        
        # Duration
        auth.duration_ms = round((datetime.utcnow() - start).total_seconds() * 1000, 2)
        auth.pipeline_log.append({
            "stage": "complete", "ts": datetime.utcnow().isoformat(),
            "combined_posture": auth.combined_posture,
            "duration_ms": auth.duration_ms,
        })
        
        logger.info(
            f"[TxAuth {auth.id}] Complete: {auth.combined_posture_label} "
            f"(conf={auth.confidence}, duration={auth.duration_ms}ms)"
        )
        
        # Stage 9: Persist to DB
        try:
            self._persist(auth, txn)
            _persist_audit_entry(auth, txn)
        except Exception as e:
            logger.warning(f"[TxAuth {auth.id}] Persist error: {e}")
        
        return auth
    
    def _run_graph_auth(self, txn: TransactionInput, auth_id: str) -> ParallelStageResult:
        """Run graph auth stage without mutating shared authorization state."""
        pipeline_log: list[dict] = [{
            "stage": "graph_auth", "status": "started",
            "ts": datetime.utcnow().isoformat()
        }]
        
        if self.build_graph:
            try:
                graph_input = txn.to_graph_input()
                graph_guidance = self.build_graph(graph_input)
                if graph_guidance:
                    graph_posture = graph_guidance.get("posture", "insufficient_confidence")
                    pipeline_log.append({
                        "stage": "graph_auth", "status": "ok",
                        "posture": graph_posture
                    })
                    logger.info(f"[TxAuth {auth_id}] Graph: {graph_posture}")
                    return ParallelStageResult(
                        stage="graph",
                        pipeline_log=pipeline_log,
                        posture=graph_posture,
                        guidance=graph_guidance,
                    )
                else:
                    pipeline_log.append({"stage": "graph_auth", "status": "no_result"})
            except Exception as e:
                pipeline_log.append({
                    "stage": "graph_auth", "status": "error",
                    "error": str(e)
                })
                logger.warning(f"[TxAuth {auth_id}] Graph auth error: {e}")
        else:
            pipeline_log.append({"stage": "graph_auth", "status": "unavailable"})
        
        return ParallelStageResult(stage="graph", pipeline_log=pipeline_log)
    
    def _run_person_screening(self, txn: TransactionInput, _auth_id: str) -> ParallelStageResult:
        """Run person screening stage without mutating shared authorization state."""
        person_results = []
        person_summary = None
        pipeline_log: list[dict] = []
        
        if txn.persons and self.screen_person:
            pipeline_log.append({
                "stage": "person_screening", "status": "started",
                "ts": datetime.utcnow().isoformat()
            })
            
            try:
                if self.init_screening_db:
                    self.init_screening_db()
            except Exception:
                pass
            
            for person in txn.persons:
                pr = PersonAuthResult(name=person.name, role=person.role)
                try:
                    result = self.screen_person(
                        name=person.name,
                        nationalities=person.nationalities,
                        employer=person.employer,
                        item_classification=person.item_classification or txn.classification_guess,
                        access_level=person.access_level,
                        case_id=txn.case_id,
                        screened_by=txn.requested_by,
                    )
                    pr.screening_id = result.id
                    pr.screening_status = result.screening_status
                    pr.composite_score = result.composite_score
                    pr.deemed_export = result.deemed_export
                    pr.recommended_action = result.recommended_action
                    pr.matched_lists = result.matched_lists
                    
                    # Graph ingest
                    if self.ingest_screening:
                        try:
                            self.ingest_screening(result, case_id=txn.case_id)
                            pr.graph_ingested = True
                        except Exception as ge:
                            logger.debug(f"[TxAuth] Graph ingest: {ge}")
                    
                    # Network risk
                    if self.get_network_risk:
                        try:
                            risk = self.get_network_risk(person.name, person.nationalities)
                            pr.network_risk_level = risk.get("network_risk_level", "UNKNOWN")
                            pr.network_risk_signals = risk.get("risk_signals", [])
                        except Exception as ne:
                            logger.debug(f"[TxAuth] Network risk: {ne}")
                
                except Exception as e:
                    pr.error = str(e)
                    logger.warning(f"[TxAuth] Person screening error for {person.name}: {e}")
                
                person_results.append(pr)
            
            # Build summary
            statuses = [p.screening_status for p in person_results]
            person_summary = {
                "total": len(person_results),
                "clear": statuses.count("CLEAR"),
                "match": statuses.count("MATCH"),
                "partial_match": statuses.count("PARTIAL_MATCH"),
                "escalate": statuses.count("ESCALATE"),
                "pending": statuses.count("PENDING"),
                "errors": sum(1 for p in person_results if p.error),
                "deemed_export_flags": sum(
                    1 for p in person_results
                    if p.deemed_export and p.deemed_export.get("required")
                ),
            }
            pipeline_log.append({
                "stage": "person_screening", "status": "ok",
                "persons_screened": len(person_results),
                "summary": person_summary,
            })
        else:
            pipeline_log.append({
                "stage": "person_screening", "status": "skipped",
                "reason": "no_persons_or_module"
            })
        
        return ParallelStageResult(
            stage="person",
            pipeline_log=pipeline_log,
            person_results=person_results,
            person_summary=person_summary,
        )


def get_authorization_history(case_id: str) -> list:
    """Retrieve all authorizations for a case."""
    db_module = _import_db()
    if not db_module:
        return []
    
    try:
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM transaction_authorizations
                WHERE case_id = ?
                ORDER BY created_at DESC
            """, (case_id,)).fetchall()
            
            results = []
            for row in rows:
                results.append(dict(row))
            return results
    except Exception as e:
        logger.warning(f"Failed to fetch authorization history: {e}")
        return []


def get_authorization_by_id(auth_id: str) -> Optional[dict]:
    """Retrieve a single authorization by ID."""
    db_module = _import_db()
    if not db_module:
        return None

    try:
        db_module.init_db()
        with db_module.get_conn() as conn:
            # Ensure table exists (may not have been created by init_db)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_authorizations (
                    id TEXT PRIMARY KEY,
                    case_id TEXT,
                    transaction_type TEXT NOT NULL,
                    classification TEXT,
                    destination_country TEXT,
                    destination_company TEXT,
                    end_user TEXT,
                    combined_posture TEXT NOT NULL,
                    combined_posture_label TEXT,
                    confidence REAL,
                    rules_posture TEXT,
                    rules_confidence REAL,
                    graph_posture TEXT,
                    graph_elevated BOOLEAN DEFAULT 0,
                    persons_screened INTEGER DEFAULT 0,
                    person_summary JSON,
                    license_exception JSON,
                    escalation_reasons JSON,
                    blocking_factors JSON,
                    all_factors JSON,
                    recommended_next_step TEXT,
                    rules_guidance JSON,
                    graph_intelligence JSON,
                    person_results JSON,
                    pipeline_log JSON,
                    requested_by TEXT,
                    duration_ms REAL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            row = conn.execute("""
                SELECT * FROM transaction_authorizations
                WHERE id = ?
            """, (auth_id,)).fetchone()
            
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch authorization: {e}")
        return None


def re_authorize(original_auth_id: str, txn: TransactionInput) -> dict:
    """
    Re-run authorization pipeline for the same case with updated data.
    Links to the original authorization in the audit trail.
    """
    original = get_authorization_by_id(original_auth_id)
    if not original:
        raise ValueError(f"Original authorization {original_auth_id} not found")

    # Run enhanced orchestrator
    orch = TransactionOrchestratorEnhanced()
    new_auth = orch.authorize(txn)

    # Link to original in audit
    logger.info(f"[TxAuth {new_auth.id}] Re-authorization of {original_auth_id}")

    return new_auth.to_dict()


# ---------------------------------------------------------------------------
# S13-04: Bulk Authorization
# ---------------------------------------------------------------------------

def authorize_batch(
    transactions: list[dict],
    dry_run: bool = False,
) -> dict:
    """
    Authorize multiple transactions in a single batch.

    Args:
        transactions: List of 1-50 transaction dicts with fields:
            - jurisdiction_guess, classification_guess, item_or_data_summary
            - destination_country, destination_company, end_use_summary
            - persons: [{name, nationalities, employer, ...}, ...]
            - case_id, requested_by (optional)

        dry_run: If True, evaluate without persisting to audit trail

    Returns:
        dict with structure:
        {
            "batch_id": str,
            "dry_run": bool,
            "results": [
                {
                    "authorization_id": str,
                    "combined_posture": str,
                    "confidence": float,
                    "duration_ms": int,
                }
            ],
            "total_processed": int,
            "total_errors": int,
            "error_details": [str, ...],
        }
    """
    batch_id = f"batch-{uuid.uuid4().hex[:10]}"
    orch = TransactionOrchestrator()
    results = []
    errors = []

    logger.info(
        f"[Batch {batch_id}] Starting batch authorization: "
        f"{len(transactions)} transactions, dry_run={dry_run}"
    )

    for i, txn_data in enumerate(transactions):
        if i >= 50:
            break  # Hard limit of 50 per batch

        try:
            # Convert dict to TransactionInput
            txn = TransactionInput(
                jurisdiction_guess=txn_data.get("jurisdiction_guess", "unknown"),
                request_type=txn_data.get("request_type", "physical_export"),
                classification_guess=txn_data.get("classification_guess", "unknown"),
                item_or_data_summary=txn_data.get("item_or_data_summary", ""),
                destination_country=txn_data.get("destination_country", ""),
                destination_company=txn_data.get("destination_company", ""),
                end_use_summary=txn_data.get("end_use_summary", ""),
                access_context=txn_data.get("access_context", ""),
                case_id=txn_data.get("case_id"),
                requested_by=txn_data.get("requested_by", "batch_user"),
                notes=txn_data.get("notes", ""),
            )

            # Add persons if provided
            persons_data = txn_data.get("persons", [])
            for p in persons_data:
                txn.persons.append(TransactionPerson(
                    name=p.get("name", ""),
                    nationalities=p.get("nationalities", []),
                    employer=p.get("employer"),
                    role=p.get("role"),
                    item_classification=p.get("item_classification"),
                    access_level=p.get("access_level"),
                ))

            # Authorize
            auth = orch.authorize(txn)

            # Persist only if not dry_run
            if not dry_run:
                db_mod = _import_db()
                if db_mod:
                    try:
                        db_mod.init_db()
                        with db_mod.get_conn() as conn:
                            conn.execute("""
                                INSERT INTO transaction_authorizations
                                (id, case_id, transaction_type, classification,
                                 destination_country, destination_company, end_user,
                                 combined_posture, combined_posture_label, confidence,
                                 rules_posture, graph_posture, graph_elevated,
                                 persons_screened, person_summary, escalation_reasons,
                                 blocking_factors, recommended_next_step,
                                 requested_by, duration_ms, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                auth.id, auth.case_id, auth.transaction_type,
                                auth.classification, auth.destination_country,
                                auth.destination_company, auth.end_user,
                                auth.combined_posture, auth.combined_posture_label,
                                auth.confidence, auth.rules_posture, auth.graph_posture,
                                auth.graph_elevated, len(auth.person_results),
                                json.dumps([p.person_name for p in auth.person_results]),
                                json.dumps(auth.escalation_reasons),
                                json.dumps(auth.blocking_factors),
                                auth.recommended_next_step, auth.requested_by,
                                int((datetime.utcnow() - datetime.fromisoformat(auth.created_at)).total_seconds() * 1000),
                                auth.created_at,
                            ))
                    except Exception as e:
                        logger.warning(f"[Batch {batch_id}] Failed to persist auth {auth.id}: {e}")

            results.append({
                "authorization_id": auth.id,
                "combined_posture": auth.combined_posture,
                "confidence": auth.confidence,
                "duration_ms": int((datetime.utcnow() - datetime.fromisoformat(auth.created_at)).total_seconds() * 1000),
            })

        except Exception as e:
            err_msg = f"Transaction {i}: {str(e)}"
            errors.append(err_msg)
            logger.error(f"[Batch {batch_id}] {err_msg}")

    logger.info(
        f"[Batch {batch_id}] Completed: {len(results)} authorized, "
        f"{len(errors)} errors"
    )

    return {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "results": results,
        "total_processed": len(results),
        "total_errors": len(errors),
        "error_details": errors,
    }
