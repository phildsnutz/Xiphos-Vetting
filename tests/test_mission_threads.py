import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from entity_resolution import ResolvedEntity


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_SECURE_ARTIFACTS_DIR", str(tmp_path / "secure-artifacts"))
    monkeypatch.setenv("XIPHOS_AUTH_ENABLED", "false")
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")

    server.db.init_db()
    server.init_auth_db()
    if server.HAS_AI:
        server.init_ai_tables()
    if server.HAS_KG:
        server.kg.init_kg_db()

    import hardening

    hardening.reset_rate_limiter()

    with server.app.test_client() as test_client:
        yield {"client": test_client, "server": server}


def _create_case(client, name="Mission Prime", country="US"):
    resp = client.post(
        "/api/cases",
        json={
            "name": name,
            "country": country,
            "ownership": {
                "publicly_traded": True,
                "state_owned": False,
                "beneficial_owner_known": True,
                "ownership_pct_resolved": 0.9,
                "shell_layers": 0,
                "pep_connection": False,
            },
            "data_quality": {
                "has_lei": True,
                "has_cage": True,
                "has_duns": True,
                "has_tax_id": True,
                "has_audited_financials": True,
                "years_of_records": 10,
            },
            "exec": {
                "known_execs": 4,
                "adverse_media": 0,
                "pep_execs": 0,
                "litigation_history": 0,
            },
            "program": "dod_unclassified",
            "profile": "defense_acquisition",
        },
    )
    assert resp.status_code == 201
    return resp.get_json()["case_id"]


def test_mission_thread_routes_create_attach_vendor_and_build_summary(client):
    test_client = client["client"]
    case_id = _create_case(test_client, name="Columbia Air Mobility")

    create_resp = test_client.post(
        "/api/mission-threads",
        json={
            "name": "INDOPACOM contested sustainment test",
            "description": "Lift sustainment across dispersed sites",
            "lane": "counterparty",
            "program": "c5isr_sustainment",
            "theater": "INDOPACOM",
            "mission_type": "contested_logistics",
        },
    )
    assert create_resp.status_code == 201
    thread = create_resp.get_json()
    thread_id = thread["id"]
    assert thread["name"] == "INDOPACOM contested sustainment test"
    assert thread["status"] == "draft"
    assert thread["member_count"] == 0

    add_member_resp = test_client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={
            "vendor_id": case_id,
            "role": "air_lift_provider",
            "criticality": "critical",
            "subsystem": "heavy_lift",
            "site": "Honolulu",
            "notes": "Primary rotary lift node",
        },
    )
    assert add_member_resp.status_code == 201
    member = add_member_resp.get_json()
    assert member["vendor_id"] == case_id
    assert member["vendor"]["name"] == "Columbia Air Mobility"
    assert member["latest_score"]["calibrated_tier"]

    get_resp = test_client.get(f"/api/mission-threads/{thread_id}")
    assert get_resp.status_code == 200
    thread_detail = get_resp.get_json()
    assert thread_detail["member_count"] == 1
    assert len(thread_detail["members"]) == 1
    assert thread_detail["members"][0]["role"] == "air_lift_provider"

    summary_resp = test_client.get(f"/api/mission-threads/{thread_id}/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.get_json()
    assert summary["member_count"] == 1
    assert summary["vendor_member_count"] == 1
    assert summary["role_distribution"]["air_lift_provider"] == 1
    assert summary["criticality_distribution"]["critical"] == 1
    assert summary["graph"]["entity_count"] >= 1
    assert summary["graph"]["relationship_count"] == 0

    graph_resp = test_client.get(f"/api/mission-threads/{thread_id}/graph?depth=2")
    assert graph_resp.status_code == 200
    graph = graph_resp.get_json()
    assert graph["mission_thread_id"] == thread_id
    assert graph["vendor_ids"] == [case_id]
    assert graph["entity_count"] >= 1
    assert graph["relationship_count"] == 0
    assert graph["intelligence"]["thin_graph"] is True


def test_mission_thread_graph_accepts_explicit_entity_members(client):
    test_client = client["client"]
    server = client["server"]

    create_resp = test_client.post(
        "/api/mission-threads",
        json={"name": "Payment route dependency map", "lane": "counterparty"},
    )
    assert create_resp.status_code == 201
    thread_id = create_resp.get_json()["id"]

    source = ResolvedEntity(
        id="entity:vendor-alpha",
        canonical_name="Vendor Alpha",
        entity_type="company",
        aliases=[],
        identifiers={"lei": "549300TESTALPHA"},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.95,
        last_updated="2026-03-31T00:00:00Z",
    )
    target = ResolvedEntity(
        id="entity:bank-bravo",
        canonical_name="Bank Bravo",
        entity_type="bank",
        aliases=[],
        identifiers={"bic": "BRAVOUS33"},
        country="US",
        relationships=[],
        sources=["fixture"],
        confidence=0.92,
        last_updated="2026-03-31T00:00:00Z",
    )
    server.kg.save_entity(source)
    server.kg.save_entity(target)
    server.kg.save_relationship(
        source.id,
        target.id,
        "routes_payment_through",
        confidence=0.88,
        data_source="fixture",
        evidence="Treasury operations route through Bank Bravo",
        vendor_id="case-fixture",
    )

    add_member_resp = test_client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={
            "entity_id": source.id,
            "role": "payment_path",
            "criticality": "high",
        },
    )
    assert add_member_resp.status_code == 201
    member = add_member_resp.get_json()
    assert member["entity"]["canonical_name"] == "Vendor Alpha"

    graph_resp = test_client.get(f"/api/mission-threads/{thread_id}/graph?depth=2")
    assert graph_resp.status_code == 200
    graph = graph_resp.get_json()
    assert graph["entity_count"] >= 2
    assert graph["relationship_count"] == 1
    assert graph["relationship_type_distribution"]["routes_payment_through"] == 1
    assert graph["intelligence"]["intermediary_edge_count"] >= 1

    list_resp = test_client.get("/api/mission-threads?limit=10")
    assert list_resp.status_code == 200
    payload = list_resp.get_json()
    assert payload["total"] >= 1
    assert any(item["id"] == thread_id for item in payload["mission_threads"])


