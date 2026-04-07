"""Minimal browser-render helper for public-page collectors."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def capture_rendered_html(
    url: str,
    *,
    timeout_ms: int = 30_000,
    wait_ms: int = 1_000,
) -> tuple[str, str]:
    """Return rendered HTML and final URL for a public page.

    The transport intentionally stays boring:
      - standard Chromium
      - standard user agent and locale
      - no stealth plugin or fingerprint spoofing
    """

    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        return path.read_text(encoding="utf-8"), url

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local tool install
        raise RuntimeError(
            "Playwright is required for live browser-render collectors. "
            "Install it with `python3 -m pip install playwright && python3 -m playwright install chromium`."
        ) from exc

    try:
        with sync_playwright() as pw:
            attempts = (
                {"headless": True, "channel": "chrome"},
                {"headless": True},
            )
            last_error: Exception | None = None
            for launch_kwargs in attempts:
                browser = None
                context = None
                try:
                    browser = pw.chromium.launch(**launch_kwargs)
                    context = browser.new_context(
                        user_agent=DEFAULT_USER_AGENT,
                        locale="en-US",
                        viewport={"width": 1440, "height": 1100},
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if wait_ms > 0:
                        page.wait_for_timeout(wait_ms)
                    html = page.content()
                    final_url = page.url
                    context.close()
                    browser.close()
                    return html, final_url
                except Exception as exc:
                    last_error = exc
                    if context is not None:
                        context.close()
                    if browser is not None:
                        browser.close()
            raise RuntimeError(str(last_error or "unknown browser render failure"))
    except Exception as exc:  # pragma: no cover - depends on local browser runtime
        raise RuntimeError(f"Browser render failed for {url}: {exc}") from exc
