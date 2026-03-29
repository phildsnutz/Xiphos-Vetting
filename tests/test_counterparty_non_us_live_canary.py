import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_counterparty_non_us_live_canary.py"
SPEC = importlib.util.spec_from_file_location("run_counterparty_non_us_live_canary", SCRIPT_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_validate_pack_rejects_missing_required_env_seed(tmp_path):
    pack_file = tmp_path / "pack.json"
    pack_file.write_text(
        '[{"company":"Kongsberg Defence & Aerospace AS","required_seed_keys":["norway_brreg_url"],"seed_metadata":{"norway_brreg_url":"$XIPHOS_NORWAY_BRREG_URL"}}]',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        runner.validate_pack(str(pack_file))

    assert "missing required live seed metadata" in str(exc.value)


def test_validate_pack_accepts_expanded_required_env_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_NORWAY_BRREG_URL", "https://example.test/brreg.json")
    pack_file = tmp_path / "pack.json"
    pack_file.write_text(
        '[{"company":"Kongsberg Defence & Aerospace AS","required_seed_keys":["norway_brreg_url"],"seed_metadata":{"norway_brreg_url":"$XIPHOS_NORWAY_BRREG_URL"}}]',
        encoding="utf-8",
    )

    payload = runner.validate_pack(str(pack_file))

    assert payload[0]["company"] == "Kongsberg Defence & Aerospace AS"
