import importlib
import os
import sys
import time


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _sample_sam_entity():
    return {
        "entityRegistration": {
            "ueiSAM": "DE95TS6Y5XR6",
            "cageCode": "CJ542",
            "legalBusinessName": "ng4T GmbH",
            "dbaName": "",
            "purposeOfRegistrationDesc": "All Awards",
            "registrationStatus": "Active",
            "registrationDate": "2016-05-09",
            "registrationExpirationDate": "2026-05-20",
            "ueiStatus": "Active",
            "publicDisplayFlag": "Y",
            "exclusionStatusFlag": "N",
            "entityURL": "https://example.test/entity/DE95TS6Y5XR6",
        },
        "coreData": {
            "entityStructure": {
                "stateOfIncorporationDesc": "MARYLAND",
                "countryOfIncorporationDesc": "UNITED STATES",
                "companySecurityLevelDesc": "Government Secret",
                "highestEmployeeSecurityLevelDesc": "Government Top Secret",
            },
            "businessTypes": {
                "businessTypeList": [
                    {"businessTypeDesc": "For Profit Organization"},
                    {"businessTypeDesc": "Woman Owned Business"},
                ]
            },
            "naicsList": [
                {"naicsCode": "541330", "naicsDesc": "Engineering Services"},
            ],
            "pscList": [
                {"pscCode": "R425", "pscDescription": "Engineering and Technical Services"},
            ],
            "physicalAddress": {
                "city": "Baltimore",
                "stateOrProvinceCode": "MD",
                "countryCode": "USA",
                "zipCode": "21201",
            },
        },
        "integrityInformation": {
            "proceedingsData": {
                "proceedingsRecordCount": 1,
            },
            "responsibilityInformationCount": 2,
            "corporateRelationships": {
                "highestOwner": {
                    "legalBusinessName": "WSP GLOBAL INC",
                    "cageCode": "7NDG5",
                    "integrityRecords": "Yes",
                },
                "immediateOwner": {
                    "legalBusinessName": "LOUIS BERGER U.S., INC.",
                    "cageCode": "7NDG5",
                    "integrityRecords": "No",
                },
            },
        },
    }


