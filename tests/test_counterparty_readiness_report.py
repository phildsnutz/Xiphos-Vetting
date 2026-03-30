from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_counterparty_readiness_report.py"
SPEC = importlib.util.spec_from_file_location("run_counterparty_readiness_report", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_overall_verdict_rolls_up_worst_case():
    results = [
        module.StepResult("smoke", "GO", ["python"], 0, "", ""),
        module.StepResult("canary", "CAUTION", ["python"], 2, "", ""),
        module.StepResult("company", "GO", ["python"], 0, "", ""),
    ]
    assert module.overall_verdict(results) == "CAUTION"


def test_build_company_command_includes_common_flags():
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        country="US",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=False,
        ai_readiness_mode="surface",
        check_assistant=False,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
        step_timeout_seconds=600,
        report_dir=str(ROOT / "tmp" / "readiness"),
    )
    command = module.build_company_command(args, "Yorktown Systems Group")
    joined = " ".join(command)
    assert "--company Yorktown Systems Group" in joined
    assert "--token abc123" in joined
    assert "--skip-ai" in command
    assert "--skip-assistant" in command
    assert "--print-json" in command


def test_run_step_marks_timeout_and_ignores_stale_artifacts(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    stale = artifact_dir / "old" / "summary.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"overall_verdict": "GO"}), encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise module.subprocess.TimeoutExpired(cmd=["python"], timeout=5, output="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.run_step("slow", ["python", "slow.py"], artifact_dir=artifact_dir, timeout_seconds=5)
    assert result.verdict == "NO_GO"
    assert result.returncode == 124
    assert "timed out after 5s" in result.stderr
    assert result.artifact_json is None


def test_ensure_access_token_promotes_email_password_to_token(monkeypatch, tmp_path):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "token-123"}

    captured = {}
    monkeypatch.setattr(module, "TOKEN_CACHE_PATH", tmp_path / "readiness_token.json")

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(module.requests, "post", fake_post)
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="ops@example.com",
        password="secret",
        token="",
    )

    module.ensure_access_token(args)

    assert args.token == "token-123"
    assert args.email == ""
    assert args.password == ""
    assert captured["url"].endswith("/api/auth/login")


def test_ensure_access_token_uses_cached_token(monkeypatch, tmp_path):
    cache_path = tmp_path / "readiness_token.json"
    cache_path.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:8080",
                "email": "ops@example.com",
                "token": "cached-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "TOKEN_CACHE_PATH", cache_path)
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="ops@example.com",
        password="secret",
        token="",
    )

    module.ensure_access_token(args)

    assert args.token == "cached-token"
    assert args.email == ""
    assert args.password == ""


def test_main_retries_smoke_once_after_expired_cached_token(monkeypatch, tmp_path, capsys):
    cache_path = tmp_path / "readiness_token.json"
    cache_path.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:8080",
                "email": "ops@example.com",
                "token": "expired-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "TOKEN_CACHE_PATH", cache_path)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "fresh-token"}

    login_calls = []

    def fake_post(url, json=None, timeout=None):
        login_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    smoke_calls = []

    def fake_run_step(name, command, artifact_dir=None, timeout_seconds=None):
        smoke_calls.append(name)
        if len(smoke_calls) == 1:
            return module.StepResult(
                "read_only_smoke",
                "NO_GO",
                command,
                1,
                'FAIL: 401 UNAUTHORIZED: {"error":"Invalid or expired token"}',
                "",
            )
        return module.StepResult("read_only_smoke", "GO", command, 0, "PASS: read-only smoke complete", "")

    args = module.argparse.Namespace(
        token="",
        email="ops@example.com",
        password="secret",
        skip_smoke=False,
        skip_canary_pack=True,
        company=[],
        pack_manifest=str(module.DEFAULT_PACK_MANIFEST),
        report_dir=str(tmp_path),
        print_json=False,
        base_url="http://127.0.0.1:8080",
        country="US",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
        step_timeout_seconds=600,
    )

    monkeypatch.setattr(module.requests, "post", fake_post)
    monkeypatch.setattr(module, "run_step", fake_run_step)
    monkeypatch.setattr(module, "parse_args", lambda: args)

    code = module.main()
    capsys.readouterr()

    assert code == 0
    assert smoke_calls == ["read_only_smoke", "read_only_smoke"]
    assert len(login_calls) == 1
    assert args.token == "fresh-token"


def test_load_pack_manifest_requires_name_and_pack_file(tmp_path):
    manifest = tmp_path / "counterparty.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "counterparty_identity_foundation",
                    "pack_file": "fixtures/customer_demo/counterparty_identity_foundation_pack.json",
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = module.load_pack_manifest(str(manifest))
    assert loaded == [
        {
            "name": "counterparty_identity_foundation",
            "pack_file": "fixtures/customer_demo/counterparty_identity_foundation_pack.json",
            "connectors": [],
            "workers": 1,
            "start_stagger_seconds": 1.5,
            "transient_retries_per_company": 1,
            "include_ai": True,
            "check_assistant": True,
            "require_dossier_html": True,
            "require_dossier_pdf": True,
            "minimum_official_corroboration": "missing",
            "max_blocked_official_connectors": -1,
        }
    ]


