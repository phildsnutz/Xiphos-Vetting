#!/usr/bin/env python3
"""
Known-outcomes validation harness for the FGAMLogit scoring engine.

Reads a CSV file of vendors with expected tiers, scores them through
the real scoring engine, and reports accuracy metrics and mismatches.

Usage:
    python3 tests/test_scoring_validation.py

Author: Xiphos Platform
Date: March 2026
"""

import csv
import sys
import os
from dataclasses import dataclass
from collections import defaultdict

# Add backend to path so we can import fgamlogit
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from fgamlogit import (
    VendorInputV5, OwnershipProfile, DataQuality, ExecProfile, DoDContext,
    score_vendor, PROGRAM_TO_SENSITIVITY
)

from regulatory_gates import (
    RegulatoryGateInput, Section889Input, NDAA1260HInput, ITARInput,
    FOCIInput, evaluate_regulatory_gates
)


@dataclass
class ValidationCase:
    """A single validation case with expected tier."""
    name: str
    country: str
    publicly_traded: bool
    state_owned: bool
    beneficial_owner_known: bool
    ownership_pct_resolved: float
    shell_layers: int
    pep_connection: bool
    has_lei: bool
    has_cage: bool
    has_duns: bool
    has_tax_id: bool
    has_audited_financials: bool
    years_of_records: int
    known_execs: int
    adverse_media: int
    pep_execs: int
    litigation_history: int
    program: str
    expected_tier: str


@dataclass
class ValidationResult:
    """Result of scoring a validation case."""
    case: ValidationCase
    actual_tier: str
    actual_score: float
    match: bool
    match_level: int  # 0=exact, 1=off-by-one, 2=off-by-two, 3+=major mismatch


def tier_to_level(tier_str: str) -> int:
    """Convert tier string to numeric level for comparison."""
    tier_map = {
        "TIER_1": 1, "TIER_2": 2, "TIER_3": 3, "TIER_4": 4,
    }
    # Extract the tier number
    for key, value in tier_map.items():
        if key in tier_str:
            return value
    return 0  # Unknown


def load_validation_cases(csv_path: str) -> list[ValidationCase]:
    """Load validation cases from CSV file."""
    cases = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            case = ValidationCase(
                name=row['name'],
                country=row['country'],
                publicly_traded=row['publicly_traded'].lower() == 'true',
                state_owned=row['state_owned'].lower() == 'true',
                beneficial_owner_known=row['beneficial_owner_known'].lower() == 'true',
                ownership_pct_resolved=float(row['ownership_pct_resolved']),
                shell_layers=int(row['shell_layers']),
                pep_connection=row['pep_connection'].lower() == 'true',
                has_lei=row['has_lei'].lower() == 'true',
                has_cage=row['has_cage'].lower() == 'true',
                has_duns=row['has_duns'].lower() == 'true',
                has_tax_id=row['has_tax_id'].lower() == 'true',
                has_audited_financials=row['has_audited_financials'].lower() == 'true',
                years_of_records=int(row['years_of_records']),
                known_execs=int(row['known_execs']),
                adverse_media=int(row['adverse_media']),
                pep_execs=int(row['pep_execs']),
                litigation_history=int(row['litigation_history']),
                program=row['program'],
                expected_tier=row['expected_tier'],
            )
            cases.append(case)
    return cases


