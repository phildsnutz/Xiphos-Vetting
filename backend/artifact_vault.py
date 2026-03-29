"""
Secure artifact vault for higher-sensitivity customer and gated-source records.

The vault stores files beneath a private runtime directory and persists only
relative storage references in SQLite. This keeps the storage substrate small,
auditable, and safe to extend for SPRS, FOCI, OSCAL, and export artifacts.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path

import db
from osint.evidence_metadata import get_source_metadata
from runtime_paths import get_secure_artifacts_dir


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _vault_root() -> Path:
    root = Path(get_secure_artifacts_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _safe_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        return "artifact.bin"
    cleaned = _FILENAME_SAFE_RE.sub("_", name).strip("._")
    return cleaned or "artifact.bin"


def _case_segment(case_id: str) -> str:
    cleaned = _FILENAME_SAFE_RE.sub("-", case_id or "case").strip("-")
    return cleaned or "case"


def _resolve_storage_ref(storage_ref: str) -> Path:
    root = _vault_root()
    candidate = (root / storage_ref).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("Storage reference escapes the secure artifact vault")
    return candidate


def _write_private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    tmp_path = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex[:8]}")
    with open(tmp_path, "wb") as handle:
        handle.write(content)
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)


def store_artifact(
    case_id: str,
    artifact_type: str,
    filename: str,
    content: bytes,
    *,
    source_system: str = "",
    source_class: str = "",
    authority_level: str = "",
    access_model: str = "",
    uploaded_by: str = "",
    content_type: str = "",
    retention_class: str = "standard",
    sensitivity: str = "controlled",
    effective_date: str | None = None,
    parse_status: str = "pending",
    structured_fields: dict | None = None,
) -> dict:
    artifact_id = f"art-{uuid.uuid4().hex[:12]}"
    safe_name = _safe_filename(filename)
    metadata = get_source_metadata(
        source_system,
        source_class=source_class,
        authority_level=authority_level,
        access_model=access_model,
    )
    payload = content if isinstance(content, bytes) else bytes(content)
    sha256 = hashlib.sha256(payload).hexdigest()
    detected_type = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    storage_ref = f"{_case_segment(case_id)}/{artifact_id}/{safe_name}"
    path = _resolve_storage_ref(storage_ref)
    _write_private_bytes(path, payload)

    db.create_artifact_record(
        artifact_id,
        case_id,
        artifact_type,
        source_system=source_system,
        source_class=metadata["source_class"],
        authority_level=metadata["authority_level"],
        access_model=metadata["access_model"],
        uploaded_by=uploaded_by,
        filename=safe_name,
        content_type=detected_type,
        size_bytes=len(payload),
        sha256=sha256,
        storage_ref=storage_ref,
        retention_class=retention_class,
        sensitivity=sensitivity,
        effective_date=effective_date,
        parse_status=parse_status,
        structured_fields=structured_fields or {},
    )
    return get_artifact_record(artifact_id)


def get_artifact_record(artifact_id: str) -> dict | None:
    record = db.get_artifact_record(artifact_id)
    if not record:
        return None
    path = _resolve_storage_ref(record["storage_ref"])
    record["artifact_path"] = str(path)
    record["exists"] = path.exists()
    return record


def list_case_artifacts(case_id: str, artifact_type: str | None = None, limit: int = 100) -> list[dict]:
    records = db.list_artifact_records(case_id, artifact_type=artifact_type, limit=limit)
    return [get_artifact_record(record["id"]) for record in records if record.get("id")]


def read_artifact_bytes(artifact_id: str) -> bytes:
    record = db.get_artifact_record(artifact_id)
    if not record:
        raise FileNotFoundError(f"Artifact not found: {artifact_id}")
    path = _resolve_storage_ref(record["storage_ref"])
    with open(path, "rb") as handle:
        return handle.read()
