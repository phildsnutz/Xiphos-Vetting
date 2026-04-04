import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _init_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.setenv("XIPHOS_DEV_MODE", "true")

    for module_name in [
        "db",
        "knowledge_graph",
        "validation_gate",
        "axiom_graph_promotion",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db
    import knowledge_graph

    db.init_db()
    knowledge_graph.init_kg_db()

    import axiom_gap_filler
    import validation_gate
    import axiom_graph_promotion

    return axiom_gap_filler, validation_gate, axiom_graph_promotion, knowledge_graph


def test_promote_validated_gap_fill_writes_claim_and_evidence(tmp_path, monkeypatch):
    axiom_gap_filler, validation_gate, axiom_graph_promotion, knowledge_graph = _init_modules(tmp_path, monkeypatch)

    result = axiom_gap_filler.GapFillResult(
        gap=axiom_gap_filler.IntelligenceGap(
            gap_id="gap-1",
            description="Unknown subcontractor identity",
            entity_name="SMX",
            vehicle_name="ITEAMS",
            gap_type="subcontractor_identity",
        ),
        filled=True,
        fill_confidence=0.87,
        attempts=[
            axiom_gap_filler.FillAttempt(
                approach_name="regulatory_filing_mine",
                approach_reasoning="Official award data resolved the vehicle participation.",
                findings=[{"source": "sam_gov", "value": "Named mission support subcontractor on active award"}],
            )
        ],
    )

    validation = validation_gate.validate_gap_fill_result(result)
    promotion = axiom_graph_promotion.promote_validated_gap_fill(result, validation, vendor_id="case-iteams")

    assert promotion.status == "promoted"
    assert promotion.promoted_claims == 1
    assert promotion.relationship_type == "awarded_under"

    network = knowledge_graph.get_entity_network(promotion.source_entity_id, depth=1, include_provenance=True)
    assert network["relationship_count"] == 1
    relationship = network["relationships"][0]
    assert relationship["rel_type"] == "awarded_under"
    assert relationship["target_entity_id"] == promotion.target_entity_id
    assert len(relationship["claim_records"]) == 1
    claim = relationship["claim_records"][0]
    assert claim["structured_fields"]["gap_id"] == "gap-1"
    assert claim["structured_fields"]["promotion_type"] == "axiom_gap_fill_validated"
    assert claim["evidence_records"][0]["source"] == "sam_gov"
    assert claim["evidence_records"][0]["artifact_ref"] == "axiom-gap://gap-1"


def test_promote_validated_gap_fill_defers_unsupported_gap_types(tmp_path, monkeypatch):
    axiom_gap_filler, validation_gate, axiom_graph_promotion, knowledge_graph = _init_modules(tmp_path, monkeypatch)

    result = axiom_gap_filler.GapFillResult(
        gap=axiom_gap_filler.IntelligenceGap(
            gap_id="gap-2",
            description="Ownership chain resolved from filings",
            entity_name="SMX",
            vehicle_name="ITEAMS",
            gap_type="ownership_chain",
        ),
        filled=True,
        fill_confidence=0.86,
        attempts=[
            axiom_gap_filler.FillAttempt(
                approach_name="regulatory_filing_mine",
                approach_reasoning="Official filings resolved the holding company.",
                findings=[{"source": "sec_edgar", "value": "Ownership statement in annual filing"}],
            )
        ],
    )

    validation = validation_gate.validate_gap_fill_result(result)
    promotion = axiom_graph_promotion.promote_validated_gap_fill(result, validation, vendor_id="case-iteams")

    assert validation.outcome == "accepted"
    assert promotion.status == "deferred"
    assert "safe automatic graph relationship" in promotion.reason
    with knowledge_graph.get_kg_conn() as conn:
        claim_count = conn.execute("SELECT COUNT(*) FROM kg_claims").fetchone()[0]
    assert claim_count == 0
