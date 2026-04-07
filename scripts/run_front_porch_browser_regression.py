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
    if login_required:
        regression_code = f"""
async (page) => {{
  await page.setViewportSize({{ width: 1440, height: 1200 }});
  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");

  await page.getByText("What are you looking at?").waitFor({{ state: "visible", timeout: 15000 }});
  await page.getByRole("button", {{ name: /^Vehicle/i }}).first().click();

  await page.waitForFunction(
    () => document.body.innerText.includes("Sign in to start the assessment"),
    undefined,
    {{ timeout: 15000 }},
  );

  const vehicleGateBody = await page.evaluate(() => document.body.innerText);
  if (vehicleGateBody.includes("Vehicle name")) {{
    throw new Error("Vehicle composer rendered before authentication");
  }}

  await page.getByRole("button", {{ name: "Change" }}).click();
  await page.getByRole("button", {{ name: /^Vendor/i }}).first().click();

  await page.waitForFunction(
    () => document.body.innerText.includes("Sign in to start the assessment"),
    undefined,
    {{ timeout: 15000 }},
  );

  const vendorGateBody = await page.evaluate(() => document.body.innerText);
  if (vendorGateBody.includes("Vendor name")) {{
    throw new Error("Vendor composer rendered before authentication");
  }}

  return {{
    auth_gate: "inline",
    vehicle_gate: vehicleGateBody.includes("Sign in to start the assessment"),
    vendor_gate: vendorGateBody.includes("Sign in to start the assessment"),
  }};
}}
""".strip()
    else:
        regression_code = f"""
async (page) => {{
  const waitForChooser = async () => {{
    await page.getByText("What are you looking at?").waitFor({{ state: "visible", timeout: 15000 }});
  }};

  const chooseMode = async (modeLabel, composerLabel) => {{
    await waitForChooser();
    await page.getByRole("button", {{ name: new RegExp(`^${{modeLabel}}`, "i") }}).first().click();
    const composer = page.getByLabel(composerLabel);
    await composer.waitFor({{ state: "visible", timeout: 15000 }});
    return composer;
  }};

  const vehicleSuccess = () => {{
    const text = document.body.innerText;
    return text.includes("The first vehicle picture is in hand.")
      || text.includes("The live vehicle search stayed thin, so I opened the first vehicle picture from the context already in hand.");
  }};

  await page.setViewportSize({{ width: 1440, height: 1200 }});

  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");
  const leiaComposer = await chooseMode("Vehicle", "Vehicle name");
  await leiaComposer.fill("LEIA");
  await leiaComposer.press("Enter");
  await page.waitForFunction(
    () => document.body.innerText.includes("Is this current, expired, or still in pre-solicitation?"),
    undefined,
    {{ timeout: 15000 }},
  );
  const afterLeia = await page.evaluate(() => document.body.innerText);
  if (afterLeia.includes("AXIOM has a few plausible entities in frame.")) {{
    throw new Error("Stoa fell into entity narrowing on LEIA after the operator selected Vehicle");
  }}
  if (afterLeia.includes("Which one do you mean?")) {{
    throw new Error("Stoa still asked an object-type clarifier after the operator selected Vehicle");
  }}

  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");
  const iteamsComposer = await chooseMode("Vehicle", "Vehicle name");
  await iteamsComposer.fill("ITEAMS");
  await iteamsComposer.press("Enter");
  await page.waitForFunction(
    () => document.body.innerText.includes("Is this current, expired, or still in pre-solicitation?"),
    undefined,
    {{ timeout: 15000 }},
  );
  const afterIteams = await page.evaluate(() => document.body.innerText);
  if (afterIteams.includes("AXIOM has a few plausible entities in frame.")) {{
    throw new Error("Stoa treated ITEAMS like a vendor-style intake after the operator selected Vehicle");
  }}
  if (afterIteams.includes("I found a clean entity match on") || afterIteams.includes("I found a few plausible matches.")) {{
    throw new Error("Stoa entered the vendor branch for ITEAMS after the operator selected Vehicle");
  }}

  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");
  const smxComposer = await chooseMode("Vendor", "Vendor name");
  await smxComposer.fill("SMX");
  await smxComposer.press("Enter");
  await page.waitForFunction(
    () => {{
      const text = document.body.innerText;
      return text.includes("I found a few plausible matches.")
        || text.includes("I found a clean entity match on")
        || text.includes("The entity resolution is still thin, but that is not a blocker.")
        || text.includes("I believe you mean ");
    }},
    undefined,
    {{ timeout: 15000 }},
  );
  const afterSmx = await page.evaluate(() => document.body.innerText);
  if (afterSmx.includes("Is this current, expired, or still in pre-solicitation?")) {{
    throw new Error("Stoa routed SMX into the contract-vehicle branch after the operator selected Vendor");
  }}

  await page.goto({base_url!r}, {{ waitUntil: "domcontentloaded" }});
  await page.waitForLoadState("networkidle");
  const ilsComposer = await chooseMode("Vehicle", "Vehicle name");
  await ilsComposer.fill("ILS 2 pre solicitation Amentum is prime");
  await ilsComposer.press("Enter");
  await page.waitForFunction(vehicleSuccess, undefined, {{ timeout: 15000 }});
  const finalBody = await page.evaluate(() => document.body.innerText);
  if (finalBody.includes("AXIOM has a few plausible entities in frame.")) {{
    throw new Error("Stoa slipped back into entity narrowing on the explicit vehicle path");
  }}

  return {{
    auth_gate: "not_required",
    leia_path: "vehicle_first",
    iteams_path: "vehicle_first",
    smx_path: "vendor_first",
    handoff: "brief_open",
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
    parser = argparse.ArgumentParser(description="Run the Stoa browser regression against a live Helios host.")
    parser.add_argument("--base-url", required=True, help="Base URL to verify, for example https://helios.xiphosllc.com")
    parser.add_argument("--wrapper", default=str(DEFAULT_WRAPPER), help="Path to the Playwright CLI wrapper")
    args = parser.parse_args()

    wrapper = pathlib.Path(args.wrapper).expanduser()
    if not wrapper.exists():
        raise SystemExit(f"Playwright wrapper not found at {wrapper}")
    if shutil.which("npx") is None:
        raise SystemExit("npx is required for the Stoa browser regression")

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
    print("PASS: Stoa browser regression")
    print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
