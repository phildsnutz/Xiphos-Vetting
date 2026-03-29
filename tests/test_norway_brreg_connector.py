from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

norway_brreg = importlib.import_module("osint.norway_brreg")


def test_norway_brreg_connector_extracts_official_identity_and_roles():
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "norway_brreg_fixture.json"
    result = norway_brreg.enrich(
        "Kongsberg Defence & Aerospace AS",
        country="NO",
        norway_brreg_url=fixture_path.as_uri(),
    )

    assert result.identifiers["norway_org_number"] == "982574145"
    assert result.identifiers["website"] == "https://www.kongsberg.com"
    assert any(rel["type"] == "officer_of" for rel in result.relationships)
    assert any(rel["type"] == "beneficially_owned_by" for rel in result.relationships)
    assert any("beneficial-owner access posture" in finding.title.lower() for finding in result.findings)
