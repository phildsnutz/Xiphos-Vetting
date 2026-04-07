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


def _run_regression_attempt(wrapper: pathlib.Path, base_url: str, *, login_required: bool, email: str, password: str) -> str:
    session = f"war-room-regress-{uuid.uuid4().hex[:8]}"
    if login_required:
        auth_block = f"""
  const authResult = await page.evaluate(async (credentials) => {{
    const response = await fetch("/api/auth/login", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(credentials),
    }});
    const payload = await response.json().catch(() => ({{ error: `HTTP ${{response.status}}` }}));
    if (response.ok && payload.token && payload.user) {{
      sessionStorage.setItem("helios_token", payload.token);
      sessionStorage.setItem("helios_user", JSON.stringify(payload.user));
      return {{ ok: true }};
    }}
    return {{ ok: false, error: payload.error || `HTTP ${{response.status}}` }};
  }}, {{ email: {email!r}, password: {password!r} }});
  if (!authResult.ok) {{
    throw new Error(`Login bootstrap failed: ${{authResult.error || "unknown error"}}`);
  }}

  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");
""".rstrip()
    else:
        auth_block = ""

    regression_code = f"""
async (page) => {{
  await page.setViewportSize({{ width: 1440, height: 1200 }});
  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");

{auth_block}

  await page.getByText("What are you looking at?").waitFor({{ state: "visible", timeout: 15000 }});
  await page.getByRole("button", {{ name: /^Vehicle/i }}).first().click();
  const composer = page.getByLabel("Vehicle name");
  await composer.waitFor({{ state: "visible", timeout: 45000 }});
  await composer.fill("ILS 2 pre solicitation Amentum is prime");
  await composer.press("Enter");
  await page.waitForFunction(
    () => (
      document.body.innerText.includes("Enter Aegis")
      || document.body.innerText.includes("Open brief")
      || document.body.innerText.includes("The first vehicle picture is in hand.")
      || document.body.innerText.includes("The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand.")
      || document.body.innerText.includes("Is this current, expired, or still in pre-solicitation?")
      || document.body.innerText.includes("Good. If this is a follow-on, do you know the incumbent prime?")
    ),
    undefined,
    {{ timeout: 60000 }},
  );

  let intakeBody = await page.evaluate(() => document.body.innerText);
  if (intakeBody.includes("Is this current, expired, or still in pre-solicitation?")) {{
    await composer.fill("pre solicitation");
    await composer.press("Enter");
    await page.waitForFunction(
      () => (
        document.body.innerText.includes("Enter Aegis")
        || document.body.innerText.includes("Open brief")
        || document.body.innerText.includes("The first vehicle picture is in hand.")
        || document.body.innerText.includes("The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand.")
        || document.body.innerText.includes("Good. If this is a follow-on, do you know the incumbent prime?")
      ),
      undefined,
      {{ timeout: 60000 }},
    );
    intakeBody = await page.evaluate(() => document.body.innerText);
  }}

  if (intakeBody.includes("Good. If this is a follow-on, do you know the incumbent prime?")) {{
    await composer.fill("Amentum");
    await composer.press("Enter");
    await page.waitForFunction(
      () => (
        document.body.innerText.includes("Enter Aegis")
        || document.body.innerText.includes("Open brief")
        || document.body.innerText.includes("The first vehicle picture is in hand.")
        || document.body.innerText.includes("The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand.")
      ),
      undefined,
      {{ timeout: 60000 }},
    );
  }}

  const enterAegisButton = page.getByRole("button", {{ name: "Enter Aegis" }});
  await enterAegisButton.waitFor({{ state: "visible", timeout: 20000 }});
  await enterAegisButton.click();

  await page.waitForFunction(
    () => (
      document.body.innerText.includes("Brief carried from Stoa")
      && document.body.innerText.includes("Exit Aegis")
      && document.body.innerText.toLowerCase().includes("axiom exchange")
    ),
    undefined,
    {{ timeout: 45000 }},
  );

  const finalBody = await page.evaluate(() => document.body.innerText);
  if (!finalBody.toLowerCase().includes("axiom exchange")) {{
    throw new Error(`Aegis did not render the AXIOM exchange after carryover. Body was: ${{finalBody}}`);
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
            return _run_cli(wrapper, session, cwd, "run-code", regression_code)
        finally:
            try:
                _run_cli(wrapper, session, cwd, "close")
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Aegis carried-brief browser regression.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--wrapper", default=str(DEFAULT_WRAPPER))
    args = parser.parse_args()

    wrapper = pathlib.Path(args.wrapper).expanduser()
    if not wrapper.exists():
        raise SystemExit(f"Playwright wrapper not found at {wrapper}")
    if shutil.which("npx") is None:
        raise SystemExit("npx is required for the Aegis browser regression")

    base_url = args.base_url.rstrip("/")
    health = _health_payload(base_url)
    login_required = bool(health.get("login_required", True))
    if login_required and (not args.email or not args.password):
        raise SystemExit("Aegis carryover regression requires --email and --password when login is enabled")

    last_error: Exception | None = None
    output = ""
    for _ in range(3):
        try:
            output = _run_regression_attempt(
                wrapper,
                base_url,
                login_required=login_required,
                email=args.email,
                password=args.password,
            )
            last_error = None
            break
        except RuntimeError as exc:
            last_error = exc
            if "EADDRINUSE" not in str(exc):
                break
    if last_error is not None:
        raise last_error
    print("PASS: Aegis carryover regression")
    print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
