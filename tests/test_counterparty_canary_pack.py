import importlib.util
import sys
from pathlib import Path
from requests import exceptions as requests_exceptions


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_counterparty_canary_pack.py"
SPEC = importlib.util.spec_from_file_location("run_counterparty_canary_pack", SCRIPT_PATH)
pack = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = pack
SPEC.loader.exec_module(pack)


def test_load_pack_returns_list():
    entries = pack.load_pack(str(pack.DEFAULT_PACK_FILE))
    assert isinstance(entries, list)
    assert len(entries) >= 10
    assert all("company" in entry for entry in entries)
    assert str(pack.DEFAULT_PACK_FILE).endswith("counterparty_canary_pack.json")


def test_overall_verdict_rolls_up_worst_case():
    assert pack.overall_verdict([{"verdict": "GO"}, {"verdict": "GO"}]) == "GO"
    assert pack.overall_verdict([{"verdict": "GO"}, {"verdict": "CAUTION"}]) == "CAUTION"
    assert pack.overall_verdict([{"verdict": "GO"}, {"verdict": "NO_GO"}]) == "NO_GO"


def test_parse_args_defaults_auto_stabilize(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_counterparty_canary_pack.py"])
    args = pack.parse_args()
    assert args.auto_stabilize is True
    assert args.workers == 1
    assert args.start_stagger_seconds == 1.5
    assert args.transient_retries_per_company == 1
    assert args.minimum_official_corroboration == "missing"
    assert args.max_blocked_official_connectors == -1
    assert args.connector == []
    assert args.require_dossier_html is True
    assert args.require_dossier_pdf is True


def test_print_json_payload_includes_report_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pack, "load_pack", lambda path: [])
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_counterparty_canary_pack.py", "--print-json", "--report-dir", str(tmp_path), "--token", "abc123"],
    )
    code = pack.main()
    payload = __import__("json").loads(capsys.readouterr().out)
    assert code == 0
    assert payload["report_md"].endswith("summary.md")
    assert payload["report_json"].endswith("summary.json")
    assert payload["verdict"] == "GO"


def test_entry_specific_connectors_override_pack_level_defaults(tmp_path, monkeypatch):
    pack_file = tmp_path / "pack.json"
    pack_file.write_text(
        '[{"company":"Demo Co","connectors":["public_html_ownership"]}]',
        encoding="utf-8",
    )

    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def wait_until_ready(self, *args, **kwargs):
            pass

        def _login(self):
            pass

    def fake_run_demo_gate(ns, client=None):
        captured["connectors"] = list(ns.connector)
        return pack.gate.DemoGateResult(
            verdict="GO",
            company_name="Demo Co",
            case_id="case-1",
            failures=[],
            warnings=[],
            timings_ms={},
            identifiers={},
            identifier_status={},
            graph={},
            ai_status={},
            assistant_ok=False,
            artifacts={
                "html": str(tmp_path / "demo" / "dossier.html"),
                "pdf": str(tmp_path / "demo" / "dossier.pdf"),
            },
        )

    monkeypatch.setattr(pack, "load_pack", lambda path: [{"company": "Demo Co", "connectors": ["public_html_ownership"]}])
    monkeypatch.setattr(pack.gate, "DemoGateClient", FakeClient)
    monkeypatch.setattr(pack.gate, "run_demo_gate", fake_run_demo_gate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_counterparty_canary_pack.py",
            "--pack-file",
            str(pack_file),
            "--report-dir",
            str(tmp_path / "reports"),
            "--token",
            "abc123",
            "--connector",
            "google_news",
        ],
    )

    code = pack.main()

    assert code == 0
    assert captured["connectors"] == ["public_html_ownership"]


def test_run_entry_converts_exceptions_into_no_go_payload(tmp_path, monkeypatch):
    def fake_run_demo_gate(ns, client=None):
        raise requests_exceptions.ReadTimeout("read timeout=90")

    monkeypatch.setattr(pack.gate, "run_demo_gate", fake_run_demo_gate)
    args = pack.argparse.Namespace(
        base_url="https://helios.xiphosllc.com",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        connector=[],
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        workers=1,
        start_stagger_seconds=0.0,
        transient_retries_per_company=0,
        max_blocked_official_connectors=-1,
        minimum_official_corroboration="missing",
        report_dir=str(tmp_path),
        print_json=False,
    )

    _, payload = pack._run_entry(1, 1, {"company": "Demo Co"}, args, tmp_path / "reports")

    assert payload["verdict"] == "NO_GO"
    assert payload["company_name"] == "Demo Co"
    assert "ReadTimeout" in payload["failures"][0]


