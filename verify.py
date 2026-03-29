#!/usr/bin/env python3
"""
Xiphos Helios Package Verification

Self-contained verification script that checks the entire package
without requiring Node.js, npm, or external services.

Checks:
  1. All required files exist
  2. Python imports work (scoring engine, OSINT connectors, etc.)
  3. Frontend bundle is present and contains expected content
  4. ML model files are present
  5. No simulated/notional data sources in active connectors
  6. Scoring engine produces sane output for known inputs

Usage: python3 verify.py
"""

import os
import sys
import importlib
import json
import importlib.util

PASS = 0
FAIL = 0
WARNS = []
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL: {name} -- {detail}")


def warn(name, detail=""):
    WARNS.append(f"{name}: {detail}")
    print(f"  WARN: {name} -- {detail}")


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.join(root, "backend")
    frontend = os.path.join(root, "frontend")
    ml_dir = os.path.join(root, "ml")
    tests_dir = os.path.join(root, "tests")

    print("=" * 60)
    print("XIPHOS HELIOS PACKAGE VERIFICATION")
    print(f"Root: {root}")
    print("=" * 60)

    # ---- 1. Required files ----
    print("\n[FILE STRUCTURE]")
    required_files = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-entrypoint.sh",
        "deploy.py",
        "backend/server.py",
        "backend/fgamlogit.py",
        "backend/osint_scoring.py",
        "backend/entity_resolver.py",
        "backend/contract_vehicle_search.py",
        "backend/regulatory_gates.py",
        "backend/auth.py",
        "backend/db.py",
        "backend/dossier.py",
        "backend/dossier_pdf.py",
        "backend/osint/enrichment.py",
        "backend/osint/matching.py",
        "backend/osint/__init__.py",
        "backend/requirements.txt",
        "backend/static/index.html",
        "frontend/package.json",
        "frontend/src/App.tsx",
        "frontend/src/lib/api.ts",
        "frontend/src/lib/tokens.ts",
        "frontend/src/components/xiphos/helios-landing.tsx",
        "ml/inference.py",
        "ml/train_classifier.py",
        "ml/export_training_data.py",
        "tests/test_integration.py",
        "tests/test_scoring_validation.py",
    ]
    for f in required_files:
        path = os.path.join(root, f)
        check(f"File exists: {f}", os.path.exists(path), "MISSING")

    # ---- 2. Python imports ----
    print("\n[PYTHON IMPORTS]")
    sys.path.insert(0, root)
    sys.path.insert(0, backend)

    try:
        import fgamlogit
        check("Import fgamlogit", True)
    except Exception as e:
        check("Import fgamlogit", False, str(e))
        print("  FATAL: Scoring engine can't load. Skipping scoring tests.")
        _print_summary()
        return

    try:
        from fgamlogit import score_vendor, VendorInputV5, PROGRAM_TO_SENSITIVITY, FACTOR_NAMES
        check("Import score_vendor + types", True)
    except Exception as e:
        check("Import score_vendor + types", False, str(e))

    try:
        from osint.enrichment import CONNECTORS
        check("Import OSINT CONNECTORS", True)
        connector_count = len(CONNECTORS)
        check(f"Connector count >= 29", connector_count >= 29, f"Got {connector_count}")
    except Exception as e:
        check("Import OSINT CONNECTORS", False, str(e))
        connector_count = 0

    try:
        from osint_scoring import SOURCE_RELIABILITY, OSINTAugmentation
        check("Import osint_scoring", True)
    except Exception as e:
        check("Import osint_scoring", False, str(e))

    try:
        from entity_resolver import resolve_entity, _strip_entity_suffixes
        check("Import entity_resolver", True)
    except Exception as e:
        check("Import entity_resolver", False, str(e))

    try:
        from contract_vehicle_search import search_contract_vehicle
        check("Import contract_vehicle_search", True)
    except Exception as e:
        check("Import contract_vehicle_search", False, str(e))

    try:
        from osint.matching import entity_match
        check("Import entity matching", True)
    except Exception as e:
        check("Import entity matching", False, str(e))

    # ---- 3. No simulated data in active connectors ----
    print("\n[CONNECTOR INTEGRITY]")
    if connector_count > 0:
        connector_names = [name for name, _ in CONNECTORS]
        simulated = {"fapiis_check", "do_not_pay", "bis_entity_list", "regulatory_compliance",
                     "cfius_risk", "usml_classifier", "end_use_risk", "deemed_export",
                     "foreign_talent_programs", "institutional_risk"}
        active_simulated = simulated.intersection(set(connector_names))
        check("No simulated connectors active", len(active_simulated) == 0,
              f"Found: {active_simulated}")

        # Check for expected connectors
        expected = {"dod_sam_exclusions", "trade_csl", "un_sanctions", "opensanctions_pep",
                    "ofac_sdn", "eu_sanctions", "uk_hmt_sanctions", "sam_gov", "sec_edgar",
                    "gleif_lei", "google_news", "gdelt_media", "courtlistener"}
        missing = expected - set(connector_names)
        check("All critical connectors present", len(missing) == 0,
              f"Missing: {missing}" if missing else "")

    # ---- 4. Frontend bundle ----
    print("\n[FRONTEND BUNDLE]")
    bundle_path = os.path.join(root, "backend", "static", "index.html")
    if os.path.exists(bundle_path):
        with open(bundle_path, 'r', errors='ignore') as f:
            bundle = f.read()
        check("Bundle > 100KB", len(bundle) > 100000, f"Only {len(bundle)} bytes")
        check("Bundle has 'dod_classified'", "dod_classified" in bundle, "Missing new contract types")
        check("Bundle has 'DoD / IC'", "DoD / IC" in bundle, "Missing new labels")
        check("No '32 OSINT' in bundle", "32 OSINT" not in bundle, "Stale connector count")
        check("No 'Weapons System' in bundle", "Weapons System" not in bundle, "Stale program labels")
    else:
        check("Frontend bundle exists", False, "backend/static/index.html missing")

    # ---- 5. ML model ----
    print("\n[ML MODEL]")
    model_config = os.path.join(root, "ml", "model", "config.json")
    model_weights = os.path.join(root, "ml", "model", "model.safetensors")
    check("ML model config exists", os.path.exists(model_config), "ml/model/config.json missing")
    if os.path.exists(model_weights):
        size_mb = os.path.getsize(model_weights) / 1e6
        check(f"ML model weights ({size_mb:.0f}MB)", size_mb > 200, f"Only {size_mb:.0f}MB")
    else:
        warn("ML model weights missing", "ml/model/model.safetensors not in package")

    try:
        from ml.inference import MODEL_DIR, is_model_available, get_runtime_status
        runtime_status = get_runtime_status()
        if is_model_available():
            check("ML model auto-detected", True, f"Resolved path: {MODEL_DIR}")
        else:
            deps_present = all(
                importlib.util.find_spec(name) is not None
                for name in ("torch", "transformers", "safetensors")
            )
            if deps_present:
                check("ML model auto-detected", False, f"Resolved path: {MODEL_DIR}")
            else:
                warn("ML runtime optional path active", json.dumps(runtime_status))
    except Exception as e:
        check("ML model auto-detected", False, str(e))

    # ---- 6. Scoring engine sanity ----
    print("\n[SCORING ENGINE]")
    try:
        from fgamlogit import (score_vendor, VendorInputV5, OwnershipProfile,
                               DataQuality, ExecProfile, PROGRAM_TO_SENSITIVITY)

        # Test: clean US vendor should score low
        clean = VendorInputV5(
            name="Test Clean Corp", country="US",
            ownership=OwnershipProfile(publicly_traded=True, beneficial_owner_known=True,
                                       ownership_pct_resolved=0.9),
            data_quality=DataQuality(has_lei=True, has_cage=True, has_duns=True,
                                     has_tax_id=True, has_audited_financials=True, years_of_records=15),
            exec_profile=ExecProfile(known_execs=5),
        )
        result = score_vendor(clean)
        score = round(result.calibrated_probability * 100)
        check(f"Clean vendor score < 20%", score < 20, f"Got {score}%")
        check("Tier is APPROVED or CLEAR", "APPROVED" in result.calibrated_tier or "CLEAR" in result.calibrated_tier,
              f"Got {result.calibrated_tier}")

        # Test: bare vendor should score higher
        bare = VendorInputV5(name="Test Bare Corp", country="US",
                             ownership=OwnershipProfile(), data_quality=DataQuality(),
                             exec_profile=ExecProfile())
        result2 = score_vendor(bare)
        score2 = round(result2.calibrated_probability * 100)
        check(f"Bare vendor score > clean ({score2}% > {score}%)", score2 > score,
              f"Bare={score2}%, Clean={score}%")

        # Test: all program types resolve to valid sensitivities
        valid_sensitivities = {"CRITICAL_SAP", "CRITICAL_SCI", "ELEVATED", "ENHANCED",
                               "CONTROLLED", "STANDARD", "COMMERCIAL"}
        for prog, sens in PROGRAM_TO_SENSITIVITY.items():
            check(f"Program '{prog}' -> valid sensitivity", sens in valid_sensitivities,
                  f"Got '{sens}'")

        # Test: country normalization
        from fgamlogit import geo_risk
        check("geo_risk('US') < 0.10", geo_risk("US") < 0.10, f"Got {geo_risk('US')}")
        check("geo_risk('USA') < 0.10", geo_risk("USA") < 0.10, f"Got {geo_risk('USA')}")
        check("geo_risk('RU') > 0.50", geo_risk("RU") > 0.50, f"Got {geo_risk('RU')}")

        # Test: entity suffix stripping
        from entity_resolver import _strip_entity_suffixes
        check("Strip 'Xiphos LLC' -> ['xiphos']",
              _strip_entity_suffixes("Xiphos LLC") == ["xiphos"],
              f"Got {_strip_entity_suffixes('Xiphos LLC')}")

        # Test: entity matching
        from osint.matching import entity_match
        r = entity_match("Lockheed Martin Corp", "LOCKHEED MARTIN CORPORATION")
        check("Entity match: Lockheed Martin", r.matched, f"score={r.score}, method={r.method}")

    except Exception as e:
        check("Scoring engine tests", False, str(e))

    # ---- 7. Source reliability weights ----
    print("\n[SOURCE RELIABILITY]")
    try:
        from osint_scoring import SOURCE_RELIABILITY
        check("Reliability weights defined", len(SOURCE_RELIABILITY) > 20,
              f"Only {len(SOURCE_RELIABILITY)} entries")
        for src, weight in SOURCE_RELIABILITY.items():
            if weight > 1.0 or weight < 0.0:
                check(f"Weight range for {src}", False, f"Got {weight}")
                break
        else:
            check("All weights in [0, 1]", True)
    except Exception as e:
        check("Source reliability", False, str(e))

    _print_summary()


def _print_summary():
    print(f"\n{'=' * 60}")
    print(f"PASSED: {PASS}  FAILED: {FAIL}  WARNINGS: {len(WARNS)}")
    if FAILURES:
        print(f"\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
    if WARNS:
        print(f"\nWARNINGS:")
        for w in WARNS:
            print(f"  - {w}")
    print(f"{'=' * 60}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