def score_case(case: ValidationCase) -> tuple[str, float]:
    """Score a single case and return (tier, probability)."""
    ownership = OwnershipProfile(
        publicly_traded=case.publicly_traded,
        state_owned=case.state_owned,
        beneficial_owner_known=case.beneficial_owner_known,
        ownership_pct_resolved=case.ownership_pct_resolved,
        shell_layers=case.shell_layers,
        pep_connection=case.pep_connection,
        foreign_ownership_pct=0.0,
        foreign_ownership_is_allied=True,
    )

    data_quality = DataQuality(
        has_lei=case.has_lei,
        has_cage=case.has_cage,
        has_duns=case.has_duns,
        has_tax_id=case.has_tax_id,
        has_audited_financials=case.has_audited_financials,
        years_of_records=case.years_of_records,
    )

    exec_profile = ExecProfile(
        known_execs=case.known_execs,
        adverse_media=case.adverse_media,
        pep_execs=case.pep_execs,
        litigation_history=case.litigation_history,
    )

    # Get sensitivity from program
    sensitivity = PROGRAM_TO_SENSITIVITY.get(case.program, "COMMERCIAL")

    dod = DoDContext(
        sensitivity=sensitivity,
        supply_chain_tier=0,
    )

    inp = VendorInputV5(
        name=case.name,
        country=case.country,
        ownership=ownership,
        data_quality=data_quality,
        exec_profile=exec_profile,
        dod=dod,
    )

    result = score_vendor(inp, regulatory_status="COMPLIANT")
    return result.combined_tier, result.calibrated_probability


