from __future__ import annotations

from pathlib import Path

import requests

from backend.osint import EnrichmentResult, public_html_ownership, public_search_ownership


SEARCH_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "public_search_ownership"
HTML_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "public_html_ownership"


class _SearchResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _HtmlResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=utf-8"):
        self.text = text
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


def test_public_search_discovers_official_site_and_emits_backed_by(monkeypatch):
    search_html = (SEARCH_FIXTURE_DIR / "hefring_search_results.html").read_text(encoding="utf-8")
    home_html = (HTML_FIXTURE_DIR / "hefring_home.html").read_text(encoding="utf-8")
    funding_html = (HTML_FIXTURE_DIR / "hefring_funding_round.html").read_text(encoding="utf-8")

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            assert timeout == public_search_ownership.TIMEOUT
            if query == "Hefring Marine":
                return _SearchResponse(search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hefring.example":
            assert timeout == public_html_ownership.TIMEOUT
            return _HtmlResponse(home_html)
        if url == "https://hefring.example/news/hefring-funding-round":
            assert timeout == public_html_ownership.TIMEOUT
            return _HtmlResponse(funding_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hefring Marine", country="IS")

    assert result.identifiers["website"] == "https://hefring.example"
    finance_findings = [finding for finding in result.findings if finding.category == "finance"]
    assert len(finance_findings) == 1
    assert finance_findings[0].title == "Public site financial backer hint: Faber Ventures"

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "backed_by"
    assert relationship["target_entity"] == "Faber Ventures"
    assert relationship["evidence_url"] == "https://hefring.example/news/hefring-funding-round"


def test_public_search_external_identifiers_prefer_canonical_registration_uei(monkeypatch):
    conflict_html = """
    <html>
      <body>
        <p>The Unconventional LLC CAGE Code 83RJ2 DUNS Number 081215850.</p>
        <p>Awardees Yorktown Systems Group UEI: WFV9A8R6SAN5 Overview Analysis Registration People - Schedules 1 Vehicles - IDVs - Contracts.</p>
        <p>Showing registration information for UEI L5LMQSN59YE5 CAGE 4VJW9 instead.</p>
        <p>Legal Name YORKTOWN SYSTEMS GROUP INC UEI L5LMQSN59YE5 CAGE Code 4VJW9 DUNS Number 801478384.</p>
      </body>
    </html>
    """

    def fake_fetch_page(url: str):
        assert url == "https://highergov.example/yorktown"
        return conflict_html, "text/html; charset=utf-8"

    monkeypatch.setattr(public_html_ownership, "_fetch_page", fake_fetch_page)

    identifiers, findings, refs = public_search_ownership._extract_external_identifiers(
        "https://ysginc.com",
        {
            "url": "https://highergov.example/yorktown",
            "title": "Yorktown Systems Group - HigherGov",
            "score": 32,
        },
        vendor_name="Yorktown Systems Group",
    )

    assert identifiers["uei"] == "L5LMQSN59YE5"
    assert identifiers["cage"] == "4VJW9"
    assert identifiers["duns"] == "801478384"
    assert refs == ["https://highergov.example/yorktown"]
    assert any(finding.title == "Public search identifier hint: UEI L5LMQSN59YE5" for finding in findings)


def test_public_search_external_identifiers_drop_weak_vendor_misaligned_duns(monkeypatch):
    weak_html = """
    <html>
      <body>
        <p>The Unconventional LLC CAGE Code 83RJ2 DUNS Number 081215850.</p>
      </body>
    </html>
    """

    def fake_fetch_page(url: str):
        assert url == "https://thirdparty.example/profile"
        return weak_html, "text/html; charset=utf-8"

    monkeypatch.setattr(public_html_ownership, "_fetch_page", fake_fetch_page)

    identifiers, findings, refs = public_search_ownership._extract_external_identifiers(
        "https://ysginc.com",
        {
            "url": "https://thirdparty.example/profile",
            "title": "Yorktown Systems Group vendor profile",
            "score": 28,
        },
        vendor_name="Yorktown Systems Group",
    )

    assert identifiers == {}
    assert findings == []
    assert refs == []


def test_public_search_identifier_merge_prefers_parsed_page_over_snippet():
    identifiers = {"uei": "WFV9A8R6SAN5"}
    ranks = {"uei": 1}

    public_search_ownership._merge_identifier_values(
        identifiers,
        {"uei": "L5LMQSN59YE5"},
        identifier_ranks=ranks,
        incoming_rank=2,
    )

    assert identifiers["uei"] == "L5LMQSN59YE5"
    assert ranks["uei"] == 2


def test_public_search_identifier_merge_prefers_higher_confidence_snippet_over_weak_external_page():
    identifiers = {"duns": "801478384"}
    ranks = {"duns": 0.60}

    public_search_ownership._merge_identifier_values(
        identifiers,
        {"duns": "081215850"},
        identifier_ranks=ranks,
        incoming_rank=2,
        incoming_ranks={"duns": 0.59},
    )

    assert identifiers["duns"] == "801478384"
    assert ranks["duns"] == 0.60


def test_public_search_identifier_merge_rejects_different_cage_cluster():
    identifiers = {"cage": "4VJW9", "duns": "801478384"}
    ranks = {"cage": 2, "duns": 2}

    public_search_ownership._merge_identifier_values(
        identifiers,
        {"cage": "83RJ2", "duns": "081215850"},
        identifier_ranks=ranks,
        incoming_rank=2,
    )

    assert identifiers["cage"] == "4VJW9"
    assert identifiers["duns"] == "801478384"


def test_public_search_snippet_relationships_ignore_management_team_false_control_path():
    relationships, findings, risk_signals, artifact_refs = public_search_ownership._extract_snippet_relationships(
        "Yorktown Systems Group",
        "US",
        "https://ysginc.com",
        {
            "url": "https://www.offsetsystemsgroup.com/leadership",
            "title": "Leadership - Offset Systems Group",
            "snippet": (
                "Bryan Dyer, the President and Chief Executive Officer of Yorktown Systems Group, "
                "is the minority member of the Offset Systems Group JV executive management team."
            ),
            "score": 30,
        },
    )

    assert relationships == []
    assert findings == []
    assert risk_signals == []
    assert artifact_refs == ["https://www.offsetsystemsgroup.com/leadership"]


def test_public_search_extracts_cage_uei_duns_and_ncage_from_public_search_snippet(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://colheli.example/">Columbia Helicopters - Home</a>
          <a class="result__snippet" href="https://colheli.example/">Heavy-lift helicopter services and MRO.</a>
        </div>
      </body>
    </html>
    """
    identifier_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://highergov.example/vendors/columbia-helicopters">Columbia Helicopters, Inc. - HigherGov</a>
          <a class="result__snippet" href="https://highergov.example/vendors/columbia-helicopters">CAGE Code: 7W206 UEI: EBD3SM6LH8D3 DUNS Number: 987654321 NCAGE Code: U0ABC Company Type: Heavy-lift helicopter operator and Maintenance, Repair, and Overhaul provider.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Heavy-lift helicopters for defense and industrial operations.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Columbia Helicopters, Inc.":
                return _SearchResponse(search_html)
            if (
                "Columbia Helicopters" in query
                and any(token in query for token in ("CAGE Code", "UEI Unique Entity ID", "DUNS Number", "NCAGE Code"))
            ):
                return _SearchResponse(identifier_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://colheli.example":
            return _HtmlResponse(root_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Columbia Helicopters, Inc.", country="US")

    assert result.identifiers["website"] == "https://colheli.example"
    assert result.identifiers["cage"] == "7W206"
    assert result.identifiers["uei"] == "EBD3SM6LH8D3"
    assert result.identifiers["duns"] == "987654321"
    assert result.identifiers["ncage"] == "U0ABC"
    assert any(finding.title == "Public search identifier hint: CAGE 7W206" for finding in result.findings)
    assert any(finding.title == "Public search identifier hint: UEI EBD3SM6LH8D3" for finding in result.findings)
    assert any(finding.title == "Public search identifier hint: DUNS 987654321" for finding in result.findings)
    assert any(finding.title == "Public search identifier hint: NCAGE U0ABC" for finding in result.findings)


def test_public_search_fetches_identifier_page_when_search_snippet_is_thin(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://colheli.example/">Columbia Helicopters - Home</a>
          <a class="result__snippet" href="https://colheli.example/">Heavy-lift helicopter services and MRO.</a>
        </div>
      </body>
    </html>
    """
    identifier_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://highergov.example/vendors/columbia-helicopters">Columbia Helicopters, Inc. - HigherGov</a>
          <a class="result__snippet" href="https://highergov.example/vendors/columbia-helicopters">Heavy-lift helicopter services and federal awards.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Heavy-lift helicopters for defense and industrial operations.</p></body></html>"
    identifier_page_html = """
    <html>
      <body>
        <h1>Columbia Helicopters, Inc.</h1>
        <p>CAGE Code: 7W206</p>
        <p>UEI: EBD3SM6LH8D3</p>
        <p>DUNS Number: 009673609</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Columbia Helicopters, Inc.":
                return _SearchResponse(search_html)
            if (
                "Columbia Helicopters" in query
                and any(token in query for token in ("CAGE Code", "UEI Unique Entity ID", "DUNS Number"))
            ):
                return _SearchResponse(identifier_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://colheli.example":
            return _HtmlResponse(root_html)
        if url == "https://highergov.example/vendors/columbia-helicopters":
            return _HtmlResponse(identifier_page_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Columbia Helicopters, Inc.", country="US")

    assert result.identifiers["cage"] == "7W206"
    assert result.identifiers["uei"] == "EBD3SM6LH8D3"
    assert result.identifiers["duns"] == "009673609"
    assert any(
        finding.title == "Public search identifier hint: UEI EBD3SM6LH8D3"
        and finding.access_model == "search_public_html"
        for finding in result.findings
    )


def test_public_search_collapses_contact_page_to_site_root():
    assert (
        public_search_ownership._official_site_root("https://www.hefringmarine.com/contact")
        == "https://hefringmarine.com"
    )


def test_public_search_prefers_non_press_official_candidate():
    candidates = [
        {
            "url": "https://www.army-technology.com/contractors/antennas/codan/pressreleases/acquisition-of-domo-tactical-communications/",
            "title": "Codan Communications completes acquisition of Domo Tactical Communications",
            "score": 34,
            "blocked_host": False,
        },
        {
            "url": "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications",
            "title": "Codan to acquire Domo Tactical Communications",
            "score": 34,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates)

    assert selected is not None
    assert selected["url"] == "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications"


def test_public_search_prefers_country_consistent_site_for_us_vendor():
    candidates = [
        {
            "url": "https://www.columbiahelicopters.ca/",
            "title": "Columbia Helicopters",
            "snippet": "Commercial services across British Columbia and Alberta with tours and adventures.",
            "score": 48,
            "blocked_host": False,
        },
        {
            "url": "https://colheli.com/",
            "title": "Columbia Helicopters - Home",
            "snippet": "Heavy-lift helicopters for defense sustainment, aid, and industrial operations.",
            "score": 20,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="US")

    assert selected is not None
    assert selected["url"] == "https://colheli.com/"


def test_public_search_rejects_event_directory_as_official_site():
    candidates = [
        {
            "url": "https://industry.ausa.org/listing/advanced-government-logistics",
            "title": "Company details | Advanced Government Logistics, Inc - AUSA",
            "score": 34,
            "blocked_host": False,
        },
        {
            "url": "https://advancedgovernmentlogistics.example/",
            "title": "Advanced Government Logistics",
            "score": 26,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates)

    assert selected is not None
    assert selected["url"] == "https://advancedgovernmentlogistics.example/"


def test_public_search_prefers_corporate_root_over_newsroom_and_supplier_portal():
    candidates = [
        {
            "url": "https://boeing.mediaroom.com/",
            "title": "Boeing Newsroom",
            "snippet": "Official news and media resources for Boeing.",
            "score": 34,
            "blocked_host": False,
        },
        {
            "url": "https://www.boeing.com/",
            "title": "The Boeing Company Official Website",
            "snippet": "Official corporate site for The Boeing Company.",
            "score": 28,
            "blocked_host": False,
        },
        {
            "url": "https://www.boeingsuppliers.com/",
            "title": "Boeing Suppliers Portal",
            "snippet": "Supplier information and procurement portal.",
            "score": 30,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="US")

    assert selected is not None
    assert selected["url"] == "https://www.boeing.com/"


def test_public_search_rejects_recruiting_host_as_official_site():
    candidates = [
        {
            "url": "https://ats.rippling.com/columbia-helicopters/jobs",
            "title": "Columbia Helicopters, Inc.",
            "snippet": "View open jobs and apply online.",
            "score": 40,
            "blocked_host": False,
        },
        {
            "url": "https://colheli.com/",
            "title": "Columbia Helicopters - Home",
            "snippet": "Heavy-lift helicopter services and defense sustainment.",
            "score": 18,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="US")

    assert selected is not None
    assert selected["url"] == "https://colheli.com/"


def test_public_search_rejects_trade_directory_host_as_official_site():
    candidates = [
        {
            "url": "https://unmanned-network.com/member/codan-communications/",
            "title": "Domo Tactical Communications - Unmanned Network",
            "snippet": "Domo Tactical Communications, part of Codan Group.",
            "score": 40,
            "blocked_host": False,
        },
        {
            "url": "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications",
            "title": "Codan to acquire Domo Tactical Communications",
            "snippet": "Codan Limited acquires Domo Tactical Communications.",
            "score": 30,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="US")

    assert selected is not None
    assert selected["url"] == "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications"


def test_public_search_rejects_wiki_clone_in_favor_of_official_site():
    candidates = [
        {
            "url": "https://grokipedia.com/page/Hellenic_Defence_Systems",
            "title": "Hellenic Defence Systems - grokipedia.com",
            "snippet": "State-owned Greek defense company profile.",
            "score": 34,
            "blocked_host": False,
        },
        {
            "url": "https://www.eas.gr/en/",
            "title": "Hellenic Defence Systems",
            "snippet": "The Hellenic Defence Systems official corporate site.",
            "score": 26,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="GR")

    assert selected is not None
    assert selected["url"] == "https://www.eas.gr/en/"


def test_public_search_rejects_member_directory_in_favor_of_acronym_official_site():
    candidates = [
        {
            "url": "https://sekpy.gr/en/companies/hellenic-defence-systems-sa-2/",
            "title": "Hellenic Defence Systems SA - sekpy",
            "snippet": "GREEK DEFENSE SYSTEMS SA (EAS) designs, develops, manufactures and supplies NATO-type weapons and ammunition.",
            "score": 24,
            "blocked_host": False,
        },
        {
            "url": "https://www.eas.gr/en/",
            "title": "homepage - eas",
            "snippet": "The HELLENIC DEFENSE SYSTEMS S.A. (EAS) design, develop, manufacture and supply the Greek Armed Forces with NATO-type systems.",
            "score": 8,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="GR")

    assert selected is not None
    assert selected["url"] == "https://www.eas.gr/en/"


def test_public_search_rejects_appone_host_as_official_site():
    candidates = [
        {
            "url": "http://yorktownsystemsgroupinc.appone.com/",
            "title": "YORKTOWN SYSTEMS GROUP INC Jobs",
            "snippet": "Apply online for open positions.",
            "score": 42,
            "blocked_host": False,
        },
        {
            "url": "https://www.ysginc.com/",
            "title": "Yorktown Systems Group - Your Mission. Our Strength.",
            "snippet": "Defense services and mission support.",
            "score": 18,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._pick_official_candidate(candidates, country="US")

    assert selected is not None
    assert selected["url"] == "https://www.ysginc.com/"


def test_public_search_queries_use_primary_alias_first_for_compound_names():
    assert public_search_ownership._search_queries("FAUN Trackway / Command Holdings Group") == [
        "FAUN Trackway",
        "FAUN Trackway / Command Holdings Group",
    ]


def test_public_search_queries_strip_trailing_jurisdiction_token():
    assert public_search_ownership._search_queries("DOMO Tactical Communications US") == [
        "DOMO Tactical Communications",
        "DOMO Tactical Communications US",
    ]


def test_public_search_queries_include_short_brand_suffix_alias():
    assert public_search_ownership._search_queries("Greensea IQ") == [
        "Greensea IQ",
        "Greensea",
    ]


def test_site_scoped_queries_include_host_brand_and_generic_variant():
    assert public_search_ownership._site_scoped_queries(
        "APEX Space & Defense Systems",
        "https://www.apexspace.com",
    ) == [
        "site:www.apexspace.com APEX Space & Defense Systems owner investor shareholder acquired backed by",
        "site:www.apexspace.com apexspace owner investor shareholder acquired backed by",
        "site:www.apexspace.com owner investor shareholder acquired backed by",
    ]



def test_public_search_penalizes_directory_titles():
    score = public_search_ownership._score_candidate(
        "https://www.dnb.com/business-directory/company-profiles.vendor.test",
        "Vendor Test - Dun & Bradstreet",
        "Vendor Test",
    )

    assert score < 0


def test_public_search_uses_same_host_company_page_for_ownership(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="results">
          <div class="result">
            <a class="result__a" href="https://example.example/">Example Defense</a>
          </div>
          <div class="result">
            <a class="result__a" href="https://example.example/en/the-company/">THE COMPANY - Example Defense</a>
          </div>
        </div>
      </body>
    </html>
    """
    root_html = '<html><body><a href="/news/test">news</a></body></html>'
    company_html = """
    <html>
      <body>
        <p>
          Example Defense is a state-owned company. Having as main shareholder the
          Hellenic Ministry of Finance, the company is supervised by the Ministry of National Defence.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://example.example":
            return _HtmlResponse(root_html)
        if url == "https://example.example/en/the-company":
            return _HtmlResponse(company_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Example Defense", country="GR")

    assert result.identifiers["website"] == "https://example.example"
    assert any(rel["target_entity"] == "Hellenic Ministry of Finance" for rel in result.relationships)


def test_public_search_uses_site_scoped_query_for_same_host_funding_page(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://www.apexspace.com/">Apex Space</a>
          <a class="result__snippet" href="https://www.apexspace.com/">Productized satellite platforms.</a>
        </div>
      </body>
    </html>
    """
    site_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://www.apexspace.com/news/series-b">Apex announces Series B</a>
          <a class="result__snippet" href="https://www.apexspace.com/news/series-b/">Funding round update.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Satellite bus manufacturer.</p></body></html>"
    funding_html = """
    <html>
      <body>
        <p>
          Apex Space is backed by Andreessen Horowitz.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q")
            if query == "APEX Space & Defense Systems":
                return _SearchResponse(search_html)
            if query in {
                "site:apexspace.com APEX Space & Defense Systems owner investor shareholder acquired backed by",
                "site:apexspace.com apexspace owner investor shareholder acquired backed by",
                "site:apexspace.com owner investor shareholder acquired backed by",
            }:
                return _SearchResponse(site_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://www.apexspace.com":
            return _HtmlResponse(root_html)
        if url == "https://www.apexspace.com/news/series-b":
            return _HtmlResponse(funding_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("APEX Space & Defense Systems", country="US")

    assert result.identifiers["website"] == "https://apexspace.com"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "Andreessen Horowitz" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: Andreessen Horowitz"
        for finding in result.findings
    )


def test_same_host_candidate_pages_prioritize_company_over_news_article():
    candidates = [
        {"url": "https://example.example/", "title": "Example Defense"},
        {"url": "https://example.example/en/the-company/", "title": "THE COMPANY - Example Defense"},
        {"url": "https://example.example/news/operational-update", "title": "Operational update"},
    ]

    selected = public_search_ownership._same_host_candidate_pages(candidates, "https://example.example")

    assert selected[:2] == [
        "https://example.example",
        "https://example.example/en/the-company",
    ]


def test_public_search_uses_external_investor_page_when_official_site_is_silent(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://dudleyfund.example/greensea">Greensea IQ - Dudley Fund</a>
          <a class="result__snippet" href="https://dudleyfund.example/greensea">Portfolio company page</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    investor_html = """
    <html>
      <body>
        <p>
          Greensea IQ is a portfolio company of Dudley Fund. The company raised growth capital
          through an investment led by Dudley Fund.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://dudleyfund.example/greensea":
            return _HtmlResponse(investor_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "Dudley Fund" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: Dudley Fund"
        for finding in result.findings
    )


def test_public_search_uses_external_media_snippet_for_owner_phrase(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://hascall.example/">Hascall-Denke</a>
          <a class="result__snippet" href="https://hascall.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://defensemedia.example/story">It's Not How You Start</a>
          <a class="result__snippet" href="https://defensemedia.example/story">Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Military antenna systems.</p></body></html>"
    article_html = """
    <html>
      <body>
        <p>
          Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience
          working in the antenna industry, the company expanded its manufacturing line.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://hascall.example":
            return _HtmlResponse(root_html)
        if url == "https://defensemedia.example/story":
            return _HtmlResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall.example"
    assert any(rel["type"] == "owned_by" and rel["target_entity"] == "Mike Hascall" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Mike Hascall"
        for finding in result.findings
    )


def test_public_search_uses_leadership_suffix_for_private_owner_media_hit(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://hascall.example/">Hascall-Denke</a>
          <a class="result__snippet" href="https://hascall.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    owner_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://defensemedia.example/story">It's Not How You Start</a>
          <a class="result__snippet" href="https://defensemedia.example/story">Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Military antenna systems.</p></body></html>"
    article_html = """
    <html>
      <body>
        <p>
          Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience
          working in the antenna industry, the company expanded its manufacturing line.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Hascall-Denke":
                return _SearchResponse(official_search_html)
            if query == "Hascall-Denke owner investor shareholder acquired backed by":
                return _SearchResponse("<html><body></body></html>")
            if query == "Hascall-Denke founder president CEO owner":
                return _SearchResponse(owner_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hascall.example":
            return _HtmlResponse(root_html)
        if url == "https://defensemedia.example/story":
            return _HtmlResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall.example"
    assert any(rel["type"] == "owned_by" and rel["target_entity"] == "Mike Hascall" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Mike Hascall"
        for finding in result.findings
    )


def test_public_search_scans_beyond_top_five_results_for_private_owner_snippet(monkeypatch):
    crowded_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://hascall.example/">Hascall-Denke</a>
          <a class="result__snippet" href="https://hascall.example/">Official site for Hascall-Denke.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://allpeople.example/michael-hascall">Michael L. Hascall - Hascall-Denke</a>
          <a class="result__snippet" href="https://allpeople.example/michael-hascall">Contact info for Michael L. Hascall at Hascall-Denke.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://corporationwiki.example/hascall">Michael Hascall - President for Denke Laboratories, Inc.</a>
          <a class="result__snippet" href="https://corporationwiki.example/hascall">Corporate profile for Michael Hascall and related businesses.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://directory.example/hascall-denke">Hascall-Denke Company Directory Profile</a>
          <a class="result__snippet" href="https://directory.example/hascall-denke">Company directory profile and contact information for Hascall-Denke.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://manufacturer.example/hascall-denke">Hascall-Denke Manufacturing Overview</a>
          <a class="result__snippet" href="https://manufacturer.example/hascall-denke">Manufacturing overview and contact details for Hascall-Denke.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://profiles.example/michael-hascall">Michael Hascall at Hascall-Denke</a>
          <a class="result__snippet" href="https://profiles.example/michael-hascall">Business profile for Michael Hascall at Hascall-Denke.</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://defensemedia.example/story">It's Not How You Start</a>
          <a class="result__snippet" href="https://defensemedia.example/story">Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Military antenna systems.</p></body></html>"
    article_html = """
    <html>
      <body>
        <p>
          Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience
          working in the antenna industry, the company expanded its manufacturing line.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Hascall-Denke":
                return _SearchResponse(crowded_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hascall.example":
            return _HtmlResponse(root_html)
        if url == "https://defensemedia.example/story":
            return _HtmlResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall.example"
    assert any(rel["type"] == "owned_by" and rel["target_entity"] == "Mike Hascall" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Mike Hascall"
        for finding in result.findings
    )


def test_public_search_rejects_unrelated_acquisition_snippet_from_snippet_phase():
    candidates = [
        {
            "url": "https://finance.yahoo.com/news/daseke-acquired-tfi-international-140000895.html",
            "title": "Daseke to be Acquired by TFI International",
            "snippet": "Daseke common stockholders to receive $8.30 per share in cash after the acquisition.",
            "score": 0,
            "blocked_host": False,
        },
        {
            "url": "https://defensemedia.example/story",
            "title": "It's Not How You Start",
            "snippet": "Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience.",
            "score": 22,
            "blocked_host": False,
        },
    ]

    selected = public_search_ownership._snippet_signal_candidates(
        candidates,
        "https://hascall-denke.com",
        "Hascall-Denke",
    )

    urls = {candidate["url"] for candidate in selected}
    assert "https://defensemedia.example/story" in urls
    assert "https://finance.yahoo.com/news/daseke-acquired-tfi-international-140000895.html" not in urls


def test_public_search_does_not_let_generic_funding_directory_short_circuit_owner_snippet(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://hascall.example/">Hascall-Denke</a>
          <a class="result__snippet" href="https://hascall.example/">Official site for Hascall-Denke.</a>
        </div>
      </body>
    </html>
    """
    finance_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://discovery.example/company/hascall-denke/funding/">Hascall-denke Corp.:Funding,Funding Rounds,Funding Analysis - Discovery</a>
          <a class="result__snippet" href="https://discovery.example/company/hascall-denke/funding/">Discovery Company profile page for Hascall-denke Corp. including technical research, competitor monitor, market trends, company profile and stock symbol.</a>
        </div>
      </body>
    </html>
    """
    owner_search_html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://defensemedia.example/story">It's Not How You Start</a>
          <a class="result__snippet" href="https://defensemedia.example/story">Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Military antenna systems.</p></body></html>"
    finance_page_html = """
    <html>
      <head>
        <title>Hascall-denke Corp.:Funding,Funding Rounds,Funding Analysis - Discovery | PatSnap</title>
      </head>
      <body>
        <p>Discovery company profile page for Hascall-denke Corp.</p>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <p>
          Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience
          working in the antenna industry, the company expanded its manufacturing line.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Hascall-Denke":
                return _SearchResponse(official_search_html)
            if query == "Hascall-Denke portfolio capital funding investors":
                return _SearchResponse(finance_search_html)
            if query == "Hascall-Denke owner investor shareholder acquired backed by":
                return _SearchResponse("<html><body></body></html>")
            if query == "Hascall-Denke founder president CEO owner":
                return _SearchResponse(owner_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hascall.example":
            return _HtmlResponse(root_html)
        if url == "https://discovery.example/company/hascall-denke/funding":
            return _HtmlResponse(finance_page_html)
        if url == "https://defensemedia.example/story":
            return _HtmlResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall.example"
    assert any(rel["type"] == "owned_by" and rel["target_entity"] == "Mike Hascall" for rel in result.relationships)
    assert not any(rel["target_entity"] == "Discovery" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Mike Hascall"
        for finding in result.findings
    )


def test_public_search_uses_blocked_host_snippet_for_investor_hint(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ - CB Insights</a>
          <a class="result__snippet" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ's latest funding round is Unattributed. Investors of Greensea IQ include FreshTracks Capital.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital" for rel in result.relationships)
    assert any(rel["access_model"] == "search_snippet_only" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: FreshTracks Capital"
        and finding.access_model == "search_snippet_only"
        for finding in result.findings
    )


def test_public_search_uses_short_brand_alias_to_find_legacy_investor_result(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    legacy_investor_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.freshtrackscap.example/portfolio/greensea-systems">Greensea Systems - FreshTracks Capital</a>
          <a class="result__snippet" href="https://www.freshtrackscap.example/portfolio/greensea-systems">Portfolio company profile for Greensea Systems.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    investor_html = "<html><body><p>Portfolio company profile for Greensea Systems.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query == "Greensea IQ owner investor shareholder acquired backed by":
                return _SearchResponse("<html><body></body></html>")
            if query == "Greensea owner investor shareholder acquired backed by":
                return _SearchResponse(legacy_investor_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.freshtrackscap.example/portfolio/greensea-systems":
            return _HtmlResponse(investor_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: FreshTracks Capital"
        and finding.access_model == "search_public_html"
        for finding in result.findings
    )


def test_public_search_uses_extracted_legacy_alias_to_find_investor_result(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    transition_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://oceannews.example/greensea-transform">Greensea Systems, Inc. transforms into Greensea IQ</a>
          <a class="result__snippet" href="https://oceannews.example/greensea-transform">Greensea Systems, Inc. transforms into Greensea IQ: a unified vision for ocean robotics.</a>
        </div>
      </body>
    </html>
    """
    legacy_investor_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.freshtrackscap.example/portfolio/greensea-systems">Greensea Systems - FreshTracks Capital</a>
          <a class="result__snippet" href="https://www.freshtrackscap.example/portfolio/greensea-systems">Portfolio company profile for Greensea Systems.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    investor_html = "<html><body><p>Portfolio company profile for Greensea Systems.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            query = (params or {}).get("q") or ""
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query == "Greensea owner investor shareholder acquired backed by":
                return _SearchResponse(transition_search_html)
            if query in {
                f"Greensea Systems Inc{public_search_ownership.FINANCING_SEARCH_SUFFIX}",
                f"Greensea Systems, Inc{public_search_ownership.FINANCING_SEARCH_SUFFIX}",
                f"Greensea Systems, Inc.{public_search_ownership.FINANCING_SEARCH_SUFFIX}",
            }:
                return _SearchResponse(legacy_investor_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.freshtrackscap.example/portfolio/greensea-systems":
            return _HtmlResponse(investor_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: FreshTracks Capital"
        and finding.access_model == "search_public_html"
        for finding in result.findings
    )


def test_public_search_uses_brave_fallback_when_ddg_snippet_search_is_thin(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    brave_search_html = """
    <html>
      <body>
        <div class="snippet" data-type="web">
          <div class="result-wrapper">
            <div class="result-content">
              <a href="https://www.cbinsights.com/company/greensea-systems/financials" class="l1">
                <div class="title">Greensea IQ Stock Price, Funding, Valuation, Revenue &amp; Financial Statements</div>
              </a>
              <div class="generic-snippet">
                <div class="content">Greensea IQ has 2 investors. <strong>FreshTracks Capital</strong> invested in Greensea IQ's Other Investors funding round.</div>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or (params or {}).get("p") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.YAHOO_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BING_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            if query == "Greensea IQ owner investor shareholder acquired backed by":
                return _SearchResponse(brave_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital" for rel in result.relationships)
    assert any(rel["access_model"] == "search_snippet_only" for rel in result.relationships)


def test_public_search_uses_brave_for_official_site_when_duckduckgo_is_empty(monkeypatch):
    brave_html = """
    <html>
      <body>
        <div class="snippet" data-type="web">
          <a href="https://colheli.com/" class="result-header l1">Columbia Helicopters - Home</a>
          <div class="title">Columbia Helicopters - Home</div>
          <div class="content">Heavy-lift helicopter services and defense sustainment.</div>
        </div>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url in {
            public_search_ownership.SEARCH_URL,
            public_search_ownership.SEARCH_LITE_URL,
            public_search_ownership.YAHOO_SEARCH_URL,
            public_search_ownership.BING_SEARCH_URL,
        }:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse(brave_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)

    candidates = public_search_ownership._search_with_fallbacks(
        "Columbia Helicopters, Inc.",
        "Columbia Helicopters, Inc.",
        country="US",
    )

    assert candidates
    assert candidates[0]["url"] == "https://colheli.com/"
    assert candidates[0]["search_provider"] == "brave"


def test_public_search_unwraps_bing_redirect_url():
    href = (
        "https://www.bing.com/ck/a?!&amp;&amp;p=dummy&amp;ptn=3&amp;ver=2&amp;hsh=4"
        "&amp;u=a1aHR0cHM6Ly9jb2xoZWxpLmNvbS8&amp;ntb=1"
    )

    assert public_search_ownership._unwrap_result_url(href) == "https://colheli.com/"


def test_public_search_uses_bing_for_official_site_when_duckduckgo_is_empty(monkeypatch):
    bing_html = """
    <html>
      <body>
        <ol id="b_results">
          <li class="b_algo">
            <h2>
              <a href="https://www.bing.com/ck/a?!&&p=dummy&u=a1aHR0cHM6Ly9jb2xoZWxpLmNvbS8&ntb=1">
                Columbia Helicopters - Home
              </a>
            </h2>
            <div class="b_caption">
              <p>Heavy-lift helicopter services and defense sustainment.</p>
            </div>
          </li>
        </ol>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url in {public_search_ownership.SEARCH_URL, public_search_ownership.SEARCH_LITE_URL}:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BING_SEARCH_URL:
            return _SearchResponse(bing_html)
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)

    candidates = public_search_ownership._search_with_fallbacks(
        "Columbia Helicopters, Inc.",
        "Columbia Helicopters, Inc.",
        country="US",
    )

    assert candidates
    assert candidates[0]["url"] == "https://colheli.com/"
    assert candidates[0]["search_provider"] == "bing"


def test_public_search_keeps_searching_until_ownership_query_has_real_signal(monkeypatch):
    provider_calls: list[str] = []

    def weak_html(*args, **kwargs):
        provider_calls.append("duckduckgo_html")
        return [
            {
                "url": "https://hascall-denke.com/",
                "title": "Hascall-Denke",
                "snippet": "Official site for tactical fiber and cable assemblies.",
                "score": 42,
                "blocked_host": False,
            }
        ]

    def empty_lite(*args, **kwargs):
        provider_calls.append("duckduckgo_lite")
        return []

    def strong_yahoo(*args, **kwargs):
        provider_calls.append("yahoo")
        return [
            {
                "url": "https://www.defensemedia.example/hascall-denke",
                "title": "Hascall-Denke Overview",
                "snippet": "Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience working in the antenna industry.",
                "score": 24,
                "blocked_host": False,
                "search_provider": "yahoo",
            }
        ]

    def should_not_run(*args, **kwargs):
        raise AssertionError("search chain should stop once a high-signal ownership candidate is found")

    monkeypatch.setattr(public_search_ownership, "_search", weak_html)
    monkeypatch.setattr(public_search_ownership, "_search_lite", empty_lite)
    monkeypatch.setattr(public_search_ownership, "_search_yahoo", strong_yahoo)
    monkeypatch.setattr(public_search_ownership, "_search_brave", should_not_run)
    monkeypatch.setattr(public_search_ownership, "_search_bing", should_not_run)

    candidates = public_search_ownership._search_with_fallbacks(
        "Hascall-Denke founder president CEO owner",
        "Hascall-Denke",
        country="US",
    )

    urls = [candidate["url"] for candidate in candidates]
    assert urls == [
        "https://hascall-denke.com/",
        "https://www.defensemedia.example/hascall-denke",
    ]
    assert provider_calls == ["duckduckgo_html", "duckduckgo_lite", "yahoo"]


def test_public_search_keeps_searching_until_identifier_query_has_real_signal(monkeypatch):
    provider_calls: list[str] = []

    def weak_html(*args, **kwargs):
        provider_calls.append("duckduckgo_html")
        return [
            {
                "url": "https://colheli.com/",
                "title": "Columbia Helicopters - Home",
                "snippet": "Heavy-lift helicopter services and defense sustainment.",
                "score": 28,
                "blocked_host": False,
            }
        ]

    def empty_lite(*args, **kwargs):
        provider_calls.append("duckduckgo_lite")
        return []

    def strong_yahoo(*args, **kwargs):
        provider_calls.append("yahoo")
        return [
            {
                "url": "https://highergov.example/vendors/columbia-helicopters",
                "title": "Columbia Helicopters, Inc. - HigherGov",
                "snippet": "CAGE Code: 7W206 UEI: EBD3SM6LH8D3 DUNS Number: 009673609.",
                "score": 18,
                "blocked_host": False,
                "search_provider": "yahoo",
            }
        ]

    def should_not_run(*args, **kwargs):
        raise AssertionError("identifier search chain should stop once an identifier-bearing candidate is found")

    monkeypatch.setattr(public_search_ownership, "_search", weak_html)
    monkeypatch.setattr(public_search_ownership, "_search_lite", empty_lite)
    monkeypatch.setattr(public_search_ownership, "_search_yahoo", strong_yahoo)
    monkeypatch.setattr(public_search_ownership, "_search_brave", should_not_run)
    monkeypatch.setattr(public_search_ownership, "_search_bing", should_not_run)

    candidates = public_search_ownership._search_with_fallbacks(
        "Columbia Helicopters, Inc. CAGE Code",
        "Columbia Helicopters, Inc.",
        allow_blocked=True,
        country="US",
    )

    urls = [candidate["url"] for candidate in candidates]
    assert urls == [
        "https://colheli.com/",
        "https://highergov.example/vendors/columbia-helicopters",
    ]
    assert provider_calls == ["duckduckgo_html", "duckduckgo_lite", "yahoo"]


def test_public_search_uses_yahoo_snippet_fallback_for_hascall_owner(monkeypatch):
    yahoo_official_html = """
    <html>
      <body>
        <div class="dd algo algo-sr Sr">
          <div class="compTitle">
            <h3 class="title"><a href="https://hascall-denke.com/">Hascall-Denke</a></h3>
          </div>
          <div class="compText"><p>Official site for tactical fiber and cable assemblies.</p></div>
        </div>
      </body>
    </html>
    """
    yahoo_owner_html = """
    <html>
      <body>
        <div class="dd algo algo-sr Sr">
          <div class="compTitle">
            <h3 class="title"><a href="https://www.defensemedia.example/hascall-denke">Hascall-Denke Overview</a></h3>
          </div>
          <div class="compText">
            <p>Thanks to Hascall-Denke owner Mike Hascall&rsquo;s extensive years of experience working in the antenna industry, the company grew into a trusted defense supplier.</p>
          </div>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Mission-ready cable assemblies and fiber optic connectivity.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or (params or {}).get("p") or ""
        if url in {public_search_ownership.SEARCH_URL, public_search_ownership.SEARCH_LITE_URL}:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.YAHOO_SEARCH_URL:
            if query == '"Hascall-Denke"':
                return _SearchResponse(yahoo_official_html)
            if query == '"Hascall-Denke" founder president CEO owner':
                return _SearchResponse(yahoo_owner_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BING_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hascall-denke.com":
            return _HtmlResponse(root_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall-denke.com"
    assert any(rel["type"] == "owned_by" and rel["target_entity"] == "Mike Hascall" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Mike Hascall"
        and finding.access_model == "search_snippet_only"
        for finding in result.findings
    )


def test_public_search_uses_leadership_snippet_as_control_path(monkeypatch):
    yahoo_official_html = """
    <html>
      <body>
        <div class="dd algo algo-sr Sr">
          <div class="compTitle">
            <h3 class="title"><a href="https://hascall-denke.com/">Hascall-Denke</a></h3>
          </div>
          <div class="compText"><p>Official site for tactical fiber and cable assemblies.</p></div>
        </div>
      </body>
    </html>
    """
    yahoo_leadership_html = """
    <html>
      <body>
        <div class="dd algo algo-sr Sr">
          <div class="compTitle">
            <h3 class="title"><a href="https://craft.co/hascall-denke/executives">Hascall-Denke CEO and Key Executive Team - Craft.co</a></h3>
          </div>
          <div class="compText">
            <p>Hascall - Denke ' s President is Michael Hascall. Other executives include Joe Hughes, Chief Operating Officer.</p>
          </div>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Mission-ready cable assemblies and fiber optic connectivity.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or (params or {}).get("p") or ""
        if url in {public_search_ownership.SEARCH_URL, public_search_ownership.SEARCH_LITE_URL}:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.YAHOO_SEARCH_URL:
            if query == '"Hascall-Denke"':
                return _SearchResponse(yahoo_official_html)
            if query == '"Hascall-Denke" founder president CEO owner':
                return _SearchResponse(yahoo_leadership_html)
            return _SearchResponse("<html><body></body></html>")
        if url in {public_search_ownership.BING_SEARCH_URL, public_search_ownership.BRAVE_SEARCH_URL}:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://hascall-denke.com":
            return _HtmlResponse(root_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Hascall-Denke", country="US")

    assert result.identifiers["website"] == "https://hascall-denke.com"
    assert any(
        rel["type"] == "led_by"
        and rel["target_entity"] == "Michael Hascall"
        and rel["access_model"] == "search_snippet_only"
        for rel in result.relationships
    )
    assert any(
        finding.title == "Public search leadership-control hint: Michael Hascall"
        for finding in result.findings
    )


def test_public_search_uses_synthetic_domain_when_search_results_are_empty(monkeypatch):
    home_html = """
    <html>
      <head><title>FAUN Trackway USA Inc - Ground Stabilization Trackway Solutions</title></head>
      <body>
        <a href="/about-us">About Us</a>
        <p>FAUN Trackway USA Inc provides military expedient roadway solutions.</p>
      </body>
    </html>
    """
    about_html = """
    <html>
      <head><title>About Us - FAUN Trackway USA Inc</title></head>
      <body>
        <p>We are proud to be a division of the KIRCHHOFF Group.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url in {
            public_search_ownership.SEARCH_URL,
            public_search_ownership.SEARCH_LITE_URL,
            public_search_ownership.YAHOO_SEARCH_URL,
            public_search_ownership.BING_SEARCH_URL,
            public_search_ownership.BRAVE_SEARCH_URL,
        }:
            return _SearchResponse("<html><body></body></html>")
        if url in {"https://fauntrackway.com", "https://www.fauntrackway.com"}:
            return _HtmlResponse(home_html)
        if url in {"https://fauntrackway.com/about-us", "https://www.fauntrackway.com/about-us"}:
            return _HtmlResponse(about_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("FAUN Trackway", country="US")

    assert result.identifiers["website"] in {"https://fauntrackway.com", "https://www.fauntrackway.com"}
    assert any(
        rel["type"] == "owned_by" and "KIRCHHOFF" in rel["target_entity"].upper()
        for rel in result.relationships
    )


def test_public_search_extracts_financing_from_blocked_host_page_when_snippet_is_thin(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    finance_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ - Products, Competitors, Financials, Employees ...</a>
          <a class="result__snippet" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ raised a total of $18.45M. Who are the investors of Greensea IQ?</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    blocked_host_html = """
    <html>
      <body>
        <p>Greensea IQ raised a total of $18.45M.</p>
        <p>Who are the investors of Greensea IQ? Investors of Greensea IQ include FreshTracks Capital.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query == f"Greensea IQ{public_search_ownership.FINANCING_SEARCH_SUFFIX}":
                return _SearchResponse(finance_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.cbinsights.com/company/greensea-systems":
            return _HtmlResponse(blocked_host_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        and rel["access_model"] == "search_public_html"
        for rel in result.relationships
    )


def test_public_search_uses_single_page_extraction_for_same_host_candidates(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/about-us">About Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/about-us">Company overview</a>
        </div>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        raise AssertionError(f"unexpected fetch: {url}")

    enrich_calls: list[str] = []
    extract_calls: list[str] = []

    def fake_enrich(vendor_name: str, country: str = "", **ids):
        enrich_calls.append(str(ids.get("website") or ""))
        result = EnrichmentResult(source=public_html_ownership.SOURCE_NAME, vendor_name=vendor_name)
        result.identifiers = {"website": "https://greensea.example"}
        result.structured_fields["visited_pages"] = ["https://greensea.example"]
        return result

    def fake_extract_page(vendor_name: str, country: str = "", *, website: str, page_url: str, discover_links: bool = False):
        extract_calls.append(page_url)
        result = EnrichmentResult(source=public_html_ownership.SOURCE_NAME, vendor_name=vendor_name)
        result.identifiers = {"website": website}
        return result, []

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership, "enrich", fake_enrich)
    monkeypatch.setattr(public_html_ownership, "extract_page", fake_extract_page)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert result.identifiers["website"] == "https://greensea.example"
    assert enrich_calls == []
    assert extract_calls == ["https://greensea.example", "https://greensea.example/about-us"]


def test_public_search_skips_identifier_phase_when_budget_is_tight(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    finance_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ - Products, Competitors, Financials, Employees ...</a>
          <a class="result__snippet" href="https://www.cbinsights.com/company/greensea-systems">Greensea IQ raised a total of $18.45M. Who are the investors of Greensea IQ?</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    blocked_host_html = """
    <html>
      <body>
        <p>Greensea IQ raised a total of $18.45M.</p>
        <p>Who are the investors of Greensea IQ? Investors of Greensea IQ include FreshTracks Capital.</p>
      </body>
    </html>
    """

    original_within_budget = public_search_ownership._within_budget

    def fake_within_budget(deadline: float, *, reserve_seconds: float = 0.0) -> bool:
        if reserve_seconds >= public_search_ownership.IDENTIFIER_PHASE_MIN_REMAINING_SECONDS:
            return False
        return original_within_budget(deadline, reserve_seconds=reserve_seconds)

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if any(token in query for token in ("CAGE Code", "UEI Unique Entity ID", "DUNS Number", "NCAGE Code")):
            raise AssertionError(f"identifier query should have been skipped: {query}")
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query == f"Greensea IQ{public_search_ownership.FINANCING_SEARCH_SUFFIX}":
                return _SearchResponse(finance_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.cbinsights.com/company/greensea-systems":
            return _HtmlResponse(blocked_host_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership, "_within_budget", fake_within_budget)
    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital" for rel in result.relationships)


def test_public_search_uses_legacy_corporate_suffix_finance_query(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    finance_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.cbinsights.com/company/greensea-systems/financials">Greensea IQ Stock Price, Funding, Valuation, Revenue &amp; Financial Statements</a>
          <a class="result__snippet" href="https://www.cbinsights.com/company/greensea-systems/financials">Greensea IQ raised a total of $18.45M. Who are the investors of Greensea IQ?</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    blocked_host_html = """
    <html>
      <body>
        <p>Greensea IQ raised a total of $18.45M.</p>
        <p>Who are the investors of Greensea IQ? Investors of Greensea IQ include FreshTracks Capital.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query == f"Greensea Systems{public_search_ownership.FINANCING_SEARCH_SUFFIX}":
                return _SearchResponse(finance_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.cbinsights.com/company/greensea-systems/financials":
            return _HtmlResponse(blocked_host_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        for rel in result.relationships
    )


def test_public_search_uses_synthetic_finance_profile_when_search_is_thin(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    blocked_host_html = """
    <html>
      <head><title>Greensea IQ Stock Price, Funding, Valuation, Revenue &amp; Financial Statements</title></head>
      <body>
        <p>Greensea IQ raised a total of $18.45M.</p>
        <p>Investors of Greensea IQ include FreshTracks Capital.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.cbinsights.com/company/greensea-systems/financials":
            return _HtmlResponse(blocked_host_html)
        if url == "https://www.cbinsights.com/company/greensea-systems":
            return _HtmlResponse(blocked_host_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        and rel["artifact_ref"] == "https://www.cbinsights.com/company/greensea-systems/financials"
        for rel in result.relationships
    )


def test_public_search_uses_synthetic_portfolio_profile_when_finance_host_is_accessible(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    portfolio_html = """
    <html>
      <head><title>Greensea Systems - FreshTracks Capital</title></head>
      <body>
        <p>FreshTracks portfolio company profile.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.freshtrackscap.com/portfolio/greensea-systems/":
            return _HtmlResponse(portfolio_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        and rel["artifact_ref"] == "https://www.freshtrackscap.com/portfolio/greensea-systems/"
        for rel in result.relationships
    )


def test_public_search_short_circuits_finance_queries_after_synthetic_profile_hit(monkeypatch):
    official_search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    portfolio_html = """
    <html>
      <head><title>Greensea Systems - FreshTracks Capital</title></head>
      <body>
        <p>FreshTracks portfolio company profile.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        query = (params or {}).get("q") or ""
        if url == public_search_ownership.SEARCH_URL:
            if query == "Greensea IQ":
                return _SearchResponse(official_search_html)
            if query.endswith(public_search_ownership.FINANCING_SEARCH_SUFFIX):
                raise AssertionError("finance query should not run after synthetic profile hit")
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.BRAVE_SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://www.freshtrackscap.com/portfolio/greensea-systems/":
            return _HtmlResponse(portfolio_html)
        raise AssertionError(f"unexpected fetch: {url} / {query}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        and rel["artifact_ref"] == "https://www.freshtrackscap.com/portfolio/greensea-systems/"
        for rel in result.relationships
    )


def test_public_search_skips_repeated_dead_search_providers_and_uses_synthetic_fallback(monkeypatch):
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    portfolio_html = """
    <html>
      <head><title>Greensea Systems - FreshTracks Capital</title></head>
      <body>
        <p>FreshTracks portfolio company profile.</p>
      </body>
    </html>
    """
    provider_calls = {"duckduckgo_html": 0, "duckduckgo_lite": 0, "yahoo": 0, "bing": 0, "brave": 0}

    def dead_html(*args, **kwargs):
        provider_calls["duckduckgo_html"] += 1
        raise requests.Timeout("duckduckgo html timed out")

    def dead_lite(*args, **kwargs):
        provider_calls["duckduckgo_lite"] += 1
        raise requests.Timeout("duckduckgo lite timed out")

    def dead_bing(*args, **kwargs):
        provider_calls["bing"] += 1
        raise requests.Timeout("bing timed out")

    def dead_yahoo(*args, **kwargs):
        provider_calls["yahoo"] += 1
        raise requests.Timeout("yahoo timed out")

    def dead_brave(*args, **kwargs):
        provider_calls["brave"] += 1
        raise requests.HTTPError("429")

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url.startswith("https://greensea.example"):
            return _HtmlResponse(root_html)
        if url == "https://www.freshtrackscap.example/portfolio/greensea-systems/":
            return _HtmlResponse(portfolio_html)
        raise AssertionError(f"unexpected fetch: {url} / {(params or {}).get('q')}")

    monkeypatch.setattr(public_search_ownership, "_search", dead_html)
    monkeypatch.setattr(public_search_ownership, "_search_lite", dead_lite)
    monkeypatch.setattr(public_search_ownership, "_search_yahoo", dead_yahoo)
    monkeypatch.setattr(public_search_ownership, "_search_bing", dead_bing)
    monkeypatch.setattr(public_search_ownership, "_search_brave", dead_brave)
    monkeypatch.setattr(
        public_search_ownership,
        "_synthetic_official_candidates",
        lambda vendor_name, country="": [
            {
                "url": "https://greensea.example/",
                "title": "Greensea IQ",
                "snippet": "Official site",
                "score": 40,
            }
        ],
    )
    monkeypatch.setattr(
        public_search_ownership,
        "_synthetic_finance_profile_candidates",
        lambda vendor_name, aliases=None: [
            {
                "url": "https://www.freshtrackscap.example/portfolio/greensea-systems/",
                "title": "Greensea Systems - FreshTracks Capital",
                "snippet": "FreshTracks portfolio company profile.",
                "score": 36,
                "blocked_host": True,
                "search_provider": "synthetic_finance_profile",
            }
        ],
    )
    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(
        rel["type"] == "backed_by" and rel["target_entity"] == "FreshTracks Capital"
        for rel in result.relationships
    )
    assert provider_calls == {"duckduckgo_html": 1, "duckduckgo_lite": 1, "yahoo": 1, "bing": 1, "brave": 1}


def test_public_search_rejects_business_designation_as_owner(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://ysg.example/">Yorktown Systems Group</a>
          <a class="result__snippet" href="https://ysg.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://defense.example/story">Yorktown wins support contract</a>
          <a class="result__snippet" href="https://defense.example/story">Yorktown Systems Group is owned by a Service-Disabled Veteran and supports federal missions.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Federal mission support contractor.</p></body></html>"
    article_html = """
    <html>
      <body>
        <p>
          Yorktown Systems Group is owned by a Service-Disabled Veteran and supports federal missions.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://ysg.example":
            return _HtmlResponse(root_html)
        if url == "https://defense.example/story":
            return _HtmlResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Yorktown Systems Group", country="US")

    assert result.identifiers["website"] == "https://ysg.example"
    assert not any(rel["type"] == "owned_by" for rel in result.relationships)
    assert not any("Service-Disabled Veteran" in finding.title for finding in result.findings)


def test_public_search_infers_backer_from_investor_site_title_when_page_is_silent(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://greensea.example/">Greensea IQ</a>
          <a class="result__snippet" href="https://greensea.example/">Official site</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://dudleyfund.example/greenseaiq">Greensea IQ - Dudley Fund</a>
          <a class="result__snippet" href="https://dudleyfund.example/greenseaiq">Autonomy and robotics profile page.</a>
        </div>
      </body>
    </html>
    """
    root_html = "<html><body><p>Greensea IQ develops intelligent ocean solutions.</p></body></html>"
    investor_html = "<html><body><p>Autonomy and robotics profile page.</p></body></html>"

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://greensea.example":
            return _HtmlResponse(root_html)
        if url == "https://dudleyfund.example/greenseaiq":
            return _HtmlResponse(investor_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("Greensea IQ", country="US")

    assert any(rel["type"] == "backed_by" and rel["target_entity"] == "Dudley Fund" for rel in result.relationships)
    assert any(
        finding.title == "Public search financial backer hint: Dudley Fund"
        and finding.access_model == "search_public_html"
        for finding in result.findings
    )


def test_public_search_uses_acquisition_snippet_when_page_is_js_gated(monkeypatch):
    search_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="https://www.dtccodan.com/newsroom/news/codan-communications-completes-acquisition-of-domo-tactical-communications-company">Codan Communications completes acquisition of Domo Tactical Communications</a>
          <a class="result__snippet" href="https://www.dtccodan.com/newsroom/news/codan-communications-completes-acquisition-of-domo-tactical-communications-company">As previously announced on 16 February 2021, Codan Limited advised that it had reached agreement to acquire all of the shares in US-based company, Domo Tactical Communications.</a>
        </div>
      </body>
    </html>
    """
    js_gate_html = """
    <html>
      <body>
        <p>JavaScript is disabled. In order to continue, we need to verify that you're not a robot.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse(search_html)
        if url == "https://www.dtccodan.com/newsroom/news/codan-communications-completes-acquisition-of-domo-tactical-communications-company":
            return _HtmlResponse(js_gate_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("DOMO Tactical Communications US", country="US")

    assert result.identifiers["website"] == "https://dtccodan.com"
    assert any(rel["type"] == "owned_by" and "Codan" in rel["target_entity"] for rel in result.relationships)
    assert any(rel["access_model"] == "search_snippet_only" for rel in result.relationships)
    assert any(
        finding.title == "Public search ownership hint: Codan Communications"
        and finding.access_model == "search_snippet_only"
        for finding in result.findings
    )


def test_public_search_lite_fallback_parses_results(monkeypatch):
    lite_html = """
    <html>
      <body>
        <table>
          <tr>
            <td>1.&nbsp;</td>
            <td>
              <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.dtccodan.com%2Fnewsroom%2Fnews%2Fcodan-limited-acquires-domo-tactical-communications" class='result-link'>Codan to acquire Domo Tactical Communications</a>
            </td>
          </tr>
          <tr>
            <td>&nbsp;&nbsp;&nbsp;</td>
            <td class='result-snippet'>Codan Limited has entered into an agreement to acquire 100% of the shares in US-based company, Domo Tactical Communications.</td>
          </tr>
        </table>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse(lite_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)

    candidates = public_search_ownership._search_lite("DOMO Tactical Communications", "DOMO Tactical Communications US", country="US")

    assert candidates
    assert candidates[0]["url"] == "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications"
    assert candidates[0]["search_provider"] == "duckduckgo_lite"


def test_public_search_falls_back_to_lite_when_primary_search_is_empty(monkeypatch):
    lite_html = """
    <html>
      <body>
        <table>
          <tr>
            <td>1.&nbsp;</td>
            <td>
              <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.dtccodan.com%2Fnewsroom%2Fnews%2Fcodan-limited-acquires-domo-tactical-communications" class='result-link'>Codan to acquire Domo Tactical Communications</a>
            </td>
          </tr>
          <tr>
            <td>&nbsp;&nbsp;&nbsp;</td>
            <td class='result-snippet'>Codan Limited has entered into an agreement to acquire 100% of the shares in US-based company, Domo Tactical Communications.</td>
          </tr>
        </table>
      </body>
    </html>
    """
    js_gate_html = """
    <html>
      <body>
        <p>JavaScript is disabled. In order to continue, we need to verify that you're not a robot.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict, params: dict | None = None):
        assert headers["User-Agent"].startswith("Helios/")
        if url == public_search_ownership.SEARCH_URL:
            return _SearchResponse("<html><body></body></html>")
        if url == public_search_ownership.SEARCH_LITE_URL:
            return _SearchResponse(lite_html)
        if url == "https://www.dtccodan.com/newsroom/news/codan-limited-acquires-domo-tactical-communications":
            return _HtmlResponse(js_gate_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_search_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_search_ownership.enrich("DOMO Tactical Communications US", country="US")

    assert result.identifiers["website"] == "https://dtccodan.com"
    assert any(rel["type"] == "owned_by" and "Codan" in rel["target_entity"] for rel in result.relationships)