def test_add_mission_thread_member_passes_boolean_flag_to_db(monkeypatch):
    import mission_threads

    captured: dict[str, tuple] = {}

    class FakeRow(dict):
        def keys(self):
            return super().keys()

    class FakeResult:
        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            if "SELECT id FROM mission_thread_members" in sql and "ORDER BY id DESC" not in sql:
                return FakeResult(None)
            if "INSERT INTO mission_thread_members" in sql:
                captured["insert_params"] = params
                return FakeResult(None)
            if "SELECT id FROM mission_thread_members" in sql and "ORDER BY id DESC" in sql:
                return FakeResult(FakeRow({"id": 7}))
            if "INSERT INTO mission_thread_roles" in sql:
                return FakeResult(None)
            if "UPDATE mission_threads SET updated_at" in sql:
                return FakeResult(None)
            raise AssertionError(sql)

    monkeypatch.setattr(mission_threads, "_ensure_thread_exists", lambda thread_id: None)
    monkeypatch.setattr(
        mission_threads,
        "_validate_member_targets",
        lambda vendor_id, entity_id: (
            {
                "id": vendor_id,
                "name": "Pacific Aerial Fuel Systems",
                "country": "US",
                "program": "ace_refuel_ops",
                "profile": "defense_acquisition",
            },
            None,
        ),
    )
    monkeypatch.setattr(mission_threads.db, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(mission_threads, "get_mission_thread_member", lambda member_id: {"id": member_id})

    member = mission_threads.add_mission_thread_member(
        "mt-postgres-bool",
        vendor_id="c-fixture-pacific-aerial-fuel",
        role="forward_refuel",
        criticality="mission_critical",
        subsystem="fuel",
        site="Saipan",
        is_alternate=False,
        notes="Primary wet-wing defuel and refuel provider.",
    )

    assert member["id"] == 7
    assert captured["insert_params"][7] is False


def test_mission_thread_member_passport_wraps_supplier_passport_with_mission_context(client):
    test_client = client["client"]
    primary_case_id = _create_case(test_client, name="Ghost Air Sustainment")
    alternate_case_id = _create_case(test_client, name="Ghost Air Alternate")

    create_resp = test_client.post(
        "/api/mission-threads",
        json={
            "name": "Rotorcraft sustainment mesh",
            "lane": "counterparty",
            "program": "rotary_lift",
            "theater": "INDOPACOM",
            "mission_type": "contested_logistics",
        },
    )
    assert create_resp.status_code == 201
    thread_id = create_resp.get_json()["id"]

    primary_member_resp = test_client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={
            "vendor_id": primary_case_id,
            "role": "heavy_lift_provider",
            "criticality": "mission_critical",
            "subsystem": "lift",
            "site": "Honolulu",
        },
    )
    assert primary_member_resp.status_code == 201
    primary_member = primary_member_resp.get_json()

    alternate_member_resp = test_client.post(
        f"/api/mission-threads/{thread_id}/members",
        json={
            "vendor_id": alternate_case_id,
            "role": "heavy_lift_provider",
            "criticality": "important",
            "subsystem": "lift",
            "site": "Honolulu",
            "is_alternate": True,
        },
    )
    assert alternate_member_resp.status_code == 201

    passport_resp = test_client.get(
        f"/api/mission-threads/{thread_id}/members/{primary_member['id']}/passport"
    )
    assert passport_resp.status_code == 200
    passport = passport_resp.get_json()
    assert passport["passport_version"] == "mission-thread-passport-v1"
    assert passport["mission_thread"]["id"] == thread_id
    assert passport["member"]["vendor_id"] == primary_case_id
    assert passport["mission_context"]["role"] == "heavy_lift_provider"
    assert passport["mission_context"]["criticality"] == "mission_critical"
    assert len(passport["mission_context"]["alternate_members"]) == 1
    assert passport["mission_context"]["alternate_members"][0]["vendor_id"] == alternate_case_id
    assert passport["supplier_passport"]["vendor"]["id"] == primary_case_id
    assert "graph" in passport["supplier_passport"]
    assert passport["supplier_passport"]["graph"]["mission_context"]["mission_thread_id"] == thread_id
    assert passport["supplier_passport"]["graph"]["top_nodes_by_mission_importance"] is not None
