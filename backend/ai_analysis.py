"""
Xiphos AI Analysis Module v2.8

Multi-provider AI integration for generating risk narratives,
executive summaries, and intelligence assessments.

Supported providers:
  - anthropic (Claude Sonnet/Opus)
  - openai (GPT-4o / GPT-4o-mini)
  - gemini (Gemini 1.5 Pro / Flash)

API keys are stored encrypted per-user in SQLite. Each user can
configure their own provider and key, with an org-wide default
set by admins.

The AI layer is strictly additive -- it generates narratives and
insights but never overrides the deterministic scoring engine.
"""

import os
import json
import time
import sqlite3
import hashlib
import base64
import urllib.request
import urllib.error
import re
from dataclasses import dataclass
from typing import Optional
from runtime_paths import get_ai_config_secret, get_main_db_path


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PROMPT_DIRECTIVE_RE = re.compile(
    r"(?i)\b(ignore\s+previous|ignore\s+all|system:|assistant:|user:|developer:|"
    r"follow\s+these\s+instructions|return\s+valid\s+json|you\s+are\s+chatgpt)\b"
)
_WHITESPACE_RE = re.compile(r"\s+")
_CODE_FENCE_RE = re.compile(r"`{3,}")
_ANALYSIS_PROMPT_VERSION = os.environ.get("XIPHOS_AI_PROMPT_VERSION", "ai-analysis-2026-03-19")


def _sanitize_prompt_fragment(value: object, max_len: int = 160) -> str:
    text = str(value or "")
    text = _URL_RE.sub("[redacted]", text)
    text = _PROMPT_DIRECTIVE_RE.sub("[redacted]", text)
    text = _CODE_FENCE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


# ---- Provider Configuration ----

@dataclass
class AIProvider:
    name: str
    display_name: str
    models: list[str]
    default_model: str
    api_url: str
    max_tokens: int = 4096


PROVIDERS = {
    "anthropic": AIProvider(
        name="anthropic",
        display_name="Anthropic Claude",
        models=["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        default_model="claude-sonnet-4-6",
        api_url="https://api.anthropic.com/v1/messages",
        max_tokens=4096,
    ),
    "openai": AIProvider(
        name="openai",
        display_name="OpenAI",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        default_model="gpt-4o",
        api_url="https://api.openai.com/v1/chat/completions",
        max_tokens=4096,
    ),
    "gemini": AIProvider(
        name="gemini",
        display_name="Google Gemini",
        models=["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        default_model="gemini-1.5-pro",
        api_url="https://generativelanguage.googleapis.com/v1beta/models",
        max_tokens=4096,
    ),
}


# ---- API Key Storage (encrypted at rest) ----

def _get_cipher_key() -> bytes:
    """Derive an encryption key from XIPHOS_AI_CONFIG_KEY or XIPHOS_SECRET_KEY."""
    secret = get_ai_config_secret()
    if not secret:
        raise RuntimeError(
            "AI config encryption requires XIPHOS_AI_CONFIG_KEY or a non-placeholder "
            "XIPHOS_SECRET_KEY. Configure one before saving AI provider credentials."
        )
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), b"xiphos-ai-keys", 100_000)


def _encrypt_key(api_key: str) -> str:
    """Simple XOR encryption of API key. Not military-grade but prevents
    plaintext storage. For production, use Fernet or AWS KMS."""
    cipher = _get_cipher_key()
    key_bytes = api_key.encode("utf-8")
    encrypted = bytes(b ^ cipher[i % len(cipher)] for i, b in enumerate(key_bytes))
    return base64.b64encode(encrypted).decode("utf-8")


def _decrypt_key(encrypted: str) -> str:
    """Decrypt an API key."""
    cipher = _get_cipher_key()
    encrypted_bytes = base64.b64decode(encrypted)
    decrypted = bytes(b ^ cipher[i % len(cipher)] for i, b in enumerate(encrypted_bytes))
    return decrypted.decode("utf-8")


