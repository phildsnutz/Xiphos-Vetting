"""
Export Lane Monitoring Sweep (S11-05)

Continuous monitoring for the Export lane that detects changes in the
knowledge graph and triggers re-screening of affected persons. This
bridges the Counterparty lane's vendor monitoring with the Export lane's
person screening pipeline.

Monitoring triggers:
  1. Graph change detection: New sanctions entries in the graph that connect
     to previously-screened persons within 2 hops
  2. Sanctions list update: When OFAC/EU/UK lists are synced, re-screen
     all persons whose status was CLEAR but whose employer or co-nationals
     now appear on updated lists
  3. Scheduled re-screening: Persons with ESCALATE or PARTIAL_MATCH status
     are re-screened on a configurable interval (default: 72 hours)
  4. Graph-triggered cascade: When a new entity is sanctioned, propagate
     through the graph and flag connected persons for re-screening

Usage:
    from export_monitor import ExportMonitor
    monitor = ExportMonitor()
    results = monitor.run_sweep()
    results = monitor.run_graph_triggered_sweep()
"""

import logging
import json
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger("xiphos.export_monitor")


def _safe_import_person_screening():
    try:
        from person_screening import (
            screen_person, get_case_screenings,
            init_person_screening_db,
        )
        return screen_person, get_case_screenings, init_person_screening_db
    except ImportError:
        return None, None, None


def _safe_import_graph_ingest():
    try:
        from person_graph_ingest import ingest_person_screening, get_person_network_risk
        return ingest_person_screening, get_person_network_risk
    except ImportError:
        return None, None


def _safe_import_analytics():
    try:
        from graph_analytics import GraphAnalytics
        return GraphAnalytics
    except ImportError:
        return None


def _safe_import_kg():
    try:
        import knowledge_graph as kg
        return kg
    except ImportError:
        return None


def _safe_import_db():
    try:
        import db
        return db
    except ImportError:
        return None


# Re-screening intervals by status (hours)
RESCREEN_INTERVALS = {
    "MATCH": 24,           # Daily for confirmed matches
    "PARTIAL_MATCH": 72,   # Every 3 days for partial matches
    "ESCALATE": 72,        # Every 3 days for escalations
    "CLEAR": 720,          # Monthly for cleared persons
}


