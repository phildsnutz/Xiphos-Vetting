"""Helpers for normalizing OSS package inventories and repository URLs."""

from __future__ import annotations

import urllib.parse


OSV_ECOSYSTEM_ALIASES = {
    "npm": "npm",
    "node": "npm",
    "pypi": "PyPI",
    "python": "PyPI",
    "maven": "Maven",
    "cargo": "crates.io",
    "crates": "crates.io",
    "crates.io": "crates.io",
    "go": "Go",
    "golang": "Go",
    "nuget": "NuGet",
    "rubygems": "RubyGems",
    "gem": "RubyGems",
}

DEPS_DEV_SYSTEM_ALIASES = {
    "npm": "NPM",
    "node": "NPM",
    "pypi": "PYPI",
    "python": "PYPI",
    "maven": "MAVEN",
    "cargo": "CARGO",
    "crates": "CARGO",
    "crates.io": "CARGO",
    "go": "GO",
    "golang": "GO",
    "nuget": "NUGET",
    "rubygems": "RUBYGEMS",
    "gem": "RUBYGEMS",
}


def _parse_purl(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    if not text.startswith("pkg:"):
        return {}
    body = text[4:]
    if "@" in body:
        path, version = body.split("@", 1)
    else:
        path, version = body, ""
    if "/" not in path:
        return {}
    ecosystem, package_name = path.split("/", 1)
    package_name = urllib.parse.unquote(package_name.strip())
    normalized = _normalize_package_fields(
        {
            "ecosystem": ecosystem,
            "name": package_name,
            "version": version.strip(),
            "purl": text,
        }
    )
    return normalized


def _parse_text_item(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    if text.startswith("pkg:"):
        return _parse_purl(text)
    ecosystem = ""
    remainder = text
    if ":" in text:
        ecosystem, remainder = text.split(":", 1)
    version = ""
    if "@" in remainder:
        name, version = remainder.rsplit("@", 1)
    else:
        name = remainder
    return _normalize_package_fields(
        {
            "ecosystem": ecosystem,
            "name": name.strip(),
            "version": version.strip(),
        }
    )


def _normalize_package_fields(item: dict) -> dict[str, str]:
    ecosystem_raw = str(item.get("ecosystem") or item.get("system") or "").strip()
    ecosystem_key = ecosystem_raw.lower()
    osv_ecosystem = OSV_ECOSYSTEM_ALIASES.get(ecosystem_key, ecosystem_raw)
    deps_system = DEPS_DEV_SYSTEM_ALIASES.get(ecosystem_key, ecosystem_raw.upper())
    name = str(item.get("name") or item.get("package") or "").strip()
    version = str(item.get("version") or "").strip()
    purl = str(item.get("purl") or "").strip()
    if not name:
        return {}
    return {
        "ecosystem": osv_ecosystem,
        "system": deps_system,
        "name": name,
        "version": version,
        "purl": purl,
    }


def normalize_package_inventory(ids: dict) -> list[dict[str, str]]:
    raw_inventory = ids.get("package_inventory") or ids.get("packages") or []
    if isinstance(raw_inventory, dict):
        raw_inventory = [raw_inventory]
    if isinstance(raw_inventory, str):
        raw_inventory = [part.strip() for part in raw_inventory.splitlines() if part.strip()]

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_inventory if isinstance(raw_inventory, list) else []:
        parsed: dict[str, str]
        if isinstance(item, dict):
            parsed = _normalize_package_fields(item)
            if not parsed and str(item.get("purl") or "").strip():
                parsed = _parse_purl(str(item.get("purl") or ""))
        else:
            parsed = _parse_text_item(str(item))
        if not parsed:
            continue
        dedupe_key = (
            parsed.get("ecosystem", ""),
            parsed.get("name", ""),
            parsed.get("version", ""),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(parsed)
    return normalized


def normalize_repository_urls(ids: dict) -> list[str]:
    raw_urls = ids.get("repository_urls") or ids.get("repos") or []
    if isinstance(raw_urls, str):
        raw_urls = [part.strip() for part in raw_urls.splitlines() if part.strip()]
    if not isinstance(raw_urls, list):
        return []

    normalized: list[str] = []
    for item in raw_urls:
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith("github.com/") or text.startswith("gitlab.com/") or text.startswith("bitbucket.org/"):
            text = f"https://{text}"
        if text.endswith(".git"):
            text = text[:-4]
        if text not in normalized:
            normalized.append(text)
    return normalized


def github_slug_from_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("github.com/"):
        text = f"https://{text}"
    parsed = urllib.parse.urlparse(text)
    if parsed.netloc.lower() != "github.com":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1]}"