def init_ai_tables():
    """Create AI config, analysis cache, and async job tables."""
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_config (
            user_id     TEXT PRIMARY KEY,
            provider    TEXT NOT NULL DEFAULT 'anthropic',
            model       TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
            api_key_enc TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ai_analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id   TEXT NOT NULL,
            provider    TEXT NOT NULL,
            model       TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            elapsed_ms  INTEGER DEFAULT 0,
            analysis    JSON NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            created_by  TEXT,
            input_hash  TEXT,
            prompt_version TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ai_analyses_vendor ON ai_analyses(vendor_id);

        CREATE TABLE IF NOT EXISTS ai_analysis_jobs (
            id          TEXT PRIMARY KEY,
            case_id     TEXT NOT NULL,
            created_by  TEXT,
            input_hash  TEXT,
            status      TEXT NOT NULL DEFAULT 'pending',
            analysis_id INTEGER,
            error       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            started_at  TEXT,
            completed_at TEXT
        );
    """)
    for statement in (
        "ALTER TABLE ai_analyses ADD COLUMN created_by TEXT",
        "ALTER TABLE ai_analyses ADD COLUMN input_hash TEXT",
        "ALTER TABLE ai_analyses ADD COLUMN prompt_version TEXT",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN created_by TEXT",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN input_hash TEXT",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN analysis_id INTEGER",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN error TEXT",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN started_at TEXT",
        "ALTER TABLE ai_analysis_jobs ADD COLUMN completed_at TEXT",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_analyses_vendor_user_hash ON ai_analyses(vendor_id, created_by, input_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_jobs_case_user_hash ON ai_analysis_jobs(case_id, created_by, input_hash)"
    )
    conn.commit()
    conn.close()


def save_ai_config(user_id: str, provider: str, model: str, api_key: str):
    """Save (or update) a user's AI provider configuration."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}. Valid: {', '.join(PROVIDERS.keys())}")
    p = PROVIDERS[provider]
    if model not in p.models:
        raise ValueError(f"Unknown model for {provider}: {model}. Valid: {', '.join(p.models)}")

    encrypted = _encrypt_key(api_key)
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO ai_config (user_id, provider, model, api_key_enc, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            provider=excluded.provider,
            model=excluded.model,
            api_key_enc=excluded.api_key_enc,
            updated_at=datetime('now')
    """, (user_id, provider, model, encrypted))
    conn.commit()
    conn.close()


def get_ai_config(user_id: str) -> Optional[dict]:
    """Get a user's AI config. Returns None if not configured."""
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM ai_config WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        # Try org default (user_id = '__org_default__')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ai_config WHERE user_id = '__org_default__'").fetchone()
        conn.close()
    if not row:
        return None
    return {
        "provider": row["provider"],
        "model": row["model"],
        "api_key": _decrypt_key(row["api_key_enc"]),
    }


def delete_ai_config(user_id: str) -> bool:
    """Delete a user's AI config."""
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("DELETE FROM ai_config WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ---- Analysis Storage ----

def save_analysis(vendor_id: str, provider: str, model: str,
                  analysis: dict, prompt_tokens: int = 0,
                  completion_tokens: int = 0, elapsed_ms: int = 0,
                  created_by: str = "", input_hash: str = "",
                  prompt_version: str = _ANALYSIS_PROMPT_VERSION) -> int:
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        INSERT INTO ai_analyses
            (vendor_id, provider, model, prompt_tokens, completion_tokens,
             elapsed_ms, analysis, created_by, input_hash, prompt_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vendor_id, provider, model, prompt_tokens, completion_tokens,
          elapsed_ms, json.dumps(analysis), created_by, input_hash, prompt_version))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_latest_analysis(vendor_id: str, user_id: str = "", input_hash: str = "") -> Optional[dict]:
    db_path = get_main_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM ai_analyses WHERE vendor_id = ?"
    params: list[object] = [vendor_id]
    if user_id:
        query += " AND created_by = ?"
        params.append(user_id)
    if input_hash:
        query += " AND input_hash = ?"
        params.append(input_hash)
    query += " ORDER BY created_at DESC, id DESC LIMIT 1"

    row = conn.execute(query, params).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "vendor_id": row["vendor_id"],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "elapsed_ms": row["elapsed_ms"],
        "analysis": json.loads(row["analysis"]),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "input_hash": row["input_hash"],
        "prompt_version": row["prompt_version"],
    }


def compute_analysis_fingerprint(vendor_data: dict, score_data: dict, enrichment_data: Optional[dict] = None) -> str:
    sanitized_enrichment = _sanitize_enrichment_data(enrichment_data) or {}
    payload = {
        "vendor": {
            "id": vendor_data.get("id"),
            "name": vendor_data.get("name"),
            "country": vendor_data.get("country"),
            "program": vendor_data.get("program"),
        },
        "score": {
            "composite_score": score_data.get("composite_score"),
            "calibrated": score_data.get("calibrated", {}),
        },
        "enrichment": sanitized_enrichment,
        "prompt_version": _ANALYSIS_PROMPT_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# ---- Prompt Templates ----

RISK_ANALYSIS_PROMPT = """You are a defense acquisition intelligence analyst reviewing a vendor for compliance risk. Analyze the following vendor data and produce a structured risk assessment.

VENDOR: {vendor_name}
COUNTRY: {country}
PROGRAM: {program}

SCORING ENGINE OUTPUT:
- Composite Score: {composite_score}/100
- Risk Tier: {tier}
- Calibrated Probability: {probability}%
- Confidence Interval: [{interval_lo}%, {interval_hi}%]

HARD STOP DECISIONS:
{hard_stops}

SOFT FLAGS:
{soft_flags}

FACTOR CONTRIBUTIONS:
{contributions}

KEY FINDINGS:
{findings}

{enrichment_section}

Provide your analysis in the following JSON format:
{{
  "executive_summary": "2-3 sentence summary for a contracting officer",
  "risk_narrative": "Detailed paragraph explaining the risk profile and what drives it",
  "critical_concerns": ["List of specific concerns requiring immediate attention"],
  "mitigating_factors": ["List of factors that reduce risk, if any"],
  "recommended_actions": ["Specific due diligence steps the analyst should take"],
  "regulatory_exposure": "Assessment of ITAR, EAR, CFIUS, OFAC exposure",
  "confidence_assessment": "How confident are you in this analysis and what data gaps exist",
  "verdict": "APPROVE | CONDITIONAL_APPROVE | ENHANCED_DUE_DILIGENCE | REJECT"
}}

Be specific and cite the data provided. Do not hedge or use vague language. If the data clearly indicates a prohibition, say so directly."""


def _sanitize_enrichment_data(enrichment_data: Optional[dict]) -> Optional[dict]:
    """Sanitize enrichment data to prevent malformed JSON in prompt.

    Handles missing fields, malformed nested structures, and ensures
    all data is JSON-serializable and safe for embedding in prompts.
    """
    if not enrichment_data or not isinstance(enrichment_data, dict):
        return None

    try:
        sanitized = {}

        # Overall risk (string)
        overall_risk = enrichment_data.get('overall_risk', 'N/A')
        sanitized['overall_risk'] = str(overall_risk)[:50] if overall_risk else 'N/A'

        # Summary (dict or string)
        summary = enrichment_data.get('summary', {})
        if isinstance(summary, dict):
            # Extract findings_total if available
            sanitized['summary_findings'] = summary.get('findings_total', 0)
        else:
            sanitized['summary_findings'] = 0

        # Identifiers (dict or list)
        identifiers = enrichment_data.get('identifiers', {})
        if not isinstance(identifiers, dict):
            identifiers = {}
        # Keep only valid identifier entries
        sanitized['identifiers'] = {
            k: v for k, v in identifiers.items()
            if isinstance(k, str) and isinstance(v, (str, int, float, bool, type(None)))
        }

        # Findings (list)
        findings = enrichment_data.get('findings', [])
        if not isinstance(findings, list):
            findings = []
        # Safely extract top 10 findings
        sanitized['findings'] = []
        for f in findings[:10]:
            if isinstance(f, dict):
                sanitized['findings'].append({
                    'title': _sanitize_prompt_fragment(f.get('title', 'Unknown'), 100),
                    'severity': _sanitize_prompt_fragment(f.get('severity', 'info'), 20),
                    'source': _sanitize_prompt_fragment(f.get('source', 'Unknown'), 50),
                })

        return sanitized
    except Exception:
        # If any sanitization fails, return None to indicate insufficient enrichment data
        return None


def _build_prompt(vendor_data: dict, score_data: dict,
                  enrichment_data: Optional[dict] = None) -> str:
    """Build the analysis prompt from vendor and scoring data.

    Safely handles malformed or missing enrichment data by sanitizing before
    embedding in the prompt. Missing or malformed data results in a graceful
    "insufficient enrichment" note rather than a prompt formatting error.
    """
    cal = score_data.get("calibrated", {})

    hard_stops = "\n".join(
        f"  - {s['trigger']}: {s['explanation']}"
        for s in cal.get("hard_stop_decisions", []) if isinstance(s, dict)
    ) or "  None"

    soft_flags = "\n".join(
        f"  - {f['trigger']}: {f['explanation']}"
        for f in cal.get("soft_flags", []) if isinstance(f, dict)
    ) or "  None"

    contributions = "\n".join(
        f"  - {c['factor']}: raw={c['raw_score']:.2f}, contribution={c['signed_contribution']:+.4f} -- {c['description']}"
        for c in cal.get("contributions", []) if isinstance(c, dict)
    ) or "  None"

    findings = "\n".join(
        f"  - {f}" for f in cal.get("narratives", {}).get("findings", []) if isinstance(f, str)
    ) or "  None"

    enrichment_section = ""
    if enrichment_data:
        sanitized = _sanitize_enrichment_data(enrichment_data)
        if sanitized:
            try:
                findings_json = json.dumps(sanitized['findings'], indent=2)
                identifiers_json = json.dumps(sanitized['identifiers'], indent=2)
                enrichment_section = f"""
OSINT ENRICHMENT RESULTS:
- Overall Risk: {sanitized['overall_risk']}
- Total Findings: {sanitized['summary_findings']}
- Identifiers Found: {identifiers_json}
- Top Findings: {findings_json}
"""
            except Exception:
                # If JSON serialization still fails, provide minimal enrichment info
                enrichment_section = f"""
OSINT ENRICHMENT RESULTS:
- Overall Risk: {sanitized.get('overall_risk', 'N/A')}
- Total Findings: {sanitized.get('summary_findings', 0)}
- Status: Enrichment data available but detailed analysis could not be generated
"""
        else:
            enrichment_section = """
OSINT ENRICHMENT RESULTS:
- Status: Enrichment data format error -- insufficient data for detailed analysis
"""

    return RISK_ANALYSIS_PROMPT.format(
        vendor_name=vendor_data.get("name", "Unknown"),
        country=vendor_data.get("country", "Unknown"),
        program=vendor_data.get("program", "standard_industrial"),
        composite_score=score_data.get("composite_score", 0),
        tier=cal.get("calibrated_tier", "unknown"),
        probability=round(cal.get("calibrated_probability", 0) * 100, 1),
        interval_lo=round(cal.get("interval", {}).get("lower", 0) * 100, 1),
        interval_hi=round(cal.get("interval", {}).get("upper", 0) * 100, 1),
        hard_stops=hard_stops,
        soft_flags=soft_flags,
        contributions=contributions,
        findings=findings,
        enrichment_section=enrichment_section,
    )


# ---- Provider API Calls ----

def _call_anthropic(api_key: str, model: str, prompt: str) -> dict:
    """Call Claude API."""
    payload = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=120)
    body = json.loads(resp.read().decode("utf-8"))

    text = body["content"][0]["text"]
    usage = body.get("usage", {})

    return {
        "text": text,
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
    }


def _call_openai(api_key: str, model: str, prompt: str) -> dict:
    """Call OpenAI API."""
    payload = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": "You are a defense acquisition intelligence analyst. Respond only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=120)
    body = json.loads(resp.read().decode("utf-8"))

    text = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})

    return {
        "text": text,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


def _call_gemini(api_key: str, model: str, prompt: str) -> dict:
    """Call Google Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=120)
    body = json.loads(resp.read().decode("utf-8"))

    text = body["candidates"][0]["content"]["parts"][0]["text"]
    usage = body.get("usageMetadata", {})

    return {
        "text": text,
        "prompt_tokens": usage.get("promptTokenCount", 0),
        "completion_tokens": usage.get("candidatesTokenCount", 0),
    }


PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


def _parse_analysis_json(text: str) -> dict:
    """Extract JSON from AI response, handling markdown code blocks."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        # Return raw text as fallback
        return {
            "executive_summary": text[:500],
            "risk_narrative": text,
            "critical_concerns": [],
            "mitigating_factors": [],
            "recommended_actions": [],
            "regulatory_exposure": "Unable to parse structured response",
            "confidence_assessment": "Low -- response could not be parsed as JSON",
            "verdict": "ENHANCED_DUE_DILIGENCE",
            "_raw_response": text,
            "_parse_error": True,
        }


# ---- Main Analysis Function ----

def analyze_vendor(
    user_id: str,
    vendor_data: dict,
    score_data: dict,
    enrichment_data: Optional[dict] = None,
) -> dict:
    """
    Run AI analysis on a vendor using the user's configured provider.

    Gracefully handles missing or malformed enrichment data. If enrichment cannot
    be safely included in the prompt, analysis proceeds with baseline data only
    and returns a clear status in the response.

    Returns:
        {
            "analysis": { ... structured analysis ... },
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "prompt_tokens": 1234,
            "completion_tokens": 567,
            "elapsed_ms": 3456,
            "enrichment_status": "partial" or "none" (optional, only if issues)
        }
    """
    # Validate vendor data
    if not isinstance(vendor_data, dict):
        raise ValueError("vendor_data must be a dictionary")
    if not isinstance(score_data, dict):
        raise ValueError("score_data must be a dictionary")

    # Validate that score has required structure
    if "calibrated" not in score_data:
        raise ValueError("score_data must contain 'calibrated' field. Score the vendor first.")
    if score_data.get("composite_score") is None:
        raise ValueError("score_data must contain 'composite_score' field. Score the vendor first.")

    config = get_ai_config(user_id)
    if not config:
        raise ValueError(
            "No AI provider configured. Set up your API key in Settings > AI Provider."
        )

    provider = config["provider"]
    model = config["model"]
    api_key = config["api_key"]

    if provider not in PROVIDER_CALLERS:
        raise ValueError(f"Unknown provider: {provider}")

    # Build prompt with graceful enrichment data handling
    try:
        prompt = _build_prompt(vendor_data, score_data, enrichment_data)
    except Exception as e:
        raise ValueError(f"Failed to build analysis prompt: {str(e)}")

    caller = PROVIDER_CALLERS[provider]
    start_ms = time.time()

    try:
        result = caller(api_key, model, prompt)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(
            f"{provider} API error (HTTP {e.code}): {error_body}"
        )
    except Exception as e:
        raise ValueError(f"{provider} API call failed: {str(e)}")

    elapsed_ms = int((time.time() - start_ms) * 1000)

    # Parse response
    try:
        analysis = _parse_analysis_json(result["text"])
    except Exception as e:
        raise ValueError(f"Failed to parse AI response: {str(e)}")

    # Persist the analysis
    vendor_id = vendor_data.get("id", "unknown")
    input_hash = compute_analysis_fingerprint(vendor_data, score_data, enrichment_data)
    analysis_id = None
    try:
        analysis_id = save_analysis(
            vendor_id=vendor_id,
            provider=provider,
            model=model,
            analysis=analysis,
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            elapsed_ms=elapsed_ms,
            created_by=user_id,
            input_hash=input_hash,
            prompt_version=_ANALYSIS_PROMPT_VERSION,
        )
    except Exception as e:
        # Log but don't fail the entire analysis if persistence fails
        print(f"Warning: Failed to persist AI analysis for {vendor_id}: {str(e)}")

    return {
        "analysis": analysis,
        "provider": provider,
        "model": model,
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "elapsed_ms": elapsed_ms,
        "analysis_id": analysis_id,
        "input_hash": input_hash,
        "prompt_version": _ANALYSIS_PROMPT_VERSION,
    }


def get_available_providers() -> list[dict]:
    """Return list of available providers and their models."""
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "models": p.models,
            "default_model": p.default_model,
        }
        for p in PROVIDERS.values()
    ]
