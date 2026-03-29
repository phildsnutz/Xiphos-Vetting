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
import os

warnings.filterwarnings('ignore')

if __name__ != "__main__":
    import pytest
    pytest.skip("integration script is intended for direct execution only", allow_module_level=True)

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
test("Connector count >= 29", data.get('osint_connector_count', 0) >= 29, f"Got {data.get('osint_connector_count')}")
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
        test("Candidate has legal_name", bool(c.get('legal_name')), "Missing legal_name")
        test("Candidate has source", bool(c.get('source')), "Missing source")
        test("Confidence 0-1", 0 <= c.get('confidence', -1) <= 1, f"Got {c.get('confidence')}")

resp = requests.post(f'{BASE}/api/resolve', json={'name': 'Xiphos LLC'}, headers=h, verify=VERIFY_TLS, timeout=90)
test("Resolve Xiphos returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    cands = resp.json().get('candidates', [])
    sam_hits = [c for c in cands if 'sam_gov' in c.get('source', '')]
    test("Xiphos found on SAM.gov", len(sam_hits) > 0, "No SAM.gov candidates")
    if sam_hits:
        test("SAM has UEI", bool(sam_hits[0].get('uei')), "Missing UEI")
        test("SAM has CAGE", bool(sam_hits[0].get('cage')), "Missing CAGE")

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
        test("Contribution has NO 'confidence' field", 'confidence' not in c0, "Has 'confidence' key (THIS WAS THE BUG)")

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
    test("Clean US vendor no hard stop", not hs, f"Got is_hard_stop={hs}")
    test("is_hard_stop is boolean", isinstance(hs, bool), f"Got type {type(hs)}")

# ---- GRAPH PROPAGATION ----
print("\n[GRAPH PROPAGATION]")
resp = requests.get(f'{BASE}/api/graph/full-intelligence', headers=h, verify=VERIFY_TLS, timeout=30)
test("GET /api/graph/full-intelligence returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    nodes = data.get('nodes', [])
    edges = data.get('edges', [])
    test("Full-intelligence has nodes", len(nodes) > 0, f"Got {len(nodes)} nodes")
    test("Full-intelligence has edges", len(edges) > 0, f"Got {len(edges)} edges")
    if nodes:
        node_id = nodes[0].get('id', '')
        if node_id:
            resp = requests.post(f'{BASE}/api/graph/propagation', 
                                 json={'source_id': node_id, 'max_hops': 2, 'decay_factor': 0.6},
                                 headers=h, verify=VERIFY_TLS, timeout=30)
            test("POST /api/graph/propagation returns 200", resp.status_code == 200, f"Got {resp.status_code}")
            if resp.status_code == 200:
                prop_data = resp.json()
                test("Propagation has 'source' key", 'source' in prop_data, f"Keys: {list(prop_data.keys())}")
                test("Propagation has 'waves' key", 'waves' in prop_data, f"Keys: {list(prop_data.keys())}")
                if 'source' in prop_data:
                    source = prop_data.get('source', {})
                    test("Source has 'name'", 'name' in source, f"Keys: {list(source.keys())}")
                    test("Source has 'type'", 'type' in source, f"Keys: {list(source.keys())}")
                if 'waves' in prop_data:
                    waves = prop_data.get('waves', [])
                    test("Propagation has at least 1 wave", len(waves) >= 1, f"Got {len(waves)} waves")

# ---- PERSON SCREENING ----
print("\n[PERSON SCREENING]")
resp = requests.post(f'{BASE}/api/export/screen-person',
                     json={'name': 'Test Person', 'nationalities': ['US']},
                     headers=h, verify=VERIFY_TLS, timeout=30)
test("POST /api/export/screen-person returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    person_data = resp.json()
    test("Screen-person response has 'screening_status'", 'screening_status' in person_data, 
         f"Keys: {list(person_data.keys())}")

resp = requests.post(f'{BASE}/api/export/screen-batch',
                     json={'persons': [
                         {'name': 'John Smith', 'nationalities': ['US']},
                         {'name': 'Test Subject', 'nationalities': ['RU']}
                     ]},
                     headers=h, verify=VERIFY_TLS, timeout=30)
test("POST /api/export/screen-batch returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    batch_data = resp.json()
    test("Screen-batch has 'screenings' array", 'screenings' in batch_data, f"Keys: {list(batch_data.keys())}")
    if 'screenings' in batch_data:
        screenings = batch_data.get('screenings', [])
        test("Screenings count >= 2", len(screenings) >= 2, f"Got {len(screenings)} screenings")

# ---- GRAPH WORKSPACES ----
print("\n[GRAPH WORKSPACES]")
resp = requests.post(f'{BASE}/api/graph/workspaces',
                     json={'name': 'Integration Test Workspace'},
                     headers=h, verify=VERIFY_TLS, timeout=30)
test("POST /api/graph/workspaces returns 200/201", resp.status_code in [200, 201], f"Got {resp.status_code}")
workspace_id = None
if resp.status_code in [200, 201]:
    workspace_data = resp.json()
    workspace_id = workspace_data.get('id', '')
    if workspace_id:
        test("Workspace response has 'id'", bool(workspace_id), "No workspace ID returned")

resp = requests.get(f'{BASE}/api/graph/workspaces', headers=h, verify=VERIFY_TLS, timeout=30)
test("GET /api/graph/workspaces returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    ws_list = resp.json()
    workspaces = ws_list if isinstance(ws_list, list) else ws_list.get('workspaces', [])
    test("Workspaces list has at least 1", len(workspaces) >= 1, f"Got {len(workspaces)}")

if workspace_id:
    resp = requests.delete(f'{BASE}/api/graph/workspaces/{workspace_id}', headers=h, verify=VERIFY_TLS, timeout=30)
    test("DELETE /api/graph/workspaces/{id} returns 200", resp.status_code == 200, f"Got {resp.status_code}")

# ---- BRIEFING PDF ----
print("\n[BRIEFING PDF]")
resp = requests.post(f'{BASE}/api/graph/briefing',
                     json={'title': 'Integration Test Briefing'},
                     headers=h, verify=VERIFY_TLS, timeout=30)
test("POST /api/graph/briefing returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    content_type = resp.headers.get('Content-Type', '')
    resp_len = len(resp.content)
    test("Briefing Content-Type contains 'pdf'", 'pdf' in content_type.lower(), f"Got '{content_type}'")
    test("Briefing response length > 100", resp_len > 100, f"Got {resp_len} bytes")

# ---- TRANSACTION AUTHORIZATION ----
print("\n[TRANSACTION AUTHORIZATION]")
tx_payload = {
    "jurisdiction_guess": "ear",
    "destination_country": "GB",
    "classification_guess": "EAR99",
    "item_or_data_summary": "electronic components for radar systems",
    "end_use_summary": "defense radar integration",
    "request_type": "item_transfer",
    "program": "dod_classified",
}
resp = requests.post(f'{BASE}/api/export/authorize', json=tx_payload, headers=h, verify=VERIFY_TLS, timeout=60)
test("POST /api/export/authorize returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    txd = resp.json()
    test("Authorization has 'combined_posture'", 'combined_posture' in txd, f"Keys: {list(txd.keys())[:10]}")
    test("Authorization has 'confidence'", 'confidence' in txd, "Missing confidence")
    test("Confidence 0-1", 0 <= txd.get('confidence', -1) <= 1, f"Got {txd.get('confidence')}")
    test("Authorization has 'rules_guidance'", 'rules_guidance' in txd, "Missing rules_guidance")
    test("Authorization has 'license_exception'", 'license_exception' in txd, "Missing license_exception")
    test("Authorization has 'pipeline_log'", 'pipeline_log' in txd, "Missing pipeline_log")
    test("GB posture is low-friction", txd.get('combined_posture') in ('likely_nlr', 'likely_exception_or_exemption'),
         f"Got '{txd.get('combined_posture')}'")

# Prohibited destination test
tx_prohibited = {**tx_payload, "destination_country": "KP"}
resp = requests.post(f'{BASE}/api/export/authorize', json=tx_prohibited, headers=h, verify=VERIFY_TLS, timeout=60)
test("Prohibited destination returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    txp = resp.json()
    test("KP posture is 'likely_prohibited'", txp.get('combined_posture') == 'likely_prohibited',
         f"Got '{txp.get('combined_posture')}'")

# Authorization listing
resp = requests.get(f'{BASE}/api/export/authorizations', headers=h, verify=VERIFY_TLS, timeout=30)
test("GET /api/export/authorizations returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    auth_list = resp.json()
    test("Authorizations response is list or has items", isinstance(auth_list, (list, dict)), f"Got {type(auth_list)}")

# ---- LICENSE EXCEPTION ENGINE (S13) ----
print("\n[LICENSE EXCEPTION ENGINE]")

# Create case for license exception testing
resp = requests.post(f'{BASE}/api/cases', json=make_case_payload("LICENSE_TEST"), headers=h, verify=VERIFY_TLS, timeout=30)
test("Create test case returns 201", resp.status_code == 201, f"Got {resp.status_code}")
case_data = resp.json() if resp.status_code == 201 else {}
test_case_id = case_data.get('id', '')

# Test STA eligibility for GB with 3A611
tx_sta = {
    "jurisdiction_guess": "ear",
    "request_type": "physical_export",
    "classification_guess": "3A611",
    "item_or_data_summary": "Advanced semiconductor component",
    "destination_country": "GB",
    "destination_company": "UK Tech Ltd",
    "end_use_summary": "Commercial use in telecommunications",
    "case_id": test_case_id,
}
resp = requests.post(f'{BASE}/api/export/authorize', json=tx_sta, headers=h, verify=VERIFY_TLS, timeout=60)
test("STA eligibility query returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    sta_result = resp.json()
    test("Has license_exception field", 'license_exception' in sta_result, f"Keys: {list(sta_result.keys())}")
    if 'license_exception' in sta_result:
        le = sta_result['license_exception']
        eligible_key = 'eligible_exceptions' if 'eligible_exceptions' in le else 'all_eligible'
        test("license_exception has eligible list", eligible_key in le, f"Keys: {list(le.keys())}")
        if eligible_key in le:
            test("eligible list is list", isinstance(le[eligible_key], list), f"Got {type(le[eligible_key])}")
            if le[eligible_key]:
                e0 = le[eligible_key][0]
                code_key = 'code' if 'code' in e0 else 'exception_code'
                test("Exception has code", code_key in e0, f"Keys: {list(e0.keys())}")
                test("Exception has eligible", 'eligible' in e0, f"Keys: {list(e0.keys())}")

# Test KP destination gets no eligible exceptions (prohibited)
tx_kp = {**tx_sta, "destination_country": "KP"}
resp = requests.post(f'{BASE}/api/export/authorize', json=tx_kp, headers=h, verify=VERIFY_TLS, timeout=60)
test("KP destination returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    kp_result = resp.json()
    test("KP posture is likely_prohibited", kp_result.get('combined_posture') == 'likely_prohibited',
         f"Got '{kp_result.get('combined_posture')}'")

# ---- RE-AUTHORIZATION (S13) ----
print("\n[RE-AUTHORIZATION]")

# Create initial authorization
resp = requests.post(f'{BASE}/api/export/authorize', json=tx_sta, headers=h, verify=VERIFY_TLS, timeout=60)
test("Create initial authorization returns 200", resp.status_code == 200, f"Got {resp.status_code}")
initial_auth = resp.json()
initial_auth_id = initial_auth.get('id', '')
test("Initial auth has ID", bool(initial_auth_id), f"Got '{initial_auth_id}'")

if initial_auth_id:
    # Re-authorize with new destination (use fresh payload without case_id to avoid lookup issues)
    tx_re = {
        'jurisdiction_guess': 'ear', 'destination_country': 'FR', 'classification_guess': '3A611',
        'item_or_data_summary': 'Radar modules re-auth', 'end_use_summary': 'NATO ally integration',
        'request_type': 'item_transfer', 'program': 'dod_classified',
    }
    resp = requests.post(f'{BASE}/api/export/re-authorize/{initial_auth_id}', json=tx_re, headers=h, verify=VERIFY_TLS, timeout=60)
    test("Re-authorize returns 200", resp.status_code == 200, f"Got {resp.status_code} body={resp.text[:120]}")
    if resp.status_code == 200:
        re_auth = resp.json()
        test("Re-auth returns new auth_id", re_auth.get('id') != initial_auth_id, f"IDs: {re_auth.get('id')} vs {initial_auth_id}")
        test("Re-auth has combined_posture", 'combined_posture' in re_auth, f"Keys: {list(re_auth.keys())}")

    # Test invalid auth_id
    resp = requests.post(f'{BASE}/api/export/re-authorize/invalid-auth-id', json=tx_re, headers=h, verify=VERIFY_TLS, timeout=60)
    test("Invalid auth_id returns error", resp.status_code in (404, 400), f"Got {resp.status_code}")

# ---- AUTHORIZATION HISTORY (S13) ----
print("\n[AUTHORIZATION HISTORY]")

resp = requests.get(f'{BASE}/api/export/authorizations', headers=h, verify=VERIFY_TLS, timeout=30)
test("GET /api/export/authorizations returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    history = resp.json()
    test("History response is list or dict", isinstance(history, (list, dict)), f"Got {type(history)}")
    if isinstance(history, list):
        test("History has entries", len(history) > 0, f"Got {len(history)} entries")
        if history:
            h0 = history[0]
            test("Entry has case_id", 'case_id' in h0, f"Keys: {list(h0.keys())}")
            test("Entry has combined_posture", 'combined_posture' in h0, f"Keys: {list(h0.keys())}")
            test("Entry has created_at", 'created_at' in h0, f"Keys: {list(h0.keys())}")

# Test pagination
resp = requests.get(f'{BASE}/api/export/authorizations?limit=5&offset=0', headers=h, verify=VERIFY_TLS, timeout=30)
test("Pagination with limit/offset returns 200", resp.status_code == 200, f"Got {resp.status_code}")

# ---- BULK AUTHORIZATION (S13) ----
print("\n[BULK AUTHORIZATION]")

batch_payload = [
    {
        "jurisdiction_guess": "ear",
        "classification_guess": "3A611",
        "item_or_data_summary": "Item 1",
        "destination_country": "GB",
    },
    {
        "jurisdiction_guess": "itar",
        "classification_guess": "Category I",
        "item_or_data_summary": "Item 2",
        "destination_country": "DE",
    },
    {
        "jurisdiction_guess": "ear",
        "classification_guess": "5A002",
        "item_or_data_summary": "Item 3",
        "destination_country": "JP",
    },
]

resp = requests.post(f'{BASE}/api/export/authorize-batch', json={"transactions": batch_payload},
                    headers=h, verify=VERIFY_TLS, timeout=120)
test("Bulk authorization returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    batch_result = resp.json()
    test("Batch result is dict", isinstance(batch_result, dict), f"Got {type(batch_result)}")
    test("Batch has batch_id", 'batch_id' in batch_result, f"Keys: {list(batch_result.keys())}")
    test("Batch has results array", 'results' in batch_result, f"Keys: {list(batch_result.keys())}")
    if 'results' in batch_result:
        test("Results length matches input", len(batch_result['results']) == 3, f"Got {len(batch_result['results'])}")

# Test dry-run mode
resp = requests.post(f'{BASE}/api/export/authorize-batch', json={"transactions": batch_payload, "dry_run": True},
                    headers=h, verify=VERIFY_TLS, timeout=120)
test("Dry-run batch returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    dry_result = resp.json()
    test("Dry-run result has dry_run=true", bool(dry_result.get('dry_run')), f"Got {dry_result.get('dry_run')}")

# ---- PERSON GRAPH INGEST (S13) ----
print("\n[PERSON GRAPH INGEST]")

# Screen a person first
person_screen = {
    "name": "John Smith",
    "nationalities": ["CN"],
    "employer": "Huawei Technologies",
    "item_classification": "USML-Aircraft",
    "case_id": test_case_id,
}
resp = requests.post(f'{BASE}/api/export/screen-person', json=person_screen, headers=h, verify=VERIFY_TLS, timeout=60)
test("Screen person returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    screening = resp.json()
    test("Screening has id", 'id' in screening, f"Keys: {list(screening.keys())}")
    screening_id = screening.get('id', '')

    # Try to retroactively ingest persons for case
    if test_case_id:
        resp = requests.post(f'{BASE}/api/graph/ingest-persons/{test_case_id}', headers=h, verify=VERIFY_TLS, timeout=60)
        test("Retroactive person ingest returns 200", resp.status_code == 200, f"Got {resp.status_code}")
        if resp.status_code == 200:
            ingest_result = resp.json()
            test("Ingest result has entity count", 'entities_created' in ingest_result,
                 f"Keys: {list(ingest_result.keys())}")

# ---- COMPLIANCE DASHBOARD (S14) ----
print("\n[COMPLIANCE DASHBOARD]")

resp = requests.get(f'{BASE}/api/compliance-dashboard', headers=h, verify=VERIFY_TLS, timeout=30)
test("GET /api/compliance-dashboard returns 200", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    dash = resp.json()
    test("Dashboard has summary", 'summary' in dash, f"Keys: {list(dash.keys())}")
    test("Dashboard has counterparty_lane", 'counterparty_lane' in dash, f"Keys: {list(dash.keys())}")
    test("Dashboard has export_lane", 'export_lane' in dash, f"Keys: {list(dash.keys())}")
    test("Dashboard has cyber_lane", 'cyber_lane' in dash, f"Keys: {list(dash.keys())}")
    test("Dashboard has cross_lane_insights", 'cross_lane_insights' in dash, f"Keys: {list(dash.keys())}")
    test("Dashboard has activity_feed", 'activity_feed' in dash, f"Keys: {list(dash.keys())}")
    if 'summary' in dash:
        s = dash['summary']
        test("Summary has total_cases", 'total_cases' in s, f"Keys: {list(s.keys())}")
        test("Summary total_cases > 0", s.get('total_cases', 0) > 0, f"Got {s.get('total_cases')}")
        test("Summary has compliance_score", 'compliance_score' in s, f"Keys: {list(s.keys())}")
        test("Compliance score 0-100", 0 <= s.get('compliance_score', -1) <= 100, f"Got {s.get('compliance_score')}")

# ---- OPENAPI SPEC ----
print("\n[OPENAPI SPEC]")
resp = requests.get(f'{BASE}/api/health', headers=h, verify=VERIFY_TLS, timeout=15)
test("API health with all new endpoints", resp.status_code == 200, f"Got {resp.status_code}")
if resp.status_code == 200:
    hd = resp.json()
    test("Connector count still >= 29", hd.get('osint_connector_count', 0) >= 29,
         f"Got {hd.get('osint_connector_count')}")

# ---- SUMMARY ----
print(f"\n{'='*60}")
print(f"PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
if failures:
    print("\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
print(f"{'='*60}")
sys.exit(0 if failed == 0 else 1)
