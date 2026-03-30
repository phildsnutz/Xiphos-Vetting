#!/usr/bin/env python3
"""
SOF Week 2024 Bulk Ingest Pipeline
===================================
Feeds 724 defense exhibitors from SOF Week 2024 through the Helios
enrichment pipeline (create case -> enrich -> score -> graph ingest).

Usage:
    # Dry run (list companies, no API calls)
    python bulk_ingest.py --dry-run

    # Ingest first 10 companies (test batch)
    python bulk_ingest.py --limit 10

    # Ingest all 724
    python bulk_ingest.py

    # Resume from a specific offset (skip first N)
    python bulk_ingest.py --offset 100

    # Skip enrichment (just create cases + score, no OSINT)
    python bulk_ingest.py --skip-enrich --limit 50

    # Custom batch size and delay
    python bulk_ingest.py --batch-size 5 --delay 2.0

Environment:
    HELIOS_BASE_URL - API host (default: http://127.0.0.1:8080)
    HELIOS_HOST     - Legacy alias for API host
    HELIOS_EMAIL    - Login email
    HELIOS_PASSWORD - Login password
"""

import json
import os
import sys
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HOST = "http://127.0.0.1:8080"
EXHIBITOR_FILE = Path(__file__).parent / "sof_week_2024_exhibitors.json"
# Status file goes in the data dir so Docker container can read it
_data_dir = os.environ.get("XIPHOS_DATA_DIR", str(Path(__file__).parent))
STATUS_FILE = Path(_data_dir) / "bulk_ingest_status.json"

# Companies that are not defense vendors (foundations, government orgs, events, etc.)
# These get filtered out to focus on actual commercial entities worth enriching
SKIP_PATTERNS = [
    "foundation",
    "fund ",
    "association",
    "society",
    " club",
    "xcursion",
    "charitable trust",
    "collaborative",
    "care coalition",
    "warrior care",
    "warrior golf",
    "transition foundation",
    "memorial foundation",
    "believe with me",
    "home base program",
    "booster club",
    "honor foundation",
    "commit foundation",
    "robert irvine",
    "juliet funt",
    "brief lab",
    "whiskey project",
    "williams real estate",
    "florida yacht",
    "valor honor outdoors",
    "word of honor",
    "special ops xcursions",
    "black dagger military hunt",
]

# Government/military orgs that aren't commercial vendors
GOV_SKIP = [
    "AFSOC",
    "SOCOM",
    "MARSOC",
    "USASOC",
    "WARCOM",
    "CIA",
    "FBI",
    "AFWERX SBIR/STTR Program",
    "DARPA SBIR/STTR Program",
    "DoD SBIR/STTR",
    "MDA SBIR/STTR Program",
    "Navy SBIR/STTR Program Office",
    "SOCOM SBIR/STTR Program",
    "JSTO Chemical and Biological Defense",
    "DoD Anti-Tamper Executive Agent",
    "DoD CIO Defense Industrial Base",
    "Defense Industrial Base (DIB) Defense",
    "Army Futures Command",
    "ASD SOLIC",
    "US Cyber Command",
    "USSOCOM Joint Reserve Office",
    "USSOCOM Office of Small Business Programs",
    "USSOCOM SOF AT&L",
    "USSOCOM Surgeon General",
    "USSOCOM Warrior Care",
    "NSW Naval Small Craft",
    "US Military Freefall Association",
    "NATO Communications",
    "NASA Solutions for Enterprise",
    "Nevada National Security Site",
    "Sandia National Laboratories",
    "Embassy of Denmark",
    "SIBAT Israel Ministry",
    "UK Pavilion",
    "SOF Network",
    "SOFWERX",
    "SOFX",
    "SOFPrep",
    "Clarion SOF Week Booth",
    "GSA AAS Defense",
    "Global SOF Foundation",
    "JSOU",
    "Task Force Dagger Special Operations",
]

