#!/usr/bin/env python3
"""
Xiphos Helios Integration Test Suite

Tests the API contract between frontend and backend.
Catches regressions like: 173% confidence, USA vs US country codes, stale labels.

Usage: python3 tests/test_integration.py
"""

import requests
import warnings
import sys
import json
import os

warnings.filterwarnings('ignore')

BASE = os.environ.get("HELIOS_BASE_URL", "").strip()
EMAIL = os.environ.get("HELIOS_LOGIN_EMAIL", "").strip()
PASSWORD = os.environ.get("HELIOS_LOGIN_PASSWORD", "").strip()
_verify_tls_raw = (
    os.environ.get("HELIOS_VERIFY_TLS", "").strip()
    or os.environ.get("HELIOS_VERIFY_SSL", "").strip()
    or "true"
)
VERIFY_TLS = _verify_tls_raw.lower() in {"1", "true", "yes", "on"}

if not BASE or not EMAIL or not PASSWORD:
    print("Set HELIOS_BASE_URL, HELIOS_LOGIN_EMAIL, and HELIOS_LOGIN_PASSWORD before running this script.")
    sys.exit(2)

passed = 0
failed = 0
failures = []


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append(f"{name}: {detail}")
        print(f"  FAIL: {name} -- {detail}")


def make_case_payload(name="TEST VENDOR", country="US", program="dod_unclassified", **overrides):
    """Build a valid case creation payload."""
    payload = {
        "name": name, "country": country,
        "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True,
                       "ownership_pct_resolved": 0.8, "shell_layers": 0, "pep_connection": False},
        "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True,
                          "has_tax_id": True, "has_audited_financials": True, "years_of_records": 10},
        "exec": {"known_execs": 5, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
        "program": program, "profile": "defense_acquisition",
    }
    payload.update(overrides)
    return payload


def make_bare_payload(name="BARE VENDOR", country="US", program="dod_unclassified"):
    """Build a case payload with no data (worst-case data quality)."""
    return {
        "name": name, "country": country,
        "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False,
                       "ownership_pct_resolved": 0, "shell_layers": 0, "pep_connection": False},
        "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False,
                          "has_tax_id": False, "has_audited_financials": False, "years_of_records": 0},
        "exec": {"known_execs": 0, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
        "program": program, "profile": "defense_acquisition",
    }


print("=" * 60)
print("XIPHOS HELIOS INTEGRATION TEST SUITE")
print("=" * 60)

