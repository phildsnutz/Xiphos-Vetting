from __future__ import annotations

import pytest

from scripts import run_public_ownership_wave as wave


def test_select_rows_skips_benchmark_names_and_filters_country():
    rows = [
        {"name": "Hefring Marine", "bucket": "create_us_component_electronics", "action": "create", "country": "US"},
        {"name": "Example Systems", "bucket": "create_us_component_electronics", "action": "create", "country": "US"},
        {"name": "Example Europe", "bucket": "create_us_component_electronics", "action": "create", "country": "DE"},
    ]

    selected = wave._select_rows(
        rows,
        limit=10,
        only_buckets={"create_us_component_electronics"},
        only_actions={"create"},
        only_country={"US"},
        exclude_names={wave.benchmark.normalize_name("Hefring Marine")},
    )

    assert [row["name"] for row in selected] == ["Example Systems"]


def test_build_summary_counts_control_and_ownership_paths():
    rows = [
        {
            "name": "Example Systems",
            "bucket": "create_us_component_electronics",
            "case_mode": "existing",
            "status": "ok",
            "control_path_count": 1,
            "ownership_path_count": 1,
            "intermediary_path_count": 0,
        },
        {
            "name": "Example Telecom",
            "bucket": "create_us_network_telecom",
            "case_mode": "created",
            "status": "ok",
            "control_path_count": 2,
            "ownership_path_count": 0,
            "intermediary_path_count": 1,
        },
        {
            "name": "Missing Case",
            "bucket": "create_us_precision_manufacturing",
            "status": "missing_case",
        },
    ]

    summary = wave._build_summary(rows, target_count=10)

    assert summary["rows_selected"] == 10
    assert summary["rows_completed"] == 3
    assert summary["rows_ok"] == 2
    assert summary["rows_error"] == 1
    assert summary["rows_with_control_paths"] == 2
    assert summary["rows_with_ownership_paths"] == 1
    assert summary["rows_with_intermediary_paths"] == 1
    assert summary["control_path_rate_pct"] == 100.0
    assert summary["case_mode_mix"] == {"existing": 1, "created": 1}


class DummyClient:
    def __init__(self, response: dict | None = None):
        self.response = response or {"case_id": "c-created"}
        self.calls: list[tuple[str, str, dict | None]] = []

    def create_case(self, name: str, country: str, *, seed_metadata: dict | None = None) -> dict:
        self.calls.append((name, country, seed_metadata))
        return self.response


def test_ensure_wave_case_creates_missing_create_rows():
    client = DummyClient()
    case_index: dict[str, dict] = {}
    row = {
        "name": "Omni Defense Technologies",
        "country": "US",
        "action": "create",
        "bucket": "create_us_component_electronics",
        "priority": "high",
        "sources": "public_search_ownership,public_html_ownership",
        "reason": "ownership_wave",
        "sequence": "42",
    }

    case_id, case_mode = wave._ensure_wave_case(client, case_index, row)

    assert case_id == "c-created"
    assert case_mode == "created"
    assert client.calls == [
        (
            "Omni Defense Technologies",
            "US",
            {
                "wave": "public_ownership",
                "bucket": "create_us_component_electronics",
                "priority": "high",
                "cohort_name": "Omni Defense Technologies",
                "sources": "public_search_ownership,public_html_ownership",
                "reason": "ownership_wave",
                "sequence": "42",
            },
        )
    ]
    assert case_index[wave.benchmark.normalize_name("Omni Defense Technologies")]["case_id"] == "c-created"


def test_ensure_wave_case_rejects_missing_replay_rows():
    client = DummyClient()
    case_index: dict[str, dict] = {}
    row = {
        "name": "Replay Missing Vendor",
        "country": "US",
        "action": "replay",
    }

    with pytest.raises(RuntimeError, match="missing case for non-create row"):
        wave._ensure_wave_case(client, case_index, row)

    assert client.calls == []
