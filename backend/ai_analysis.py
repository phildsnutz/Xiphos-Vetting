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
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from runtime_paths import get_ai_config_secret, get_main_db_path
import db


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PROMPT_DIRECTIVE_RE = re.compile(
    r"(?i)\b(ignore\s+previous|ignore\s+all|system:|assistant:|user:|developer:|"
    r"follow\s+these\s+instructions|return\s+valid\s+json|you\s+are\s+chatgpt)\b"
)
_WHITESPACE_RE = re.compile(r"\s+")
_CODE_FENCE_RE = re.compile(r"`{3,}")
_ANALYSIS_PROMPT_VERSION = os.environ.get("XIPHOS_AI_PROMPT_VERSION", "ai-analysis-2026-03-27")
_LOCAL_FALLBACK_MODEL = "heuristic-v1"
logger = logging.getLogger(__name__)


class AIProviderTemporaryError(ValueError):
    """Transient upstream failure. Caller should retry or keep warming."""


class AIProviderPermanentError(ValueError):
    """Non-transient upstream or validation failure."""


def _sanitize_prompt_fragment(value: object, max_len: int = 160) -> str:
    text = str(value or "")
    text = _URL_RE.sub("[redacted]", text)
    text = _PROMPT_DIRECTIVE_RE.sub("[redacted]", text)
    text = _CODE_FENCE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _load_json_field(value: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return {}
    return json.loads(str(value))


def _local_fallback_enabled() -> bool:
    return os.environ.get("XIPHOS_LOCAL_AI_FALLBACK", "true").lower() != "false"


def _classify_provider_http_error(provider: str, error: urllib.error.HTTPError) -> ValueError:
    error_body = error.read().decode("utf-8", errors="replace")[:500]
    message = f"{provider} API error (HTTP {error.code}): {error_body}"
    if error.code in {408, 409, 425, 429, 500, 502, 503, 504, 529}:
        return AIProviderTemporaryError(message)
    return AIProviderPermanentError(message)


def _classify_provider_exception(provider: str, error: Exception) -> ValueError:
    message = f"{provider} API call failed: {str(error)}"
    lowered = message.lower()
    transient_markers = (
        "timeout",
        "temporar",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "service unavailable",
        "overloaded",
        "unstable",
        "rate limit",
        "too many requests",
        "remote end closed connection",
    )
    if isinstance(error, TimeoutError) or any(marker in lowered for marker in transient_markers):
        return AIProviderTemporaryError(message)
    return AIProviderPermanentError(message)


def _analysis_verdict_for_tier(tier: str) -> str:
    normalized = str(tier or "").upper()
    if normalized.startswith("TIER_1"):
        return "REJECT"
    if normalized in {"TIER_2_CONDITIONAL_ACCEPTABLE", "TIER_3_CONDITIONAL"}:
        return "CONDITIONAL_APPROVE"
    if normalized.startswith("TIER_2") or normalized.startswith("TIER_3"):
        return "ENHANCED_DUE_DILIGENCE"
    return "APPROVE"


def _build_local_fallback_analysis(
    vendor_data: dict,
    score_data: dict,
    enrichment_data: Optional[dict] = None,
    *,
    fallback_reason: str = "",
) -> dict:
    """Build a deterministic narrative when no external AI provider is configured."""
    vendor_name = str(vendor_data.get("name") or "Unknown vendor")
    country = str(vendor_data.get("country") or "unknown")
    calibrated = score_data.get("calibrated") or {}
    tier = str(
        calibrated.get("calibrated_tier")
        or score_data.get("tier")
        or score_data.get("calibrated_tier")
        or "UNSCORED"
    )
    probability = float(calibrated.get("calibrated_probability") or 0.0)
    composite_score = int(score_data.get("composite_score") or 0)
    verdict = _analysis_verdict_for_tier(tier)

    hard_stops = score_data.get("hard_stop_decisions") or []
    soft_flags = score_data.get("soft_flags") or []
    findings = (enrichment_data or {}).get("findings") or []

    critical_concerns: list[str] = []
    for stop in hard_stops[:3]:
        trigger = _sanitize_prompt_fragment(stop.get("trigger") or "Hard stop", max_len=120)
        explanation = _sanitize_prompt_fragment(stop.get("explanation") or "", max_len=220)
        critical_concerns.append(f"{trigger}: {explanation}".strip(": "))

    if not critical_concerns:
        for flag in soft_flags[:3]:
            trigger = _sanitize_prompt_fragment(flag.get("trigger") or "Risk flag", max_len=120)
            explanation = _sanitize_prompt_fragment(flag.get("explanation") or "", max_len=220)
            critical_concerns.append(f"{trigger}: {explanation}".strip(": "))

    if len(critical_concerns) < 3:
        for finding in findings:
            severity = str(finding.get("severity") or "").lower()
            if severity not in {"critical", "high", "medium"}:
                continue
            title = _sanitize_prompt_fragment(finding.get("title") or finding.get("signal") or "Material finding", max_len=140)
            detail = _sanitize_prompt_fragment(finding.get("detail") or "", max_len=220)
            item = f"{title}: {detail}".strip(": ")
            if item and item not in critical_concerns:
                critical_concerns.append(item)
            if len(critical_concerns) >= 3:
                break

    mitigating_factors: list[str] = []
    ownership = vendor_data.get("ownership") or {}
    data_quality = vendor_data.get("data_quality") or {}
    exec_profile = vendor_data.get("exec") or {}
    if ownership.get("beneficial_owner_known"):
        mitigating_factors.append("Beneficial ownership is resolved in the submitted case data.")
    if ownership.get("publicly_traded"):
        mitigating_factors.append("Public-company status improves transparency and external verification.")
    if int(data_quality.get("years_of_records") or 0) >= 5:
        mitigating_factors.append("Operating history is long enough to support baseline diligence review.")
    if bool(data_quality.get("has_lei")) and bool(data_quality.get("has_cage")):
        mitigating_factors.append("Core corporate identifiers are present for follow-on verification.")
    if int(exec_profile.get("adverse_media") or 0) == 0:
        mitigating_factors.append("No adverse-media signal is present in the structured executive profile.")

    recommended_actions: list[str] = []
    if verdict == "REJECT":
        recommended_actions.append("Do not proceed until the blocking hard-stop signals are resolved by counsel or compliance leadership.")
    elif verdict == "ENHANCED_DUE_DILIGENCE":
        recommended_actions.append("Escalate for analyst review and document why the current risk posture is acceptable or not.")
    else:
        recommended_actions.append("Proceed only after confirming the current score and evidence package remain fresh.")

    export_auth = vendor_data.get("export_authorization") or {}
    if export_auth:
        recommended_actions.append(
            f"Validate {str(export_auth.get('jurisdiction_guess') or 'export').upper()} handling for "
            f"{_sanitize_prompt_fragment(export_auth.get('destination_country') or 'the destination', max_len=32)} "
            "before release or access."
        )
    if findings:
        recommended_actions.append("Review the highest-severity enrichment findings and capture disposition notes in the case record.")
    if not findings:
        recommended_actions.append("Run fresh enrichment before relying on this narrative for an external-facing decision.")

    recommended_actions = recommended_actions[:4]
    critical_concerns = critical_concerns[:5]
    mitigating_factors = mitigating_factors[:5]

    regulatory_bits = [f"Tier {tier}", f"country {country}", f"composite score {composite_score}"]
    if export_auth:
        jurisdiction = str(export_auth.get("jurisdiction_guess") or "").upper()
        classification = _sanitize_prompt_fragment(export_auth.get("classification_guess") or "", max_len=40)
        destination = _sanitize_prompt_fragment(export_auth.get("destination_country") or "", max_len=32)
        if jurisdiction:
            regulatory_bits.append(f"jurisdiction {jurisdiction}")
        if classification:
            regulatory_bits.append(f"classification {classification}")
        if destination:
            regulatory_bits.append(f"destination {destination}")

    summary_open = (
        f"{vendor_name} currently sits at {tier} with calibrated probability {probability:.1%} "
        f"and composite score {composite_score}."
    )
    if critical_concerns:
        summary_open += f" Primary analyst attention areas are {critical_concerns[0].lower()}."
    else:
        summary_open += " No material critical concerns were surfaced beyond the deterministic model inputs."

    confidence_tail = (
        "Moderate. This is a deterministic local fallback narrative built from the current case, score, "
        "and enrichment data because no external AI provider is configured."
    )
    if fallback_reason:
        confidence_tail = (
            "Moderate. This is a deterministic local fallback narrative built from the current case, score, "
            f"and enrichment data because the external AI provider failed: {fallback_reason}."
        )

    return {
        "executive_summary": summary_open,
        "risk_narrative": (
            f"Local fallback narrative generated because "
            f"{'the external AI provider failed' if fallback_reason else 'no external AI provider is configured'}. "
            f"This case is assessed for {vendor_name} in {country} using the deterministic scoring engine and "
            f"the current evidence package, which places the matter in {tier} with verdict {verdict.replace('_', ' ').title()}."
        ),
        "critical_concerns": critical_concerns,
        "mitigating_factors": mitigating_factors,
        "recommended_actions": recommended_actions,
        "regulatory_exposure": "; ".join(regulatory_bits) + ".",
        "confidence_assessment": confidence_tail,
        "verdict": verdict,
        "_fallback": True,
    }


def _persist_local_fallback_result(
    *,
    user_id: str,
    vendor_data: dict,
    score_data: dict,
    enrichment_data: Optional[dict],
    input_hash: str,
    fallback_reason: str = "",
) -> dict:
    analysis = _build_local_fallback_analysis(
        vendor_data,
        score_data,
        enrichment_data,
        fallback_reason=fallback_reason,
    )
    vendor_id = vendor_data.get("id", "unknown")
    analysis_id = None
    try:
        analysis_id = save_analysis(
            vendor_id=vendor_id,
            provider="local_fallback",
            model=_LOCAL_FALLBACK_MODEL,
            analysis=analysis,
            prompt_tokens=0,
            completion_tokens=0,
            elapsed_ms=0,
            created_by=user_id,
            input_hash=input_hash,
            prompt_version=_ANALYSIS_PROMPT_VERSION,
        )
    except Exception as e:
        print(f"Warning: Failed to persist local fallback AI analysis for {vendor_id}: {str(e)}")

    return {
        "analysis": analysis,
        "provider": "local_fallback",
        "model": _LOCAL_FALLBACK_MODEL,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "elapsed_ms": 0,
        "analysis_id": analysis_id,
        "input_hash": input_hash,
        "prompt_version": _ANALYSIS_PROMPT_VERSION,
    }


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


def _get_fernet():
    """Get a Fernet instance derived from the cipher key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    raw_key = _get_cipher_key()
    # Fernet requires a 32-byte url-safe base64 key
    fernet_key = base64.urlsafe_b64encode(raw_key[:32])
    return Fernet(fernet_key)


def _encrypt_key(api_key: str) -> str:
    """Encrypt API key using Fernet (authenticated encryption).
    Falls back to XOR if cryptography library is unavailable."""
    fernet = _get_fernet()
    if fernet:
        token = fernet.encrypt(api_key.encode("utf-8"))
        return "fernet:" + token.decode("utf-8")
    # Fallback: XOR (legacy, will be migrated on next save)
    cipher = _get_cipher_key()
    key_bytes = api_key.encode("utf-8")
    encrypted = bytes(b ^ cipher[i % len(cipher)] for i, b in enumerate(key_bytes))
    return base64.b64encode(encrypted).decode("utf-8")


def _decrypt_key(encrypted: str) -> str:
    """Decrypt an API key. Supports both Fernet and legacy XOR format."""
    if encrypted.startswith("fernet:"):
        fernet = _get_fernet()
        if not fernet:
            raise RuntimeError("cryptography library required to decrypt Fernet-encrypted keys")
        token = encrypted[7:].encode("utf-8")
        return fernet.decrypt(token).decode("utf-8")
    # Legacy XOR decryption (backward compatible)
    cipher = _get_cipher_key()
    encrypted_bytes = base64.b64decode(encrypted)
    decrypted = bytes(b ^ cipher[i % len(cipher)] for i, b in enumerate(encrypted_bytes))
    return decrypted.decode("utf-8")


def _load_legacy_ai_config_rows(legacy_db_path: str | None = None) -> list[dict]:
    """Read legacy AI config rows from the SQLite main DB, if present."""
    path = legacy_db_path or get_main_db_path()
    if not path or not os.path.exists(path):
        return []

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "ai_config" not in tables:
            return []

        rows = conn.execute(
            """
            SELECT user_id, provider, model, api_key_enc, created_at, updated_at
            FROM ai_config
            ORDER BY user_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _migrate_legacy_ai_config_rows(target_conn, legacy_db_path: str | None = None) -> int:
    """Copy missing legacy AI config rows into the active DB without overwriting."""
    legacy_rows = _load_legacy_ai_config_rows(legacy_db_path)
    if not legacy_rows:
        return 0

    existing_rows = target_conn.execute("SELECT user_id FROM ai_config").fetchall()
    existing_ids = {row["user_id"] for row in existing_rows}
    migrated = 0

    for row in legacy_rows:
        if row["user_id"] in existing_ids:
            continue
        target_conn.execute(
            """
            INSERT INTO ai_config (user_id, provider, model, api_key_enc, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (
                row["user_id"],
                row["provider"],
                row["model"],
                row["api_key_enc"],
                row.get("created_at") or _utc_now(),
                row.get("updated_at") or row.get("created_at") or _utc_now(),
            ),
        )
        existing_ids.add(row["user_id"])
        migrated += 1

    if migrated:
        logger.info(
            "Migrated %s legacy ai_config row(s) from %s into active database",
            migrated,
            legacy_db_path or get_main_db_path(),
        )
    return migrated


def init_ai_tables():
    """Create AI config, analysis cache, and async job tables."""
    use_postgres = bool(getattr(db, "_use_postgres", False))
    if use_postgres:
        with db.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_config (
                    user_id     TEXT PRIMARY KEY,
                    provider    TEXT NOT NULL DEFAULT 'anthropic',
                    model       TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                    api_key_enc TEXT NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS ai_analyses (
                    id          SERIAL PRIMARY KEY,
                    vendor_id   TEXT NOT NULL,
                    provider    TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    elapsed_ms  INTEGER DEFAULT 0,
                    analysis    JSONB NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_by  TEXT,
                    input_hash  TEXT,
                    prompt_version TEXT
                );

                CREATE TABLE IF NOT EXISTS ai_analysis_jobs (
                    id          TEXT PRIMARY KEY,
                    case_id     TEXT NOT NULL,
                    created_by  TEXT,
                    input_hash  TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    analysis_id INTEGER,
                    error       TEXT,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    started_at  TIMESTAMP,
                    completed_at TIMESTAMP
                );

                ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS created_by TEXT;
                ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS input_hash TEXT;
                ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS prompt_version TEXT;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS created_by TEXT;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS input_hash TEXT;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS analysis_id INTEGER;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS error TEXT;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
                ALTER TABLE ai_analysis_jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;

                CREATE INDEX IF NOT EXISTS idx_ai_analyses_vendor ON ai_analyses(vendor_id);
                CREATE INDEX IF NOT EXISTS idx_ai_analyses_vendor_user_hash ON ai_analyses(vendor_id, created_by, input_hash);
                CREATE INDEX IF NOT EXISTS idx_ai_jobs_case_user_hash ON ai_analysis_jobs(case_id, created_by, input_hash);
            """)
            _migrate_legacy_ai_config_rows(conn)
        return

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
    now = _utc_now()
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO ai_config (user_id, provider, model, api_key_enc, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                provider=excluded.provider,
                model=excluded.model,
                api_key_enc=excluded.api_key_enc,
                updated_at=excluded.updated_at
        """, (user_id, provider, model, encrypted, now, now))


def get_ai_config(user_id: str) -> Optional[dict]:
    """Get a user's AI config. Returns None if not configured."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_config WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM ai_config WHERE user_id = '__org_default__'").fetchone()
    if not row:
        return None
    return {
        "provider": row["provider"],
        "model": row["model"],
        "api_key": _decrypt_key(row["api_key_enc"]),
    }


def delete_ai_config(user_id: str) -> bool:
    """Delete a user's AI config."""
    with db.get_conn() as conn:
        cursor = conn.execute("DELETE FROM ai_config WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0


# ---- Analysis Storage ----

def save_analysis(vendor_id: str, provider: str, model: str,
                  analysis: dict, prompt_tokens: int = 0,
                  completion_tokens: int = 0, elapsed_ms: int = 0,
                  created_by: str = "", input_hash: str = "",
                  prompt_version: str = _ANALYSIS_PROMPT_VERSION) -> int:
    now = _utc_now()
    with db.get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO ai_analyses
                (vendor_id, provider, model, prompt_tokens, completion_tokens,
                 elapsed_ms, analysis, created_by, input_hash, prompt_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (vendor_id, provider, model, prompt_tokens, completion_tokens,
              elapsed_ms, json.dumps(analysis), created_by, input_hash, prompt_version, now))
        row = cursor.fetchone()
        if row and row["id"] is not None:
            return int(row["id"])
        if cursor.lastrowid is not None:
            return int(cursor.lastrowid)
    raise RuntimeError("Failed to persist AI analysis row")


def get_latest_analysis(vendor_id: str, user_id: str = "", input_hash: str = "") -> Optional[dict]:
    query = "SELECT * FROM ai_analyses WHERE vendor_id = ?"
    params: list[object] = [vendor_id]
    if user_id:
        query += " AND created_by = ?"
        params.append(user_id)
    if input_hash:
        query += " AND input_hash = ?"
        params.append(input_hash)
    query += " ORDER BY created_at DESC, id DESC LIMIT 1"

    with db.get_conn() as conn:
        row = conn.execute(query, params).fetchone()
    if not row:
        return None
    analysis_payload = row["analysis"]
    return {
        "id": row["id"],
        "vendor_id": row["vendor_id"],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "elapsed_ms": row["elapsed_ms"],
        "analysis": _load_json_field(analysis_payload),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "input_hash": row["input_hash"],
        "prompt_version": row["prompt_version"],
    }


def compute_analysis_fingerprint(vendor_data: dict, score_data: dict, enrichment_data: Optional[dict] = None) -> str:
    sanitized_enrichment = _sanitize_enrichment_data(enrichment_data) or {}
    graph_context = _sanitize_graph_context(vendor_data.get("id"))
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
        "graph": graph_context,
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
{graph_section}

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

Be specific and cite the data provided. Do not hedge or use vague language. If the data clearly indicates a prohibition, say so directly.

Critical evidence-handling rules:
- Treat connector rate limits, outages, or unavailable lookups as UNVERIFIED, not as confirmed absence.
- Do not say an identifier is missing unless the data explicitly confirms it is absent. If a registry lookup was throttled or unavailable, say the identifier could not be verified.
- Do not infer public-company status unless the data includes a ticker, exchange listing, or a high-confidence CIK / public-market filing match.
- When ownership evidence is media-reported or search-derived instead of registry-grade, say that plainly in the confidence or diligence language."""


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
                item = {
                    'title': _sanitize_prompt_fragment(f.get('title', 'Unknown'), 100),
                    'severity': _sanitize_prompt_fragment(f.get('severity', 'info'), 20),
                    'source': _sanitize_prompt_fragment(f.get('source', 'Unknown'), 50),
                }
                if f.get("source_class"):
                    item["source_class"] = _sanitize_prompt_fragment(f.get("source_class", ""), 32)
                if f.get("authority_level"):
                    item["authority_level"] = _sanitize_prompt_fragment(f.get("authority_level", ""), 32)
                sanitized['findings'].append(item)

        return sanitized
    except Exception:
        # If any sanitization fails, return None to indicate insufficient enrichment data
        return None


def _sanitize_graph_context(vendor_id: object) -> dict:
    normalized_vendor_id = str(vendor_id or "").strip()
    if not normalized_vendor_id:
        return {}

    try:
        from graph_ingest import get_vendor_graph_summary
    except ImportError:
        return {}

    network_risk = {}
    try:
        from network_risk import compute_network_risk

        network_risk = compute_network_risk(normalized_vendor_id) or {}
    except Exception:
        network_risk = {}

    try:
        summary = get_vendor_graph_summary(
            normalized_vendor_id,
            depth=2,
            include_provenance=False,
            max_claim_records=1,
            max_evidence_records=1,
        ) or {}
    except Exception:
        return {}

    relationships = summary.get("relationships") if isinstance(summary.get("relationships"), list) else []
    entities = summary.get("entities") if isinstance(summary.get("entities"), list) else []
    intelligence = summary.get("intelligence") if isinstance(summary.get("intelligence"), dict) else {}
    top_relationships = []
    for rel in relationships[:3]:
        if not isinstance(rel, dict):
            continue
        top_relationships.append({
            "source": _sanitize_prompt_fragment(rel.get("source_name") or rel.get("source_entity_name") or rel.get("source_entity_id"), 80),
            "target": _sanitize_prompt_fragment(rel.get("target_name") or rel.get("target_entity_name") or rel.get("target_entity_id"), 80),
            "type": _sanitize_prompt_fragment(rel.get("rel_type") or "related_entity", 48),
            "confidence": round(float(rel.get("confidence") or 0.0), 3),
        })

    return {
        "entity_count": int(summary.get("entity_count") or len(entities) or 0),
        "relationship_count": int(summary.get("relationship_count") or len(relationships) or 0),
        "control_path_count": int(intelligence.get("control_path_count") or 0),
        "thin_graph": bool(intelligence.get("thin_graph")),
        "dominant_edge_family": _sanitize_prompt_fragment(intelligence.get("dominant_edge_family") or "", 48),
        "top_relationships": top_relationships,
        "network_risk_level": _sanitize_prompt_fragment(network_risk.get("network_risk_level") or "", 32),
        "high_risk_neighbors": int(network_risk.get("high_risk_neighbors") or 0),
    }


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

    graph_context = _sanitize_graph_context(vendor_data.get("id"))
    graph_section = ""
    if graph_context:
        try:
            top_relationships = json.dumps(graph_context.get("top_relationships", []), indent=2)
        except Exception:
            top_relationships = "[]"
        graph_section = f"""
GRAPH RELATIONSHIP CONTEXT:
- Entity Count: {graph_context.get('entity_count', 0)}
- Relationship Count: {graph_context.get('relationship_count', 0)}
- Control Paths: {graph_context.get('control_path_count', 0)}
- Thin Graph: {"yes" if graph_context.get('thin_graph') else "no"}
- Dominant Edge Family: {graph_context.get('dominant_edge_family') or "unknown"}
- Network Risk: {graph_context.get('network_risk_level') or "unknown"}
- High-Risk Neighbors: {graph_context.get('high_risk_neighbors', 0)}
- Top Relationships: {top_relationships}
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
        graph_section=graph_section,
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
        lines = [line for line in lines if not line.strip().startswith("```")]
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

    input_hash = compute_analysis_fingerprint(vendor_data, score_data, enrichment_data)
    config = get_ai_config(user_id)
    if not config:
        if not _local_fallback_enabled():
            raise ValueError(
                "No AI provider configured. Set up your API key in Settings > AI Provider."
            )

        return _persist_local_fallback_result(
            user_id=user_id,
            vendor_data=vendor_data,
            score_data=score_data,
            enrichment_data=enrichment_data,
            input_hash=input_hash,
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
        elapsed_ms = int((time.time() - start_ms) * 1000)

        # Parse response
        try:
            analysis = _parse_analysis_json(result["text"])
        except Exception as e:
            raise AIProviderPermanentError(f"Failed to parse AI response: {str(e)}")
    except urllib.error.HTTPError as e:
        raise _classify_provider_http_error(provider, e)
    except Exception as e:
        if isinstance(e, (AIProviderTemporaryError, AIProviderPermanentError)):
            raise
        raise _classify_provider_exception(provider, e)

    # Persist the analysis
    vendor_id = vendor_data.get("id", "unknown")
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
