#!/usr/bin/env python3
"""
Batch ITAR Scoring CLI Tool

Reads ITAR validation CSV, scores each vendor through the ITAR module,
and outputs scored results to CSV and HTML report.

Usage:
    python3 batch_itar_scorer.py [csv_path] [output_path]

Defaults:
    csv_path: ../tests/itar_validation_cases.csv
    output_path: ../tests/itar_validation_results.csv
    html_report: ../tests/itar_validation_report.html
"""

import sys
import csv
import os
from typing import Optional, Dict, List, Any

# Add backend directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from itar_module import (
    evaluate_itar_compliance,
    check_ddtc_debarred,
    ITARComplianceResult,
)


# Risk level mappings
DEEMED_EXPORT_RISK_RANGES = {
    'LOW': (0.0, 0.30),
    'MEDIUM': (0.30, 0.70),
    'HIGH': (0.70, 0.85),
    'EXTREME': (0.85, 1.01),
}

RED_FLAG_LEVEL_RANGES = {
    'CLEAN': (0.0, 0.10),
    'LOW': (0.10, 0.25),
    'MEDIUM': (0.25, 0.60),
    'HIGH': (0.60, 0.80),
    'EXTREME': (0.80, 1.01),
}


def parse_foreign_nationals(raw_string: Optional[str]) -> Optional[List[Dict]]:
    """Parse semicolon-separated country codes into foreign national dicts."""
    if not raw_string or raw_string.strip() == '':
        return None
    
    codes = [code.strip() for code in raw_string.split(';') if code.strip()]
    if not codes:
        return None
    
    return [
        {'nationality': code, 'role': 'engineer', 'has_clearance': False}
        for code in codes
    ]


def parse_red_flags(raw_string: Optional[str]) -> Optional[Dict[str, bool]]:
    """Parse semicolon-separated red flag indicators into dict."""
    if not raw_string or raw_string.strip() == '':
        return None
    
    flags = [flag.strip() for flag in raw_string.split(';') if flag.strip()]
    if not flags:
        return None
    
    return {flag: True for flag in flags}


def parse_ddtc_registered(value: str) -> Optional[bool]:
    """Convert REGISTERED/UNREGISTERED string to boolean."""
    if value.upper() == 'REGISTERED':
        return True
    elif value.upper() == 'UNREGISTERED':
        return False
    return None


def parse_tcp_status(value: str) -> str:
    """Convert has_tcp true/false to tcp_status string."""
    if value.lower() == 'true':
        return 'IMPLEMENTED'
    return 'MISSING'


def map_risk_score_to_level(score: float, ranges: Dict[str, tuple]) -> str:
    """Map a numeric risk score to a risk level based on ranges."""
    for level, (min_val, max_val) in ranges.items():
        if min_val <= score < max_val:
            return level
    return 'EXTREME'


def compare_overall_status(expected: str, actual: str) -> bool:
    """
    Compare overall status with flexibility.
    NON_COMPLIANT and PROHIBITED are considered equivalent for matching.
    """
    non_compliant_variants = {'NON_COMPLIANT', 'PROHIBITED'}
    
    expected_normalized = expected.upper()
    actual_normalized = actual.upper()
    
    if expected_normalized in non_compliant_variants:
        return actual_normalized in non_compliant_variants
    
    return expected_normalized == actual_normalized


