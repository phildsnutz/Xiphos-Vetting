from __future__ import annotations

from pathlib import Path

from backend.osint import public_html_ownership


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "public_html_ownership"


class _FakeResponse:
    def __init__(
        self,
        text: str,
        content_type: str = "text/html; charset=utf-8",
        *,
        url: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.text = text
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.url = url or ""

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


def test_public_html_extracts_json_ld_parent_and_lei(monkeypatch):
    home_html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Acme Avionics",
            "legalName": "Acme Avionics LLC",
            "url": "https://acme.example",
            "leiCode": "5493001KJTIIGC8Y1R12",
            "parentOrganization": {
              "@type": "Organization",
              "name": "Horizon Mission Systems"
            }
          }
        </script>
      </head>
      <body>
        <p>Mission systems for defense operators.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        if url == "https://acme.example":
            return _FakeResponse(home_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership, "_fetch_dns_answers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(public_html_ownership, "_fetch_rdap_record", lambda *_args, **_kwargs: {})

    result = public_html_ownership.enrich("Acme Avionics", country="US", website="https://acme.example")

    assert result.identifiers["lei"] == "5493001KJTIIGC8Y1R12"
    assert result.identifiers["legal_name"] == "Acme Avionics LLC"
    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert ("owned_by", "Horizon Mission Systems") in rel_types


def test_public_html_extracts_domain_dependency_hints_from_fixture(monkeypatch):
    home_html = """
    <html>
      <body>
        <p>Secure operations platform.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        if url == "https://atlas.example":
            return _FakeResponse(home_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich(
        "Atlas Mission Grid",
        country="US",
        website="https://atlas.example",
        public_domain_osint_fixture={
            "rdap": {"registrarName": "MarkMonitor Inc."},
            "dns": {
                "MX": ["atlas-example.mail.protection.outlook.com."],
                "TXT": ['v=spf1 include:spf.protection.outlook.com include:sendgrid.net ~all'],
                "NS": ["nina.ns.cloudflare.com.", "jake.ns.cloudflare.com."],
            },
        },
    )

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert ("depends_on_service", "Microsoft 365") in rel_types
    assert ("depends_on_service", "SendGrid") in rel_types
    assert ("depends_on_network", "Cloudflare") in rel_types
    assert result.identifiers["domain_registrar"] == "MarkMonitor Inc."


def test_public_html_extracts_network_dependency_from_response_headers(monkeypatch):
    home_html = """
    <html>
      <body>
        <p>Secure operations platform.</p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        if url == "https://atlas.example":
            return _FakeResponse(
                home_html,
                headers={
                    "Server": "cloudflare",
                    "CF-RAY": "8f8d7b6c5a4f1234-LAX",
                },
            )
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership, "_fetch_dns_answers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(public_html_ownership, "_fetch_rdap_record", lambda *_args, **_kwargs: {})

    result = public_html_ownership.enrich("Atlas Mission Grid", country="US", website="https://atlas.example")

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert ("depends_on_network", "Cloudflare") in rel_types


def test_public_html_discovers_support_subdomain_and_extracts_intercom(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="https://support.atlas.example/help">Support Center</a>
      </body>
    </html>
    """
    support_html = """
    <html>
      <body>
        <script src="https://widget.intercom.io/widget/abc123"></script>
      </body>
    </html>
    """
    fetched_urls: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict):
        fetched_urls.append(url)
        assert timeout == public_html_ownership.TIMEOUT
        if url == "https://atlas.example":
            return _FakeResponse(home_html)
        if url == "https://support.atlas.example/help":
            return _FakeResponse(support_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership, "_fetch_dns_answers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(public_html_ownership, "_fetch_rdap_record", lambda *_args, **_kwargs: {})

    result = public_html_ownership.enrich("Atlas Mission Grid", country="US", website="https://atlas.example")

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert "https://support.atlas.example/help" in fetched_urls
    assert ("depends_on_service", "Intercom") in rel_types


def test_public_html_discovers_status_subdomain_and_extracts_cloudflare(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="https://status.atlas.example/health">System Status</a>
      </body>
    </html>
    """
    status_html = """
    <html>
      <body>
        <p>Operational status</p>
      </body>
    </html>
    """
    fetched_urls: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict):
        fetched_urls.append(url)
        assert timeout == public_html_ownership.TIMEOUT
        if url == "https://atlas.example":
            return _FakeResponse(home_html)
        if url == "https://status.atlas.example/health":
            return _FakeResponse(
                status_html,
                headers={
                    "Server": "cloudflare",
                    "CF-RAY": "8f8d7b6c5a4f1234-LAX",
                },
            )
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)
    monkeypatch.setattr(public_html_ownership, "_fetch_dns_answers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(public_html_ownership, "_fetch_rdap_record", lambda *_args, **_kwargs: {})

    result = public_html_ownership.enrich("Atlas Mission Grid", country="US", website="https://atlas.example")

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert "https://status.atlas.example/health" in fetched_urls
    assert ("depends_on_network", "Cloudflare") in rel_types


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


def test_public_html_prefers_first_party_pages_and_domain_over_mismatched_website():
    resolved = public_html_ownership._resolve_website(
        {
            "website": "https://www.city-data.com",
            "domain": "channelpartners.com",
            "first_party_pages": [
                "https://channelpartners.com/first-impressions-in-the-field-how-strong-retail-merchandising-assisted-sales-teams-build-trust-from-day-one",
                "https://channelpartners.com/teams-in-action-channel-partners-launches-the-bridge-podcast-focused-on-retail-execution-excellence",
            ],
        }
    )

    assert resolved == "https://channelpartners.com"


def test_public_html_rejects_generic_terms_document_as_owner():
    matches = public_html_ownership._extract_candidates(
        (
            'The FAQs are an integral part of the Specific Terms and Conditions of Sale and '
            'are incorporated therein by reference.'
        ),
        "Northern Channel Partners",
        "https://www.visit.brussels/en/visitors/about-us/general-terms-and-conditions-of-sale",
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


def test_public_html_extracts_descriptor_beneficial_owner_from_first_party_article(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/">OSG news</a>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <p>
          This will be the first prime contract win for OSG as an All-Small Mentor Protégé Program
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html)
        if url == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.relationships == []
    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )


def test_public_html_discovers_wordpress_rest_post_for_descriptor_owner(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/news">News</a>
      </body>
    </html>
    """
    post_json = """
    [
      {
        "link": "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
        "title": {"rendered": "The U.S. Army awards Offset Systems Group $829M IDIQ contract."},
        "excerpt": {"rendered": "Offset Systems Group, owned by a Service-Disabled Veteran."},
        "content": {"rendered": "<p>Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran.</p>"}
      }
    ]
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html)
        if "/wp-json/wp/v2/posts?search=" in url:
            return _FakeResponse(post_json, "application/json; charset=utf-8")
        if url == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        if url in {"https://ysg.example/feed", "https://ysg.example/news/feed"}:
            return _FakeResponse("<?xml version='1.0'?><rss><channel></channel></rss>", "application/rss+xml")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.relationships == []
    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )
    assert "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract" in result.structured_fields["visited_pages"]