# ---- AUTH ----
print("\n[AUTHENTICATION]")
resp = requests.post(f'{BASE}/api/auth/login', json={'email': EMAIL, 'password': PASSWORD}, verify=VERIFY_TLS, timeout=15)
test("Login returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code != 200:
    print("FATAL: Cannot authenticate. Aborting.")
    sys.exit(1)
token = resp.json().get('token', '')
h = {'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}

# ---- HEALTH ----
print("\n[HEALTH]")
resp = requests.get(f'{BASE}/api/health', headers=h, verify=VERIFY_TLS, timeout=15)
data = resp.json()
test("Health returns 200", resp.status_code == 200, f"Got {resp.status_code}")
test("Connector count == 27", data.get('osint_connector_count') == 27, f"Got {data.get('osint_connector_count')}")
test("Version is set", bool(data.get('version')), f"Got '{data.get('version')}'")

# ---- ENTITY RESOLUTION ----
print("\n[ENTITY RESOLUTION]")
resp = requests.post(f'{BASE}/api/resolve', json={'name': 'Boeing'}, headers=h, verify=VERIFY_TLS, timeout=90)
test("Resolve Boeing returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    cands = resp.json().get('candidates', [])
    test("Boeing returns candidates", len(cands) > 0, f"Got {len(cands)}")
    if cands:
        c = cands[0]
        test("Candidate has legal_name", bool(c.get('legal_name')), f"Missing legal_name")
        test("Candidate has source", bool(c.get('source')), f"Missing source")
        test("Confidence 0-1", 0 <= c.get('confidence', -1) <= 1, f"Got {c.get('confidence')}")

resp = requests.post(f'{BASE}/api/resolve', json={'name': 'Xiphos LLC'}, headers=h, verify=VERIFY_TLS, timeout=90)
test("Resolve Xiphos returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    cands = resp.json().get('candidates', [])
    sam_hits = [c for c in cands if 'sam_gov' in c.get('source', '')]
    test("Xiphos found on SAM.gov", len(sam_hits) > 0, f"No SAM.gov candidates")
    if sam_hits:
        test("SAM has UEI", bool(sam_hits[0].get('uei')), f"Missing UEI")
        test("SAM has CAGE", bool(sam_hits[0].get('cage')), f"Missing CAGE")

# ---- CASE CREATION & SCORING ----
print("\n[SCORING]")

# Clean vendor with US country
resp = requests.post(f'{BASE}/api/cases', json=make_case_payload("CLEAN US VENDOR", "US"), headers=h, verify=VERIFY_TLS, timeout=30)
test("Create clean US case returns 201", resp.status_code == 201, f"Got {resp.status_code}")
if resp.status_code == 201:
    d = resp.json()
    score = d.get('composite_score', -1)
    test("Clean vendor score < 20%", score < 20, f"Got {score}%")
    test("Composite score 0-100", 0 <= score <= 100, f"Got {score}")

    cal = d.get('calibrated', {})
    contribs = cal.get('contributions', [])
    test("Has contributions", len(contribs) > 0, f"Got {len(contribs)}")

    if contribs:
        c0 = contribs[0]
        test("Contribution has 'factor'", 'factor' in c0, f"Keys: {list(c0.keys())}")
        test("Contribution has 'weight'", 'weight' in c0, f"Keys: {list(c0.keys())}")
        test("Contribution has 'signed_contribution'", 'signed_contribution' in c0, f"Keys: {list(c0.keys())}")
        test("Contribution has 'description'", 'description' in c0, f"Keys: {list(c0.keys())}")
        test("Contribution has NO 'confidence' field", 'confidence' not in c0, f"Has 'confidence' key (THIS WAS THE BUG)")

    # Check interval
    interval = cal.get('interval', {})
    if interval:
        lo = interval.get('lower', -1)
        hi = interval.get('upper', -1)
        cov = interval.get('coverage', -1)
        test("Interval lower 0-1", 0 <= lo <= 1, f"Got {lo}")
        test("Interval upper 0-1", 0 <= hi <= 1, f"Got {hi}")
        test("Interval coverage 0-1", 0 <= cov <= 1, f"Got {cov}")

    # Geography check for US
    geo = [c for c in contribs if c.get('factor') == 'geography']
    if geo:
        geo_raw = geo[0].get('raw_score', 1)
        geo_desc = geo[0].get('description', '')
        test("US geography raw < 0.10", geo_raw < 0.10, f"Got {geo_raw}")
        test("US geography says 'Allied'", 'Allied' in geo_desc, f"Got '{geo_desc}'")

# Country code normalization: "USA" (3-letter) should work like "US"
resp = requests.post(f'{BASE}/api/cases', json=make_case_payload("USA CODE TEST", "USA"), headers=h, verify=VERIFY_TLS, timeout=30)
test("Create case with 'USA' returns 201", resp.status_code == 201, f"Got {resp.status_code}")
if resp.status_code == 201:
    contribs = resp.json().get('calibrated', {}).get('contributions', [])
    geo = [c for c in contribs if c.get('factor') == 'geography']
    if geo:
        test("'USA' normalized: geography < 0.10", geo[0].get('raw_score', 1) < 0.10, f"Got {geo[0].get('raw_score')}")

# Bare vendor should score higher (data quality penalty)
resp = requests.post(f'{BASE}/api/cases', json=make_bare_payload("BARE VENDOR"), headers=h, verify=VERIFY_TLS, timeout=30)
test("Create bare case returns 201", resp.status_code == 201, f"Got {resp.status_code}")
if resp.status_code == 201:
    bare_score = resp.json().get('composite_score', -1)
    test("Bare vendor score > 20%", bare_score > 20, f"Got {bare_score}%")

# ---- CONTRACT TYPE VALIDATION ----
print("\n[CONTRACT TYPES]")
type_tests = [
    ("dod_classified", "CRITICAL_SCI"),
    ("dod_unclassified", "ELEVATED"),
    ("federal_non_dod", "ENHANCED"),
    ("regulated_commercial", "CONTROLLED"),
    ("commercial", "COMMERCIAL"),
    ("weapons_system", "ELEVATED"),  # backward compat
]
for program, expected_sensitivity in type_tests:
    resp = requests.post(f'{BASE}/api/cases', json=make_case_payload(f"TYPE_{program}", "US", program),
                         headers=h, verify=VERIFY_TLS, timeout=30)
    if resp.status_code == 201:
        sens = resp.json().get('calibrated', {}).get('sensitivity_context', '')
        test(f"'{program}' -> {expected_sensitivity}", sens == expected_sensitivity, f"Got '{sens}'")
    else:
        test(f"'{program}' case creation", False, f"Got {resp.status_code}")

# ---- VEHICLE SEARCH ----
print("\n[VEHICLE SEARCH]")
resp = requests.post(f'{BASE}/api/vehicle-search', json={'vehicle': 'OASIS', 'limit': 5},
                     headers=h, verify=VERIFY_TLS, timeout=60)
test("Vehicle search returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    vd = resp.json()
    test("Has primes or subs", vd.get('total_primes', 0) + vd.get('total_subs', 0) > 0,
         f"Primes={vd.get('total_primes')}, Subs={vd.get('total_subs')}")

# ---- HARD STOPS ----
print("\n[HARD STOPS]")
resp = requests.post(f'{BASE}/api/cases', json=make_case_payload("CLEAN NO STOPS", "US"),
                     headers=h, verify=VERIFY_TLS, timeout=30)
if resp.status_code == 201:
    hs = resp.json().get('is_hard_stop', None)
    test("Clean US vendor no hard stop", hs == False, f"Got is_hard_stop={hs}")
    test("is_hard_stop is boolean", isinstance(hs, bool), f"Got type {type(hs)}")

# ---- SUMMARY ----
print(f"\n{'='*60}")
print(f"PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
if failures:
    print(f"\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
print(f"{'='*60}")
sys.exit(0 if failed == 0 else 1)
