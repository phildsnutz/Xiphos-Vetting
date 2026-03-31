"""
Public HTML Ownership Connector

Cheap ownership/control hints from a company's public website.
This connector is deliberately narrow:
  - only uses analyst-provided or previously discovered website/domain hints
  - fetches a small set of first-party pages
  - extracts ownership phrases with deterministic pattern matching

It avoids search automation, anti-bot workarounds, or broad crawling.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote, urljoin, urlparse
import urllib.error
import urllib.request

import requests

from . import EnrichmentResult, Finding


SOURCE_NAME = "public_html_ownership"
REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 12
MAX_PAGES = 16
MAX_DISCOVERED_LINKS = 3
MAX_DISCOVERY_SURFACE_LINKS = 6
EARLY_STOP_RELATION_CONFIDENCE = 0.74
DEFAULT_PATHS = (
    "",
    "/about",
    "/about-us",
    "/who-we-are",
    "/company",
    "/the-company",
    "/en/the-company",
    "/leadership",
    "/ysgleadership",
    "/history",
    "/news",
    "/newsroom",
    "/blog",
)
DISCOVERY_HUB_PATHS = ("/news", "/newsroom", "/blog", "/press", "/articles", "/updates")
USER_AGENT = "Helios/5.2 (+https://xiphosllc.com)"
FIXTURE_PAGE_KEYS = ("public_html_fixture_page", "public_html_fixture_pages")
DOMAIN_OSINT_FIXTURE_KEYS = ("public_domain_osint_fixture", "public_domain_osint_fixture_path")
JSON_LD_SCRIPT = re.compile(
    r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
GOOGLE_DNS_ENDPOINT = "https://dns.google/resolve"
RDAP_ENDPOINT = "https://rdap.org/domain/{domain}"

SIGNAL_PATTERNS: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (
        re.compile(r"\b(?:is|was)\s+(?:a\s+)?subsidiary of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.78,
        "subsidiary_of_phrase",
    ),
    (
        re.compile(r"\bowned by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.76,
        "owned_by_phrase",
    ),
    (
        re.compile(r"\bpart of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,90})(?:\s+group|\s+family|\s+portfolio)?", re.IGNORECASE),
        "owned_by",
        0.70,
        "part_of_phrase",
    ),
    (
        re.compile(
            r"\bmember of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,90}\s+(?:group|family|portfolio|holdings|network|alliance))",
            re.IGNORECASE,
        ),
        "owned_by",
        0.68,
        "member_of_phrase",
    ),
    (
        re.compile(r"\bacquired by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.64,
        "acquired_by_phrase",
    ),
    (
        re.compile(r"\bdivision of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.72,
        "division_of_phrase",
    ),
    (
        re.compile(
            r"\b(?:main|majority|principal)\s+shareholder\s+(?:is\s+|the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
            re.IGNORECASE,
        ),
        "owned_by",
        0.74,
        "main_shareholder_phrase",
    ),
    (
        re.compile(r"\bowner\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.62,
        "owner_phrase",
    ),
    (
        re.compile(r"\b(?:funding round|investment round)[^.]{0,120}?led by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.64,
        "funding_round_led_by_phrase",
    ),
    (
        re.compile(
            r"\b(?:investment|financing|funding|seed(?:\s+round)?|series\s+[a-z]+|raised)\b.{0,180}?led by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "backed_by",
        0.66,
        "investment_led_by_phrase",
    ),
    (
        re.compile(r"\bbacked by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.62,
        "backed_by_phrase",
    ),
    (
        re.compile(r"\bportfolio company of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.60,
        "portfolio_company_phrase",
    ),
    (
        re.compile(
            r"\binvestors?\s+of\s+[A-Z][A-Za-z0-9&.,'()/ -]{2,90}\s+(?:include|are)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)(?:\s*[?.!]|$)",
            re.IGNORECASE,
        ),
        "backed_by",
        0.58,
        "investors_include_phrase",
    ),
    (
        re.compile(r"\binvestment from\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.60,
        "investment_from_phrase",
    ),
    (
        re.compile(
            r"\b(?:payments?|receivables?|payables?)\s+(?:are|is)\s+(?:processed|settled|routed)\s+(?:through|via)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "routes_payment_through",
        0.60,
        "first_party_payment_intermediary",
    ),
    (
        re.compile(
            r"\b(?:banking|treasury|settlement)\s+(?:partner|provider|bank)\s+(?:is\s+|:?\s*)([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "routes_payment_through",
        0.58,
        "first_party_payment_intermediary",
    ),
    (
        re.compile(
            r"\b(?:payment processor|merchant of record|settlement bank|acquiring bank|account bank|cash management bank)\s+(?:is\s+|:?\s*)([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "routes_payment_through",
        0.60,
        "first_party_payment_intermediary",
    ),
    (
        re.compile(
            r"\b(?:wire transfers?|payments?|receipts?)\s+(?:should be|are|were)?\s*(?:sent|routed|settled|processed)?\s*(?:through|via|to|with)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "routes_payment_through",
        0.57,
        "first_party_payment_intermediary",
    ),
    (
        re.compile(
            r"\b(?:managed services?|cloud hosting|hosting|patch signing|identity platform|monitoring platform)\s+(?:partner|provider|service)\s+(?:is\s+|:?\s*)([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "depends_on_service",
        0.56,
        "first_party_service_dependency",
    ),
    (
        re.compile(
            r"\b(?:relies on|depends on)\s+(?:a\s+)?(?:managed services?|cloud hosting|hosting|patch signing|identity platform|monitoring platform)\s+(?:partner|provider|service)?[,:\s]+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "depends_on_service",
        0.56,
        "first_party_service_dependency",
    ),
    (
        re.compile(
            r"\b(?:telecom|network|connectivity|carrier)\s+(?:partner|provider|carrier)\s+(?:is\s+|:?\s*|\s+)([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "depends_on_network",
        0.56,
        "first_party_network_dependency",
    ),
)

DESCRIPTOR_OWNERSHIP_PATTERNS: tuple[tuple[re.Pattern[str], float, str, str], ...] = (
    (
        re.compile(
            r"\bowned by\s+(?:a\s+|an\s+)?(Service[- ]Disabled Veteran)\b",
            re.IGNORECASE,
        ),
        0.78,
        "Service-Disabled Veteran",
        "self_disclosed_owner_descriptor",
    ),
    (
        re.compile(
            r"\bowned by\s+(?:a\s+|an\s+)?(Veteran)\b",
            re.IGNORECASE,
        ),
        0.68,
        "Veteran",
        "self_disclosed_owner_descriptor",
    ),
)

TRAILING_GENERIC = re.compile(
    r"\s+(?:group|family|portfolio|company|companies|corporation|corp\.?|inc\.?|llc|ltd\.?|plc|gmbh)\s*$",
    re.IGNORECASE,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAGS = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
ANCHOR_TAG = re.compile(r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>", re.IGNORECASE | re.DOTALL)
RSS_ITEM_RE = re.compile(
    r"<item\b[^>]*>.*?<title>(?P<title>.*?)</title>.*?<link>(?P<link>https?://[^<]+)</link>.*?</item>",
    re.IGNORECASE | re.DOTALL,
)
SITEMAP_LOC_RE = re.compile(r"<loc>(?P<link>https?://[^<]+)</loc>", re.IGNORECASE)
DISCOVERY_KEYWORDS = (
    "fund",
    "invest",
    "back",
    "acquir",
    "bank",
    "payment",
    "settlement",
    "telecom",
    "network",
    "carrier",
    "hosting",
    "cloud",
    "managed service",
    "news",
    "press",
    "growth",
    "history",
    "leadership",
    "about",
    "company",
    "corporate",
    "support",
    "help",
    "status",
    "trust",
    "security",
    "billing",
    "checkout",
    "portal",
)
RAW_CTA_NOISE_PHRASES = (
    "let's ",
    "let’s ",
    "get a quote",
    "order equipment",
    "find a power solution",
    "power problems",
)
ENTITY_NOISE_PHRASES = (
    "proven in the field",
    "years of experience",
    "building solutions",
    "broad product line",
    "industry recognized benchmarks",
    "iso 9001",
    "cmmi",
    "lean six sigma",
    "quality auditing",
)
PART_OF_CONTEXT_NOISE_PHRASES = (
    "essential part of",
    "integral part of",
    "important part of",
    "critical part of",
    "key part of",
    "core part of",
)
MARKET_TEXT_NOISE_PHRASES = (
    "prices of the securities",
    "conventional funds",
    "lose money investing",
    "etf go down",
)
DESCRIPTOR_OWNER_PHRASES = (
    "service disabled veteran",
    "service-disabled veteran",
    "veteran owned",
    "veteran-owned",
    "small business",
    "woman owned",
    "woman-owned",
    "minority owned",
    "minority-owned",
    "hubzone",
    "sdb",
    "sdvosb",
    "vosb",
    "wosb",
    "edwosb",
    "8(a)",
)
GENERIC_NON_ENTITY_EXACT = {
    "specific terms",
    "general terms",
    "terms and conditions",
    "general terms and conditions",
    "frequently asked questions",
    "faq",
    "faqs",
    "privacy policy",
    "cookie policy",
    "cookie preferences",
}
GENERIC_NON_ENTITY_SUFFIXES = (
    " terms",
    " conditions",
    " policy",
    " policies",
    " questions",
)
GEOGRAPHIC_NON_ENTITY_EXACT = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
    "district of columbia",
    "united states",
    "united kingdom",
    "north america",
    "south america",
    "europe",
    "asia",
    "africa",
    "oceania",
    "middle east",
}
PART_OF_CORPORATE_SIGNAL_TOKENS = (
    "group",
    "family",
    "portfolio",
    "holdings",
    "network",
    "alliance",
    "company",
    "companies",
    "corporation",
    "corp",
    "inc",
    "llc",
    "ltd",
    "plc",
    "gmbh",
)
ENTITY_CONNECTOR_WORDS = {
    "and",
    "of",
    "the",
    "for",
    "de",
    "del",
    "della",
    "di",
    "da",
    "du",
    "van",
    "von",
    "der",
    "den",
    "la",
    "le",
    "el",
    "al",
    "bin",
    "ibn",
    "y",
}
CONTROL_BODY_NOISE_PHRASES = (
    "executive management team",
    "management team",
    "leadership team",
    "board of directors",
    "advisory board",
    "executive committee",
    "steering committee",
)
DISCOVERY_SURFACE_KEYWORDS = (
    "owner",
    "owned",
    "ownership",
    "parent",
    "subsidiary",
    "shareholder",
    "investor",
    "bank",
    "payment",
    "settlement",
    "telecom",
    "network",
    "carrier",
    "hosting",
    "cloud",
    "managed service",
    "support",
    "help",
    "status",
    "trust",
    "security",
    "billing",
    "checkout",
    "portal",
    "veteran",
    "sdvosb",
    "wosb",
)
DISCOVERY_QUERY_STOPWORDS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "plc",
    "gmbh",
}
OWNERSHIP_DISCOVERY_QUERIES = (
    "Service-Disabled Veteran",
    "sdvosb",
    "veteran-owned",
    "ownership",
    "owner",
    "parent company",
    "banking partner",
    "payment provider",
    "payment processor",
    "merchant of record",
    "settlement bank",
    "acquiring bank",
    "cash management bank",
    "network provider",
    "managed services",
    "support",
    "help center",
    "status",
    "trust center",
    "security",
    "billing",
    "checkout",
)
INTERMEDIARY_DISCOVERY_KEYWORDS = (
    "support",
    "help",
    "status",
    "trust",
    "security",
    "billing",
    "checkout",
    "portal",
)
DISCOVERY_PROVIDER_HOST_SUFFIXES = (
    "statuspage.io",
    "zendesk.com",
    "freshdesk.com",
    "freshservice.com",
    "intercom.help",
    "helpscoutdocs.com",
    "helpscout.net",
    "atlassian.net",
)

_RELATIONSHIP_META: dict[str, dict[str, str]] = {
    "owned_by": {
        "target_entity_type": "holding_company",
        "finding_category": "ownership",
        "finding_title_prefix": "Public site ownership hint: ",
        "relationship_scope_default": "first_party_control",
        "evidence_title": "Public company website ownership statement",
    },
    "backed_by": {
        "target_entity_type": "holding_company",
        "finding_category": "finance",
        "finding_title_prefix": "Public site financial backer hint: ",
        "relationship_scope_default": "first_party_financing",
        "evidence_title": "Public company website financing statement",
    },
    "routes_payment_through": {
        "target_entity_type": "bank",
        "finding_category": "intermediary",
        "finding_title_prefix": "Public site payment intermediary hint: ",
        "relationship_scope_default": "first_party_payment_intermediary",
        "evidence_title": "Public company website payment intermediary statement",
    },
    "depends_on_service": {
        "target_entity_type": "service",
        "finding_category": "intermediary",
        "finding_title_prefix": "Public site service dependency hint: ",
        "relationship_scope_default": "first_party_service_dependency",
        "evidence_title": "Public company website service dependency statement",
    },
    "depends_on_network": {
        "target_entity_type": "telecom_provider",
        "finding_category": "intermediary",
        "finding_title_prefix": "Public site network dependency hint: ",
        "relationship_scope_default": "first_party_network_dependency",
        "evidence_title": "Public company website network dependency statement",
    },
    "parent_of": {
        "target_entity_type": "company",
        "finding_category": "ownership",
        "finding_title_prefix": "Public site subsidiary hint: ",
        "relationship_scope_default": "json_ld_sub_organization",
        "evidence_title": "Public company website subsidiary statement",
    },
}
TECH_SIGNATURES: tuple[tuple[re.Pattern[str], str, str, float, str], ...] = (
    (
        re.compile(r"https?://js\.stripe\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Stripe",
        0.82,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://(?:www\.)?paypal\.com/sdk/js|https?://www\.paypalobjects\.com/", re.IGNORECASE),
        "routes_payment_through",
        "PayPal",
        0.82,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://js\.braintreegateway\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Braintree",
        0.80,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://(?:checkoutshopper|live|test)\.adyen\.com/|https?://.*?adyen\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Adyen",
        0.80,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://.*?checkout\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Checkout.com",
        0.78,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://.*?authorize\.net/", re.IGNORECASE),
        "routes_payment_through",
        "Authorize.net",
        0.76,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://.*?cybersource\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Cybersource",
        0.76,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://.*?worldpay\.com/", re.IGNORECASE),
        "routes_payment_through",
        "Worldpay",
        0.76,
        "payment_sdk_signature",
    ),
    (
        re.compile(r"https?://(?:cdn|assets)\.shopify\.com|https?://checkout\.shopify\.com", re.IGNORECASE),
        "depends_on_service",
        "Shopify",
        0.72,
        "commerce_platform_signature",
    ),
    (
        re.compile(r"cdn-cgi|cloudflareinsights\.com|cdnjs\.cloudflare\.com", re.IGNORECASE),
        "depends_on_network",
        "Cloudflare",
        0.74,
        "network_edge_signature",
    ),
    (
        re.compile(r"https?://[^\"'\\s>]*okta\.com/", re.IGNORECASE),
        "depends_on_service",
        "Okta",
        0.72,
        "identity_platform_signature",
    ),
    (
        re.compile(r"https?://static\.zdassets\.com|https?://[^\"'\\s>]*zendesk\.com/", re.IGNORECASE),
        "depends_on_service",
        "Zendesk",
        0.70,
        "support_platform_signature",
    ),
    (
        re.compile(r"https?://[^\"'\\s>]*statuspage\.io/", re.IGNORECASE),
        "depends_on_service",
        "Atlassian Statuspage",
        0.68,
        "status_platform_signature",
    ),
    (
        re.compile(r"https?://(?:widget|js)\.intercom(?:cdn)?\.io/|https?://[^\"'\\s>]*intercom\.help/", re.IGNORECASE),
        "depends_on_service",
        "Intercom",
        0.70,
        "support_platform_signature",
    ),
    (
        re.compile(r"https?://[^\"'\\s>]*freshdesk\.com/|https?://[^\"'\\s>]*freshservice\.com/", re.IGNORECASE),
        "depends_on_service",
        "Freshworks",
        0.68,
        "support_platform_signature",
    ),
    (
        re.compile(r"https?://[^\"'\\s>]*helpscoutdocs\.com/|https?://secure\.helpscout\.net/", re.IGNORECASE),
        "depends_on_service",
        "Help Scout",
        0.68,
        "support_platform_signature",
    ),
)
MX_PROVIDER_HINTS: tuple[tuple[re.Pattern[str], str, str, float, str], ...] = (
    (
        re.compile(r"(?:^|\.)google\.com\.?$|aspmx\.l\.google\.com\.?", re.IGNORECASE),
        "depends_on_service",
        "Google Workspace",
        0.66,
        "mx_provider_signature",
    ),
    (
        re.compile(r"protection\.outlook\.com\.?$", re.IGNORECASE),
        "depends_on_service",
        "Microsoft 365",
        0.66,
        "mx_provider_signature",
    ),
    (
        re.compile(r"mimecast\.com\.?$", re.IGNORECASE),
        "depends_on_service",
        "Mimecast",
        0.64,
        "mx_provider_signature",
    ),
    (
        re.compile(r"ppe-hosted\.com\.?$|proofpoint\.com\.?$", re.IGNORECASE),
        "depends_on_service",
        "Proofpoint",
        0.64,
        "mx_provider_signature",
    ),
)
TXT_PROVIDER_HINTS: tuple[tuple[re.Pattern[str], str, str, float, str], ...] = (
    (
        re.compile(r"include:_spf\.google\.com", re.IGNORECASE),
        "depends_on_service",
        "Google Workspace",
        0.64,
        "spf_provider_signature",
    ),
    (
        re.compile(r"include:spf\.protection\.outlook\.com", re.IGNORECASE),
        "depends_on_service",
        "Microsoft 365",
        0.64,
        "spf_provider_signature",
    ),
    (
        re.compile(r"include:mailgun\.org", re.IGNORECASE),
        "depends_on_service",
        "Mailgun",
        0.62,
        "spf_provider_signature",
    ),
    (
        re.compile(r"include:sendgrid\.net", re.IGNORECASE),
        "depends_on_service",
        "SendGrid",
        0.62,
        "spf_provider_signature",
    ),
    (
        re.compile(r"include:amazonses\.com", re.IGNORECASE),
        "depends_on_service",
        "Amazon SES",
        0.60,
        "spf_provider_signature",
    ),
)
NS_PROVIDER_HINTS: tuple[tuple[re.Pattern[str], str, str, float, str], ...] = (
    (
        re.compile(r"cloudflare\.com\.?$", re.IGNORECASE),
        "depends_on_network",
        "Cloudflare",
        0.70,
        "nameserver_signature",
    ),
    (
        re.compile(r"awsdns-[^.]+\.com\.?$|awsdns-[^.]+\.net\.?$|awsdns-[^.]+\.org\.?$|awsdns-[^.]+\.co\.uk\.?$", re.IGNORECASE),
        "depends_on_network",
        "Amazon Route 53",
        0.66,
        "nameserver_signature",
    ),
    (
        re.compile(r"akam\.net\.?$|akamaiedge\.net\.?$", re.IGNORECASE),
        "depends_on_network",
        "Akamai",
        0.64,
        "nameserver_signature",
    ),
)
HEADER_PROVIDER_HINTS: tuple[tuple[str | None, re.Pattern[str], str, str, float, str], ...] = (
    (
        "server",
        re.compile(r"cloudflare", re.IGNORECASE),
        "depends_on_network",
        "Cloudflare",
        0.78,
        "response_header_signature",
    ),
    (
        "cf-ray",
        re.compile(r".+", re.IGNORECASE),
        "depends_on_network",
        "Cloudflare",
        0.80,
        "response_header_signature",
    ),
    (
        "x-amz-cf-id",
        re.compile(r".+", re.IGNORECASE),
        "depends_on_network",
        "Amazon CloudFront",
        0.78,
        "response_header_signature",
    ),
    (
        "via",
        re.compile(r"cloudfront", re.IGNORECASE),
        "depends_on_network",
        "Amazon CloudFront",
        0.76,
        "response_header_signature",
    ),
    (
        "x-served-by",
        re.compile(r"fastly", re.IGNORECASE),
        "depends_on_network",
        "Fastly",
        0.74,
        "response_header_signature",
    ),
    (
        "server",
        re.compile(r"akamaighost|akamai", re.IGNORECASE),
        "depends_on_network",
        "Akamai",
        0.74,
        "response_header_signature",
    ),
)
IDENTIFIER_PATTERNS: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
    (
        "cage",
        "CAGE",
        re.compile(
            r"\b(?:CAGE(?:\s+Code)?|Commercial and Government Entity(?:\s+Code)?)\s*[:#]?\s*([A-Z0-9]{5})\b",
            re.IGNORECASE,
        ),
        0.72,
    ),
    (
        "uei",
        "UEI",
        re.compile(
            r"\b(?:UEI|Unique Entity ID(?:entifier)?)\s*(?:Number|Code|#)?\s*[:#]?\s*([A-Z0-9]{12})\b",
            re.IGNORECASE,
        ),
        0.70,
    ),
    (
        "duns",
        "DUNS",
        re.compile(
            r"\b(?:D[- ]?U[- ]?N[- ]?S(?:\s+Number)?|DUNS(?:\s+Number)?)\s*[:#]?\s*([0-9]{9})\b",
            re.IGNORECASE,
        ),
        0.68,
    ),
    (
        "ncage",
        "NCAGE",
        re.compile(
            r"\b(?:N[- ]?CAGE(?:\s+Code)?|NCAGE(?:\s+Code)?)\s*[:#]?\s*([A-Z0-9]{5})\b",
            re.IGNORECASE,
        ),
        0.66,
    ),
)
INVALID_IDENTIFIER_VALUES: dict[str, set[str]] = {
    "cage": {"CAGE", "CODES", "CODE", "ENTITY"},
    "uei": {"REGISTRATION", "IDENTIFIER", "ENTITY", "NUMBER", "UNIQUE"},
    "ncage": {"NCAGE", "CODES", "CODE", "ENTITY"},
}
IDENTIFIER_CONTEXT_BONUSES: tuple[tuple[str, float], ...] = (
    ("legal name", 0.18),
    ("active registration", 0.14),
    ("registration information", 0.14),
    ("registered in the system for award management", 0.12),
    ("registered with sam", 0.12),
    ("showing registration information", 0.12),
    ("headquartered", 0.04),
)
IDENTIFIER_CONTEXT_PENALTIES: tuple[tuple[str, float], ...] = (
    ("copy url email tweet", 0.16),
    ("search awardees", 0.14),
    ("people - schedules", 0.10),
    ("vehicles - idvs - contracts", 0.10),
    ("overview analysis registration people", 0.08),
)
IDENTIFIER_VENDOR_TOKEN_STOPWORDS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "plc",
    "gmbh",
    "sa",
    "systems",
    "group",
    "solutions",
    "services",
    "technologies",
    "technology",
    "defense",
    "holdings",
    "holding",
}
FOUNDED_YEAR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:in\s+)?((?:19|20)\d{2})\b[^.]{0,80}\b(?:was\s+founded|founded|began|established|started|launched)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:founded|began|established|started|launched)\b[^.]{0,80}\b((?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),
)


def _normalize_website(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value.lstrip('/')}"
    parsed = urlparse(value)
    if parsed.scheme == "file":
        if not parsed.path:
            return ""
        return Path(unquote(parsed.path)).resolve().as_uri()
    if not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    normalized = f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"
    return normalized.rstrip("/")


def _root_website(raw: str) -> str:
    normalized = _normalize_website(raw)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme == "file":
        return normalized
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")


def _first_party_host_key(value: str) -> str:
    parsed = urlparse(_normalize_website(value))
    if parsed.scheme == "file":
        return f"file://{Path(unquote(parsed.path or '')).resolve().parent.as_posix()}"
    host = parsed.netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _same_first_party_host(left: str, right: str) -> bool:
    left_key = _first_party_host_key(left)
    right_key = _first_party_host_key(right)
    return bool(left_key and right_key and left_key == right_key)


def _website_variants(website: str) -> list[str]:
    base = _normalize_website(website)
    if not base:
        return []
    variants = [base]
    parsed = urlparse(base)
    host = parsed.netloc.lower()
    if host and not host.startswith("www.") and host.count(".") >= 1:
        with_www = f"{parsed.scheme or 'https'}://www.{host}{parsed.path.rstrip('/')}"
        if with_www not in variants:
            variants.append(with_www)
    return variants


def _page_visit_key(raw: str) -> str:
    normalized = _normalize_website(raw)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme == "file":
        return normalized
    path = parsed.path.rstrip("/") or "/"
    return f"{_first_party_host_key(normalized)}{path}"


def _canonical_first_party_website(seed_website: str, evidence_urls: list[str] | tuple[str, ...] | set[str]) -> str:
    normalized_seed = _normalize_website(seed_website)
    seed_root = _root_website(normalized_seed)
    if not normalized_seed:
        return ""

    root_stats: dict[str, dict[str, int]] = {}
    for candidate in evidence_urls or []:
        normalized = _normalize_website(str(candidate or ""))
        if not normalized or not _same_first_party_host(normalized, normalized_seed):
            continue
        root = _root_website(normalized)
        if not root:
            continue
        stats = root_stats.setdefault(root, {"hits": 0, "root_hits": 0})
        stats["hits"] += 1
        if normalized == root:
            stats["root_hits"] += 1

    if not root_stats:
        return seed_root or normalized_seed

    def _rank(root: str) -> tuple[int, int, int]:
        stats = root_stats[root]
        return (
            stats["hits"],
            stats["root_hits"],
            1 if root == seed_root else 0,
        )

    best_root = max(root_stats, key=_rank)
    if seed_root and seed_root in root_stats and _rank(seed_root) >= _rank(best_root):
        return seed_root
    return best_root


def _candidate_urls(website: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    variants = _website_variants(website)
    if not variants:
        return urls
    primary_base = variants[0]
    alternate_bases = variants[1:]

    for path in DEFAULT_PATHS:
        candidate = urljoin(f"{primary_base}/", path.lstrip("/"))
        candidate = candidate.rstrip("/") if path else candidate.rstrip("/")
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
        if len(urls) >= MAX_PAGES:
            return urls

    alternate_priority_paths = ("", "/about", "/company", "/leadership", "/news")
    for base in alternate_bases:
        for path in alternate_priority_paths:
            candidate = urljoin(f"{base}/", path.lstrip("/"))
            candidate = candidate.rstrip("/") if path else candidate.rstrip("/")
            if candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)
            if len(urls) >= MAX_PAGES:
                return urls
    return urls


def _resolve_first_party_pages(ids: dict, website: str) -> list[str]:
    raw_pages = ids.get("first_party_pages")
    if isinstance(raw_pages, str):
        candidates = [raw_pages]
    elif isinstance(raw_pages, (list, tuple, set)):
        candidates = [str(item or "") for item in raw_pages]
    else:
        candidates = []

    normalized_website = _normalize_website(website)
    seen: set[str] = set()
    pages: list[str] = []
    for candidate in candidates:
        normalized = _normalize_website(candidate)
        if not normalized:
            continue
        if not _same_first_party_host(normalized, normalized_website):
            continue
        page_key = _page_visit_key(normalized)
        if normalized == normalized_website or not page_key or page_key in seen:
            continue
        seen.add(page_key)
        pages.append(normalized)
    return pages[:MAX_PAGES]


def _resolve_fixture_pages(ids: dict) -> list[str]:
    raw_values: list[str] = []
    for key in FIXTURE_PAGE_KEYS:
        raw = ids.get(key)
        if isinstance(raw, str):
            raw_values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            raw_values.extend(str(item or "") for item in raw)

    pages: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        if "://" not in candidate:
            resolved = (REPO_ROOT / candidate).resolve()
            if not resolved.exists():
                continue
            candidate = resolved.as_uri()
        normalized = _normalize_website(candidate)
        if not normalized or normalized in seen:
            continue
        if urlparse(normalized).scheme != "file":
            continue
        seen.add(normalized)
        pages.append(normalized)
    return pages[:MAX_PAGES]


def _is_truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _has_identity_anchor(
    identifiers: dict[str, str],
    findings: list[Finding],
) -> bool:
    for key in ("cage", "uei", "duns", "ncage", "founded_year"):
        if identifiers.get(key):
            return True
    return any(finding.category in {"identity", "profile"} for finding in findings)


def _should_stop_optional_fetches(
    relationships: list[dict],
    identifiers: dict[str, str],
    findings: list[Finding],
) -> bool:
    if not _has_identity_anchor(identifiers, findings):
        return False
    return any(
        relationship.get("type") in {
            "owned_by",
            "backed_by",
            "routes_payment_through",
            "depends_on_service",
            "depends_on_network",
        }
        and float(relationship.get("confidence") or 0.0) >= EARLY_STOP_RELATION_CONFIDENCE
        for relationship in relationships
    )


def _extract_text(markup: str) -> str:
    if not markup:
        return ""
    cleaned = HTML_COMMENT.sub(" ", markup)
    cleaned = SCRIPT_STYLE.sub(" ", cleaned)
    cleaned = TAGS.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned)
    return cleaned.strip()


def _normalize_entity_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()


def _entity_match_score(left: str, right: str) -> float:
    normalized_left = _normalize_entity_name(left)
    normalized_right = _normalize_entity_name(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.94
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens))
    return overlap


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _website_host(value: str) -> str:
    parsed = urlparse(_normalize_website(value))
    return str(parsed.netloc or "").lower()


def _json_ld_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            nodes.extend(_json_ld_nodes(item))
        return nodes
    if not isinstance(payload, dict):
        return nodes
    graph_nodes = payload.get("@graph")
    if isinstance(graph_nodes, list):
        for item in graph_nodes:
            nodes.extend(_json_ld_nodes(item))
    nodes.append(payload)
    return nodes


def _extract_json_ld_blocks(markup: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in JSON_LD_SCRIPT.finditer(markup or ""):
        body = html.unescape(match.group("body") or "").strip()
        if not body:
            continue
        body = re.sub(r"^\s*<!--", "", body)
        body = re.sub(r"-->\s*$", "", body)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        blocks.extend(_json_ld_nodes(payload))
    return blocks


def _identifier_value_from_json_ld(value: Any) -> tuple[str, str] | None:
    if isinstance(value, str):
        normalized = value.strip()
        if re.fullmatch(r"[0-9A-Z]{18,20}", normalized):
            return "lei", normalized
        return None
    if not isinstance(value, dict):
        return None
    property_id = str(value.get("propertyID") or value.get("propertyId") or value.get("name") or "").strip().lower()
    identifier_value = str(value.get("value") or value.get("@value") or "").strip()
    if not identifier_value:
        return None
    if property_id in {"lei", "lei code", "leicode"}:
        return "lei", identifier_value.upper()
    if property_id in {"uei", "uei code"}:
        return "uei", identifier_value.upper()
    if property_id in {"cage", "cage code"}:
        return "cage", identifier_value.upper()
    return None


def _json_ld_matches_vendor(node: dict[str, Any], vendor_name: str, website: str) -> bool:
    node_type_values = {str(item).lower() for item in _as_list(node.get("@type"))}
    if node_type_values and not {"organization", "corporation", "localbusiness", "thing"} & node_type_values:
        return False
    website_host = _website_host(website)
    for candidate in [node.get("url"), *(_as_list(node.get("sameAs")))]:
        host = _website_host(str(candidate or ""))
        if host and website_host and host == website_host:
            return True
    for name_candidate in (node.get("name"), node.get("legalName")):
        if _entity_match_score(str(name_candidate or ""), vendor_name) >= 0.72:
            return True
    return False


def _json_ld_target_name(value: Any) -> str:
    if isinstance(value, str):
        return _clean_parent_name(value)
    if isinstance(value, dict):
        return _clean_parent_name(str(value.get("name") or value.get("legalName") or value.get("@id") or ""))
    return ""


def _extract_json_ld_hints(
    markup: str,
    *,
    vendor_name: str,
    country: str,
    website: str,
    page_url: str,
) -> dict[str, Any]:
    identifiers: dict[str, str] = {}
    relationships: list[dict[str, Any]] = []
    findings: list[Finding] = []
    matched_nodes = [node for node in _extract_json_ld_blocks(markup) if _json_ld_matches_vendor(node, vendor_name, website)]
    if not matched_nodes:
        return {"identifiers": identifiers, "relationships": relationships, "findings": findings}

    seen_relationships: set[tuple[str, str]] = set()
    for node in matched_nodes:
        legal_name = str(node.get("legalName") or "").strip()
        if legal_name and _entity_match_score(legal_name, vendor_name) >= 0.72:
            identifiers.setdefault("legal_name", legal_name)
        lei_code = str(node.get("leiCode") or node.get("lei") or "").strip().upper()
        if lei_code:
            identifiers.setdefault("lei", lei_code)
        for identifier in _as_list(node.get("identifier")):
            parsed_identifier = _identifier_value_from_json_ld(identifier)
            if parsed_identifier:
                identifiers.setdefault(parsed_identifier[0], parsed_identifier[1])

        parent_targets = _as_list(node.get("parentOrganization"))
        for parent in parent_targets:
            target_name = _json_ld_target_name(parent)
            if not target_name or _looks_like_vendor(target_name, vendor_name):
                continue
            dedupe_key = ("owned_by", target_name.upper())
            if dedupe_key in seen_relationships:
                continue
            seen_relationships.add(dedupe_key)
            snippet = f"JSON-LD parentOrganization: {target_name}"
            relationships.append(
                _build_relationship(
                    vendor_name=vendor_name,
                    country=country,
                    website=website,
                    rel_type="owned_by",
                    parent_name=target_name,
                    page_url=page_url,
                    confidence=0.84,
                    scope="json_ld_parent_organization",
                    snippet=snippet,
                )
            )
            findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="ownership",
                    title=f"Public site ownership hint: {target_name}",
                    detail=f"{snippet} | Source page: {page_url}",
                    severity="info",
                    confidence=0.84,
                    url=page_url,
                    artifact_ref=page_url,
                    structured_fields={
                        "relationship_type": "owned_by",
                        "relationship_scope": "json_ld_parent_organization",
                        "target_entity": target_name,
                        "website": website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )

        for child in _as_list(node.get("subOrganization")):
            target_name = _json_ld_target_name(child)
            if not target_name or _looks_like_vendor(target_name, vendor_name):
                continue
            dedupe_key = ("parent_of", target_name.upper())
            if dedupe_key in seen_relationships:
                continue
            seen_relationships.add(dedupe_key)
            snippet = f"JSON-LD subOrganization: {target_name}"
            relationships.append(
                _build_relationship(
                    vendor_name=vendor_name,
                    country=country,
                    website=website,
                    rel_type="parent_of",
                    parent_name=target_name,
                    page_url=page_url,
                    confidence=0.76,
                    scope="json_ld_sub_organization",
                    snippet=snippet,
                )
            )
            findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="ownership",
                    title=f"Public site subsidiary hint: {target_name}",
                    detail=f"{snippet} | Source page: {page_url}",
                    severity="info",
                    confidence=0.76,
                    url=page_url,
                    artifact_ref=page_url,
                    structured_fields={
                        "relationship_type": "parent_of",
                        "relationship_scope": "json_ld_sub_organization",
                        "target_entity": target_name,
                        "website": website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )

        accepted_payment_method = [str(item).strip() for item in _as_list(node.get("acceptedPaymentMethod")) if str(item or "").strip()]
        if accepted_payment_method:
            findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="profile",
                    title="Public site payment method disclosure via JSON-LD",
                    detail=f"{', '.join(accepted_payment_method[:6])} | Source page: {page_url}",
                    severity="info",
                    confidence=0.62,
                    url=page_url,
                    artifact_ref=page_url,
                    structured_fields={
                        "accepted_payment_method": accepted_payment_method[:12],
                        "website": website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )

    return {"identifiers": identifiers, "relationships": relationships, "findings": findings}


def _extract_technology_signature_hints(
    markup: str,
    *,
    vendor_name: str,
    country: str,
    website: str,
    page_url: str,
) -> dict[str, Any]:
    relationships: list[dict[str, Any]] = []
    findings: list[Finding] = []
    lowered_markup = str(markup or "")
    seen_relationships: set[tuple[str, str]] = set()
    for pattern, rel_type, target_name, confidence, scope in TECH_SIGNATURES:
        match = pattern.search(lowered_markup)
        if not match:
            continue
        dedupe_key = (rel_type, target_name.upper())
        if dedupe_key in seen_relationships:
            continue
        seen_relationships.add(dedupe_key)
        snippet = match.group(0)
        relationships.append(
            _build_relationship(
                vendor_name=vendor_name,
                country=country,
                website=website,
                rel_type=rel_type,
                parent_name=target_name,
                page_url=page_url,
                confidence=confidence,
                scope=scope,
                snippet=snippet,
            )
        )
        relationship_meta = _RELATIONSHIP_META.get(rel_type, _RELATIONSHIP_META["depends_on_service"])
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category=relationship_meta["finding_category"],
                title=f"{relationship_meta['finding_title_prefix']}{target_name}",
                detail=f"{snippet} | Source page: {page_url}",
                severity="info",
                confidence=confidence,
                url=page_url,
                artifact_ref=page_url,
                structured_fields={
                    "relationship_type": rel_type,
                    "relationship_scope": scope,
                    "target_entity": target_name,
                    "website": website,
                },
                source_class="public_connector",
                authority_level="first_party_self_disclosed",
                access_model="public_html",
            )
        )
    return {"relationships": relationships, "findings": findings}


def _load_domain_osint_fixture(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    path = Path(str(value or "")).expanduser()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fetch_dns_answers(domain: str, record_type: str) -> list[str]:
    url = _dns_evidence_url(domain, record_type)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/dns-json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=min(TIMEOUT, 8)) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []
    answers = payload.get("Answer") if isinstance(payload, dict) else None
    if not isinstance(answers, list):
        return []
    extracted: list[str] = []
    for answer in answers:
        data = str((answer or {}).get("data") or "").strip().strip('"')
        if data:
            extracted.append(data)
    return extracted


def _fetch_rdap_record(domain: str) -> dict[str, Any] | None:
    url = RDAP_ENDPOINT.format(domain=domain)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rdap+json, application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=min(TIMEOUT, 8)) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _rdap_registrar_name(payload: dict[str, Any]) -> str:
    registrar = str(payload.get("registrarName") or "").strip()
    if registrar:
        return registrar
    for entity in _as_list(payload.get("entities")):
        if not isinstance(entity, dict):
            continue
        roles = {str(item).lower() for item in _as_list(entity.get("roles"))}
        if "registrar" not in roles:
            continue
        vcard_array = entity.get("vcardArray")
        if isinstance(vcard_array, list) and len(vcard_array) == 2 and isinstance(vcard_array[1], list):
            for item in vcard_array[1]:
                if isinstance(item, list) and len(item) >= 4 and str(item[0]).lower() == "fn":
                    return str(item[3] or "").strip()
    return ""


def _dns_evidence_url(domain: str, record_type: str) -> str:
    return f"{GOOGLE_DNS_ENDPOINT}?name={quote_plus(domain)}&type={record_type}"


def _extract_domain_dependency_hints(
    vendor_name: str,
    *,
    country: str,
    website: str,
    ids: dict[str, Any],
) -> dict[str, Any]:
    domain = _website_host(website)
    if not domain:
        return {"identifiers": {}, "relationships": [], "findings": []}

    fixture_payload: dict[str, Any] = {}
    for key in DOMAIN_OSINT_FIXTURE_KEYS:
        if key in ids:
            fixture_payload = _load_domain_osint_fixture(ids.get(key))
            if fixture_payload:
                break

    dns_payload = fixture_payload.get("dns") if isinstance(fixture_payload.get("dns"), dict) else {}
    rdap_payload = fixture_payload.get("rdap") if isinstance(fixture_payload.get("rdap"), dict) else {}
    mx_records = [str(item).strip() for item in _as_list(dns_payload.get("MX")) if str(item or "").strip()] or _fetch_dns_answers(domain, "MX")
    txt_records = [str(item).strip() for item in _as_list(dns_payload.get("TXT")) if str(item or "").strip()] or _fetch_dns_answers(domain, "TXT")
    ns_records = [str(item).strip() for item in _as_list(dns_payload.get("NS")) if str(item or "").strip()] or _fetch_dns_answers(domain, "NS")
    rdap_record = rdap_payload or _fetch_rdap_record(domain) or {}

    identifiers: dict[str, str] = {}
    findings: list[Finding] = []
    relationships: list[dict[str, Any]] = []
    seen_relationships: set[tuple[str, str]] = set()

    registrar_name = _rdap_registrar_name(rdap_record) if isinstance(rdap_record, dict) else ""
    if registrar_name:
        identifiers["domain_registrar"] = registrar_name
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="identity",
                title=f"Domain registration hint: {registrar_name}",
                detail=f"RDAP registrar for {domain}: {registrar_name}",
                severity="info",
                confidence=0.58,
                url=RDAP_ENDPOINT.format(domain=domain),
                artifact_ref=RDAP_ENDPOINT.format(domain=domain),
                structured_fields={
                    "website": website,
                    "domain": domain,
                    "registrar": registrar_name,
                },
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        )

    def add_relationship(rel_type: str, target_name: str, confidence: float, scope: str, snippet: str, evidence_url: str) -> None:
        dedupe_key = (rel_type, target_name.upper())
        if dedupe_key in seen_relationships:
            return
        seen_relationships.add(dedupe_key)
        relationship = _build_relationship(
            vendor_name=vendor_name,
            country=country,
            website=website,
            rel_type=rel_type,
            parent_name=target_name,
            page_url=evidence_url,
            confidence=confidence,
            scope=scope,
            snippet=snippet,
        )
        relationship["authority_level"] = "third_party_public"
        relationship["access_model"] = "public_api"
        relationship["structured_fields"]["domain"] = domain
        relationships.append(relationship)
        relationship_meta = _RELATIONSHIP_META.get(rel_type, _RELATIONSHIP_META["depends_on_service"])
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category=relationship_meta["finding_category"],
                title=f"{relationship_meta['finding_title_prefix']}{target_name}",
                detail=f"{snippet} | Domain: {domain}",
                severity="info",
                confidence=confidence,
                url=evidence_url,
                artifact_ref=evidence_url,
                structured_fields={
                    "relationship_type": rel_type,
                    "relationship_scope": scope,
                    "target_entity": target_name,
                    "website": website,
                    "domain": domain,
                },
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        )

    for record in mx_records:
        for pattern, rel_type, target_name, confidence, scope in MX_PROVIDER_HINTS:
            if pattern.search(record):
                add_relationship(rel_type, target_name, confidence, scope, f"MX record: {record}", _dns_evidence_url(domain, "MX"))

    joined_txt = "\n".join(txt_records)
    for pattern, rel_type, target_name, confidence, scope in TXT_PROVIDER_HINTS:
        match = pattern.search(joined_txt)
        if match:
            add_relationship(rel_type, target_name, confidence, scope, f"TXT record: {match.group(0)}", _dns_evidence_url(domain, "TXT"))

    for record in ns_records:
        for pattern, rel_type, target_name, confidence, scope in NS_PROVIDER_HINTS:
            if pattern.search(record):
                add_relationship(rel_type, target_name, confidence, scope, f"NS record: {record}", _dns_evidence_url(domain, "NS"))

    return {"identifiers": identifiers, "relationships": relationships, "findings": findings}


def _clean_parent_name(raw_name: str) -> str:
    text = (raw_name or "").strip(" ,.;:-")
    text = re.split(r"\.\s+(?:the|our|its|their|in|at|as|with|for)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.;:-")
    text = re.split(r"['’]s\b", text, maxsplit=1)[0].strip(" ,.;:-")
    text = re.split(r"[|•·]", text, maxsplit=1)[0].strip()
    text = re.split(r",\s+(?:part of|boasting)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.split(
        r",\s+(?:boosting|bringing|driving|giving|making|positioning|raising|lifting)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    text = re.split(r",\s+(?:for|to|from|via|through)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.split(r",\s+(?:the|which|with|that)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.split(r"\s+(?:and|which|with|that)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = TRAILING_GENERIC.sub("", text).strip(" ,.;:-")
    return text


def _looks_like_vendor(parent_name: str, vendor_name: str) -> bool:
    norm_parent = re.sub(r"[^A-Z0-9]+", " ", parent_name.upper()).strip()
    norm_vendor = re.sub(r"[^A-Z0-9]+", " ", vendor_name.upper()).strip()
    return bool(norm_parent and norm_vendor and (norm_parent == norm_vendor or norm_parent in norm_vendor or norm_vendor in norm_parent))


def _looks_like_entity_name(raw_name: str, parent_name: str) -> bool:
    raw = str(raw_name or "").strip()
    cleaned = str(parent_name or "").strip()
    if len(cleaned) < 3:
        return False
    lowered = cleaned.lower()
    raw_lowered = raw.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    if any(
        token in lowered
        for token in (
            "vice president",
            "engineer other",
            "leave this field empty",
            "free subscription",
            "email",
            "select title",
        )
    ):
        return False
    if any(fragment in raw_lowered for fragment in RAW_CTA_NOISE_PHRASES):
        return False
    if any(fragment in lowered for fragment in ENTITY_NOISE_PHRASES):
        return False
    if any(fragment in lowered or fragment in raw_lowered for fragment in MARKET_TEXT_NOISE_PHRASES):
        return False
    if any(phrase in lowered or phrase in normalized for phrase in DESCRIPTOR_OWNER_PHRASES):
        return False
    if normalized in GENERIC_NON_ENTITY_EXACT:
        return False
    if any(normalized.endswith(suffix) for suffix in GENERIC_NON_ENTITY_SUFFIXES):
        return False
    if re.search(r"\b(?:go down|lose money)\b", lowered):
        return False
    if len(cleaned.split()) > 8:
        return False
    alpha_tokens = re.findall(r"[A-Za-z][A-Za-z'’-]*", cleaned)
    lowercase_noise_tokens = [
        token
        for token in alpha_tokens
        if token.lower() not in ENTITY_CONNECTOR_WORDS
        and token != token.upper()
        and not token[:1].isupper()
    ]
    if lowercase_noise_tokens:
        return False
    candidate_for_case = cleaned if cleaned and raw[:1].lower() == raw[:1] else raw
    first_alpha = re.search(r"[A-Za-z]", candidate_for_case)
    if not first_alpha or candidate_for_case[first_alpha.start()] != candidate_for_case[first_alpha.start()].upper():
        return False
    if re.search(r"\b\d{1,2}\.\s*[A-Za-z]{2,}\b", cleaned):
        return False
    return True


def _looks_like_geographic_name(parent_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(parent_name or "").lower()).strip()
    return normalized in GEOGRAPHIC_NON_ENTITY_EXACT


def _part_of_phrase_has_corporate_signal(raw_parent_name: str, parent_name: str, snippet: str) -> bool:
    raw = str(raw_parent_name or "")
    cleaned = str(parent_name or "")
    snippet_lower = str(snippet or "").lower()
    lowered = cleaned.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    if any(phrase in snippet_lower for phrase in PART_OF_CONTEXT_NOISE_PHRASES):
        return False
    if _looks_like_geographic_name(cleaned):
        return False
    if any(token in normalized.split() for token in PART_OF_CORPORATE_SIGNAL_TOKENS):
        return True
    if any(token in raw.lower() for token in PART_OF_CORPORATE_SIGNAL_TOKENS):
        return True
    if cleaned.isupper() and len(cleaned) >= 3:
        return True
    return len(cleaned.split()) >= 2 and any(char.isupper() for char in cleaned[1:])


def _is_news_like_page(page_url: str) -> bool:
    path = urlparse(page_url).path.lower()
    return any(segment in path for segment in ("/news", "/press", "/blog", "/article"))


def _extract_candidates(text: str, vendor_name: str, page_url: str) -> list[dict]:
    matches: list[dict] = []
    news_like_page = _is_news_like_page(page_url)
    for pattern, rel_type, confidence, scope in SIGNAL_PATTERNS:
        for hit in pattern.finditer(text):
            if news_like_page and scope in {"part_of_phrase", "member_of_phrase"}:
                continue
            raw_parent_name = hit.group(1)
            parent_name = _clean_parent_name(raw_parent_name)
            if not _looks_like_entity_name(raw_parent_name, parent_name):
                continue
            if _looks_like_vendor(parent_name, vendor_name):
                continue
            snippet_start = max(hit.start() - 80, 0)
            snippet_end = min(hit.end() + 80, len(text))
            snippet = text[snippet_start:snippet_end].strip()
            parent_lower = parent_name.lower()
            snippet_lower = snippet.lower()
            if scope == "part_of_phrase" and not _part_of_phrase_has_corporate_signal(raw_parent_name, parent_name, snippet):
                continue
            if rel_type == "owned_by":
                if any(phrase in parent_lower for phrase in CONTROL_BODY_NOISE_PHRASES):
                    continue
                if any(phrase in snippet_lower for phrase in CONTROL_BODY_NOISE_PHRASES):
                    continue
                if "minority member of" in snippet_lower:
                    continue
            if rel_type == "backed_by":
                if any(phrase in parent_lower for phrase in ENTITY_NOISE_PHRASES):
                    continue
                if "performance is backed by" in snippet_lower:
                    continue
            matches.append(
                {
                    "target_entity": parent_name,
                    "rel_type": rel_type,
                    "confidence": confidence,
                    "scope": scope,
                    "snippet": snippet,
                }
            )
    return matches


def _extract_descriptor_owner_hints(text: str) -> list[dict]:
    matches: list[dict] = []
    seen: set[str] = set()
    for pattern, confidence, normalized_target, scope in DESCRIPTOR_OWNERSHIP_PATTERNS:
        for hit in pattern.finditer(text):
            snippet_start = max(hit.start() - 80, 0)
            snippet_end = min(hit.end() + 120, len(text))
            snippet = text[snippet_start:snippet_end].strip()
            dedupe_key = normalized_target.upper()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            matches.append(
                {
                    "descriptor": normalized_target,
                    "confidence": confidence,
                    "scope": scope,
                    "snippet": snippet,
                }
            )
    return matches


def _identifier_hint_bonus(key: str, snippet: str) -> float:
    context = re.sub(r"\s+", " ", (snippet or "").lower())
    bonus = 0.0
    for phrase, weight in IDENTIFIER_CONTEXT_BONUSES:
        if phrase in context:
            bonus += weight
    for phrase, weight in IDENTIFIER_CONTEXT_PENALTIES:
        if phrase in context:
            bonus -= weight
    if key == "uei" and "cage" in context:
        bonus += 0.06
    if key == "duns" and "cage" in context:
        bonus += 0.04
    if key in {"uei", "cage", "duns"} and "instead" in context:
        bonus += 0.08
    return bonus


def _identifier_vendor_tokens(vendor_name: str) -> list[str]:
    raw = str(vendor_name or "").strip().lower().replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", raw)
    return [token for token in tokens if token and token not in IDENTIFIER_VENDOR_TOKEN_STOPWORDS][:4]


def _identifier_vendor_bonus(
    key: str,
    haystack: str,
    hit_start: int,
    hit_end: int,
    vendor_tokens: list[str],
) -> float:
    if not vendor_tokens:
        return 0.0
    before = re.sub(r"[^a-z0-9]+", " ", (haystack[max(0, hit_start - 120):hit_start] or "").lower()).strip()
    after = re.sub(r"[^a-z0-9]+", " ", (haystack[hit_end:min(len(haystack), hit_end + 120)] or "").lower()).strip()
    if not before and not after:
        return -0.22 if key in {"cage", "uei", "duns", "ncage"} else -0.12
    before_haystack = f" {before} " if before else ""
    after_haystack = f" {after} " if after else ""
    before_hits = sum(1 for token in vendor_tokens if before_haystack and f" {token} " in before_haystack)
    after_hits = sum(1 for token in vendor_tokens if after_haystack and f" {token} " in after_haystack)
    if before_hits >= min(2, len(vendor_tokens)):
        return 0.16
    if before_hits >= 1:
        return 0.11
    if after_hits >= 1:
        return -0.10 if key in {"cage", "uei", "duns", "ncage"} else -0.04
    return -0.22 if key in {"cage", "uei", "duns", "ncage"} else -0.12


def _extract_identifier_hints(text: str, *, vendor_name: str = "") -> dict[str, dict[str, str | float]]:
    hints: dict[str, dict[str, str | float]] = {}
    haystack = text or ""
    vendor_tokens = _identifier_vendor_tokens(vendor_name)
    for key, label, pattern, confidence in IDENTIFIER_PATTERNS:
        best_hint: dict[str, str | float] | None = None
        for hit in pattern.finditer(haystack):
            value = str(hit.group(1) or "").strip().upper()
            if not value:
                continue
            snippet_start = max(hit.start() - 80, 0)
            snippet_end = min(hit.end() + 80, len(haystack))
            snippet = haystack[snippet_start:snippet_end].strip()
            if value in INVALID_IDENTIFIER_VALUES.get(key, set()):
                continue
            if key == "uei" and not any(ch.isdigit() for ch in value):
                continue
            adjusted_confidence = max(
                0.30,
                min(
                    confidence
                    + _identifier_hint_bonus(key, snippet)
                    + _identifier_vendor_bonus(key, haystack, hit.start(), hit.end(), vendor_tokens),
                    0.92,
                ),
            )
            candidate_hint = {
                "label": label,
                "value": value,
                "confidence": adjusted_confidence,
                "snippet": snippet,
            }
            if best_hint is None:
                best_hint = candidate_hint
                continue
            current_confidence = float(best_hint["confidence"])
            if adjusted_confidence > current_confidence + 1e-9:
                best_hint = candidate_hint
                continue
            if abs(adjusted_confidence - current_confidence) <= 1e-9 and len(snippet) > len(str(best_hint["snippet"])):
                best_hint = candidate_hint
        if best_hint is not None:
            hints[key] = best_hint
    return hints


def _extract_profile_hints(text: str) -> dict[str, dict[str, str | float]]:
    hints: dict[str, dict[str, str | float]] = {}
    haystack = text or ""
    for pattern in FOUNDED_YEAR_PATTERNS:
        hit = pattern.search(haystack)
        if not hit:
            continue
        year = str(hit.group(1)).strip()
        if not year:
            continue
        snippet_start = max(hit.start() - 100, 0)
        snippet_end = min(hit.end() + 100, len(haystack))
        hints["founded_year"] = {
            "label": "Founded",
            "value": year,
            "confidence": 0.72,
            "snippet": haystack[snippet_start:snippet_end].strip(),
        }
        break
    return hints


def _extract_internal_candidate_links(markup: str, page_url: str, website: str) -> list[str]:
    base = _normalize_website(website)
    parsed_base = urlparse(base)
    base_host = str(parsed_base.netloc or "").lower()
    normalized_page_url = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}{urlparse(page_url).path}".rstrip("/")
    current_path = urlparse(page_url).path.lower().rstrip("/")
    on_discovery_hub = current_path in DISCOVERY_HUB_PATHS
    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()

    def host_is_same_or_subdomain(candidate_host: str) -> bool:
        lowered = str(candidate_host or "").lower()
        return bool(lowered and base_host and (lowered == base_host or lowered.endswith(f".{base_host}")))

    def host_matches_provider_suffix(candidate_host: str) -> bool:
        lowered = str(candidate_host or "").lower()
        return any(lowered == suffix or lowered.endswith(f".{suffix}") for suffix in DISCOVERY_PROVIDER_HOST_SUFFIXES)

    for match in ANCHOR_TAG.finditer(markup or ""):
        href = match.group("href") or ""
        label = _extract_text(match.group("label") or "")
        candidate = urljoin(page_url, href)
        parsed_candidate = urlparse(candidate)
        candidate_host = str(parsed_candidate.netloc or "").lower()
        if parsed_candidate.scheme not in {"http", "https"}:
            continue
        lowered = f"{candidate} {label}".lower()
        is_intermediary_surface = any(keyword in lowered for keyword in INTERMEDIARY_DISCOVERY_KEYWORDS)
        same_or_subdomain = host_is_same_or_subdomain(candidate_host)
        provider_surface = host_matches_provider_suffix(candidate_host) and is_intermediary_surface
        if not same_or_subdomain and not provider_surface:
            continue
        candidate_path = parsed_candidate.path.lower().rstrip("/")
        is_article_like = (
            on_discovery_hub
            and candidate_path not in DISCOVERY_HUB_PATHS
            and len(label.split()) >= 3
            and not candidate_path.endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf"))
            and not candidate_path.endswith(("/feed", "/rss"))
        )
        if not any(keyword in lowered for keyword in DISCOVERY_KEYWORDS) and not is_article_like:
            continue
        normalized = f"{parsed_candidate.scheme}://{parsed_candidate.netloc}{parsed_candidate.path}".rstrip("/")
        if not normalized or normalized == normalized_page_url:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        score = 0
        if is_intermediary_surface:
            score += 65
        if any(keyword in lowered for keyword in ("billing", "checkout", "payment", "merchant")):
            score += 55
        if any(keyword in lowered for keyword in ("support", "help", "status", "trust", "security", "portal")):
            score += 48
        if any(keyword in lowered for keyword in ("fund", "invest", "back", "acquir")):
            score += 50
        if any(keyword in lowered for keyword in ("history", "leadership", "about")):
            score += 25
        if any(keyword in lowered for keyword in ("company", "corporate")):
            score += 22
        if same_or_subdomain and candidate_host != base_host:
            score += 30
        if provider_surface:
            score += 30
        if "growth" in lowered:
            score += 20
        if any(keyword in lowered for keyword in ("news", "press")):
            score += 5
        if parsed_candidate.path.lower().endswith("/news"):
            score -= 10
        if is_article_like:
            score += 18
        discovered.append((score, normalized))
    discovered.sort(key=lambda item: (-item[0], item[1]))
    return [url for _score, url in discovered[:MAX_DISCOVERED_LINKS]]


def _vendor_discovery_queries(vendor_name: str) -> list[str]:
    raw = re.split(r"\s*[|/]\s*", str(vendor_name or "").strip(), maxsplit=1)[0]
    queries: list[str] = []
    seen: set[str] = set()
    if raw:
        queries.append(raw)
        seen.add(raw.lower())
    tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", raw)
        if token and token.lower() not in DISCOVERY_QUERY_STOPWORDS
    ]
    for width in (3, 2):
        if len(tokens) >= width:
            candidate = " ".join(tokens[:width]).strip()
            if candidate and candidate.lower() not in seen:
                seen.add(candidate.lower())
                queries.append(candidate)
    return queries[:3]


def _wordpress_discovery_queries(vendor_name: str) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for candidate in [*_vendor_discovery_queries(vendor_name), *OWNERSHIP_DISCOVERY_QUERIES]:
        normalized = str(candidate or "").strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        queries.append(normalized)
    return queries[:8]


def _discovery_candidate_score(link: str, text: str, vendor_tokens: list[str]) -> int:
    haystack = f"{str(link or '').lower()} {str(text or '').lower()}"
    score = 0
    for token in vendor_tokens:
        if token and token in haystack:
            score += 18
    for keyword in DISCOVERY_SURFACE_KEYWORDS:
        if keyword in haystack:
            score += 15
    if "/news/" in str(link or "").lower() or "/blog/" in str(link or "").lower():
        score += 8
    return score


def _fetch_wordpress_post_links(website: str, vendor_name: str) -> list[str]:
    vendor_tokens = [
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", vendor_name or "")
        if token and token.lower() not in DISCOVERY_QUERY_STOPWORDS
    ]
    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()
    for base in _website_variants(website):
        for query in _wordpress_discovery_queries(vendor_name):
            endpoint = f"{base}/wp-json/wp/v2/posts?search={quote_plus(query)}&per_page=5&_fields=link,title,excerpt,content,slug"
            try:
                response = requests.get(
                    endpoint,
                    timeout=TIMEOUT,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                response.raise_for_status()
                payload = json.loads(response.text or "[]")
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                link = str(item.get("link") or "").strip().rstrip("/")
                if not link or link in seen:
                    continue
                title = _extract_text(str((item.get("title") or {}).get("rendered") if isinstance(item.get("title"), dict) else item.get("title") or ""))
                excerpt = _extract_text(str((item.get("excerpt") or {}).get("rendered") if isinstance(item.get("excerpt"), dict) else item.get("excerpt") or ""))
                content = _extract_text(str((item.get("content") or {}).get("rendered") if isinstance(item.get("content"), dict) else item.get("content") or ""))
                score = _discovery_candidate_score(link, f"{title} {excerpt} {content}", vendor_tokens)
                if score <= 0:
                    continue
                seen.add(link)
                discovered.append((score, link))
    discovered.sort(key=lambda item: (-item[0], item[1]))
    return [link for _score, link in discovered[:MAX_DISCOVERY_SURFACE_LINKS]]


def _fetch_rss_post_links(website: str, vendor_name: str, *, page_url: str) -> list[str]:
    page_path = urlparse(page_url).path.rstrip("/")
    vendor_tokens = [
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", vendor_name or "")
        if token and token.lower() not in DISCOVERY_QUERY_STOPWORDS
    ]
    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()
    for base in _website_variants(website):
        feed_candidates = [f"{base}/feed", f"{base}/news/feed"]
        if page_path in DISCOVERY_HUB_PATHS:
            feed_candidates.insert(0, f"{base}{page_path}/feed")
        for candidate_url in dict.fromkeys(feed_candidates):
            try:
                xml_text, _content_type, _resolved_url, _response_headers = _coerce_fetch_page_result(_fetch_page(candidate_url), candidate_url)
            except Exception:
                continue
            for match in RSS_ITEM_RE.finditer(xml_text or ""):
                link = str(match.group("link") or "").strip().rstrip("/")
                if not link or link in seen:
                    continue
                title = _extract_text(match.group("title") or "")
                score = _discovery_candidate_score(link, title, vendor_tokens)
                if score <= 0:
                    continue
                seen.add(link)
                discovered.append((score, link))
    discovered.sort(key=lambda item: (-item[0], item[1]))
    return [link for _score, link in discovered[:MAX_DISCOVERY_SURFACE_LINKS]]


def _fetch_sitemap_post_links(website: str, vendor_name: str) -> list[str]:
    vendor_tokens = [
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", vendor_name or "")
        if token and token.lower() not in DISCOVERY_QUERY_STOPWORDS
    ]
    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()
    for base in _website_variants(website):
        sitemap_urls = [f"{base}/post-sitemap.xml"]
        try:
            index_xml, _content_type, _resolved_url, _response_headers = _coerce_fetch_page_result(_fetch_page(f"{base}/sitemap_index.xml"), f"{base}/sitemap_index.xml")
        except Exception:
            index_xml = ""
        for match in SITEMAP_LOC_RE.finditer(index_xml or ""):
            link = str(match.group("link") or "").strip()
            if link.endswith("post-sitemap.xml"):
                sitemap_urls.insert(0, link)
        for sitemap_url in dict.fromkeys(sitemap_urls):
            try:
                sitemap_xml, _content_type, _resolved_url, _response_headers = _coerce_fetch_page_result(_fetch_page(sitemap_url), sitemap_url)
            except Exception:
                continue
            for match in SITEMAP_LOC_RE.finditer(sitemap_xml or ""):
                link = str(match.group("link") or "").strip().rstrip("/")
                if not link or link in seen:
                    continue
                if link.rstrip("/") == base.rstrip("/"):
                    continue
                score = _discovery_candidate_score(link, link, vendor_tokens)
                if score <= 0:
                    continue
                seen.add(link)
                discovered.append((score, link))
    discovered.sort(key=lambda item: (-item[0], item[1]))
    return [link for _score, link in discovered[:MAX_DISCOVERY_SURFACE_LINKS]]


def _discover_first_party_links(vendor_name: str, markup: str, page_url: str, website: str) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()

    def add_links(candidates: list[str]) -> None:
        for candidate in candidates:
            normalized = str(candidate or "").rstrip("/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            discovered.append(normalized)
            if len(discovered) >= MAX_DISCOVERED_LINKS:
                return

    current_path = urlparse(page_url).path.lower().rstrip("/")
    internal_candidates = _extract_internal_candidate_links(markup, page_url, website)
    root_links_to_discovery_hub = current_path == "" and any(
        urlparse(candidate).path.lower().rstrip("/") in DISCOVERY_HUB_PATHS
        for candidate in internal_candidates
    )
    if current_path in DISCOVERY_HUB_PATHS or root_links_to_discovery_hub:
        add_links(_fetch_wordpress_post_links(website, vendor_name))
        if len(discovered) < MAX_DISCOVERED_LINKS:
            add_links(_fetch_rss_post_links(website, vendor_name, page_url=page_url))
        if len(discovered) < MAX_DISCOVERED_LINKS:
            add_links(_fetch_sitemap_post_links(website, vendor_name))
    if len(discovered) < MAX_DISCOVERED_LINKS:
        add_links(internal_candidates)
    return discovered[:MAX_DISCOVERED_LINKS]


def _fetch_page(url: str) -> tuple[str, str, str, dict[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path or "")).resolve()
        content_type = "text/html; charset=utf-8" if path.suffix.lower() in {".html", ".htm", ".xhtml"} else "text/plain; charset=utf-8"
        return path.read_text(encoding="utf-8"), content_type, path.as_uri(), {}
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    resolved_url = _normalize_website(str(getattr(response, "url", "") or url))
    if "html" not in content_type and response.text.lstrip()[:1] != "<":
        return "", content_type, resolved_url, {str(key): str(value) for key, value in response.headers.items()}
    return response.text, content_type, resolved_url, {str(key): str(value) for key, value in response.headers.items()}


def _coerce_fetch_page_result(payload, fallback_url: str) -> tuple[str, str, str, dict[str, str]]:
    if isinstance(payload, tuple):
        if len(payload) == 4:
            html_text, content_type, resolved_url, response_headers = payload
            headers = {str(key): str(value) for key, value in dict(response_headers or {}).items()}
            return str(html_text or ""), str(content_type or ""), _normalize_website(str(resolved_url or fallback_url)), headers
        if len(payload) == 3:
            html_text, content_type, resolved_url = payload
            return str(html_text or ""), str(content_type or ""), _normalize_website(str(resolved_url or fallback_url)), {}
        if len(payload) == 2:
            html_text, content_type = payload
            return str(html_text or ""), str(content_type or ""), _normalize_website(fallback_url), {}
    raise ValueError("unexpected fetch page result")


def _extract_header_signature_hints(
    response_headers: dict[str, str],
    *,
    vendor_name: str,
    country: str,
    website: str,
    page_url: str,
) -> dict[str, list]:
    headers = {str(key).lower(): str(value or "") for key, value in dict(response_headers or {}).items()}
    relationships: list[dict] = []
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for header_name, pattern, rel_type, target_name, confidence, scope in HEADER_PROVIDER_HINTS:
        header_value = headers.get(header_name.lower(), "") if header_name else " ".join(headers.values())
        if not header_value or not pattern.search(header_value):
            continue
        dedupe_key = (rel_type, target_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        relationship_meta = _RELATIONSHIP_META.get(rel_type, _RELATIONSHIP_META["depends_on_service"])
        snippet = f"{header_name or 'header'}: {header_value}".strip()
        relationships.append(
            _build_relationship(
                vendor_name=vendor_name,
                country=country,
                website=website,
                rel_type=rel_type,
                parent_name=target_name,
                page_url=page_url,
                confidence=confidence,
                scope=scope,
                snippet=snippet[:240],
            )
        )
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category=relationship_meta["finding_category"],
                title=f"{relationship_meta['finding_title_prefix']}{target_name}",
                detail=f"{snippet[:240]} | Source page: {page_url}",
                severity="info",
                confidence=confidence,
                url=page_url,
                artifact_ref=page_url,
                structured_fields={
                    "relationship_scope": relationship_meta["relationship_scope_default"],
                    "relationship_type": rel_type,
                    "target_entity": target_name,
                    "source_header": header_name,
                    "website": website,
                },
                source_class="public_connector",
                authority_level="first_party_self_disclosed",
                access_model="public_html",
            )
        )
    return {"relationships": relationships, "findings": findings}


def _build_relationship(
    *,
    vendor_name: str,
    country: str,
    website: str,
    rel_type: str,
    parent_name: str,
    page_url: str,
    confidence: float,
    scope: str,
    snippet: str,
) -> dict:
    relationship_meta = _RELATIONSHIP_META.get(rel_type, _RELATIONSHIP_META["owned_by"])
    relationship_scope = scope if rel_type == "owned_by" else relationship_meta["relationship_scope_default"]
    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {"website": website} if website else {},
        "target_entity": parent_name,
        "target_entity_type": relationship_meta["target_entity_type"],
        "target_identifiers": {},
        "country": country,
        "data_source": SOURCE_NAME,
        "confidence": confidence,
        "evidence": snippet,
        "observed_at": datetime.utcnow().isoformat() + "Z",
        "artifact_ref": page_url,
        "evidence_url": page_url,
        "evidence_title": relationship_meta["evidence_title"],
        "structured_fields": {
            "relationship_scope": relationship_scope,
            "extraction_method": "public_html_pattern",
            "source_page": page_url,
            "website": website,
        },
        "source_class": "public_connector",
        "authority_level": "first_party_self_disclosed",
        "access_model": "public_html",
        "raw_data": {
            "snippet": snippet,
            "website": website,
            "page_url": page_url,
        },
    }


def _resolve_website(ids: dict) -> str:
    raw_pages = ids.get("first_party_pages")
    page_candidates = (
        [raw_pages]
        if isinstance(raw_pages, str)
        else list(raw_pages)
        if isinstance(raw_pages, (list, tuple, set))
        else []
    )
    seen_page_roots: set[str] = set()
    for candidate in page_candidates:
        root = _root_website(str(candidate or ""))
        if root.startswith("file://"):
            continue
        if not root or root in seen_page_roots:
            continue
        seen_page_roots.add(root)
        return root

    for key in ("official_website", "domain", "website"):
        value = ids.get(key)
        if isinstance(value, str) and value.strip():
            return _root_website(value) or _normalize_website(value)
    return ""


def extract_page(
    vendor_name: str,
    country: str = "",
    *,
    website: str,
    page_url: str,
    discover_links: bool = False,
) -> tuple[EnrichmentResult, list[str]]:
    result = EnrichmentResult(source=SOURCE_NAME, vendor_name=vendor_name)
    started = datetime.utcnow()
    normalized_website = _normalize_website(website)
    normalized_page_url = _normalize_website(page_url)
    canonical_website = _canonical_first_party_website(normalized_website, [normalized_page_url])
    result.source_class = "public_connector"
    result.authority_level = "first_party_self_disclosed"
    result.access_model = "public_html"

    if not normalized_website or not normalized_page_url:
        result.elapsed_ms = 0
        return result, []

    discovered_links: list[str] = []
    try:
        html_text, _content_type, resolved_page_url, response_headers = _coerce_fetch_page_result(_fetch_page(normalized_page_url), normalized_page_url)
        effective_page_url = resolved_page_url or normalized_page_url
        canonical_website = _canonical_first_party_website(normalized_website, [effective_page_url])
        text = _extract_text(html_text)
        json_ld_hints = _extract_json_ld_hints(
            html_text,
            vendor_name=vendor_name,
            country=country,
            website=canonical_website or normalized_website,
            page_url=effective_page_url,
        )
        for key, value in json_ld_hints.get("identifiers", {}).items():
            result.identifiers.setdefault(str(key), str(value))
        result.relationships.extend(list(json_ld_hints.get("relationships", [])))
        result.findings.extend(list(json_ld_hints.get("findings", [])))
        tech_hints = _extract_technology_signature_hints(
            html_text,
            vendor_name=vendor_name,
            country=country,
            website=canonical_website or normalized_website,
            page_url=effective_page_url,
        )
        result.relationships.extend(list(tech_hints.get("relationships", [])))
        result.findings.extend(list(tech_hints.get("findings", [])))
        header_hints = _extract_header_signature_hints(
            response_headers,
            vendor_name=vendor_name,
            country=country,
            website=canonical_website or normalized_website,
            page_url=effective_page_url,
        )
        result.relationships.extend(list(header_hints.get("relationships", [])))
        result.findings.extend(list(header_hints.get("findings", [])))
        if not text:
            result.identifiers["website"] = canonical_website or normalized_website
            result.structured_fields["resolved_page_url"] = effective_page_url
            result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return result, discovered_links

        for key, hint in _extract_identifier_hints(text).items():
            value = str(hint["value"])
            result.identifiers.setdefault(key, value)
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="identity",
                    title=f"Public site identifier hint: {hint['label']} {value}",
                    detail=f"{hint['snippet']} | Source page: {effective_page_url}",
                    severity="info",
                    confidence=float(hint["confidence"]),
                    url=effective_page_url,
                    artifact_ref=effective_page_url,
                    structured_fields={
                        "identifier_type": key,
                        "identifier_value": value,
                        "source_page": effective_page_url,
                        "website": canonical_website or normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        for key, hint in _extract_profile_hints(text).items():
            value = str(hint["value"])
            result.identifiers.setdefault(key, value)
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="profile",
                    title=f"Public site operating history hint: founded in {value}",
                    detail=f"{hint['snippet']} | Source page: {effective_page_url}",
                    severity="info",
                    confidence=float(hint["confidence"]),
                    url=effective_page_url,
                    artifact_ref=effective_page_url,
                    structured_fields={
                        "identifier_type": key,
                        "identifier_value": value,
                        "source_page": effective_page_url,
                        "website": canonical_website or normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        for descriptor_hint in _extract_descriptor_owner_hints(text):
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="ownership",
                    title=f"Public site beneficial ownership descriptor: {descriptor_hint['descriptor']}",
                    detail=f"{descriptor_hint['snippet']} | Source page: {effective_page_url}",
                    severity="info",
                    confidence=float(descriptor_hint["confidence"]),
                    url=effective_page_url,
                    artifact_ref=effective_page_url,
                    structured_fields={
                        "ownership_descriptor": descriptor_hint["descriptor"],
                        "ownership_descriptor_scope": descriptor_hint["scope"],
                        "website": canonical_website or normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        for candidate in _extract_candidates(text, vendor_name, effective_page_url):
            relationship_meta = _RELATIONSHIP_META.get(candidate["rel_type"], _RELATIONSHIP_META["owned_by"])
            result.relationships.append(
                _build_relationship(
                    vendor_name=vendor_name,
                    country=country,
                    website=canonical_website or normalized_website,
                    rel_type=candidate["rel_type"],
                    parent_name=candidate["target_entity"],
                    page_url=effective_page_url,
                    confidence=candidate["confidence"],
                    scope=candidate["scope"],
                    snippet=candidate["snippet"],
                )
            )
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category=relationship_meta["finding_category"],
                    title=f"{relationship_meta['finding_title_prefix']}{candidate['target_entity']}",
                    detail=f"{candidate['snippet']} | Source page: {effective_page_url}",
                    severity="info",
                    confidence=candidate["confidence"],
                    url=effective_page_url,
                    artifact_ref=effective_page_url,
                    structured_fields={
                        "relationship_scope": (
                            candidate["scope"]
                            if candidate["rel_type"] == "owned_by"
                            else relationship_meta["relationship_scope_default"]
                        ),
                        "relationship_type": candidate["rel_type"],
                        "target_entity": candidate["target_entity"],
                        "website": canonical_website or normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        if discover_links:
            discovered_links = _discover_first_party_links(
                vendor_name,
                html_text,
                effective_page_url,
                canonical_website or normalized_website,
            )
    except Exception as exc:
        result.error = str(exc)

    result.identifiers["website"] = canonical_website or normalized_website
    if "effective_page_url" in locals():
        result.structured_fields["resolved_page_url"] = effective_page_url
    result.artifact_refs = list(
        dict.fromkeys(
            [
                *(rel["artifact_ref"] for rel in result.relationships if rel.get("artifact_ref")),
                *(finding.artifact_ref for finding in result.findings if finding.artifact_ref),
            ]
        )
    )
    result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    if result.relationships:
        result.risk_signals.append(
            {
                "signal": "ownership_self_disclosed",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": max((rel["confidence"] for rel in result.relationships), default=0.0),
                "summary": f"Public website ownership hint found for {vendor_name}",
                "website": canonical_website or normalized_website,
            }
        )
    return result, discovered_links


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source=SOURCE_NAME, vendor_name=vendor_name)
    started = datetime.utcnow()
    website = _resolve_website(ids)
    result.source_class = "public_connector"
    result.authority_level = "first_party_self_disclosed"
    result.access_model = "public_html"

    if not website:
        result.elapsed_ms = 0
        return result

    relationships: list[dict] = []
    findings: list[Finding] = []
    seen_targets: set[tuple[str, str]] = set()
    seen_identifiers: set[tuple[str, str]] = set()
    identifier_artifact_refs: list[str] = []
    seen_page_findings: set[tuple[str, str, str]] = set()
    successful_pages: list[str] = []
    fixture_pages = _resolve_fixture_pages(ids)
    fixture_only = _is_truthy_flag(ids.get("public_html_fixture_only"))
    seeded_pages = fixture_pages + [candidate for candidate in _resolve_first_party_pages(ids, website) if candidate not in fixture_pages]
    seeded_page_keys = {
        (_page_visit_key(candidate) or candidate)
        for candidate in seeded_pages
        if candidate
    }
    queue = list(seeded_pages)
    if not fixture_only:
        queue.extend(candidate for candidate in _candidate_urls(website) if candidate not in queue)
    visited_urls: set[str] = set()
    successful_page_keys: set[str] = set()
    visited_pages: list[str] = []

    try:
        while queue and len(visited_urls) < MAX_PAGES:
            page_url = _normalize_website(queue.pop(0))
            if not page_url:
                continue
            page_key = _page_visit_key(page_url) or page_url
            if page_url in visited_urls or page_key in successful_page_keys:
                continue
            visited_urls.add(page_url)
            visited_pages.append(page_url)
            discover_more_links = (
                not fixture_only
                and urlparse(page_url).scheme != "file"
                and not _should_stop_optional_fetches(relationships, result.identifiers, findings)
            )
            page_result, discovered_links = extract_page(
                vendor_name,
                country,
                website=website,
                page_url=page_url,
                discover_links=discover_more_links,
            )
            if page_result.error:
                continue
            successful_page_keys.add(page_key)
            resolved_page_url = str(page_result.structured_fields.get("resolved_page_url") or page_url).rstrip("/")
            successful_pages.append(resolved_page_url)
            for key, value in page_result.identifiers.items():
                if key == "website":
                    continue
                dedupe_key = (key, value)
                if dedupe_key in seen_identifiers:
                    continue
                seen_identifiers.add(dedupe_key)
                result.identifiers.setdefault(key, value)
            for finding in page_result.findings:
                artifact_ref = finding.artifact_ref or page_url
                structured_fields = finding.structured_fields if isinstance(finding.structured_fields, dict) else {}
                keep_without_relationship = (
                    finding.category == "ownership"
                    and bool(structured_fields.get("ownership_descriptor"))
                )
                if finding.category not in {"identity", "profile"} and not keep_without_relationship:
                    continue
                dedupe_key = (finding.category, finding.title, artifact_ref)
                if dedupe_key in seen_page_findings:
                    continue
                seen_page_findings.add(dedupe_key)
                if artifact_ref:
                    identifier_artifact_refs.append(artifact_ref)
                findings.append(finding)
            relationship_findings = {
                (
                    str(finding.structured_fields.get("relationship_type") or ""),
                    str(finding.structured_fields.get("target_entity") or "").upper(),
                ): finding
                for finding in page_result.findings
                if finding.category in {"ownership", "finance", "intermediary"}
            }
            for relationship in page_result.relationships:
                dedupe_key = (relationship["type"], relationship["target_entity"].upper())
                if dedupe_key in seen_targets:
                    continue
                seen_targets.add(dedupe_key)
                relationships.append(relationship)
                relationship_finding = relationship_findings.get(dedupe_key)
                if relationship_finding:
                    findings.append(relationship_finding)
            if not fixture_only and _should_stop_optional_fetches(relationships, result.identifiers, findings):
                queue = [
                    candidate
                    for candidate in queue
                    if (_page_visit_key(candidate) or _normalize_website(candidate) or candidate) in seeded_page_keys
                ]
                if not queue:
                    break
            for discovered in reversed(discovered_links):
                normalized_discovered = _normalize_website(discovered)
                if not normalized_discovered:
                    continue
                discovered_key = _page_visit_key(normalized_discovered) or normalized_discovered
                queued = any(
                    (_page_visit_key(candidate) or _normalize_website(candidate) or candidate) == discovered_key
                    for candidate in queue
                )
                if (
                    normalized_discovered not in visited_urls
                    and discovered_key not in successful_page_keys
                    and not queued
                ):
                    queue.insert(0, normalized_discovered)
    except Exception as exc:
        result.error = str(exc)

    canonical_website = _canonical_first_party_website(
        website,
        [*seeded_pages, *successful_pages, *identifier_artifact_refs, *(rel.get("artifact_ref") for rel in relationships)],
    )
    domain_hints = _extract_domain_dependency_hints(
        vendor_name,
        country=country,
        website=canonical_website or website,
        ids=ids,
    )
    for key, value in domain_hints.get("identifiers", {}).items():
        result.identifiers.setdefault(str(key), str(value))
    seen_finding_keys = {
        (finding.category, finding.title, finding.artifact_ref or "")
        for finding in findings
    }
    for relationship in domain_hints.get("relationships", []):
        dedupe_key = (relationship["type"], relationship["target_entity"].upper())
        if dedupe_key in seen_targets:
            continue
        seen_targets.add(dedupe_key)
        relationships.append(relationship)
    for finding in domain_hints.get("findings", []):
        dedupe_key = (finding.category, finding.title, finding.artifact_ref or "")
        if dedupe_key in seen_finding_keys:
            continue
        seen_finding_keys.add(dedupe_key)
        findings.append(finding)
    result.identifiers["website"] = canonical_website or website
    canonical_seed_pages = _resolve_first_party_pages(
        {"first_party_pages": [*seeded_pages, *identifier_artifact_refs, *(rel.get("artifact_ref") for rel in relationships)]},
        canonical_website or website,
    )
    if canonical_seed_pages:
        result.identifiers["first_party_pages"] = canonical_seed_pages
    result.relationships = relationships
    result.findings = findings
    result.artifact_refs = list(
        dict.fromkeys(
            [rel["artifact_ref"] for rel in relationships if rel.get("artifact_ref")] + identifier_artifact_refs
        )
    )
    result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    if canonical_seed_pages:
        result.structured_fields["seed_pages"] = canonical_seed_pages
    if fixture_pages:
        result.structured_fields["fixture_pages"] = fixture_pages
    result.structured_fields["visited_pages"] = visited_pages
    result.structured_fields["successful_pages"] = successful_pages
    if relationships:
        result.risk_signals.append(
            {
                "signal": "ownership_self_disclosed",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": max((rel["confidence"] for rel in relationships), default=0.0),
                "summary": f"Public website control-path hint found for {vendor_name}",
                "website": canonical_website or website,
            }
        )
    return result
