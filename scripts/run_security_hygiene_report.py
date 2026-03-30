#!/usr/bin/env python3
"""Generate a repo hygiene report for secrets, prod refs, tracked env files, and fixture PII."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "security_hygiene"
SKIP_PREFIXES = (
    "backend/static/",
    "frontend/node_modules/",
    "node_modules/",
    "docs/reports/",
    ".git/",
    "tests/e2e/playwright-report/",
)
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".gz",
    ".patch",
    ".min.js",
}
TRACKED_ENV_NAMES = {".env", "deploy.env"}
TRACKED_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
PRODUCTION_HOST_PATTERNS = (
    re.compile(r"\b209\.38\.141\.101\b"),
    re.compile(r"\b24\.199\.122\.225\b"),
    re.compile(r"\broot@(?:209\.38\.141\.101|24\.199\.122\.225)\b"),
    re.compile(r"\b[a-z0-9.-]+\.sslip\.io\b", re.IGNORECASE),
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
CREDENTIAL_RE = re.compile(
    r"(?i)\b(api[_-]?key|client[_ -]?secret|token|password|secret)\b\s*[:=]\s*[\"']([^\"']+)[\"']"
)
PLACEHOLDER_VALUES = {
    "",
    "secret",
    "password",
    "token",
    "test",
    "test-key",
    "example",
    "example-token",
    "sk-test",
    "analystpass123!",
    "abc123",
    "token-123",
    "failed",
    "flaky",
    "passed",
    "skipped",
}
PLACEHOLDER_EMAIL_SUFFIXES = (
    "@example.com",
    "@example.org",
    "@example.net",
    "@example.test",
)


@dataclass
class Finding:
    category: str
    file: str
    line: int
    value: str
    recommendation: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Helios security and production-data hygiene sweep.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def git_tracked_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=False,
        check=True,
    )
    files: list[Path] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="ignore")
        if rel.startswith(SKIP_PREFIXES):
            continue
        if any(rel.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        files.append(ROOT / rel)
    return files


def iter_text_lines(paths: Iterable[Path]) -> Iterable[tuple[Path, int, str]]:
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            yield path, line_no, line


def scan_tracked_env_files(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if path.name in TRACKED_ENV_NAMES or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(
                Finding(
                    category="tracked_env_file",
                    file=rel,
                    line=1,
                    value=path.name,
                    recommendation="Keep live env files out of git and use example templates only.",
                )
            )
    return findings


def scan_tracked_db_files(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in TRACKED_DB_SUFFIXES:
            findings.append(
                Finding(
                    category="tracked_database_file",
                    file=rel,
                    line=1,
                    value=path.name,
                    recommendation="Do not keep database artifacts under version control unless they are deliberate sanitized fixtures.",
                )
            )
    return findings


def scan_production_refs(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path, line_no, line in iter_text_lines(paths):
        rel = path.relative_to(ROOT).as_posix()
        for pattern in PRODUCTION_HOST_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            findings.append(
                Finding(
                    category="production_host_reference",
                    file=rel,
                    line=line_no,
                    value=match.group(0),
                    recommendation="Move live hosts and SSH targets into local ops notes or env, not tracked source.",
                )
            )
    return findings


def scan_credentials(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path, line_no, line in iter_text_lines(paths):
        rel = path.relative_to(ROOT).as_posix()
        for match in CREDENTIAL_RE.finditer(line):
            key_name = str(match.group(1) or "").lower()
            value = str(match.group(2) or "").strip()
            if value.lower() in PLACEHOLDER_VALUES:
                continue
            if (value.startswith("<") and value.endswith(">")) or value.startswith("$("):
                continue
            if value.startswith("${") or value.startswith("os.environ") or value.startswith("env("):
                continue
            findings.append(
                Finding(
                    category="hardcoded_credential_like_value",
                    file=rel,
                    line=line_no,
                    value=f"{key_name}={value[:24]}",
                    recommendation="Replace hardcoded secrets with env-backed configuration or a secret manager.",
                )
            )
    return findings


def scan_fixture_pii(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path, line_no, line in iter_text_lines(paths):
        rel = path.relative_to(ROOT).as_posix()
        if not (rel.startswith("tests/") or rel.startswith("fixtures/")):
            continue
        for match in EMAIL_RE.finditer(line):
            email = match.group(0)
            if email.lower().endswith(PLACEHOLDER_EMAIL_SUFFIXES):
                continue
            findings.append(
                Finding(
                    category="fixture_or_test_pii_email",
                    file=rel,
                    line=line_no,
                    value=email,
                    recommendation="Replace real email addresses in tests and fixtures with sanitized placeholders unless they are intentional public reference data.",
                )
            )
    return findings


def render_markdown(summary: dict) -> str:
    findings = summary["findings"]
    lines = [
        "# Helios Security Hygiene Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Status: **{summary['status'].upper()}**",
        f"Findings: {summary['finding_count']}",
        "",
    ]
    if not findings:
        lines.extend(["No issues found.", ""])
        return "\n".join(lines)

    lines.extend(["## Findings", ""])
    for finding in findings:
        lines.extend(
            [
                f"- `{finding['category']}` {finding['file']}:{finding['line']}",
                f"  - Value: `{finding['value']}`",
                f"  - Recommendation: {finding['recommendation']}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    tracked = git_tracked_files()
    findings = [
        *scan_tracked_env_files(tracked),
        *scan_tracked_db_files(tracked),
        *scan_production_refs(tracked),
        *scan_credentials(tracked),
        *scan_fixture_pii(tracked),
    ]
    findings = sorted(findings, key=lambda item: (item.category, item.file, item.line, item.value))
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "failed" if findings else "ok",
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_json = report_dir / f"security-hygiene-{stamp}.json"
    output_md = report_dir / f"security-hygiene-{stamp}.md"
    output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(summary), encoding="utf-8")

    if args.print_json:
        print(json.dumps({**summary, "report_json": str(output_json), "report_md": str(output_md)}, indent=2))
    else:
        print(f"{summary['status'].upper()}: security hygiene ({summary['finding_count']} findings)")
        print(f"JSON: {output_json}")
        print(f"Markdown: {output_md}")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