def test_sam_gov_enrich_extracts_registration_integrity_and_owner_context(monkeypatch):
    if "osint.sam_gov" in sys.modules:
        sam_gov = importlib.reload(sys.modules["osint.sam_gov"])
    else:
        from osint import sam_gov  # type: ignore

    monkeypatch.setattr(sam_gov, "API_KEY", "test-key")
    monkeypatch.setattr(sam_gov, "_search_entities", lambda *_args, **_kwargs: [_sample_sam_entity()])
    monkeypatch.setattr(sam_gov, "_search_exclusions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sam_gov.time, "sleep", lambda *_args, **_kwargs: None)

    result = sam_gov.enrich("ng4T GmbH", country="DE")

    assert result.identifiers["uei"] == "DE95TS6Y5XR6"
    assert result.identifiers["cage"] == "CJ542"
    assert result.structured_fields["entity_matches"][0]["responsibility_information_count"] == 2
    categories = {finding.category for finding in result.findings}
    assert "registration" in categories
    assert "integrity" in categories
    assert "ownership" in categories
    assert any(signal["signal"] == "sam_integrity_records" for signal in result.risk_signals)
    rel_types = {rel["type"] for rel in result.relationships}
    assert rel_types == {"owned_by", "beneficially_owned_by"}
    immediate_rel = next(rel for rel in result.relationships if rel["type"] == "owned_by")
    assert immediate_rel["target_entity"] == "LOUIS BERGER U.S., INC."
    assert immediate_rel["structured_fields"]["relationship_scope"] == "immediate_owner"
    assert immediate_rel["target_identifiers"]["cage"] == "7NDG5"
    highest_rel = next(rel for rel in result.relationships if rel["type"] == "beneficially_owned_by")
    assert highest_rel["target_entity"] == "WSP GLOBAL INC"
    assert highest_rel["structured_fields"]["relationship_scope"] == "highest_owner"
    assert highest_rel["source_class"] == "gated_federal_source"


def test_sam_gov_report_surfaces_entity_match_summary(monkeypatch):
    from osint import enrichment as enrichment_mod
    from osint import sam_gov

    monkeypatch.setattr(sam_gov, "API_KEY", "test-key")
    monkeypatch.setattr(sam_gov, "_search_entities", lambda *_args, **_kwargs: [_sample_sam_entity()])
    monkeypatch.setattr(sam_gov, "_search_exclusions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sam_gov.time, "sleep", lambda *_args, **_kwargs: None)

    result = sam_gov.enrich("ng4T GmbH", country="DE")
    report = enrichment_mod._build_report("ng4T GmbH", "DE", [result], time.time())

    assert report["connector_status"]["sam_gov"]["structured_fields"]["entity_matches"][0]["highest_owner"]["name"] == "WSP GLOBAL INC"
    registration_finding = next(f for f in report["findings"] if f["category"] == "registration")
    assert registration_finding["structured_fields"]["company_security_level"] == "Government Secret"
    assert registration_finding["structured_fields"]["naics"] == ["541330 - Engineering Services"]


def test_sam_gov_accepts_legacy_env_alias(monkeypatch):
    monkeypatch.delenv("XIPHOS_SAM_API_KEY", raising=False)
    monkeypatch.setenv("SAM_GOV_API_KEY", "legacy-key")

    if "osint.sam_gov" in sys.modules:
        sam_gov = importlib.reload(sys.modules["osint.sam_gov"])
    else:
        from osint import sam_gov  # type: ignore

    assert sam_gov._get_api_key() == "legacy-key"


def test_sam_gov_entity_search_url_omits_include_sections_by_default():
    from osint import sam_gov

    url = sam_gov._build_entity_search_url("Boeing")

    assert "legalBusinessName=Boeing" in url
    assert "includeSections=" not in url


def test_sam_gov_entity_search_url_can_include_sections():
    from osint import sam_gov

    url = sam_gov._build_entity_search_url("Boeing", "entityRegistration,coreData")

    assert "includeSections=entityRegistration,coreData" in url


def test_sam_gov_exclusions_search_uses_exclusion_name_parameter(monkeypatch):
    from osint import sam_gov

    monkeypatch.setattr(sam_gov, "API_KEY", "test-key")
    captured: dict[str, str] = {}

    def fake_get(url, **_kwargs):
        captured["url"] = url
        return {"excludedEntity": []}, {"status": 200, "throttled": False, "error": ""}

    monkeypatch.setattr(sam_gov, "_get", fake_get)

    rows, meta = sam_gov._search_exclusions("Boeing")

    assert rows == []
    assert meta["status"] == 200
    assert "exclusionName=Boeing" in captured["url"]


def test_sam_gov_reports_rate_limit_without_false_no_match(monkeypatch):
    from osint import sam_gov

    monkeypatch.setattr(sam_gov, "API_KEY", "test-key")
    monkeypatch.setattr(
        sam_gov,
        "_search_entities",
        lambda *_args, **_kwargs: (
            [],
            {
                "status": 429,
                "throttled": True,
                "next_access_time": "2026-Mar-27 00:00:00+0000 UTC",
                "error": "SAM.gov rate limit reached. API access resumes at 2026-Mar-27 00:00:00+0000 UTC.",
            },
        ),
    )
    monkeypatch.setattr(sam_gov, "_search_exclusions", lambda *_args, **_kwargs: ([], {"status": 200, "throttled": False, "error": ""}))
    monkeypatch.setattr(sam_gov.time, "sleep", lambda *_args, **_kwargs: None)

    result = sam_gov.enrich("Boeing", country="US")

    titles = [finding.title for finding in result.findings]
    assert "SAM.gov registration lookup deferred by rate limit" in titles
    assert "No SAM registration found" not in titles
    assert "rate limit reached" in result.error.lower()
    assert result.structured_fields["sam_api_status"]["entity_lookup"]["throttled"] is True


def test_sam_gov_exclusions_timeout_preserves_registration_signal(monkeypatch):
    from osint import sam_gov

    monkeypatch.setattr(sam_gov, "API_KEY", "test-key")
    monkeypatch.setattr(sam_gov, "_search_entities", lambda *_args, **_kwargs: [_sample_sam_entity()])
    monkeypatch.setattr(
        sam_gov,
        "_search_exclusions",
        lambda *_args, **_kwargs: (
            [],
            {"status": 0, "throttled": False, "error": "SAM.gov exclusions lookup unavailable: timed out"},
        ),
    )
    monkeypatch.setattr(sam_gov.time, "sleep", lambda *_args, **_kwargs: None)

    result = sam_gov.enrich("Boeing", country="US")

    titles = [finding.title for finding in result.findings]
    assert any(title.startswith("SAM authority record:") for title in titles)
    assert "SAM.gov exclusions lookup unavailable" in titles
    assert "No SAM registration found" not in titles


def test_sam_gov_relevance_scoring_accepts_trade_name_variants():
    from osint import sam_gov

    assert sam_gov._is_relevant_candidate("Anduril", "Anduril Industries, Inc.", threshold=0.6)
    assert sam_gov._is_relevant_candidate("LMT Defense", "LMT Defense, LLC", threshold=0.6)
    assert "anduril" in sam_gov._entity_query_variants("Anduril Industries, Inc.")