def score_case(row: Dict[str, str]) -> Dict[str, Any]:
    """Score a single case and return results."""
    case_id = row['case_id']
    vendor_name = row['vendor_name']
    vendor_country = row['vendor_country']
    usml_category = int(row['usml_category'])
    
    # Parse inputs
    ddtc_registered = parse_ddtc_registered(row['ddtc_registered'])
    foreign_nationals = parse_foreign_nationals(row['foreign_nationals'])
    tcp_status = parse_tcp_status(row['has_tcp'])
    transaction_flags = parse_red_flags(row['red_flag_indicators'])
    end_user_country = row.get('end_user_country') or None
    
    # Call ITAR compliance evaluation
    result: ITARComplianceResult = evaluate_itar_compliance(
        vendor_name=vendor_name,
        vendor_country=vendor_country,
        usml_category=usml_category,
        ddtc_registered=ddtc_registered,
        foreign_nationals=foreign_nationals,
        tcp_status=tcp_status,
        transaction_flags=transaction_flags,
        end_user_country=end_user_country,
    )
    
    # Check DDTC debarred status
    debarred_info = check_ddtc_debarred(vendor_name)
    debarred_match = 'MATCH' if debarred_info else 'CLEAR'
    
    # Parse expected results from CSV
    expected_country_status = row['expected_country_status']
    expected_deemed_export_risk_level = row['expected_deemed_export_risk_level']
    expected_red_flag_level = row['expected_red_flag_level']
    expected_overall_result = row['expected_overall_result']
    
    # Map actual scores to levels
    actual_deemed_export_risk_level = map_risk_score_to_level(
        result.deemed_export_risk.risk_score,
        DEEMED_EXPORT_RISK_RANGES
    )
    actual_red_flag_level = map_risk_score_to_level(
        result.red_flag_assessment.score,
        RED_FLAG_LEVEL_RANGES
    )
    
    # If entity is debarred, override actual status to PROHIBITED
    effective_overall_status = result.overall_status
    if debarred_info:
        effective_overall_status = "PROHIBITED"

    # Compare results
    overall_match = compare_overall_status(
        expected_overall_result,
        effective_overall_status
    )
    country_match = expected_country_status == result.country_status
    deemed_export_match = expected_deemed_export_risk_level == actual_deemed_export_risk_level
    red_flag_match = expected_red_flag_level == actual_red_flag_level
    
    # Overall PASS/FAIL logic
    overall_pass = overall_match and country_match and deemed_export_match and red_flag_match
    status = 'PASS' if overall_pass else 'FAIL'
    
    return {
        'case_id': case_id,
        'vendor_name': vendor_name,
        'vendor_country': vendor_country,
        'usml_category': usml_category,
        'expected_overall_result': expected_overall_result,
        'actual_overall_result': effective_overall_status,
        'overall_match': overall_match,
        'expected_country_status': expected_country_status,
        'actual_country_status': result.country_status,
        'country_match': country_match,
        'expected_deemed_export_risk_level': expected_deemed_export_risk_level,
        'actual_deemed_export_risk_level': actual_deemed_export_risk_level,
        'deemed_export_match': deemed_export_match,
        'deemed_export_risk_score': round(result.deemed_export_risk.risk_score, 3),
        'expected_red_flag_level': expected_red_flag_level,
        'actual_red_flag_level': actual_red_flag_level,
        'red_flag_match': red_flag_match,
        'red_flag_score': round(result.red_flag_assessment.score, 3),
        'red_flag_count': result.red_flag_assessment.total_flags_checked,
        'triggered_flags': len(result.red_flag_assessment.flags_triggered),
        'debarred_info': debarred_info,
        'debarred_match': debarred_match,
        'required_license_type': result.required_license_type,
        'explanation': result.explanation,
        'status': status,
    }


def write_csv_results(results: List[Dict[str, Any]], output_path: str) -> None:
    """Write results to CSV file."""
    if not results:
        return
    
    fieldnames = [
        'case_id',
        'vendor_name',
        'vendor_country',
        'usml_category',
        'expected_overall_result',
        'actual_overall_result',
        'overall_match',
        'expected_country_status',
        'actual_country_status',
        'country_match',
        'expected_deemed_export_risk_level',
        'actual_deemed_export_risk_level',
        'deemed_export_match',
        'deemed_export_risk_score',
        'expected_red_flag_level',
        'actual_red_flag_level',
        'red_flag_match',
        'red_flag_score',
        'red_flag_count',
        'triggered_flags',
        'debarred_match',
        'required_license_type',
        'explanation',
        'status',
    ]
    
    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            # Filter result to only include fieldnames
            filtered = {k: v for k, v in result.items() if k in fieldnames}
            writer.writerow(filtered)