def test_entry_specific_official_thresholds_flow_into_gate_namespace(tmp_path):
    entry = {
        "company": "Demo Co",
        "minimum_official_corroboration": "strong",
        "max_blocked_official_connectors": 2,
    }
    args = pack.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        connector=[],
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        workers=2,
        start_stagger_seconds=2.0,
        transient_retries_per_company=1,
        report_dir=str(tmp_path),
        print_json=False,
    )

    ns = pack._build_gate_namespace(args, entry, output_dir=tmp_path / "out", wait_for_ready_seconds=0)

    assert ns.minimum_official_corroboration == "strong"
    assert ns.max_blocked_official_connectors == 2


def test_fixture_files_resolve_into_seed_metadata(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text('{"records":[]}', encoding="utf-8")
    entry = {
        "company": "Lion City Mission Systems Pte. Ltd.",
        "seed_metadata": {"uen": "201912345N"},
        "fixture_files": {"singapore_acra_url": str(fixture)},
    }
    args = pack.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        connector=[],
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        workers=1,
        start_stagger_seconds=0.0,
        transient_retries_per_company=0,
        max_blocked_official_connectors=-1,
        minimum_official_corroboration="missing",
        report_dir=str(tmp_path),
        print_json=False,
    )

    ns = pack._build_gate_namespace(args, entry, output_dir=tmp_path / "out", wait_for_ready_seconds=0)

    assert ns.seed_metadata["uen"] == "201912345N"
    assert ns.seed_metadata["singapore_acra_url"].startswith("file://")


def test_public_html_fixture_files_stay_repo_relative_in_seed_metadata(tmp_path):
    entry = {
        "company": "FAUN Trackway",
        "fixture_files": {"public_html_fixture_page": "fixtures/public_html_ownership/faun_trackway_control.html"},
    }
    args = pack.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        connector=[],
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        workers=1,
        start_stagger_seconds=0.0,
        transient_retries_per_company=0,
        max_blocked_official_connectors=-1,
        minimum_official_corroboration="missing",
        report_dir=str(tmp_path),
        print_json=False,
    )

    ns = pack._build_gate_namespace(args, entry, output_dir=tmp_path / "out", wait_for_ready_seconds=0)

    assert ns.seed_metadata["public_html_fixture_page"] == "fixtures/public_html_ownership/faun_trackway_control.html"


def test_seed_metadata_expands_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_NORWAY_BRREG_URL", "https://example.test/brreg-live.json")
    entry = {
        "company": "Kongsberg Defence & Aerospace AS",
        "seed_metadata": {
            "norway_brreg_url": "$XIPHOS_NORWAY_BRREG_URL",
            "norway_org_number": "982574145",
        },
        "expected_fr_siren": "unused",
    }
    args = pack.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        connector=[],
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=0,
        auto_stabilize=True,
        workers=1,
        start_stagger_seconds=0.0,
        transient_retries_per_company=0,
        max_blocked_official_connectors=-1,
        minimum_official_corroboration="missing",
        report_dir=str(tmp_path),
        print_json=False,
    )

    ns = pack._build_gate_namespace(args, entry, output_dir=tmp_path / "out", wait_for_ready_seconds=0)

    assert ns.seed_metadata["norway_brreg_url"] == "https://example.test/brreg-live.json"


def test_control_path_pack_uses_fixture_backed_public_html_cases():
    entries = pack.load_pack(str(pack.ROOT / "fixtures" / "customer_demo" / "counterparty_control_path_pack.json"))
    by_company = {entry["company"]: entry for entry in entries}

    for company, expected_domain in (
        ("FAUN Trackway", "fauntrackway.com"),
        ("Greensea IQ", "greenseaiq.com"),
        ("Hascall-Denke", "hascall-denke.com"),
        ("HELLENIC DEFENCE SYSTEMS SA", "eas.gr"),
    ):
        entry = by_company[company]
        assert entry["connectors"] == ["public_html_ownership"]
        assert entry["seed_metadata"]["public_html_fixture_only"] is True
        assert entry["seed_metadata"]["website"].endswith(expected_domain)
        assert "public_html_fixture_page" in entry["fixture_files"]
