#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid
import urllib.request


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_WRAPPER = pathlib.Path.home() / ".codex" / "skills" / "playwright" / "scripts" / "playwright_cli.sh"


def _run_cli(wrapper: pathlib.Path, session: str, cwd: pathlib.Path, *args: str) -> str:
    env = os.environ.copy()
    env["PLAYWRIGHT_CLI_SESSION"] = session
    completed = subprocess.run(
        [str(wrapper), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Playwright CLI failed").strip())
    if "### Error" in completed.stdout:
        raise RuntimeError(completed.stdout.strip())
    return completed.stdout.strip()


def _run_regression_attempt(wrapper: pathlib.Path, base_url: str, login_required: bool) -> str:
    session = f"front-porch-regress-{uuid.uuid4().hex[:8]}"
    success_condition = (
        "document.body.innerText.includes(\"Sign in and I’ll work the incumbent path and public ecosystem from there.\")"
        if login_required
        else "document.body.innerText.includes(\"The first vehicle picture is in hand.\") || document.body.innerText.includes(\"The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand.\")"
    )
    success_label = "ready" if login_required else "brief_open"
    regression_code = f"""
async (page) => {{
  await page.setViewportSize({{ width: 1440, height: 1200 }});
  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");

  const composer = page.getByLabel("Brief AXIOM");
  await composer.waitFor({{ state: "visible", timeout: 15000 }});
  await composer.fill("ILS 2 pre solicitation Amentum is prime");
  await composer.press("Enter");

  await page.waitForFunction(
    () => document.body.innerText.includes("Good. If this is a follow-on, do you know the incumbent prime?"),
    undefined,
    {{ timeout: 15000 }},
  );

  const bodyAfterQuestion = await page.evaluate(() => document.body.innerText);
  if (!/Confirming prime|Clarifying incumbent/.test(bodyAfterQuestion)) {{
    throw new Error("Front Porch did not show the clarifying-state cue while waiting on the prime answer");
  }}

  await composer.fill("Amentum");
  await composer.press("Enter");

  await page.waitForFunction(
    () => {success_condition},
    undefined,
    {{ timeout: 15000 }},
  );

  const finalBody = await page.evaluate(() => document.body.innerText);
  const repeatedQuestionCount = (finalBody.match(/Good\\. If this is a follow-on, do you know the incumbent prime\\?/g) || []).length;
  if (repeatedQuestionCount > 1) {{
    throw new Error("Front Porch repeated the incumbent-prime question instead of consuming the answer");
  }}

  return {{
    clarifying_state: "visible",
    handoff: {success_label!r},
  }};
}}
""".strip()

    with tempfile.TemporaryDirectory(prefix="front-porch-regression-") as tmp:
        cwd = pathlib.Path(tmp)
        try:
            _run_cli(wrapper, session, cwd, "open", base_url)
            return _run_cli(wrapper, session, cwd, "run-code", regression_code)
        finally:
            try:
                _run_cli(wrapper, session, cwd, "close")
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Front Porch browser regression against a live Helios host.")
    parser.add_argument("--base-url", required=True, help="Base URL to verify, for example https://helios.xiphosllc.com")
    parser.add_argument("--wrapper", default=str(DEFAULT_WRAPPER), help="Path to the Playwright CLI wrapper")
    args = parser.parse_args()

    wrapper = pathlib.Path(args.wrapper).expanduser()
    if not wrapper.exists():
        raise SystemExit(f"Playwright wrapper not found at {wrapper}")
    if shutil.which("npx") is None:
        raise SystemExit("npx is required for the Front Porch browser regression")

    base_url = args.base_url.rstrip("/")
    health_url = f"{base_url}/api/health"
    login_required = True
    try:
        with urllib.request.urlopen(health_url, timeout=20) as response:
            health_payload = json.loads(response.read().decode("utf-8"))
        login_required = bool(health_payload.get("login_required", True))
    except Exception:
        login_required = True
    last_error: Exception | None = None
    output = ""
    for _ in range(3):
        try:
            output = _run_regression_attempt(wrapper, base_url, login_required)
            last_error = None
            break
        except RuntimeError as exc:
            last_error = exc
            if "EADDRINUSE" not in str(exc):
                break
    if last_error is not None:
        raise last_error
    print("PASS: Front Porch browser regression")
    print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
