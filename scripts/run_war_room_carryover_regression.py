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
import urllib.request
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
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


def _health_payload(base_url: str) -> dict:
    health_url = f"{base_url.rstrip('/')}/api/health"
    with urllib.request.urlopen(health_url, timeout=20) as response:
        body = response.read()
    return json.loads(body.decode("utf-8")) if body else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the War Room carried-brief browser regression.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--wrapper", default=str(DEFAULT_WRAPPER))
    args = parser.parse_args()

    wrapper = pathlib.Path(args.wrapper).expanduser()
    if not wrapper.exists():
        raise SystemExit(f"Playwright wrapper not found at {wrapper}")
    if shutil.which("npx") is None:
        raise SystemExit("npx is required for the War Room browser regression")

    base_url = args.base_url.rstrip("/")
    health = _health_payload(base_url)
    login_required = bool(health.get("login_required", True))
    if login_required and (not args.email or not args.password):
        raise SystemExit("War Room carryover regression requires --email and --password when login is enabled")

    session = f"war-room-regress-{uuid.uuid4().hex[:8]}"
    if login_required:
        auth_block = f"""
  const dialog = page.getByText("Sign in to continue");
  await dialog.waitFor({{ state: "visible", timeout: 15000 }});
  await page.getByLabel("Email").fill({args.email!r});
  await page.getByLabel("Password").fill({args.password!r});
  await page.getByRole("button", {{ name: "Continue" }}).click();
  await page.waitForFunction(
    () => document.body.innerText.includes("Take into War Room"),
    undefined,
    {{ timeout: 20000 }},
  );
""".rstrip()
    else:
        auth_block = """
  await page.waitForFunction(
    () => document.body.innerText.includes("Take into War Room"),
    undefined,
    { timeout: 20000 },
  );
""".rstrip()

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
  await composer.fill("Amentum");
  await composer.press("Enter");

{auth_block}

  const takeIntoWarRoom = page.getByRole("button", {{ name: "Take into War Room" }});
  await takeIntoWarRoom.waitFor({{ state: "visible", timeout: 15000 }});
  await takeIntoWarRoom.click();

  await page.waitForFunction(
    () => document.body.innerText.includes("Brief carried from Front Porch") && document.body.innerText.includes("War Room"),
    undefined,
    {{ timeout: 15000 }},
  );

  const finalBody = await page.evaluate(() => document.body.innerText);
  if (!finalBody.toLowerCase().includes("axiom exchange")) {{
    throw new Error(`War Room did not render the AXIOM exchange after carryover. Body was: ${{finalBody}}`);
  }}

  return {{
    carryover: "passed",
    login_required: {str(login_required).lower()},
  }};
}}
""".strip()

    with tempfile.TemporaryDirectory(prefix="war-room-regression-") as tmp:
        cwd = pathlib.Path(tmp)
        try:
            _run_cli(wrapper, session, cwd, "open", base_url)
            output = _run_cli(wrapper, session, cwd, "run-code", regression_code)
            print("PASS: War Room carryover regression")
            print(output)
        finally:
            try:
                _run_cli(wrapper, session, cwd, "close")
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
