import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import vendor_procurement_support  # type: ignore  # noqa: E402


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "fixtures",
    "procurement_footprint",
    "vendor_procurement_support_fixture.json",
)


def test_vendor_procurement_support_builds_bundle_from_fixture():
    vendor_procurement_support.clear_vendor_procurement_support_cache()
    bundle = vendor_procurement_support.build_vendor_procurement_support(
        vendor_id="c-051e0cee",
        vendor={
            "id": "c-051e0cee",
            "name": "PARSONS CORPORATION",
            "vendor_input": {
                "seed_metadata": {
                    "vendor_procurement_fixture_path": FIXTURE_PATH,
                }
            },
        },
        sync_graph=False,
    )

    assert bundle is not None
    assert bundle["connectors_run"] == 1
    assert bundle["connectors_with_data"] == 1
    assert bundle["prime_vehicles"][0]["vehicle_name"] == "OASIS"
    assert bundle["sub_vehicles"][0]["vehicle_name"] == "OASIS"
    assert bundle["top_customers"][0]["agency"] in {"General Services Administration", "Department of Energy"}
    assert any(rel.get("rel_type") == "prime_on_vehicle" for rel in bundle["relationships"])
