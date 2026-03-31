#!/usr/bin/env python3
"""Download a public Open Ownership BODS dataset into the local cache."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "var" / "openownership_bods_public.json"
USER_AGENT = "Helios/5.2 (+https://xiphosllc.com)"


def _resolve_url(explicit_url: str) -> str:
    if explicit_url:
        return explicit_url
    return str(os.environ.get("XIPHOS_OPENOWNERSHIP_BODS_URL") or "").strip()


def sync_dataset(url: str, output_path: Path) -> Path:
    if not url:
        raise ValueError("No dataset URL provided. Pass --url or set XIPHOS_OPENOWNERSHIP_BODS_URL.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with tempfile.NamedTemporaryFile(delete=False, dir=str(output_path.parent), suffix=".tmp") as temp_file:
        temp_path = Path(temp_file.name)
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temp_path.replace(output_path)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download Open Ownership dataset: {exc}") from exc
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="Public Open Ownership dataset URL")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output path for the local cache (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)
    output_path = Path(args.output).expanduser().resolve()
    try:
        synced = sync_dataset(_resolve_url(args.url), output_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(synced))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
