from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("/Users/tyegonzalez/Desktop/Helios-Package Merged/scripts/run_current_product_stress_harness.py")
spec = importlib.util.spec_from_file_location("current_product_stress_harness", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_evaluate_room_contract_accepts_vehicle_first_leia_with_warning():
    stoa = module.CheckResult(
        name="stoa_browser_regression",
        status="PASS",
        details={
            "result": {
                "clarifying_state": "visible",
                "handoff": "ready",
                "leia_path": "vehicle_first",
                "smx_path": "vendor_first",
            }
        },
    )
    aegis = module.CheckResult(
        name="aegis_carryover_regression",
        status="PASS",
        details={"result": {"carryover": "passed"}},
    )

    result = module.evaluate_room_contract(stoa, aegis)

    assert result.status == "PASS"
    assert result.failures == []
    assert result.warnings == [
        "LEIA resolved vehicle-first; acceptable when no competing entity-memory signal is present"
    ]


def test_evaluate_room_contract_still_rejects_wrong_smx_path():
    stoa = module.CheckResult(
        name="stoa_browser_regression",
        status="PASS",
        details={
            "result": {
                "clarifying_state": "visible",
                "handoff": "ready",
                "leia_path": "ambiguity_then_vehicle",
                "smx_path": "vehicle_first",
            }
        },
    )
    aegis = module.CheckResult(
        name="aegis_carryover_regression",
        status="PASS",
        details={"result": {"carryover": "passed"}},
    )

    result = module.evaluate_room_contract(stoa, aegis)

    assert result.status == "FAIL"
    assert "SMX path drifted: vehicle_first" in result.failures