class ExportMonitor:
    """
    Export lane monitoring engine.
    Detects graph changes and triggers person re-screening.
    """

    def __init__(self):
        self.sweep_id = f"esweep-{uuid.uuid4().hex[:8]}"
        self.results = {
            "sweep_id": self.sweep_id,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "persons_rescreened": 0,
            "status_changes": [],
            "graph_triggers": [],
            "errors": [],
        }

    def run_sweep(self, max_persons: int = 100) -> dict:
        """
        Run a full export monitoring sweep.

        Steps:
        1. Load all person screenings from the database
        2. Identify persons due for re-screening based on status intervals
        3. Re-screen each person
        4. Compare results and flag status changes
        5. Update graph with new screening results

        Returns sweep results dict.
        """
        screen_person, get_case_screenings, init_db = _safe_import_person_screening()
        ingest_fn, get_risk = _safe_import_graph_ingest()
        main_db = _safe_import_db()

        if not screen_person or not main_db:
            self.results["errors"].append("Person screening or database module not available")
            self.results["completed_at"] = datetime.utcnow().isoformat()
            return self.results

        try:
            init_db()
        except Exception as e:
            self.results["errors"].append(f"DB init failed: {str(e)}")
            self.results["completed_at"] = datetime.utcnow().isoformat()
            return self.results

        # Load all person screenings
        try:
            with main_db.get_conn() as conn:
                rows = conn.execute("""
                    SELECT * FROM person_screenings
                    ORDER BY created_at DESC
                """).fetchall()
        except Exception as e:
            self.results["errors"].append(f"Failed to load screenings: {str(e)}")
            self.results["completed_at"] = datetime.utcnow().isoformat()
            return self.results

        # Group by person (latest screening per person)
        latest_by_person = {}
        for row in rows:
            key = row["person_name"]
            if key not in latest_by_person:
                latest_by_person[key] = dict(row)

        now = datetime.utcnow()
        rescreened = 0

        for person_name, screening in latest_by_person.items():
            if rescreened >= max_persons:
                break

            # Check if re-screening is due
            status = screening.get("screening_status", "CLEAR")
            interval_hours = RESCREEN_INTERVALS.get(status, 720)

            created_at = screening.get("created_at", "")
            try:
                screening_time = datetime.fromisoformat(created_at.replace("Z", ""))
            except (ValueError, TypeError):
                screening_time = now - timedelta(hours=interval_hours + 1)  # Force re-screen

            hours_since = (now - screening_time).total_seconds() / 3600
            if hours_since < interval_hours:
                continue  # Not yet due

            # Re-screen
            nationalities = json.loads(screening.get("nationalities", "[]")) if isinstance(screening.get("nationalities"), str) else screening.get("nationalities", [])
            employer = screening.get("employer")
            case_id = screening.get("case_id")

            try:
                new_result = screen_person(
                    name=person_name,
                    nationalities=nationalities,
                    employer=employer,
                    case_id=case_id,
                    screened_by="export_monitor",
                )

                rescreened += 1

                # Detect status change
                old_status = status
                new_status = new_result.screening_status

                if old_status != new_status:
                    change = {
                        "person_name": person_name,
                        "old_status": old_status,
                        "new_status": new_status,
                        "old_score": screening.get("composite_score", 0),
                        "new_score": new_result.composite_score,
                        "case_id": case_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    self.results["status_changes"].append(change)
                    logger.warning(
                        f"Export monitor: Status change for {person_name}: "
                        f"{old_status} -> {new_status}"
                    )

                # Ingest updated result into graph
                if ingest_fn:
                    try:
                        ingest_fn(new_result, case_id=case_id)
                    except Exception:
                        pass

            except Exception as e:
                self.results["errors"].append(f"Re-screening {person_name} failed: {str(e)}")

        self.results["persons_rescreened"] = rescreened
        self.results["completed_at"] = datetime.utcnow().isoformat()
        return self.results

    def run_graph_triggered_sweep(self) -> dict:
        """
        Graph-triggered re-screening sweep.

        Analyzes the knowledge graph for persons connected to sanctions
        entities and checks if their screening status should be elevated.

        Steps:
        1. Load graph and compute sanctions exposure
        2. Find person entities with non-zero exposure
        3. Cross-reference with person_screenings table
        4. Re-screen persons whose graph risk exceeds their current status
        """
        AnalyticsClass = _safe_import_analytics()
        screen_person, _, init_db = _safe_import_person_screening()
        ingest_fn, _ = _safe_import_graph_ingest()
        main_db = _safe_import_db()

        if not AnalyticsClass or not screen_person:
            self.results["errors"].append("Analytics or person screening not available")
            self.results["completed_at"] = datetime.utcnow().isoformat()
            return self.results

        try:
            init_db()
        except Exception:
            pass

        # Step 1: Compute sanctions exposure across the graph
        try:
            analytics = AnalyticsClass()
            analytics.load_graph()
            exposure = analytics.compute_sanctions_exposure()
        except Exception as e:
            self.results["errors"].append(f"Graph analytics failed: {str(e)}")
            self.results["completed_at"] = datetime.utcnow().isoformat()
            return self.results

        # Step 2: Find person entities with elevated exposure
        at_risk_persons = []
        for entity_id, exp_data in exposure.items():
            if exp_data.get("risk_level") in ("CRITICAL", "HIGH", "MEDIUM"):
                node = analytics.nodes.get(entity_id, {})
                if node.get("entity_type") == "person":
                    at_risk_persons.append({
                        "entity_id": entity_id,
                        "name": node.get("canonical_name", ""),
                        "exposure_score": exp_data.get("exposure_score", 0),
                        "risk_level": exp_data.get("risk_level"),
                        "nearest_sanction": exp_data.get("nearest_sanction"),
                    })

        # Step 3: Cross-reference with person_screenings and re-screen if needed
        rescreened = 0
        for person in at_risk_persons:
            person_name = person["name"]
            if not person_name:
                continue

            # Check current screening status
            try:
                with main_db.get_conn() as conn:
                    row = conn.execute(
                        "SELECT * FROM person_screenings WHERE person_name = ? ORDER BY created_at DESC LIMIT 1",
                        (person_name,)
                    ).fetchone()
            except Exception:
                row = None

            current_status = dict(row).get("screening_status", "CLEAR") if row else "UNKNOWN"

            # If graph says HIGH/CRITICAL but screening says CLEAR, re-screen
            should_rescreen = (
                person["risk_level"] in ("CRITICAL", "HIGH") and
                current_status in ("CLEAR", "UNKNOWN")
            )

            if should_rescreen:
                nationalities = json.loads(row["nationalities"]) if row and row["nationalities"] else []
                employer = row["employer"] if row else None
                case_id = row["case_id"] if row else None

                try:
                    new_result = screen_person(
                        name=person_name,
                        nationalities=nationalities,
                        employer=employer,
                        case_id=case_id,
                        screened_by="graph_triggered_monitor",
                    )
                    rescreened += 1

                    trigger = {
                        "person_name": person_name,
                        "trigger": "graph_sanctions_exposure",
                        "graph_risk_level": person["risk_level"],
                        "graph_exposure_score": person["exposure_score"],
                        "nearest_sanction": person.get("nearest_sanction", {}).get("name", ""),
                        "previous_status": current_status,
                        "new_status": new_result.screening_status,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    self.results["graph_triggers"].append(trigger)

                    if ingest_fn:
                        try:
                            ingest_fn(new_result, case_id=case_id)
                        except Exception:
                            pass

                except Exception as e:
                    self.results["errors"].append(
                        f"Graph-triggered re-screening of {person_name} failed: {str(e)}"
                    )

        self.results["persons_rescreened"] += rescreened
        self.results["completed_at"] = datetime.utcnow().isoformat()
        return self.results

    def run_full_sweep(self) -> dict:
        """Run both time-based and graph-triggered sweeps."""
        self.run_sweep()
        self.run_graph_triggered_sweep()
        return self.results
