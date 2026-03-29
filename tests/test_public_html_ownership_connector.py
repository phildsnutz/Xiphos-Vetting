from __future__ import annotations

from pathlib import Path

from backend.osint import public_html_ownership


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "public_html_ownership"


class _FakeResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=utf-8"):
        self.text = text
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


def test_public_html_requires_known_website():
    result = public_html_ownership.enrich("Acme Avionics", country="US")
    assert result.has_data is False
    assert result.findings == []
    assert result.relationships == []


def test_public_html_emits_owned_by_from_company_site(monkeypatch):
    home_html = (FIXTURE_DIR / "acme_home.html").read_text(encoding="utf-8")
    about_html = (FIXTURE_DIR / "acme_about.html").read_text(encoding="utf-8")

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://acme.example":
            return _FakeResponse(home_html)
        if url == "https://acme.example/about":
            return _FakeResponse(about_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Acme Avionics", country="US", website="acme.example")

    assert result.identifiers["website"] == "https://acme.example"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "owned_by"
    assert relationship["target_entity"] == "Horizon Mission Systems"
    assert relationship["source_identifiers"]["website"] == "https://acme.example"
    assert relationship["structured_fields"]["relationship_scope"] == "subsidiary_of_phrase"
    assert relationship["evidence_url"] == "https://acme.example/about"
    assert result.findings[0].title == "Public site ownership hint: Horizon Mission Systems"
    assert result.access_model == "public_html"


def test_public_html_extracts_cage_uei_duns_and_ncage_from_company_site(monkeypatch):
    identifier_html = """
    <html>
      <body>
        <p>Berry Aviation, Inc.</p>
        <p>CAGE Code: 0EA28</p>
        <p>UEI: V1HATBT1N7V5</p>
        <p>DUNS Number: 123456789</p>
        <p>NCAGE Code: A1B2C</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://berry.example":
            return _FakeResponse(identifier_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Berry Aviation, Inc.", country="US", website="https://berry.example")

    assert result.identifiers["cage"] == "0EA28"
    assert result.identifiers["uei"] == "V1HATBT1N7V5"
    assert result.identifiers["duns"] == "123456789"
    assert result.identifiers["ncage"] == "A1B2C"
    assert any(finding.title == "Public site identifier hint: CAGE 0EA28" for finding in result.findings)
    assert any(finding.title == "Public site identifier hint: UEI V1HATBT1N7V5" for finding in result.findings)
    assert any(finding.title == "Public site identifier hint: DUNS 123456789" for finding in result.findings)
    assert any(finding.title == "Public site identifier hint: NCAGE A1B2C" for finding in result.findings)


def test_public_html_rejects_identifier_label_garbage():
    hints = public_html_ownership._extract_identifier_hints(
        "UEI Registration NCAGE Codes CAGE Codes DUNS Number 123456789"
    )

    assert "uei" not in hints
    assert "cage" not in hints
    assert "ncage" not in hints
    assert hints["duns"]["value"] == "123456789"


def test_public_html_prefers_canonical_registration_uei_when_page_contains_conflict():
    hints = public_html_ownership._extract_identifier_hints(
        """
        Awardees Yorktown Systems Group UEI: WFV9A8R6SAN5 Overview Analysis Registration
        People - Schedules 1 Vehicles - IDVs - Contracts.
        Showing registration information for UEI L5LMQSN59YE5 CAGE 4VJW9 instead.
        Legal Name YORKTOWN SYSTEMS GROUP INC UEI L5LMQSN59YE5 CAGE Code 4VJW9.
        """
    )

    assert hints["uei"]["value"] == "L5LMQSN59YE5"
    assert hints["cage"]["value"] == "4VJW9"


def test_public_html_vendor_scoped_identifier_hints_prefer_vendor_aligned_duns():
    hints = public_html_ownership._extract_identifier_hints(
        """
        The Unconventional LLC CAGE Code 83RJ2 DUNS Number 081215850.
        Yorktown Systems Group, Inc. Legal Name YORKTOWN SYSTEMS GROUP INC
        CAGE Code 4VJW9 UEI L5LMQSN59YE5 DUNS Number 801478384.
        """,
        vendor_name="Yorktown Systems Group",
    )

    assert hints["duns"]["value"] == "801478384"
    assert hints["uei"]["value"] == "L5LMQSN59YE5"
    assert hints["cage"]["value"] == "4VJW9"


def test_public_html_ignores_management_team_phrase_as_ownership():
    matches = public_html_ownership._extract_candidates(
        (
            "Bryan Dyer, the President and Chief Executive Officer of Yorktown Systems Group, "
            "is the minority member of the Offset Systems Group JV executive management team."
        ),
        "Yorktown Systems Group",
        "https://www.offsetsystemsgroup.com/leadership",
    )

    assert matches == []


def test_public_html_extracts_founded_year_from_first_party_history_page(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/who-we-are">Who We Are</a>
      </body>
    </html>
    """
    who_we_are_html = """
    <html>
      <body>
        <p>
          In 2008, Yorktown Systems Group, Inc., was founded by a Service Disabled Veteran
          on a mission to provide customized solutions to federal and civil organizations.
        </p>
        <p>
          Yorktown began in 2008 with the goal of providing training and tools to Soldiers
          prior to deployment.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html)
        if url == "https://ysg.example/who-we-are":
            return _FakeResponse(who_we_are_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.identifiers["founded_year"] == "2008"
    assert any(finding.title == "Public site operating history hint: founded in 2008" for finding in result.findings)


def test_public_html_discovers_funding_article_and_emits_backed_by(monkeypatch):
    home_html = (FIXTURE_DIR / "hefring_home.html").read_text(encoding="utf-8")
    funding_html = (FIXTURE_DIR / "hefring_funding_round.html").read_text(encoding="utf-8")

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://hefring.example":
            return _FakeResponse(home_html)
        if url == "https://hefring.example/news/hefring-funding-round":
            return _FakeResponse(funding_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Hefring Marine", country="IS", website="https://hefring.example")

    finance_findings = [finding for finding in result.findings if finding.category == "finance"]
    assert len(finance_findings) == 1
    assert finance_findings[0].title == "Public site financial backer hint: Faber Ventures"

    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship["type"] == "backed_by"
    assert relationship["target_entity"] == "Faber Ventures"
    assert relationship["structured_fields"]["relationship_scope"] == "first_party_financing"
    assert relationship["evidence_url"] == "https://hefring.example/news/hefring-funding-round"


def test_public_html_ignores_generic_part_of_prose(monkeypatch):
    generic_html = """
    <html>
      <body>
        <p>
          Unmanned Surface Vehicles are no longer niche, they are rapidly becoming
          an essential part of modern maritime operations.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://generic.example":
            return _FakeResponse(generic_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Generic Marine", country="US", website="https://generic.example")

    assert result.relationships == []
    assert result.findings == []


def test_public_html_ignores_part_of_phrase_on_news_page(monkeypatch):
    news_html = """
    <html>
      <body>
        <p>
          The platform is becoming an essential part of Modern Maritime Operations
          as operators adapt to weather and fatigue.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://generic.example":
            return _FakeResponse('<html><body><a href="/news/test">news</a></body></html>')
        if url == "https://generic.example/news/test":
            return _FakeResponse(news_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Generic Marine", country="US", website="https://generic.example")

    assert result.relationships == []
    assert result.findings == []


def test_internal_candidate_links_prioritize_funding_pages():
    markup = """
    <html>
      <body>
        <a href="/news">News</a>
        <a href="/news/operational-update">Operational update</a>
        <a href="/news/funding-round-led-by-faber">Funding round led by Faber Ventures</a>
      </body>
    </html>
    """

    discovered = public_html_ownership._extract_internal_candidate_links(
        markup,
        "https://generic.example/news",
        "https://generic.example",
    )

    assert discovered[0] == "https://generic.example/news/funding-round-led-by-faber"


def test_candidate_urls_include_blog_and_newsroom():
    urls = public_html_ownership._candidate_urls("https://generic.example")

    assert "https://generic.example/blog" in urls
    assert "https://generic.example/newsroom" in urls
    assert "https://generic.example/the-company" in urls
    assert "https://generic.example/en/the-company" in urls


def test_internal_candidate_links_accept_company_page_labels():
    markup = """
    <html>
      <body>
        <a href="/en/the-company">The Company</a>
      </body>
    </html>
    """

    discovered = public_html_ownership._extract_internal_candidate_links(
        markup,
        "https://generic.example",
        "https://generic.example",
    )

    assert discovered == ["https://generic.example/en/the-company"]


def test_public_html_emits_backed_by_from_investment_led_by_phrase(monkeypatch):
    investment_html = """
    <html>
      <body>
        <p>
          Example Marine today announced an investment of €2.2 million led by Faber Ventures
          with participation by Innoport VC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(investment_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Example Marine", country="IS", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "backed_by"
    assert result.relationships[0]["target_entity"] == "Faber Ventures"


def test_public_html_ignores_benchmarks_backed_by_phrase_as_non_entity():
    matches = public_html_ownership._extract_candidates(
        (
            "OSG's performance is backed by Industry recognized benchmarks of CMMI, "
            "ISO 9001: 2015, ASQ Certified Quality Auditing, Army Certified Lean Six Sigma Blackbelts."
        ),
        "Yorktown Systems Group",
        "https://www.ysginc.com/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
    )

    assert matches == []


def test_public_html_emits_owned_by_from_main_shareholder_phrase(monkeypatch):
    shareholder_html = """
    <html>
      <body>
        <p>
          Example Defense is a state-owned company. Having as main shareholder the
          Hellenic Ministry of Finance, the company is supervised by the Ministry of National Defence.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(shareholder_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Example Defense", country="GR", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "Hellenic Ministry of Finance"


def test_public_html_emits_owned_by_from_owner_phrase(monkeypatch):
    owner_html = """
    <html>
      <body>
        <p>
          Thanks to Hascall-Denke owner Mike Hascall's extensive years of experience
          working in the antenna industry, the company expanded its manufacturing line.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(owner_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Hascall-Denke", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "Mike Hascall"


def test_clean_parent_name_trims_part_of_and_boasting_suffixes():
    assert public_html_ownership._clean_parent_name("FAUN GmbH, part of the Kirchhoff group") == "FAUN"
    assert public_html_ownership._clean_parent_name("KIRCHHOFF Group, boasting Europe-wide manufacturing expertise") == "KIRCHHOFF"
    assert public_html_ownership._clean_parent_name("Interlagos, boosting the company's valuation") == "Interlagos"


def test_public_html_truncates_division_phrase_before_next_sentence(monkeypatch):
    division_html = """
    <html>
      <body>
        <p>
          We are proud to be a division of the KIRCHHOFF Group. The FAUN Group boasts
          Europe-wide manufacturing expertise.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(division_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich(
        "FAUN Trackway / Command Holdings Group",
        country="US",
        website="https://example.example",
    )

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "KIRCHHOFF"


def test_public_html_emits_backed_by_from_investors_include_phrase(monkeypatch):
    investor_html = """
    <html>
      <body>
        <p>
          Investors of Greensea IQ include FreshTracks Capital.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(investor_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Greensea IQ", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "backed_by"
    assert result.relationships[0]["target_entity"] == "FreshTracks Capital"


def test_public_html_rejects_marketing_copy_as_backer(monkeypatch):
    marketing_html = """
    <html>
      <body>
        <p>
          Constraints 02 70 Years of Experience Building Solutions 03 Broad Product Line
          Backed by Expert Engineering Proven in the Field Let’s Solve Your Power Problems.
          Get a quote. Order equipment. Find a power solution.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(marketing_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich(
        "Dewey Electronics & INI Power Systems",
        country="US",
        website="https://example.example",
    )

    assert result.relationships == []
    assert result.findings == []