def run_validation(csv_path: str) -> None:
    """Run validation and print results."""
    print("\n" + "=" * 100)
    print("XIPHOS FGAMLOGIT SCORING VALIDATION HARNESS")
    print("=" * 100 + "\n")

    # Load cases
    cases = load_validation_cases(csv_path)
    print(f"Loaded {len(cases)} validation cases from {csv_path}\n")

    # Score all cases
    results = []
    for case in cases:
        try:
            actual_tier, actual_score = score_case(case)
            expected_level = tier_to_level(case.expected_tier)
            actual_level = tier_to_level(actual_tier)

            match = (expected_level == actual_level)
            match_level = abs(expected_level - actual_level)

            result = ValidationResult(
                case=case,
                actual_tier=actual_tier,
                actual_score=actual_score,
                match=match,
                match_level=match_level,
            )
            results.append(result)
        except Exception as e:
            print(f"ERROR scoring {case.name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Print detailed results table
    print("\nDETAILED RESULTS:")
    print("-" * 150)
    print(
        f"{'Name':<30} {'Country':<8} {'Program':<25} "
        f"{'Expected':<20} {'Actual':<20} {'Score':<8} {'Match':<8}"
    )
    print("-" * 150)

    for result in results:
        match_str = "✓" if result.match else f"✗ ({result.match_level})"
        print(
            f"{result.case.name:<30} {result.case.country:<8} {result.case.program:<25} "
            f"{result.case.expected_tier:<20} {result.actual_tier:<20} "
            f"{result.actual_score:.3f}    {match_str:<8}"
        )

    print("\n" + "=" * 100)
    print("ACCURACY METRICS")
    print("=" * 100 + "\n")

    # Calculate overall accuracy
    correct = sum(1 for r in results if r.match)
    total = len(results)
    accuracy = (correct / total * 100) if total > 0 else 0.0

    print(f"Overall Accuracy: {correct}/{total} ({accuracy:.1f}%)\n")

    # Accuracy by expected tier
    by_tier = defaultdict(lambda: {"correct": 0, "total": 0})
    for result in results:
        tier = result.case.expected_tier
        by_tier[tier]["total"] += 1
        if result.match:
            by_tier[tier]["correct"] += 1

    print("Accuracy by Expected Tier:")
    print("-" * 50)
    for tier in sorted(by_tier.keys(), key=lambda x: tier_to_level(x), reverse=True):
        stats = by_tier[tier]
        acc = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0.0
        print(f"  {tier:<20}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")

    # Confusion matrix (by tier level)
    print("\n" + "-" * 50)
    print("Tier-Level Accuracy (T1/T2/T3/T4):")
    print("-" * 50)

    by_level = defaultdict(lambda: {"correct": 0, "total": 0})
    for result in results:
        expected_level = tier_to_level(result.case.expected_tier)
        actual_level = tier_to_level(result.actual_tier)

        level_key = f"TIER_{expected_level}"
        by_level[level_key]["total"] += 1
        if expected_level == actual_level:
            by_level[level_key]["correct"] += 1

    for level in ["TIER_4", "TIER_3", "TIER_2", "TIER_1"]:
        stats = by_level[level]
        if stats["total"] > 0:
            acc = (stats["correct"] / stats["total"] * 100)
            print(f"  {level}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")

    # Mismatches
    mismatches = [r for r in results if not r.match]
    if mismatches:
        print("\n" + "=" * 100)
        print(f"MISMATCHES ({len(mismatches)} cases)")
        print("=" * 100 + "\n")
        print("-" * 150)
        print(
            f"{'Name':<30} {'Expected':<20} {'Actual':<20} {'Delta':<8} "
            f"{'Score':<8} {'Key Factors':<50}"
        )
        print("-" * 150)

        for result in sorted(mismatches, key=lambda r: r.match_level, reverse=True):
            delta_str = f"Δ{result.match_level}L"
            key_factors = []

            if result.case.state_owned:
                key_factors.append("StateOwned")
            if result.case.shell_layers >= 3:
                key_factors.append(f"Shells({result.case.shell_layers})")
            if result.case.adverse_media > 0:
                key_factors.append(f"Media({result.case.adverse_media})")
            if result.case.pep_connection:
                key_factors.append("PEP")
            if not result.case.beneficial_owner_known:
                key_factors.append("NoOwner")

            factors_str = ", ".join(key_factors[:3])

            print(
                f"{result.case.name:<30} {result.case.expected_tier:<20} "
                f"{result.actual_tier:<20} {delta_str:<8} {result.actual_score:.3f}    "
                f"{factors_str:<50}"
            )

    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Total Cases:   {total}")
    print(f"Exact Matches: {correct} ({accuracy:.1f}%)")
    print(f"Mismatches:    {len(mismatches)} ({(len(mismatches)/total*100):.1f}%)")

    # Flag major mismatches (off-by-2 or more)
    major_mismatches = [r for r in mismatches if r.match_level >= 2]
    if major_mismatches:
        print(f"\nWARNING: {len(major_mismatches)} major mismatch(es) (Δ≥2 tier levels)")
        for result in major_mismatches:
            print(f"  - {result.case.name}: expected {result.case.expected_tier}, got {result.actual_tier}")

    print("\n" + "=" * 100 + "\n")

    return 0 if accuracy >= 80.0 else 1


def _make_clean_gate_input(entity_name: str, entity_country: str = "US",
                           sensitivity: str = "COMMERCIAL") -> RegulatoryGateInput:
    """Helper: minimal RegulatoryGateInput with all gates defaulted (should PASS/SKIP)."""
    return RegulatoryGateInput(
        entity_name=entity_name,
        entity_country=entity_country,
        sensitivity=sensitivity,
        section_889=Section889Input(entity_name=entity_name),
        ndaa_1260h=NDAA1260HInput(entity_name=entity_name),
    )


def _make_vendor(name, country, sensitivity="COMMERCIAL",
                 publicly_traded=True, state_owned=False,
                 beneficial_owner_known=True, ownership_pct_resolved=1.0,
                 shell_layers=0, pep_connection=False,
                 foreign_ownership_pct=0.0, foreign_ownership_is_allied=True,
                 has_lei=True, has_cage=True, has_duns=True, has_tax_id=True,
                 has_audited_financials=True, years_of_records=15,
                 known_execs=30, adverse_media=0, pep_execs=0,
                 litigation_history=0, supply_chain_tier=0) -> VendorInputV5:
    """Helper: build VendorInputV5 with sensible defaults."""
    return VendorInputV5(
        name=name,
        country=country,
        ownership=OwnershipProfile(
            publicly_traded=publicly_traded, state_owned=state_owned,
            beneficial_owner_known=beneficial_owner_known,
            ownership_pct_resolved=ownership_pct_resolved,
            shell_layers=shell_layers, pep_connection=pep_connection,
            foreign_ownership_pct=foreign_ownership_pct,
            foreign_ownership_is_allied=foreign_ownership_is_allied,
        ),
        data_quality=DataQuality(
            has_lei=has_lei, has_cage=has_cage, has_duns=has_duns,
            has_tax_id=has_tax_id, has_audited_financials=has_audited_financials,
            years_of_records=years_of_records,
        ),
        exec_profile=ExecProfile(
            known_execs=known_execs, adverse_media=adverse_media,
            pep_execs=pep_execs, litigation_history=litigation_history,
        ),
        dod=DoDContext(sensitivity=sensitivity, supply_chain_tier=supply_chain_tier),
    )


def run_pipeline_validation() -> int:
    """
    Validate the full Layer 1 -> Layer 2 pipeline.
    Tests regulatory gates feeding into scoring engine with hardcoded scenarios.
    Uses tier-LEVEL matching (TIER_1/2/3/4) not exact sub-tier strings.
    """
    print("\n" + "=" * 100)
    print("LAYER 1 -> LAYER 2 PIPELINE VALIDATION")
    print("=" * 100 + "\n")

    pipeline_cases = []

    # ── Case 1: Section 889 entity (Huawei) -> NON_COMPLIANT -> TIER_1 ──
    pipeline_cases.append({
        "name": "Section 889 Entity (Huawei)",
        "gate_input": RegulatoryGateInput(
            entity_name="Huawei Technologies",
            entity_country="CN",
            section_889=Section889Input(entity_name="Huawei Technologies"),
            ndaa_1260h=NDAA1260HInput(entity_name="Huawei Technologies"),
        ),
        "vendor": _make_vendor("Huawei Technologies", "CN",
                               state_owned=True, foreign_ownership_is_allied=False),
        "expected_status": "NON_COMPLIANT",
        "expected_tier_level": 1,
    })

    # ── Case 2: Clean US vendor -> COMPLIANT -> TIER_4 ──
    pipeline_cases.append({
        "name": "Clean US Vendor (Lockheed Martin)",
        "gate_input": _make_clean_gate_input("Lockheed Martin", "US"),
        "vendor": _make_vendor("Lockheed Martin", "US", known_execs=50,
                               years_of_records=20),
        "expected_status": "COMPLIANT",
        "expected_tier_level": 4,
    })

    # ── Case 3: ITAR pending -- Tier 2 sub with ITAR item, no cert -> REQUIRES_REVIEW -> TIER_2 ──
    # A Tier 2+ supplier handling ITAR items without compliance cert triggers PENDING.
    case3_gate = _make_clean_gate_input("Precision Aero Components", "US")
    case3_gate.supply_chain_tier = 2  # Tier 2 sub -- gate engine copies this to itar sub-input
    case3_gate.itar = ITARInput(
        item_is_itar_controlled=True,
        entity_has_itar_compliance_certification=False,
        entity_manufacturing_process_certified=False,
        entity_nationality_of_control="US",
        entity_foci_status="NOT_APPLICABLE",
    )
    pipeline_cases.append({
        "name": "ITAR Pending (Tier 2 Sub, no cert)",
        "gate_input": case3_gate,
        "vendor": _make_vendor("Precision Aero Components", "US",
                               publicly_traded=False, years_of_records=8,
                               known_execs=10, supply_chain_tier=2),
        "expected_status": "REQUIRES_REVIEW",
        "expected_tier_level": 2,
    })

    # ── Case 4: NDAA 1260H entity (AVIC) -> NON_COMPLIANT -> TIER_1 ──
    pipeline_cases.append({
        "name": "NDAA 1260H Entity (AVIC)",
        "gate_input": RegulatoryGateInput(
            entity_name="Aviation Industry Corporation of China",
            entity_country="CN",
            section_889=Section889Input(
                entity_name="Aviation Industry Corporation of China"),
            ndaa_1260h=NDAA1260HInput(
                entity_name="Aviation Industry Corporation of China",
                entity_country="CN"),
        ),
        "vendor": _make_vendor("Aviation Industry Corporation of China", "CN",
                               state_owned=True, foreign_ownership_is_allied=False),
        "expected_status": "NON_COMPLIANT",
        "expected_tier_level": 1,
    })

    # ── Case 5: FOCI concern (allied nation) -> REQUIRES_REVIEW -> TIER_2 ──
    case5_gate = _make_clean_gate_input("Siemens AG", "DE")
    case5_gate.foci = FOCIInput(
        entity_foreign_ownership_pct=0.60,
        entity_foreign_control_pct=0.40,
        foreign_controlling_country="DE",
        entity_foci_mitigation_status="IN_PROGRESS",
        entity_has_facility_clearance=False,
        sensitivity="ELEVATED",
    )
    pipeline_cases.append({
        "name": "FOCI Concern (Siemens)",
        "gate_input": case5_gate,
        "vendor": _make_vendor("Siemens AG", "DE", sensitivity="ELEVATED",
                               foreign_ownership_pct=0.60,
                               foreign_ownership_is_allied=True,
                               ownership_pct_resolved=0.6, has_cage=False,
                               years_of_records=30, known_execs=40,
                               adverse_media=1, litigation_history=2),
        "expected_status": "REQUIRES_REVIEW",
        "expected_tier_level": 2,
    })

    # ── Case 6: Extra hard stops override clean vendor -> TIER_1 ──
    pipeline_cases.append({
        "name": "Hard Stops Override (SAM Exclusion)",
        "gate_input": _make_clean_gate_input("Acme Corp", "US"),
        "vendor": _make_vendor("Acme Corp", "US", publicly_traded=False,
                               years_of_records=5, known_execs=5),
        "expected_status": "COMPLIANT",
        "expected_tier_level": 1,
        "extra_hard_stops": [{"trigger": "SAM_EXCLUSION", "source": "SAM.gov"}],
    })

    # ── Case 7a/7b: Sensitivity escalation ──
    mid_tier_vendor_commercial = _make_vendor(
        "Mid-Tier Defense Contractor", "US", sensitivity="COMMERCIAL",
        publicly_traded=False, has_lei=False, ownership_pct_resolved=0.8,
        shell_layers=1, foreign_ownership_pct=0.2,
        years_of_records=8, known_execs=12, adverse_media=1,
        litigation_history=1,
    )
    mid_tier_vendor_critical = _make_vendor(
        "Mid-Tier Defense Contractor", "US", sensitivity="CRITICAL_SCI",
        publicly_traded=False, has_lei=False, ownership_pct_resolved=0.8,
        shell_layers=1, foreign_ownership_pct=0.2,
        years_of_records=8, known_execs=12, adverse_media=1,
        litigation_history=1,
    )
    mid_gate = _make_clean_gate_input("Mid-Tier Defense Contractor", "US")

    pipeline_cases.append({
        "name": "Sensitivity: COMMERCIAL (lenient)",
        "gate_input": mid_gate,
        "vendor": mid_tier_vendor_commercial,
        "expected_status": "COMPLIANT",
        "expected_tier_level": 4,  # COMMERCIAL is lenient
    })
    pipeline_cases.append({
        "name": "Sensitivity: CRITICAL_SCI (strict)",
        "gate_input": mid_gate,
        "vendor": mid_tier_vendor_critical,
        "expected_status": "COMPLIANT",
        "expected_tier_level_max": 3,  # Must be worse (lower tier number) than COMMERCIAL
        "sensitivity_compare": True,
    })

    # ── Run all pipeline cases ──
    print(f"Running {len(pipeline_cases)} pipeline validation cases...\n")
    print("-" * 150)
    print(
        f"{'Case Name':<45} {'Gate Status':<20} {'Expected':<12} "
        f"{'Actual Tier':<30} {'Score':<10} {'Match':<8}"
    )
    print("-" * 150)

    passed = 0
    failed = 0
    failures = []
    commercial_tier_level = None  # For sensitivity comparison

    for case in pipeline_cases:
        try:
            # Evaluate regulatory gates
            gate_result = evaluate_regulatory_gates(case["gate_input"])
            regulatory_status = gate_result.status.value

            # Build regulatory_findings from gate details
            regulatory_findings = []
            for g in gate_result.failed_gates:
                regulatory_findings.append({"gate": g.gate_name, "state": "FAIL",
                                            "details": g.details})
            for g in gate_result.pending_gates:
                regulatory_findings.append({"gate": g.gate_name, "state": "PENDING",
                                            "details": g.details})

            # Score vendor
            extra_hard_stops = case.get("extra_hard_stops", None)
            score_result = score_vendor(
                case["vendor"],
                regulatory_status=regulatory_status,
                regulatory_findings=regulatory_findings,
                extra_hard_stops=extra_hard_stops,
            )

            actual_tier = score_result.combined_tier
            actual_score = score_result.calibrated_probability
            actual_level = tier_to_level(actual_tier)

            # Determine pass/fail
            if case.get("sensitivity_compare"):
                # For sensitivity escalation: CRITICAL_SCI level must be <= max
                tier_match = actual_level <= case["expected_tier_level_max"]
                expected_str = f"<= TIER_{case['expected_tier_level_max']}"
                # Also verify it's stricter than COMMERCIAL
                if commercial_tier_level is not None:
                    tier_match = tier_match and (actual_level <= commercial_tier_level)
            else:
                expected_level = case["expected_tier_level"]
                tier_match = (actual_level == expected_level)
                expected_str = f"TIER_{expected_level}"

                # Track commercial tier for comparison
                if "COMMERCIAL" in case["name"]:
                    commercial_tier_level = actual_level

            # Check expected regulatory status if specified
            if "expected_status" in case:
                status_match = (regulatory_status == case["expected_status"])
                tier_match = tier_match and status_match

            if tier_match:
                passed += 1
                match_str = "PASS"
            else:
                failed += 1
                match_str = "FAIL"
                failures.append({
                    "name": case["name"],
                    "expected": expected_str,
                    "actual_tier": actual_tier,
                    "actual_level": actual_level,
                    "regulatory_status": regulatory_status,
                    "expected_status": case.get("expected_status", ""),
                })

            print(
                f"{case['name']:<45} {regulatory_status:<20} {expected_str:<12} "
                f"{actual_tier:<30} {actual_score:.3f}     {match_str:<8}"
            )

        except Exception as e:
            failed += 1
            print(f"{case['name']:<45} ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            failures.append({
                "name": case["name"],
                "error": str(e),
            })

    # Summary
    print("\n" + "=" * 100)
    print("PIPELINE VALIDATION SUMMARY")
    print("=" * 100)
    print(f"Total Cases:   {len(pipeline_cases)}")
    print(f"Passed:        {passed}")
    print(f"Failed:        {failed}")

    if failed > 0:
        print("\nFailed Cases:")
        for failure in failures:
            if "error" in failure:
                print(f"  - {failure['name']}: ERROR - {failure['error']}")
            else:
                print(
                    f"  - {failure['name']}: expected {failure['expected']}, "
                    f"got {failure['actual_tier']} (level {failure['actual_level']}) "
                    f"[gate_status={failure['regulatory_status']}, "
                    f"expected_status={failure['expected_status']}]"
                )

    print("\n" + "=" * 100 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "validation_cases.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: Validation CSV not found at {csv_path}")
        sys.exit(1)

    # Run CSV-based validation
    csv_exit = run_validation(csv_path)

    # Run pipeline validation
    pipeline_exit = run_pipeline_validation()

    # Exit with worst code
    sys.exit(max(csv_exit, pipeline_exit))