def test_public_html_wordpress_descriptor_queries_find_owner_class_when_vendor_query_misses(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/news">News</a>
      </body>
    </html>
    """
    unrelated_posts = """
    [
      {
        "link": "https://ysg.example/yorktown-systems-group-announces-2025-employees-of-the-year/",
        "title": {"rendered": "Yorktown Systems Group Announces 2025 Employees of the Year"},
        "excerpt": {"rendered": "<p>Company update.</p>"},
        "content": {"rendered": "<p>Company update.</p>"}
      }
    ]
    """
    descriptor_post = """
    [
      {
        "link": "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
        "title": {"rendered": "The U.S. Army awards Offset Systems Group $829M IDIQ contract."},
        "excerpt": {"rendered": "Offset Systems Group, owned by a Service-Disabled Veteran."},
        "content": {"rendered": "<p>Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran.</p>"}
      }
    ]
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html)
        if "/wp-json/wp/v2/posts?search=Yorktown%20Systems%20Group" in url:
            return _FakeResponse(unrelated_posts, "application/json; charset=utf-8")
        if "/wp-json/wp/v2/posts?search=Service-Disabled+Veteran" in url:
            return _FakeResponse(descriptor_post, "application/json; charset=utf-8")
        if "/wp-json/wp/v2/posts?search=" in url:
            return _FakeResponse("[]", "application/json; charset=utf-8")
        if url == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        if url in {"https://ysg.example/feed", "https://ysg.example/news/feed"}:
            return _FakeResponse("<?xml version='1.0'?><rss><channel></channel></rss>", "application/rss+xml")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.relationships == []
    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )


