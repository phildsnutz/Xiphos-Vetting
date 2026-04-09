import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import axiom_known_proximity  # noqa: E402


def test_axiom_known_proximity_returns_kavaliro_fixture_signal():
    result = axiom_known_proximity.enrich("Kavaliro")

    assert result.error == ""
    assert result.identifiers["website"] == "https://www.kavaliro.com"
    assert result.identifiers["cage"] == "5B1D2"
    assert any(finding.category == "teaming_proximity" for finding in result.findings)
    assert any(finding.category == "vehicle_proximity" for finding in result.findings)

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert ("subcontractor_of", "SMX") in rel_types
    assert ("subcontractor_of", "Parsons") in rel_types
    assert ("subcontractor_of", "Alion") in rel_types
    assert ("subcontractor_of", "CACI") in rel_types
    assert ("teamed_with", "The Unconventional") in rel_types
    assert ("competed_on", "CEOIS") in rel_types
    assert ("competed_on", "JCETII") in rel_types
    assert ("competed_on", "C3PO") in rel_types
    assert ("competed_on", "LEIA") in rel_types
