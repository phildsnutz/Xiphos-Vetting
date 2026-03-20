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
from pathlib import Path
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

# Add backend to path so we can import fgamlogit
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from fgamlogit import (
    VendorInputV5, OwnershipProfile, DataQuality, ExecProfile, DoDContext,
    score_vendor, PROGRAM_TO_SENSITIVITY
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


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "validation_cases.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: Validation CSV not found at {csv_path}")
        sys.exit(1)

    exit_code = run_validation(csv_path)
    sys.exit(exit_code)