def test_public_html_promotes_successful_www_host_to_canonical_website(monkeypatch):
    article_url = "https://www.ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract"
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == article_url:
            return _FakeResponse(article_html)
        raise ConnectionError(f"unreachable host: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich(
        "Yorktown Systems Group",
        country="US",
        website="https://ysg.example",
        first_party_pages=[article_url],
    )

    assert result.identifiers["website"] == "https://www.ysg.example"
    assert article_url in result.identifiers["first_party_pages"]
    assert article_url in result.structured_fields["successful_pages"]
    assert article_url in result.structured_fields["visited_pages"]


def test_public_html_uses_resolved_www_host_for_canonical_website(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/">OSG news</a>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """
    home_url = "https://www.ysg.example"
    article_url = "https://www.ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract"

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html, url=home_url)
        if url == article_url:
            return _FakeResponse(article_html, url=article_url)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.identifiers["website"] == home_url
    assert home_url in result.structured_fields["successful_pages"]
    assert article_url in result.structured_fields["successful_pages"]
    assert article_url in result.identifiers["first_party_pages"]


def test_public_html_uses_seeded_first_party_page_before_default_paths(monkeypatch):
    home_html = """
    <html>
      <body>
        <p>Yorktown Systems Group home page.</p>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """
    fetch_order: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        fetch_order.append(url)
        if url == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        if url.startswith("https://ysg.example"):
            return _FakeResponse(home_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich(
        "Yorktown Systems Group",
        country="US",
        website="https://ysg.example",
        first_party_pages=["https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/"],
    )

    assert fetch_order[0] == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract"
    assert result.identifiers["first_party_pages"] == [
        "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract"
    ]
    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )


def test_public_html_falls_through_to_www_variant_when_bare_domain_tls_fails(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/news">News</a>
      </body>
    </html>
    """
    descriptor_post = """
    [
      {
        "link": "https://www.ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/",
        "title": {"rendered": "The U.S. Army awards Offset Systems Group $829M IDIQ contract."},
        "excerpt": {"rendered": "Offset Systems Group, owned by a Service-Disabled Veteran."},
        "content": {"rendered": "<p>Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran.</p>"}
      }
    ]
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url.startswith("https://ysg.example"):
            raise public_html_ownership.requests.exceptions.SSLError("tls handshake failure")
        if url in {"https://www.ysg.example", "https://www.ysg.example/news"}:
            return _FakeResponse(home_html)
        if "/wp-json/wp/v2/posts?search=Service-Disabled+Veteran" in url:
            return _FakeResponse(descriptor_post, "application/json; charset=utf-8")
        if "/wp-json/wp/v2/posts?search=" in url:
            return _FakeResponse("[]", "application/json; charset=utf-8")
        if url == "https://www.ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        if url in {"https://www.ysg.example/feed", "https://www.ysg.example/news/feed"}:
            return _FakeResponse("<?xml version='1.0'?><rss><channel></channel></rss>", "application/rss+xml")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )
    assert "https://www.ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract" in result.structured_fields["visited_pages"]


