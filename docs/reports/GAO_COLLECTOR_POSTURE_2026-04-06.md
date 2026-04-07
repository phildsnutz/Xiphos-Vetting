# GAO Collector Posture

Date: 2026-04-06  
Scope: contract-vehicle protest and decision collection for Helios

## Bottom Line

GAO is publicly accessible, but in this environment the site blocks plain HTTP clients and allows a normal browser render.

That means the correct Helios posture is:

1. use seeded official GAO URLs
2. default to artifact-first operation
3. use browser render only as a local operator helper
4. capture the rendered artifact
5. parse the artifact locally
6. stop if access requires real anti-bot evasion

Helios should treat GAO as an **artifact-first, browser-assisted source**, not a plain `requests` scraper and not a guaranteed always-on autonomous collector.

## Allowed

These are inside the current collector-lab boundary:

- seeded official GAO docket or decision URLs only
- real browser transport such as Chromium or Playwright
- ordinary browser defaults:
  - normal user agent
  - normal viewport
  - normal language headers
  - normal JS execution
- low-volume retrieval
- storing rendered HTML, text, PDF, and metadata as replayable fixtures
- local parsing after capture
- analyst-provided HTML or PDF exports when live capture is unstable

## Light Stealth Boundary

If a little bit of stealth is used, it must stay inside this line:

- acceptable:
  - use a real browser instead of raw `requests`
  - set a standard desktop user agent
  - set a standard viewport and locale
  - wait for the page to finish rendering before capture
- not acceptable:
  - stealth plugins
  - navigator or WebGL spoofing
  - fingerprint randomization
  - proxy rotation
  - CAPTCHA solving
  - rate-limit evasion
  - session laundering
  - anti-bot bypass infrastructure

If a normal browser with normal defaults fails, Helios should not escalate into evasive infrastructure.

## Fallback Order

Best default fallback order:

1. rendered HTML
2. PDF
3. screenshot plus extracted text
4. analyst-provided export

Why:

- rendered HTML is best for structured field extraction on docket pages
- PDF is best for preservation and citation when GAO publishes a full written decision
- screenshot is weak for structured parsing but useful as a last-resort preservation artifact

Practical rule:

- for docket pages: prefer HTML first
- for written decisions: capture HTML first, and PDF too when available

## State Contract

GAO collector output should enter Helios as:

- `support_evidence` first
- not graph fact by default
- not first-turn routing input
- not tribunal authority by itself

Promotion to graph fact should require a later validation step.

## Implementation Rule

The GAO connector should:

1. accept seeded official GAO URLs
2. default to saved HTML or PDF artifacts when available
3. only attempt live browser-render capture when a local operator explicitly enables it
4. save raw artifact references
5. extract:
   - protester
   - agency
   - solicitation number
   - file number
   - outcome
   - filed date
   - due date
   - decision date
   - case type
   - attorney
6. parse decision-page narrative when present
7. fall back to saved HTML or PDF fixtures if live capture fails or is disabled

Current operator flag:

- `XIPHOS_ENABLE_GAO_BROWSER_CAPTURE=1`

Without that flag, the connector should return an honest “live capture disabled” message and continue supporting fixture or analyst-provided artifacts.

## Stop Condition

Stop and fall back to analyst-provided artifacts if:

- the page requires CAPTCHA
- repeated browser renders are blocked
- the site starts requiring brittle bypass behavior
- capture starts depending on evasive retries or transport tricks

## Product Effect

This posture is enough to improve:

- `Litigation & Protest Profile`
- vehicle dossier legal-read sections
- protest status visibility
- public decision narrative coverage

without creating anti-bot infrastructure debt.
