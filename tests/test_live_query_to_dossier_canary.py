from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_live_query_to_dossier_canary.py")
spec = importlib.util.spec_from_file_location("live_query_to_dossier_canary", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_main_prints_json_payload(monkeypatch, capsys, tmp_path):
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"overall_verdict": "PASS", "report_md": str(tmp_path / "a.md"), "report_json": str(tmp_path / "a.json")})
        stderr = ""

    monkeypatch.setattr(module, "parse_args", lambda: module.argparse.Namespace(
        base_url="http://127.0.0.1:8080",
        email="",
        password="",
        token="abc",
        spec_file="/tmp/spec.json",
        report_dir=str(tmp_path),
        print_json=True,
    ))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: FakeProc())

    exit_code = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["overall_verdict"] == "PASS"