def test_public_html_discovers_sitemap_post_for_descriptor_owner_when_rest_is_empty(monkeypatch):
    home_html = """
    <html>
      <body>
        <a href="/news">News</a>
      </body>
    </html>
    """
    sitemap_index = """
    <sitemapindex>
      <sitemap><loc>https://ysg.example/post-sitemap.xml</loc></sitemap>
    </sitemapindex>
    """
    post_sitemap = """
    <urlset>
      <url><loc>https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract/</loc></url>
    </urlset>
    """
    article_html = """
    <html>
      <body>
        <p>
          Joint Venture formed by Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran,
          and Offset Strategic Services, LLC.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://ysg.example":
            return _FakeResponse(home_html)
        if "/wp-json/wp/v2/posts?search=" in url:
            return _FakeResponse("[]", "application/json; charset=utf-8")
        if url in {"https://ysg.example/feed", "https://ysg.example/news/feed"}:
            return _FakeResponse("<?xml version='1.0'?><rss><channel></channel></rss>", "application/rss+xml")
        if url == "https://ysg.example/sitemap_index.xml":
            return _FakeResponse(sitemap_index, "text/xml; charset=utf-8")
        if url == "https://ysg.example/post-sitemap.xml":
            return _FakeResponse(post_sitemap, "text/xml; charset=utf-8")
        if url == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract":
            return _FakeResponse(article_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Yorktown Systems Group", country="US", website="https://ysg.example")

    assert result.relationships == []
    assert any(
        finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
        for finding in result.findings
    )
    finding = next(
        finding
        for finding in result.findings
        if finding.title == "Public site beneficial ownership descriptor: Service-Disabled Veteran"
    )
    assert finding.structured_fields["ownership_descriptor"] == "Service-Disabled Veteran"
    assert finding.structured_fields["ownership_descriptor_scope"] == "self_disclosed_owner_descriptor"
    assert finding.artifact_ref == "https://ysg.example/the-u-s-army-awards-offset-systems-group-829m-idiq-contract"


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


def test_public_html_emits_routes_payment_through_from_bank_partner_phrase(monkeypatch):
    bank_html = """
    <html>
      <body>
        <p>
          Example Defense's banking partner is First National Bank and treasury settlement
          for customer invoices is routed through the same institution.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(bank_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Example Defense", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "routes_payment_through"
    assert result.relationships[0]["target_entity"] == "First National Bank"
    assert result.relationships[0]["target_entity_type"] == "bank"
    assert result.findings[0].category == "intermediary"


def test_public_html_emits_routes_payment_through_from_payment_processor_phrase(monkeypatch):
    processor_html = """
    <html>
      <body>
        <p>
          Example Defense's merchant of record is Adyen and the payment processor is
          Adyen for international card settlement.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(processor_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Example Defense", country="US", website="https://example.example")

    rel_types = {(rel["type"], rel["target_entity"]) for rel in result.relationships}
    assert ("routes_payment_through", "Adyen") in rel_types


def test_public_html_emits_depends_on_service_from_managed_service_phrase(monkeypatch):
    service_html = """
    <html>
      <body>
        <p>
          Vector Mission relies on a managed services provider, Harbor Patch Signing Service,
          for release signing and hosted operational support.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(service_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Vector Mission", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "depends_on_service"
    assert result.relationships[0]["target_entity"] == "Harbor Patch Signing Service"
    assert result.relationships[0]["target_entity_type"] == "service"


def test_public_html_emits_depends_on_network_from_network_provider_phrase(monkeypatch):
    network_html = """
    <html>
      <body>
        <p>
          Connectivity for deployed sensors is maintained through telecom provider Orbital Mesh Telecom
          with redundancy across regional carrier links.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(network_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Orbital Sensors", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "depends_on_network"
    assert result.relationships[0]["target_entity"] == "Orbital Mesh Telecom"
    assert result.relationships[0]["target_entity_type"] == "telecom_provider"


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


def test_public_html_ignores_geographic_part_of_phrase(monkeypatch):
    bio_html = """
    <html>
      <body>
        <p>
          I grew up in a very poor part of Ohio and learned early how to work hard.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://generic.example":
            return _FakeResponse(bio_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Generic Marine", country="US", website="https://generic.example")

    assert result.relationships == []
    assert result.findings == []


def test_public_html_keeps_corporate_part_of_phrase(monkeypatch):
    corporate_html = """
    <html>
      <body>
        <p>
          FAUN Trackway is part of the KIRCHHOFF Group and serves expeditionary mobility programs.
        </p>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int, headers: dict):
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://example.example":
            return _FakeResponse(corporate_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("FAUN Trackway", country="US", website="https://example.example")

    assert len(result.relationships) == 1
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "KIRCHHOFF"


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


def test_public_html_stops_optional_fetches_after_strong_first_party_signal(monkeypatch):
    home_html = """
    <html>
      <body>
        <p>CAGE Code: 0EA28</p>
      </body>
    </html>
    """
    about_html = """
    <html>
      <body>
        <p>Acme Avionics is a subsidiary of Horizon Mission Systems.</p>
      </body>
    </html>
    """
    visited: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict):
        visited.append(url)
        assert timeout == public_html_ownership.TIMEOUT
        assert headers["User-Agent"].startswith("Helios/")
        if url == "https://acme.example":
            return _FakeResponse(home_html)
        if url == "https://acme.example/about":
            return _FakeResponse(about_html)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(public_html_ownership.requests, "get", fake_get)

    result = public_html_ownership.enrich("Acme Avionics", country="US", website="https://acme.example")

    assert visited == ["https://acme.example", "https://acme.example/about"]
    assert result.identifiers["cage"] == "0EA28"
    assert result.relationships[0]["target_entity"] == "Horizon Mission Systems"
    assert result.structured_fields["visited_pages"] == visited


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


def test_public_html_uses_file_fixture_pages_without_network(tmp_path, monkeypatch):
    fixture_path = tmp_path / "faun_fixture.html"
    fixture_path.write_text(
        """
        <html>
          <body>
            <p>FAUN Trackway is part of the KIRCHHOFF Group and serves expeditionary mobility programs.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("network fetch should not run in fixture-only mode")

    monkeypatch.setattr(public_html_ownership.requests, "get", fail_get)

    result = public_html_ownership.enrich(
        "FAUN Trackway",
        country="US",
        website="https://fauntrackway.com",
        public_html_fixture_page=fixture_path.as_uri(),
        public_html_fixture_only=True,
    )

    assert result.identifiers["website"] == "https://fauntrackway.com"
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "KIRCHHOFF"
    assert result.structured_fields["fixture_pages"] == [fixture_path.as_uri()]
    assert result.structured_fields["visited_pages"] == [fixture_path.as_uri()]


def test_public_html_resolves_repo_relative_fixture_pages_without_network(monkeypatch):
    fixture_path = Path("fixtures/public_html_ownership/faun_trackway_control.html")

    def fail_get(*args, **kwargs):
        raise AssertionError("network fetch should not run in fixture-only mode")

    monkeypatch.setattr(public_html_ownership.requests, "get", fail_get)

    result = public_html_ownership.enrich(
        "FAUN Trackway",
        country="US",
        website="https://fauntrackway.com",
        public_html_fixture_page=str(fixture_path),
        public_html_fixture_only=True,
    )

    resolved_fixture = (public_html_ownership.REPO_ROOT / fixture_path).resolve().as_uri()
    assert result.identifiers["website"] == "https://fauntrackway.com"
    assert result.relationships[0]["type"] == "owned_by"
    assert result.relationships[0]["target_entity"] == "KIRCHHOFF"
    assert result.structured_fields["fixture_pages"] == [resolved_fixture]
    assert result.structured_fields["visited_pages"] == [resolved_fixture]


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


def test_public_html_page_visit_key_collapses_www_variants_and_prioritizes_identity_pages():
    urls = public_html_ownership._candidate_urls("https://vectorsolutions.us")

    assert public_html_ownership._page_visit_key("https://vectorsolutions.us/news") == public_html_ownership._page_visit_key(
        "https://www.vectorsolutions.us/news"
    )
    assert urls.index("https://vectorsolutions.us/about") < urls.index("https://vectorsolutions.us/news")
    assert "https://vectorsolutions.us/news" in urls