def generate_html_report(results: List[Dict[str, Any]], report_path: str) -> None:
    """Generate styled HTML report with color-coded results."""
    html_lines = [
        '<!DOCTYPE html>',
        '<html>',
        '<head>',
        '  <meta charset="utf-8">',
        '  <title>ITAR Validation Report</title>',
        '  <style>',
        '    body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }',
        '    h1 { color: #333; }',
        '    .summary { background-color: white; padding: 15px; margin-bottom: 20px; border-radius: 4px; }',
        '    .summary p { margin: 5px 0; }',
        '    table { border-collapse: collapse; width: 100%; background-color: white; }',
        '    th { background-color: #2c3e50; color: white; padding: 12px; text-align: left; }',
        '    td { padding: 10px 12px; border-bottom: 1px solid #ddd; }',
        '    tr:hover { background-color: #f9f9f9; }',
        '    .pass { background-color: #d4edda; color: #155724; font-weight: bold; }',
        '    .fail { background-color: #f8d7da; color: #721c24; font-weight: bold; }',
        '    .match { background-color: #d4edda; }',
        '    .mismatch { background-color: #fff3cd; }',
        '    .status-compliant { background-color: #d4edda; }',
        '    .status-non-compliant { background-color: #f8d7da; }',
        '    .status-requires-review { background-color: #fff3cd; }',
        '    .status-prohibited { background-color: #f8d7da; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <h1>ITAR Validation Report</h1>',
    ]
    
    # Summary section
    passed = sum(1 for r in results if r['status'] == 'PASS')
    failed = sum(1 for r in results if r['status'] == 'FAIL')
    total = len(results)
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    html_lines.extend([
        '  <div class="summary">',
        '    <h2>Summary</h2>',
        f'    <p><strong>Total Cases:</strong> {total}</p>',
        f'    <p><strong>Passed:</strong> {passed}</p>',
        f'    <p><strong>Failed:</strong> {failed}</p>',
        f'    <p><strong>Pass Rate:</strong> {pass_rate:.1f}%</p>',
        '  </div>',
    ])
    
    # Results table
    html_lines.extend([
        '  <table>',
        '    <thead>',
        '      <tr>',
        '        <th>Case ID</th>',
        '        <th>Vendor</th>',
        '        <th>Country</th>',
        '        <th>USML</th>',
        '        <th>Overall Status</th>',
        '        <th>Country Status</th>',
        '        <th>Deemed Export Risk</th>',
        '        <th>Red Flag Score</th>',
        '        <th>License Type</th>',
        '        <th>Result</th>',
        '      </tr>',
        '    </thead>',
        '    <tbody>',
    ])
    
    for result in results:
        status_class = 'pass' if result['status'] == 'PASS' else 'fail'
        country_class = 'match' if result['country_match'] else 'mismatch'
        
        overall_status_class = f"status-{result['actual_overall_result'].lower().replace('_', '-')}"
        
        html_lines.extend([
            '      <tr>',
            f'        <td>{result["case_id"]}</td>',
            f'        <td>{result["vendor_name"]}</td>',
            f'        <td>{result["vendor_country"]}</td>',
            f'        <td>{result["usml_category"]}</td>',
            f'        <td class="{overall_status_class}">{result["actual_overall_result"]}</td>',
            f'        <td class="{country_class}">{result["actual_country_status"]}</td>',
            f'        <td>{result["actual_deemed_export_risk_level"]} ({result["deemed_export_risk_score"]})</td>',
            f'        <td>{result["actual_red_flag_level"]} ({result["red_flag_score"]})</td>',
            f'        <td>{result["required_license_type"]}</td>',
            f'        <td class="{status_class}">{result["status"]}</td>',
            '      </tr>',
        ])
    
    html_lines.extend([
        '    </tbody>',
        '  </table>',
        '</body>',
        '</html>',
    ])
    
    with open(report_path, 'w') as f:
        f.write('\n'.join(html_lines))


def print_summary(results: List[Dict[str, Any]]) -> None:
    """Print summary statistics."""
    passed = sum(1 for r in results if r['status'] == 'PASS')
    failed = sum(1 for r in results if r['status'] == 'FAIL')
    total = len(results)
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    print('\n' + '='*70)
    print('BATCH SCORING SUMMARY')
    print('='*70)
    print(f'Total Cases Scored: {total}')
    print(f'Passed: {passed}')
    print(f'Failed: {failed}')
    print(f'Pass Rate: {pass_rate:.1f}%')
    print('='*70)
    
    # Breakdown by failure type
    if failed > 0:
        print('\nFailure Breakdown:')
        overall_failures = sum(1 for r in results if not r['overall_match'])
        country_failures = sum(1 for r in results if not r['country_match'])
        deemed_failures = sum(1 for r in results if not r['deemed_export_match'])
        red_flag_failures = sum(1 for r in results if not r['red_flag_match'])
        
        if overall_failures > 0:
            print(f'  Overall Status Mismatches: {overall_failures}')
        if country_failures > 0:
            print(f'  Country Status Mismatches: {country_failures}')
        if deemed_failures > 0:
            print(f'  Deemed Export Risk Mismatches: {deemed_failures}')
        if red_flag_failures > 0:
            print(f'  Red Flag Level Mismatches: {red_flag_failures}')
    
    print()


def main():
    """Main entry point."""
    # Parse arguments
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = '../tests/itar_validation_cases.csv'
    
    if len(sys.argv) > 2:
        output_path = sys.argv[2]
    else:
        output_path = '../tests/itar_validation_results.csv'
    
    html_report_path = output_path.replace('.csv', '_report.html')
    
    # Resolve relative paths from script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(script_dir, csv_path)
    if not os.path.isabs(output_path):
        output_path = os.path.join(script_dir, output_path)
    if not os.path.isabs(html_report_path):
        html_report_path = os.path.join(script_dir, html_report_path)
    
    # Read input CSV
    print(f'Reading ITAR validation cases from: {csv_path}')
    if not os.path.exists(csv_path):
        print(f'ERROR: CSV file not found: {csv_path}')
        sys.exit(1)
    
    cases = []
    with open(csv_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        cases = list(reader)
    
    print(f'Found {len(cases)} cases to score')
    
    # Score each case
    print('Scoring cases...')
    results = []
    for i, case in enumerate(cases, 1):
        try:
            result = score_case(case)
            results.append(result)
            if i % 10 == 0:
                print(f'  Scored {i}/{len(cases)} cases...')
        except Exception as e:
            print(f'ERROR scoring case {case.get("case_id", i)}: {e}')
            # Continue with next case
    
    # Write results
    print(f'\nWriting CSV results to: {output_path}')
    write_csv_results(results, output_path)
    
    # Generate HTML report
    print(f'Generating HTML report to: {html_report_path}')
    generate_html_report(results, html_report_path)
    
    # Print summary
    print_summary(results)


if __name__ == '__main__':
    main()