# Universities
UNI_SKIP = [
    "Arizona State University",
    "Columbia Southern University",
    "Cornell University",
    "USF Global and National Security",
    "USF Institute of Applied Engineering",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bulk_ingest")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_exhibitors() -> list[str]:
    """Load exhibitor names from the JSON file."""
    with open(EXHIBITOR_FILE) as f:
        data = json.load(f)
    return data["exhibitors"]


def filter_commercial_vendors(names: list[str]) -> list[str]:
    """Remove foundations, government orgs, universities, and event booths."""
    filtered = []
    for name in names:
        name_lower = name.lower()

        # Skip patterns (partial match)
        if any(pat.lower() in name_lower for pat in SKIP_PATTERNS):
            continue

        # Exact gov/mil skip
        if any(name.startswith(g) for g in GOV_SKIP):
            continue

        # Universities
        if name in UNI_SKIP:
            continue

        filtered.append(name)
    return filtered


def guess_country(name: str) -> str:
    """Guess country of origin from company name indicators.
    Default to US since SOF Week is a US-centric event."""
    name_lower = name.lower()

    # Explicit non-US indicators
    if any(k in name_lower for k in ["pty ltd", "australia"]):
        return "AU"
    if any(k in name_lower for k in ["gmbh", "kg"]):
        return "DE"
    if any(k in name_lower for k in [" a/s", " as ", "a.s."]) and "usa" not in name_lower:
        return "DK"  # or NO
    if "oy" in name_lower.split():
        return "FI"
    if " ab " in f" {name_lower} " or name_lower.endswith(" ab"):
        return "SE"
    if any(k in name_lower for k in ["uk ", " uk", "limited"]):
        return "GB"
    if any(k in name_lower for k in ["israel", "iwi"]):
        return "IL"
    if "srl" in name_lower.split():
        return "IT"
    if "bae systems" in name_lower:
        return "GB"
    if "thales" in name_lower and "uk" in name_lower:
        return "GB"
    if "thales" in name_lower:
        return "FR"
    if "airbus" in name_lower:
        return "FR"
    if "leonardo" in name_lower:
        return "IT"
    if "rafael" in name_lower:
        return "IL"
    if "bombardier" in name_lower:
        return "CA"
    if any(k in name_lower for k in ["norwegian", "norbit"]):
        return "NO"

    # Default: US (most SOF Week exhibitors are US-based)
    return "US"


class HeliosClient:
    """Thin HTTP client for the Helios API."""

    def __init__(self, host: str, email: str, password: str):
        self.host = host.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = None
        self._login(email, password)

    def _login(self, email: str, password: str):
        resp = self.session.post(
            f"{self.host}/api/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data.get("token")
        if not self.token:
            raise RuntimeError(f"Login failed: {data}")
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        log.info("Authenticated with Helios API")

    def create_case(self, name: str, country: str) -> dict:
        """POST /api/cases - Create a new vendor case."""
        resp = self.session.post(
            f"{self.host}/api/cases",
            json={
                "name": name,
                "country": country,
                "program": "standard_industrial",
                "profile": "defense_acquisition",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def enrich_and_score(self, case_id: str) -> dict:
        """POST /api/cases/<id>/enrich-and-score - Full enrichment pipeline."""
        resp = self.session.post(
            f"{self.host}/api/cases/{case_id}/enrich-and-score",
            json={},
            timeout=120,  # Enrichment can be slow
        )
        resp.raise_for_status()
        return resp.json()

    def enrich(self, case_id: str) -> dict:
        """POST /api/cases/<id>/enrich - OSINT enrichment only."""
        resp = self.session.post(
            f"{self.host}/api/cases/{case_id}/enrich",
            json={},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def sync_neo4j(self) -> dict:
        """POST /api/neo4j/sync - Sync knowledge graph to Neo4j."""
        resp = self.session.post(
            f"{self.host}/api/neo4j/sync",
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        job_id = str(payload.get("job_id") or "")
        if not job_id:
            return payload

        started = time.time()
        while True:
            status_resp = self.session.get(
                f"{self.host}/api/neo4j/sync/{job_id}",
                timeout=30,
            )
            status_resp.raise_for_status()
            status_payload = status_resp.json()
            status = str(status_payload.get("status") or "").strip().lower()
            if status in {"completed", "failed"}:
                return status_payload
            if time.time() - started > 300:
                raise TimeoutError(f"Neo4j sync job {job_id} exceeded 300s")
            time.sleep(2)

    def get_graph_stats(self) -> dict:
        """GET /api/graph/stats"""
        resp = self.session.get(f"{self.host}/api/graph/stats", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_existing_vendor_names(self) -> set[str]:
        """GET /api/cases - Fetch all existing vendor names for dedup."""
        resp = self.session.get(
            f"{self.host}/api/cases",
            params={"limit": 5000},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        cases = data if isinstance(data, list) else data.get("cases", data.get("vendors", []))
        names = set()
        for c in cases:
            name = c.get("vendor_name") or c.get("name") or ""
            if name:
                names.add(name.strip().lower())
        log.info(f"Found {len(names)} existing vendor cases for dedup")
        return names


# ---------------------------------------------------------------------------
# Status tracking (read by /api/bulk-ingest/status)
# ---------------------------------------------------------------------------

def _write_status(state: str, total: int, processed: int, results: dict,
                  started_at: float, current_company: str = ""):
    """Write a JSON status file so the API can report ingest progress."""
    elapsed = time.time() - started_at
    rate = processed / elapsed if elapsed > 0 and processed > 0 else 0
    remaining = total - processed
    eta_seconds = remaining / rate if rate > 0 else 0

    status = {
        "state": state,  # idle | running | completed | error
        "total": total,
        "processed": processed,
        "created": results.get("created", 0),
        "enriched": results.get("enriched", 0),
        "errors": len(results.get("errors", [])),
        "skipped": results.get("skipped", 0),
        "current_company": current_company,
        "rate_per_min": round(rate * 60, 1),
        "eta_minutes": round(eta_seconds / 60, 1),
        "elapsed_minutes": round(elapsed / 60, 1),
        "started_at": datetime.utcfromtimestamp(started_at).isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "error_details": results.get("errors", [])[-5:],  # last 5 errors
    }
    try:
        STATUS_FILE.write_text(json.dumps(status, indent=2))
    except Exception:
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_bulk_ingest(
    client: HeliosClient,
    companies: list[str],
    skip_enrich: bool = False,
    batch_size: int = 10,
    delay: float = 1.0,
    neo4j_sync_interval: int = 50,
):
    """
    Process companies in batches through the Helios pipeline.

    Steps per company:
        1. Create case (POST /api/cases)
        2. Enrich + score (POST /api/cases/<id>/enrich-and-score)

    Every neo4j_sync_interval companies, sync to Neo4j.
    """
    total = len(companies)
    results = {"created": 0, "enriched": 0, "errors": [], "skipped": 0}

    log.info(f"Starting bulk ingest: {total} companies, batch_size={batch_size}, delay={delay}s")
    if skip_enrich:
        log.info("SKIP ENRICHMENT mode: cases will be created and scored but NOT enriched")

    start_time = time.time()
    _write_status("running", total, 0, results, start_time)

    for i, name in enumerate(companies):
        idx = i + 1
        country = guess_country(name)

        try:
            # Step 1: Create case
            log.info(f"[{idx}/{total}] Creating case: {name} ({country})")
            case_resp = client.create_case(name, country)
            case_id = case_resp["case_id"]
            results["created"] += 1

            # Step 2: Enrich (unless skipped)
            if not skip_enrich:
                log.info(f"[{idx}/{total}] Enriching: {name} (case_id={case_id})")
                try:
                    enrich_resp = client.enrich_and_score(case_id)
                    risk = enrich_resp.get("enrichment", {}).get("overall_risk", "unknown")
                    score = enrich_resp.get("scoring", {}).get("composite_score", "N/A")
                    log.info(f"[{idx}/{total}] Done: {name} | risk={risk} | score={score}")
                    results["enriched"] += 1
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 501:
                        log.warning(f"[{idx}/{total}] OSINT module not available, skipping enrichment")
                        results["skipped"] += 1
                    else:
                        raise
                except requests.exceptions.Timeout:
                    log.warning(f"[{idx}/{total}] Enrichment timeout for {name}, continuing...")
                    results["errors"].append({"name": name, "error": "enrichment_timeout"})

            # Periodic Neo4j sync
            if idx % neo4j_sync_interval == 0:
                log.info(f"[{idx}/{total}] Syncing knowledge graph to Neo4j...")
                try:
                    sync_resp = client.sync_neo4j()
                    log.info(f"  Neo4j sync: {sync_resp.get('entities_synced', '?')} entities, "
                             f"{sync_resp.get('relationships_synced', '?')} relationships")
                except Exception as e:
                    log.warning(f"  Neo4j sync failed: {e}")

            # Update status file
            _write_status("running", total, idx, results, start_time, name)

            # Rate limiting delay
            if delay > 0 and idx < total:
                time.sleep(delay)

            # Batch progress report
            if idx % batch_size == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                eta = (total - idx) / rate if rate > 0 else 0
                log.info(f"--- Batch progress: {idx}/{total} ({idx/total*100:.1f}%) | "
                         f"Rate: {rate:.1f}/s | ETA: {eta/60:.1f}min ---")

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            log.error(f"[{idx}/{total}] HTTP {status} error for {name}: {e}")
            results["errors"].append({"name": name, "error": f"http_{status}", "detail": str(e)})
        except Exception as e:
            log.error(f"[{idx}/{total}] Error processing {name}: {e}")
            results["errors"].append({"name": name, "error": str(e)})

    # Final Neo4j sync
    log.info("Running final Neo4j sync...")
    try:
        sync_resp = client.sync_neo4j()
        log.info(f"Final sync: {sync_resp.get('entities_synced', '?')} entities, "
                 f"{sync_resp.get('relationships_synced', '?')} relationships")
    except Exception as e:
        log.warning(f"Final Neo4j sync failed: {e}")

    # Summary
    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info("BULK INGEST COMPLETE")
    log.info(f"  Total companies: {total}")
    log.info(f"  Cases created:   {results['created']}")
    log.info(f"  Enriched:        {results['enriched']}")
    log.info(f"  Skipped:         {results['skipped']}")
    log.info(f"  Errors:          {len(results['errors'])}")
    log.info(f"  Duration:        {elapsed/60:.1f} minutes")
    log.info("=" * 60)

    if results["errors"]:
        log.warning("Errors encountered:")
        for err in results["errors"][:20]:
            log.warning(f"  {err['name']}: {err['error']}")

    _write_status("completed", total, total, results, start_time)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Helios SOF Week 2024 Bulk Ingest")
    parser.add_argument("--dry-run", action="store_true", help="List companies without making API calls")
    parser.add_argument("--limit", type=int, default=0, help="Max companies to process (0=all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N companies")
    parser.add_argument("--skip-enrich", action="store_true", help="Create cases only (no enrichment)")
    parser.add_argument("--batch-size", type=int, default=10, help="Progress report interval")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between companies (seconds)")
    parser.add_argument("--sync-interval", type=int, default=50, help="Neo4j sync every N companies")
    parser.add_argument("--host", default=None, help=f"API host (default: {DEFAULT_HOST})")
    parser.add_argument("--include-all", action="store_true", help="Include foundations/gov orgs")
    parser.add_argument("--skip-dedup", action="store_true", help="Skip duplicate checking (ingest even if case exists)")
    args = parser.parse_args()

    # Load exhibitors
    if not EXHIBITOR_FILE.exists():
        log.error(f"Exhibitor file not found: {EXHIBITOR_FILE}")
        sys.exit(1)

    all_names = load_exhibitors()
    log.info(f"Loaded {len(all_names)} exhibitors from {EXHIBITOR_FILE.name}")

    # Filter
    if args.include_all:
        companies = all_names
    else:
        companies = filter_commercial_vendors(all_names)
        log.info(f"After filtering non-commercial entities: {len(companies)} vendors")

    # Offset + limit
    if args.offset > 0:
        companies = companies[args.offset:]
        log.info(f"Offset {args.offset}: {len(companies)} remaining")
    if args.limit > 0:
        companies = companies[:args.limit]
        log.info(f"Limited to {len(companies)} companies")

    # Dry run
    if args.dry_run:
        log.info(f"\n{'='*60}")
        log.info(f"DRY RUN: {len(companies)} companies would be ingested:")
        log.info(f"{'='*60}")
        for i, name in enumerate(companies):
            country = guess_country(name)
            log.info(f"  {i+1:4d}. {name} ({country})")
        log.info(f"\nTotal: {len(companies)} commercial defense vendors")
        log.info(f"Filtered out: {len(all_names) - len(companies)} non-commercial entities")
        return

    # Connect to API
    host = args.host or os.environ.get("HELIOS_BASE_URL") or os.environ.get("HELIOS_HOST") or DEFAULT_HOST
    email = (os.environ.get("HELIOS_LOGIN_EMAIL") or os.environ.get("HELIOS_EMAIL") or "").strip()
    password = (os.environ.get("HELIOS_LOGIN_PASSWORD") or os.environ.get("HELIOS_PASSWORD") or "").strip()
    if not email or not password:
        log.error("Set HELIOS_LOGIN_EMAIL/HELIOS_LOGIN_PASSWORD or HELIOS_EMAIL/HELIOS_PASSWORD before live ingest.")
        sys.exit(1)

    client = HeliosClient(host, email, password)

    # Get baseline stats
    try:
        stats = client.get_graph_stats()
        log.info(f"Pre-ingest graph: {stats.get('total_entities', '?')} entities, "
                 f"{stats.get('total_relationships', '?')} relationships")
    except Exception:
        pass

    # Dedup: skip companies that already have a case in Helios
    if not args.skip_dedup:
        try:
            existing = client.list_existing_vendor_names()
            before = len(companies)
            companies = [c for c in companies if c.strip().lower() not in existing]
            skipped = before - len(companies)
            if skipped:
                log.info(f"Dedup: skipped {skipped} companies already in Helios ({len(companies)} remaining)")
        except Exception as e:
            log.warning(f"Dedup check failed, proceeding without dedup: {e}")

    if not companies:
        log.info("No new companies to ingest (all already exist). Exiting.")
        return

    # Run pipeline
    main_start = time.time()
    results = run_bulk_ingest(
        client=client,
        companies=companies,
        skip_enrich=args.skip_enrich,
        batch_size=args.batch_size,
        delay=args.delay,
        neo4j_sync_interval=args.sync_interval,
    )

    # Post-ingest stats
    try:
        stats = client.get_graph_stats()
        log.info(f"Post-ingest graph: {stats.get('total_entities', '?')} entities, "
                 f"{stats.get('total_relationships', '?')} relationships")
    except Exception:
        pass

    # Save results (latest run)
    results_file = Path(__file__).parent / "bulk_ingest_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log.info(f"Results saved to {results_file}")

    # Append to history log (audit trail across all batches)
    history_file = Path(__file__).parent / "bulk_ingest_history.jsonl"
    history_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "offset": args.offset,
        "limit": args.limit,
        "total_in_batch": len(companies),
        "created": results["created"],
        "enriched": results["enriched"],
        "skipped": results["skipped"],
        "errors": len(results["errors"]),
        "duration_min": round((time.time() - main_start) / 60, 1),
        "error_names": [e["name"] for e in results["errors"][:10]],
    }
    try:
        with open(history_file, "a") as f:
            f.write(json.dumps(history_entry, default=str) + "\n")
        log.info(f"History appended to {history_file}")
    except Exception as e:
        log.warning(f"Failed to write history: {e}")


if __name__ == "__main__":
    main()