def test_default_counterparty_pack_manifest_contains_three_steps():
    loaded = module.load_pack_manifest(str(module.DEFAULT_PACK_MANIFEST))
    assert [entry["name"] for entry in loaded] == [
        "counterparty_identity_foundation",
        "counterparty_dossier_quality",
        "counterparty_control_paths",
    ]
    assert loaded[0]["require_dossier_html"] is False
    assert loaded[0]["include_ai"] is False
    assert loaded[0]["workers"] == 1
    assert loaded[0]["start_stagger_seconds"] == 2.0
    assert loaded[0]["transient_retries_per_company"] == 1
    assert loaded[0]["minimum_official_corroboration"] == "strong"
    assert "sam_gov" in loaded[0]["connectors"]
    assert loaded[1]["require_dossier_pdf"] is True
    assert loaded[1]["workers"] == 1


def test_build_canary_command_includes_pack_file_and_scoped_report_dir():
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc123",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
        step_timeout_seconds=420,
        report_dir=str(ROOT / "tmp" / "readiness"),
    )
    command = module.build_canary_command(
        args,
        pack_name="counterparty_identity_foundation",
        pack_file="fixtures/customer_demo/counterparty_identity_foundation_pack.json",
        include_ai=False,
        check_assistant=False,
        require_dossier_html=False,
        require_dossier_pdf=False,
        connectors=["sam_gov", "public_search_ownership"],
        workers=2,
        start_stagger_seconds=2.0,
        transient_retries_per_company=1,
        minimum_official_corroboration="strong",
        max_blocked_official_connectors=-1,
    )
    joined = " ".join(command)
    assert "--pack-file" in command
    assert "--wait-for-ready-seconds" in command
    assert "--ai-readiness-mode" in command
    assert "--print-json" in command
    assert "--skip-ai" in command
    assert "--skip-assistant" in command
    assert "--skip-dossier-html" in command
    assert "--skip-dossier-pdf" in command
    assert "--workers" in command
    assert "--start-stagger-seconds" in command
    assert "--transient-retries-per-company" in command
    assert "--connector" in command
    assert "--minimum-official-corroboration" in command
    assert "--step-timeout-seconds" not in command
    assert "counterparty_identity_foundation_pack.json" in joined
    assert "canary-pack/counterparty_identity_foundation" in joined


def test_run_step_parses_json_payload(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.returncode = 2
            self.stdout = json.dumps(
                {
                    "overall_verdict": "CAUTION",
                    "report_md": "tmp/report.md",
                    "report_json": "tmp/report.json",
                }
            )
            self.stderr = ""

    def fake_run(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.run_step("canary", ["python", "script.py"])
    assert result.verdict == "CAUTION"
    assert result.payload["overall_verdict"] == "CAUTION"
    assert result.artifact_md == "tmp/report.md"
    assert result.artifact_json == "tmp/report.json"


def test_run_step_keeps_top_level_report_paths_over_company_artifacts(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.returncode = 0
            self.stdout = json.dumps(
                {
                    "overall_verdict": "GO",
                    "report_md": "tmp/readiness.md",
                    "report_json": "tmp/readiness.json",
                    "companies": [
                        {
                            "company_name": "Yorktown Systems Group",
                            "artifacts": {"json": "tmp/company.json", "md": "tmp/company.md"},
                        }
                    ],
                }
            )
            self.stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())
    result = module.run_step("canary", ["python", "script.py"])
    assert result.artifact_md == "tmp/readiness.md"
    assert result.artifact_json == "tmp/readiness.json"


def test_build_smoke_command_includes_ready_wait():
    args = module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="ops@example.com",
        password="secret",
        token="",
        wait_for_ready_seconds=180,
    )
    command = module.build_smoke_command(args)
    joined = " ".join(command)
    assert "--wait-for-ready-seconds 180" in joined


def test_smoke_no_go_short_circuits_canary_steps(monkeypatch, tmp_path, capsys):
    smoke = module.StepResult("read_only_smoke", "NO_GO", ["python"], 1, "", "")
    calls = []

    def fake_run_step(name, command, artifact_dir=None, timeout_seconds=None):
        calls.append(name)
        return smoke

    monkeypatch.setattr(module, "run_step", fake_run_step)
    args = module.argparse.Namespace(
        token="abc123",
        email="",
        password="",
        skip_smoke=False,
        skip_canary_pack=False,
        company=[],
        pack_manifest=str(module.DEFAULT_PACK_MANIFEST),
        report_dir=str(tmp_path),
        print_json=False,
        base_url="http://127.0.0.1:8080",
        country="US",
        program="dod_unclassified",
        profile="defense_acquisition",
        include_ai=True,
        ai_readiness_mode="surface",
        check_assistant=True,
        max_enrich_seconds=90,
        max_dossier_seconds=60,
        max_pdf_seconds=60,
        max_ai_seconds=90,
        max_warnings=2,
        wait_for_ready_seconds=120,
        step_timeout_seconds=600,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    code = module.main()
    captured = capsys.readouterr()
    assert code == 1
    assert calls == ["read_only_smoke"]
    assert "counterparty readiness" in captured.out


def test_write_report_includes_verdict_alias(tmp_path):
    results = [
        module.StepResult("read_only_smoke", "GO", ["python"], 0, "", ""),
        module.StepResult("counterparty_identity_foundation", "GO", ["python"], 0, "", ""),
    ]
    _, json_path = module.write_report(tmp_path, results)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["overall_verdict"] == "GO"
    assert payload["verdict"] == "GO"
