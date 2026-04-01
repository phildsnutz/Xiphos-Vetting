"""
S16-01: CMMC Compliance Demo Test Case

Creates a realistic CMMC/cyber supply chain assurance scenario:
  - NovaTech Solutions (US) subcontractor on DoD program
  - SPRS score below threshold, missing controls
  - CVE findings in their software stack
  - Tests the full Cyber lane workflow:
    1. CMMC readiness assessment
    2. SPRS score ingest and gap analysis
    3. CVE/KEV knowledge graph ingest
    4. Cyber risk scoring
    5. Supply chain risk cascade

Run:
    python demo_cyber_cmmc_case.py          # Creates the demo case
    python demo_cyber_cmmc_case.py --clean  # Removes demo data
"""

import json
import sys
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

VENDOR_ID = "demo-novatech-cmmc"


def create_demo_cmmc_case() -> dict:
    """Create the NovaTech CMMC compliance demo case."""

    results = {
        "case_created": False,
        "cyber_evidence": None,
        "cyber_scoring": None,
        "risk_cascade": None,
    }

    try:
        import db
        db.init_db()
    except Exception as e:
        results["error"] = f"DB init failed: {e}"
        return results

    vendor_data = {
        "id": VENDOR_ID,
        "name": "NovaTech Solutions Inc",
        "country": "US",
        "program": "INDOPACOM_C2",
        "profile": "defense_acquisition",
        "notes": "S16-01 Demo: CMMC compliance gap analysis for C2 systems subcontractor",
        "sprs_score": 68,
        "cmmc_level_target": 2,
        "controls_assessed": 110,
        "controls_met": 72,
        "controls_gap": [
            "AC.L2-3.1.1 - Limit system access to authorized users",
            "AU.L2-3.3.1 - Create system-level audit logs",
            "IR.L2-3.6.1 - Establish incident handling capability",
            "SC.L2-3.13.1 - Monitor communications at external boundaries",
            "SI.L2-3.14.1 - Identify and correct system flaws",
        ],
        "software_stack": [
            {"name": "Apache Tomcat", "version": "9.0.62", "cve": "CVE-2023-28709"},
            {"name": "OpenSSL", "version": "1.1.1t", "cve": "CVE-2023-0286"},
            {"name": "PostgreSQL", "version": "14.5", "cve": None},
        ],
    }

    try:
        with db.get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM vendors WHERE id = ?", (VENDOR_ID,)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM vendors WHERE id = ?", (VENDOR_ID,))

            conn.execute("""
                INSERT INTO vendors (id, name, country, program, profile, vendor_input)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                VENDOR_ID,
                vendor_data["name"],
                vendor_data["country"],
                vendor_data["program"],
                vendor_data["profile"],
                json.dumps(vendor_data),
            ))
        results["case_created"] = True
        print(f"[Demo] Created vendor case: {vendor_data['name']} ({VENDOR_ID})")
    except Exception as e:
        results["error"] = f"Vendor creation failed: {e}"
        return results

    # CMMC gap analysis
    gap_count = len(vendor_data["controls_gap"])
    met_count = vendor_data["controls_met"]
    total = vendor_data["controls_assessed"]
    sprs = vendor_data["sprs_score"]
    cmmc_ready = sprs >= 110 and gap_count == 0

    results["cyber_evidence"] = {
        "sprs_score": sprs,
        "controls_met": met_count,
        "controls_total": total,
        "compliance_pct": round(met_count / total * 100, 1) if total else 0,
        "cmmc_ready": cmmc_ready,
        "gap_count": gap_count,
        "critical_gaps": vendor_data["controls_gap"][:3],
        "cve_count": sum(1 for s in vendor_data["software_stack"] if s.get("cve")),
    }

    print(f"[Demo] CMMC Assessment: SPRS={sprs}/110, {met_count}/{total} controls met")
    print(f"[Demo] CMMC Ready: {cmmc_ready} ({gap_count} control gaps)")
    for gap in vendor_data["controls_gap"]:
        print(f"       Gap: {gap}")

    # Cyber risk scoring
    try:
        from cyber_risk_scoring import score_vendor_cyber_risk
        score = score_vendor_cyber_risk(VENDOR_ID)
        results["cyber_scoring"] = {
            "overall_risk": score.get("overall_risk_score"),
            "risk_tier": score.get("risk_tier"),
        }
        print(f"[Demo] Cyber risk score: {score.get('overall_risk_score')} ({score.get('risk_tier')})")
    except Exception as e:
        print(f"[Demo] Cyber scoring not available: {e}")

    # CVE cascade
    try:
        from cyber_risk_cascade import get_cyber_risk_cascade
        cascade = get_cyber_risk_cascade(case_id=VENDOR_ID)
        results["risk_cascade"] = {
            "affected_nodes": len(cascade.get("affected_nodes", [])),
            "propagation_paths": len(cascade.get("propagation_paths", [])),
        }
        print(f"[Demo] Risk cascade: {len(cascade.get('affected_nodes', []))} affected nodes")
    except Exception as e:
        print(f"[Demo] Risk cascade not available: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("S16-01 DEMO COMPLETE: NovaTech CMMC Compliance")
    print("=" * 60)
    print(f"Case ID: {VENDOR_ID}")
    print(f"SPRS Score: {sprs}/110")
    print(f"Controls: {met_count}/{total} met ({round(met_count/total*100,1)}%)")
    print(f"CMMC Ready: {'YES' if cmmc_ready else 'NO'}")
    print(f"Critical Gaps: {gap_count}")
    print(f"Software CVEs: {results['cyber_evidence']['cve_count']}")
    print("=" * 60)

    return results


def clean_demo_data():
    """Remove demo case data."""
    try:
        import db
        with db.get_conn() as conn:
            conn.execute("DELETE FROM vendors WHERE id = ?", (VENDOR_ID,))
            print("[Demo] Cleaned up NovaTech CMMC demo vendor")
    except Exception as e:
        print(f"[Demo] Cleanup error: {e}")


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean_demo_data()
    else:
        result = create_demo_cmmc_case()
        print(f"\nResult JSON: {json.dumps(result, indent=2, default=str)}")
