#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid


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

    session = f"front-porch-regress-{uuid.uuid4().hex[:8]}"
    base_url = args.base_url.rstrip("/")
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
    {{ timeout: 15000 }},
  );

  const bodyAfterQuestion = await page.evaluate(() => document.body.innerText);
  if (!/Confirming prime|Clarifying incumbent/.test(bodyAfterQuestion)) {{
    throw new Error("Front Porch did not show the clarifying-state cue while waiting on the prime answer");
  }}

  await composer.fill("Amentum");
  await composer.press("Enter");

  await page.waitForFunction(
    () => document.body.innerText.includes("Sign in and I’ll work the incumbent path and public ecosystem from there."),
    {{ timeout: 15000 }},
  );

  const finalBody = await page.evaluate(() => document.body.innerText);
  const repeatedQuestionCount = (finalBody.match(/Good\\. If this is a follow-on, do you know the incumbent prime\\?/g) || []).length;
  if (repeatedQuestionCount > 1) {{
    throw new Error("Front Porch repeated the incumbent-prime question instead of consuming the answer");
  }}

  return {{
    clarifying_state: "visible",
    handoff: "ready",
  }};
}}
""".strip()

    with tempfile.TemporaryDirectory(prefix="front-porch-regression-") as tmp:
        cwd = pathlib.Path(tmp)
        try:
            _run_cli(wrapper, session, cwd, "open", base_url)
            output = _run_cli(wrapper, session, cwd, "run-code", regression_code)
            print("PASS: Front Porch browser regression")
            print(output)
        finally:
            try:
                _run_cli(wrapper, session, cwd, "close")
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
