#!/usr/bin/env python3
"""
Xiphos Helios deploy helper.

This script supports two modes:
  1. Password or key-based exact-tree deploys via SSH/SFTP
  2. Post-deploy verification against a live URL

Preferred env names match deploy.sh and deploy-ssl.sh.
Legacy names are still accepted for backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import warnings
from typing import Any

warnings.filterwarnings("ignore")
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_DIR = pathlib.Path(os.environ.get("XIPHOS_CONFIG_DIR", "~/.config/xiphos")).expanduser()
HELIOS_ENV_PATH = CONFIG_DIR / "helios.env"
SECURE_RUNTIME_ENV_KEYS = (
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_DATABASE",
    "NEO4J_PASSWORD",
    "XIPHOS_SAM_API_KEY",
    "XIPHOS_OPENOWNERSHIP_BODS_URL",
    "XIPHOS_OPENOWNERSHIP_BODS_PATH",
)


def _deploy_env_paths() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    explicit = os.environ.get("XIPHOS_DEPLOY_ENV_FILE", "").strip()
    if explicit:
        paths.append(pathlib.Path(explicit).expanduser())
    else:
        secure_path = CONFIG_DIR / "deploy.env"
        repo_path = SCRIPT_DIR / "deploy.env"
        if secure_path.exists():
            paths.append(secure_path)
        elif repo_path.exists():
            paths.append(repo_path)
        else:
            paths.append(secure_path)

    if HELIOS_ENV_PATH not in paths:
        paths.append(HELIOS_ENV_PATH)
    return paths


def load_env_file() -> None:
    for path in _deploy_env_paths():
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


load_env_file()


def env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def env_bool(*names: str, default: bool = False) -> bool:
    value = env(*names)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def secure_runtime_env() -> dict[str, str]:
    payload: dict[str, str] = {}
    for key in SECURE_RUNTIME_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            payload[key] = value
    return payload


def expects_neo4j() -> bool:
    payload = secure_runtime_env()
    return bool(payload.get("NEO4J_URI") and payload.get("NEO4J_PASSWORD"))


SSH_TARGET = env("XIPHOS_DEPLOY_SSH_TARGET")
SERVER = env("XIPHOS_DEPLOY_HOST")
SSH_USER = env("XIPHOS_DEPLOY_SSH_USER", "XIPHOS_DEPLOY_USER", default="root")
SSH_PASS = env("XIPHOS_DEPLOY_PASSWORD")
SSH_KEY_PATH = env("XIPHOS_DEPLOY_SSH_KEY", "XIPHOS_DEPLOY_SSH_KEY_PATH")
REMOTE_DIR = env("XIPHOS_REMOTE_DIR", "XIPHOS_DEPLOY_REMOTE_DIR", default="/opt/xiphos")
APP_URL = env("XIPHOS_PUBLIC_BASE_URL", "XIPHOS_DEPLOY_APP_URL")
ADMIN_EMAIL = env("XIPHOS_DEPLOY_ADMIN_EMAIL", "XIPHOS_DEPLOY_LOGIN_EMAIL")
ADMIN_PASS = env("XIPHOS_DEPLOY_ADMIN_PASSWORD", "XIPHOS_DEPLOY_LOGIN_PASSWORD")
DOCKER_PORT = env("XIPHOS_DOCKER_PORT", default="8080")
VERIFY_TLS = env_bool("XIPHOS_DEPLOY_VERIFY_TLS", default=False)
DEPLOY_SECRET_KEY = env("XIPHOS_SECRET_KEY", "XIPHOS_DEPLOY_SECRET_KEY")

if not APP_URL and SERVER:
    APP_URL = f"http://{SERVER}:{DOCKER_PORT}"
if not env("XIPHOS_DEPLOY_VERIFY_TLS") and APP_URL.startswith("https://"):
    VERIFY_TLS = True

LOCAL_ROOT = SCRIPT_DIR
ARCHIVE_EXCLUDES = {
    ".git",
    ".env",
    "node_modules",
    "frontend/node_modules",
    "frontend/dist",
    "deploy.env",
    "backups",
    "vps_snapshot",
    "memory",
    "secure-archive",
    "CODEX_HANDOFF_20260322.md",
    "var",
    ".pytest_cache",
    "__pycache__",
    ".codex-backups",
    ".DS_Store",
    "docs/reports",
    "output",
    "tmp",
    "ml/model",
    ".ruff_cache",
}

BUNDLE_MUST_HAVE = [
    "Helios | Xiphos",
    "Entity and vehicle intelligence",
    "Stoa",
    "Aegis",
    "Brief AXIOM",
]
BUNDLE_MUST_NOT_HAVE = ["32 OSINT", "Weapons System", "xiphos-dashboard"]


def step(msg: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def fail(msg: str, code: int = 2) -> None:
    print(msg)
    sys.exit(code)


def require_paramiko():
    try:
        import paramiko  # type: ignore
    except ModuleNotFoundError:
        fail("deploy.py requires paramiko. Install it with: python3 -m pip install paramiko", code=2)
    return paramiko


def require_requests():
    try:
        import requests  # type: ignore
    except ModuleNotFoundError:
        fail("deploy.py requires requests. Install it with: python3 -m pip install requests", code=2)
    return requests


def load_ssh_config(alias: str) -> dict[str, object]:
    paramiko = require_paramiko()
    config_path = pathlib.Path("~/.ssh/config").expanduser()
    if not config_path.exists():
        return {}

    ssh_config = paramiko.SSHConfig()
    with config_path.open(encoding="utf-8") as handle:
        ssh_config.parse(handle)
    return ssh_config.lookup(alias)


def resolve_connection() -> dict[str, object]:
    target = SSH_TARGET
    explicit_user = ""
    if target and "@" in target:
        explicit_user, target = target.split("@", 1)

    host = SERVER
    port = 22
    username = explicit_user or SSH_USER
    key_path = SSH_KEY_PATH

    if target:
        ssh_lookup = load_ssh_config(target)
        host = ssh_lookup.get("hostname", target)
        if not explicit_user:
            username = ssh_lookup.get("user", username)
        if not key_path:
            identity = ssh_lookup.get("identityfile", [])
            if identity:
                key_path = identity[0]
        if ssh_lookup.get("port"):
            port = int(ssh_lookup["port"])

    if not host:
        fail("Missing deployment target. Set XIPHOS_DEPLOY_SSH_TARGET or XIPHOS_DEPLOY_HOST.")

    return {
        "hostname": host,
        "port": port,
        "username": username or "root",
        "key_filename": os.path.expanduser(key_path) if key_path else "",
    }


def ssh_connect() -> Any:
    paramiko = require_paramiko()
    conn = resolve_connection()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = {
        "hostname": conn["hostname"],
        "username": conn["username"],
        "port": conn["port"],
        "timeout": 15,
    }
    if conn["key_filename"]:
        connect_kwargs["key_filename"] = conn["key_filename"]
    elif SSH_PASS:
        connect_kwargs["password"] = SSH_PASS
    ssh.connect(**connect_kwargs)
    return ssh


def run_cmd(ssh: Any, cmd: str, timeout: int = 300) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    channel = stdout.channel
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout

    while True:
        if channel.recv_ready():
            out_chunks.append(channel.recv(65536))
        if channel.recv_stderr_ready():
            err_chunks.append(channel.recv_stderr(65536))
        if channel.exit_status_ready():
            while channel.recv_ready():
                out_chunks.append(channel.recv(65536))
            while channel.recv_stderr_ready():
                err_chunks.append(channel.recv_stderr(65536))
            break
        if time.monotonic() > deadline:
            channel.close()
            raise TimeoutError(f"Remote command timed out after {timeout}s: {cmd}")
        time.sleep(0.1)

    exit_code = channel.recv_exit_status()
    return exit_code, b"".join(out_chunks).decode(), b"".join(err_chunks).decode()


def _decode_json_from_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def run_graph_training_runtime_probe(ssh: Any, compose_prefix: str) -> dict[str, Any]:
    remote_report_dir = "/data/reports/graph_training_probe"
    probe_cmd = (
        f"{compose_prefix}"
        "docker compose exec -T xiphos "
        "python3 /app/scripts/run_graph_training_tranche.py "
        "--skip-train --skip-queue "
        f"--report-dir {shlex.quote(remote_report_dir)} "
        "--json-only"
    )
    code, out, err = run_cmd(ssh, probe_cmd, timeout=300)
    if code != 0:
        raise RuntimeError((err or out or "graph training runtime probe failed").strip())
    payload = _decode_json_from_stdout(out)
    if not payload:
        raise RuntimeError("graph training runtime probe did not return JSON")
    return payload


def cleanup_remote_vendor(vendor_id: str) -> tuple[bool, str]:
    if not vendor_id:
        return False, "missing vendor id"

    try:
        ssh = ssh_connect()
    except Exception as exc:  # pragma: no cover - deploy helper
        return False, f"ssh unavailable: {exc}"

    try:
        secret_key = resolve_secret_key(ssh)
    except Exception as exc:  # pragma: no cover - deploy helper
        ssh.close()
        return False, f"secret unavailable: {exc}"

    cleanup_code = f"""
import sqlite3, sys
sys.path.insert(0, '/app/backend')
import db
vendor_id = {vendor_id!r}
conn = sqlite3.connect(db.get_db_path())
tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for table in tables:
    if table.startswith('sqlite_'):
        continue
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({{table}})").fetchall()]
    if table == 'vendors':
        conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
        continue
    if 'vendor_id' in cols:
        conn.execute(f"DELETE FROM {{table}} WHERE vendor_id = ?", (vendor_id,))
conn.commit()
conn.close()
print('verification vendor cleanup complete')
""".strip()

    cmd = (
        f"cd {shlex.quote(REMOTE_DIR)} && "
        f"export XIPHOS_SECRET_KEY={shlex.quote(secret_key)} && "
        "docker compose exec -T xiphos python3 - <<'PY'\n"
        f"{cleanup_code}\n"
        "PY"
    )
    try:
        code, out, err = run_cmd(ssh, cmd, timeout=120)
    except Exception as exc:  # pragma: no cover - deploy helper
        return False, str(exc)
    finally:
        ssh.close()

    if code != 0:
        return False, (err or out or "remote cleanup failed").strip()
    return True, (out or "ok").strip()


def ensure_remote_parent(sftp: Any, remote_path: str) -> None:
    parts = pathlib.PurePosixPath(remote_path).parts[:-1]
    current = "/"
    for part in parts:
        if part == "/":
            continue
        current = f"{current.rstrip('/')}/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def should_exclude(rel_path: str) -> bool:
    path = pathlib.PurePosixPath(rel_path).as_posix()
    if path.startswith("./"):
        path = path[2:]
    if not path:
        return False
    name = pathlib.PurePosixPath(path).name
    if name == "deploy.env":
        return True
    if name.startswith(".env") and name != ".env.example":
        return True
    if name.endswith((".db", ".db-journal", ".db-shm", ".db-wal")):
        return True
    parts = path.split("/")
    for index in range(1, len(parts) + 1):
        prefix = "/".join(parts[:index])
        if prefix in ARCHIVE_EXCLUDES:
            return True
    return False


def create_deploy_archive(backend_only: bool = False) -> pathlib.Path:
    temp_dir = tempfile.mkdtemp(prefix="xiphos-deploy-")
    archive_path = pathlib.Path(temp_dir) / "deploy.tar.gz"
    allowed_backend_roots = {
        "backend",
        "ml",
        "osint",
        "tests",
        "Dockerfile",
        "docker-compose.yml",
        "docker-entrypoint.sh",
        "deploy.py",
        "deploy.sh",
        "deploy-ssl.sh",
        "deploy.env.example",
        "DEPLOY.md",
        "scripts",
        "fixtures",
    }
    with tarfile.open(archive_path, "w:gz") as tar:
        for path in sorted(LOCAL_ROOT.rglob("*")):
            rel_path = path.relative_to(LOCAL_ROOT).as_posix()
            if should_exclude(rel_path):
                continue
            if backend_only:
                root = rel_path.split("/", 1)[0]
                if root not in allowed_backend_roots:
                    continue
            tar.add(path, arcname=rel_path, recursive=False)
    return archive_path


def resolve_secret_key(ssh: Any) -> str:
    if DEPLOY_SECRET_KEY:
        return DEPLOY_SECRET_KEY

    probes = [
        "docker exec xiphos-xiphos-1 /bin/sh -lc 'printf %s \"$XIPHOS_SECRET_KEY\"' 2>/dev/null || true",
        f"cd {shlex.quote(REMOTE_DIR)} && if [ -f deploy.env ]; then set -a; . ./deploy.env; set +a; fi; "
        "if [ -f .env ]; then set -a; . ./.env; set +a; fi; printf %s \"${XIPHOS_SECRET_KEY:-}\"",
    ]
    for probe in probes:
        _, out, _ = run_cmd(ssh, probe)
        value = out.strip()
        if value:
            return value
    fail("Set XIPHOS_SECRET_KEY (or XIPHOS_DEPLOY_SECRET_KEY) before deploying, or keep it available on the live host.")


def upload_archive(ssh: Any, archive_path: pathlib.Path) -> str:
    remote_archive = f"/tmp/{archive_path.name}"
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(archive_path), remote_archive)
    finally:
        sftp.close()
    return remote_archive


def sync_secure_runtime_env(ssh: Any) -> None:
    payload = secure_runtime_env()
    if not payload:
        return

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", prefix="xiphos-runtime-", suffix=".env") as handle:
        local_path = pathlib.Path(handle.name)
        for key in SECURE_RUNTIME_ENV_KEYS:
            value = payload.get(key)
            if value:
                handle.write(f"{key}={value}\n")

    remote_path = f"/tmp/{local_path.name}"
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(local_path), remote_path)
    finally:
        sftp.close()
        local_path.unlink(missing_ok=True)

    merge_cmd = (
        f"cd {shlex.quote(REMOTE_DIR)} && "
        f"python3 - <<'PY'\n"
        f"from pathlib import Path\n"
        f"keys = {list(SECURE_RUNTIME_ENV_KEYS)!r}\n"
        f"source = Path({remote_path!r})\n"
        f"target = Path('.env')\n"
        f"updates = {{}}\n"
        f"if source.exists():\n"
        f"    for raw in source.read_text(encoding='utf-8').splitlines():\n"
        f"        line = raw.strip()\n"
        f"        if not line or line.startswith('#') or '=' not in line:\n"
        f"            continue\n"
        f"        key, value = line.split('=', 1)\n"
        f"        if key in keys:\n"
        f"            updates[key] = value\n"
        f"existing = []\n"
        f"if target.exists():\n"
        f"    existing = target.read_text(encoding='utf-8').splitlines()\n"
        f"kept = []\n"
        f"for raw in existing:\n"
        f"    line = raw.strip()\n"
        f"    if not line or line.startswith('#') or '=' not in line:\n"
        f"        kept.append(raw)\n"
        f"        continue\n"
        f"    key = line.split('=', 1)[0].strip()\n"
        f"    if key in updates:\n"
        f"        continue\n"
        f"    kept.append(raw)\n"
        f"for key in keys:\n"
        f"    if key in updates:\n"
        f"        kept.append(f'{{key}}={{updates[key]}}')\n"
        f"target.write_text('\\n'.join(kept).rstrip() + '\\n', encoding='utf-8')\n"
        f"source.unlink(missing_ok=True)\n"
        f"PY"
    )
    code, out, err = run_cmd(ssh, merge_cmd, timeout=60)
    if code != 0:
        fail((err or out or "failed to sync secure runtime env").strip())


def ensure_env(require_auth: bool = False) -> None:
    missing: list[str] = []
    if not (SSH_TARGET or SERVER):
        missing.append("XIPHOS_DEPLOY_SSH_TARGET or XIPHOS_DEPLOY_HOST")
    if not APP_URL:
        missing.append("XIPHOS_PUBLIC_BASE_URL or XIPHOS_DEPLOY_APP_URL")
    if require_auth and not (ADMIN_EMAIL and ADMIN_PASS):
        missing.append("XIPHOS_DEPLOY_ADMIN_EMAIL and XIPHOS_DEPLOY_ADMIN_PASSWORD")

    if missing:
        print("Missing deployment environment variables:")
        for item in missing:
            print(f"  - {item}")
        sys.exit(2)


def deploy(args: argparse.Namespace) -> None:
    ensure_env()
    ssh = ssh_connect()

    secret_key = resolve_secret_key(ssh)

    step("BUILDING DEPLOY ARCHIVE")
    archive_path = create_deploy_archive(backend_only=args.backend_only)
    print(f"  Built {archive_path.name}")

    try:
        step("UPLOADING EXACT TREE")
        remote_archive = upload_archive(ssh, archive_path)
        print(f"  Uploaded archive to {remote_archive}")

        temp_unpack = f"/tmp/xiphos-deploy-{int(time.time())}"
        sync_cmd = (
            f"mkdir -p {shlex.quote(REMOTE_DIR)} {shlex.quote(temp_unpack)} && "
            f"tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(temp_unpack)} && "
            f"find {shlex.quote(REMOTE_DIR)} -mindepth 1 -maxdepth 1 "
            "! -name .git ! -name deploy.env ! -name .env "
            "! -name backups ! -name vps_snapshot ! -name var "
            "-exec rm -rf {} + && "
            f"cp -a {shlex.quote(temp_unpack)}/. {shlex.quote(REMOTE_DIR)}/ && "
            f"rm -rf {shlex.quote(temp_unpack)} {shlex.quote(remote_archive)}"
        )
        code, out, err = run_cmd(ssh, sync_cmd, timeout=600)
        if code != 0:
            print(out or err)
            ssh.close()
            sys.exit(1)
        print("  Remote tree synchronized")
        sync_secure_runtime_env(ssh)
        print("  Secure runtime env synchronized")

        step("REBUILDING DOCKER")
        rebuild_cmd = (
            f"cd {shlex.quote(REMOTE_DIR)} && "
            f"export XIPHOS_SECRET_KEY={shlex.quote(secret_key)} && "
            "export DOCKER_BUILDKIT=0 && "
            "docker build --no-cache -t xiphos-xiphos . 2>&1"
        )
        code, out, err = run_cmd(ssh, rebuild_cmd, timeout=900)
        if code == 0:
            print("  Docker build OK")
        else:
            print(out or err)
            ssh.close()
            sys.exit(1)

        step("RESTARTING CONTAINER")
        restart_cmd = (
            f"cd {shlex.quote(REMOTE_DIR)} && "
            f"export XIPHOS_SECRET_KEY={shlex.quote(secret_key)} && "
            "docker compose up -d --no-build 2>&1"
        )
        _, out, err = run_cmd(ssh, restart_cmd, timeout=180)
        print((out or err).strip().splitlines()[-1])
    finally:
        try:
            archive_path.unlink(missing_ok=True)
            archive_path.parent.rmdir()
        except OSError:
            pass
        ssh.close()

    print("\n  Waiting 8s for startup...")
    time.sleep(8)
    verify()


def verify() -> None:
    requests = require_requests()
    ensure_env()
    step("POST-DEPLOY VERIFICATION")
    issues: list[str] = []
    verify_case_id = ""

    ssh = ssh_connect()
    secret_key = resolve_secret_key(ssh)
    compose_prefix = f"cd {shlex.quote(REMOTE_DIR)} && export XIPHOS_SECRET_KEY={shlex.quote(secret_key)} && "

    health_deadline = time.monotonic() + 45
    container_status = ""
    while time.monotonic() < health_deadline:
        _, out, _ = run_cmd(ssh, f"{compose_prefix}docker compose ps --format json")
        container_status = out.strip()
        lowered = container_status.lower()
        if "healthy" in lowered:
            print("  PASS: Container healthy")
            break
        if "health: starting" not in lowered and "starting" not in lowered:
            print(f"  FAIL: Container status: {container_status}")
            issues.append("Container not healthy")
            break
        time.sleep(2)
    else:
        print(f"  FAIL: Container status: {container_status}")
        issues.append("Container not healthy")

    for term in BUNDLE_MUST_HAVE:
        escaped = term.replace('"', '\\"')
        _, out, _ = run_cmd(
            ssh,
            f"{compose_prefix}docker compose exec -T xiphos grep -c \"{escaped}\" /app/backend/static/index.html",
        )
        if int((out.strip() or "0")) > 0:
            print(f"  PASS: '{term}' present in bundle")
        else:
            print(f"  FAIL: '{term}' missing from bundle")
            issues.append(f"Missing bundle text: {term}")

    for term in BUNDLE_MUST_NOT_HAVE:
        escaped = term.replace('"', '\\"')
        _, out, _ = run_cmd(
            ssh,
            f"{compose_prefix}docker compose exec -T xiphos grep -c \"{escaped}\" /app/backend/static/index.html",
        )
        if int((out.strip() or "0")) == 0:
            print(f"  PASS: '{term}' absent from bundle")
        else:
            print(f"  FAIL: '{term}' still present in bundle")
            issues.append(f"Stale bundle text: {term}")

    try:
        graph_training = run_graph_training_runtime_probe(ssh, compose_prefix)
        review_stats = graph_training.get("review_stats") if isinstance(graph_training.get("review_stats"), dict) else {}
        print(
            "  PASS: Graph training runtime probe "
            f"(predicted_links={review_stats.get('total_links', 0)}, "
            f"reviewed={review_stats.get('reviewed_links', 0)})"
        )
    except Exception as exc:
        print(f"  FAIL: Graph training runtime probe failed: {exc}")
        issues.append(f"Graph training runtime probe failed: {exc}")

    ssh.close()

    external_health_data: dict[str, Any] = {}
    try:
        external_deadline = time.monotonic() + 90
        while True:
            try:
                health = requests.get(f"{APP_URL}/api/health", verify=VERIFY_TLS, timeout=20)
                health.raise_for_status()
                external_health_data = health.json()
                break
            except Exception:
                if time.monotonic() >= external_deadline:
                    raise
                time.sleep(2)
        connector_count = external_health_data.get("osint_connector_count", 0)
        if connector_count >= 28:
            print(f"  PASS: {connector_count} connectors")
        else:
            print(f"  FAIL: {connector_count} connectors (expected at least 28)")
            issues.append(f"Connector count mismatch: {connector_count}")
        if expects_neo4j():
            neo4j = requests.get(f"{APP_URL}/api/neo4j/health", verify=VERIFY_TLS, timeout=20)
            neo4j.raise_for_status()
            neo4j_payload = neo4j.json()
            if bool(neo4j_payload.get("neo4j_available")):
                print("  PASS: Neo4j health route is available")
            else:
                print("  FAIL: Neo4j health route reports unavailable")
                issues.append("Neo4j unavailable")
    except Exception as exc:  # pragma: no cover - deploy helper
        print(f"  FAIL: API health check failed: {exc}")
        issues.append(f"API health failed: {exc}")

    try:
        regression = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "scripts" / "run_front_porch_browser_regression.py"),
                "--base-url",
                APP_URL,
            ],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if regression.returncode == 0:
            print("  PASS: Stoa browser regression")
        else:
            detail = (regression.stderr or regression.stdout or "browser regression failed").strip()
            print(f"  FAIL: Stoa browser regression failed: {detail}")
            issues.append(f"Stoa browser regression failed: {detail}")
    except Exception as exc:
        print(f"  FAIL: Stoa browser regression failed: {exc}")
        issues.append(f"Stoa browser regression failed: {exc}")

    if not (ADMIN_EMAIL and ADMIN_PASS):
        print("  WARN: Skipping auth-verified API checks (set XIPHOS_DEPLOY_ADMIN_EMAIL/PASSWORD)")
    else:
        try:
            aegis_regression = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "scripts" / "run_war_room_carryover_regression.py"),
                    "--base-url",
                    APP_URL,
                    "--email",
                    ADMIN_EMAIL,
                    "--password",
                    ADMIN_PASS,
                ],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if aegis_regression.returncode == 0:
                print("  PASS: Aegis carryover regression")
            else:
                detail = (aegis_regression.stderr or aegis_regression.stdout or "carryover regression failed").strip()
                print(f"  FAIL: Aegis carryover regression failed: {detail}")
                issues.append(f"Aegis carryover regression failed: {detail}")
        except Exception as exc:
            print(f"  FAIL: Aegis carryover regression failed: {exc}")
            issues.append(f"Aegis carryover regression failed: {exc}")

        try:
            auth_deadline = time.monotonic() + 90
            token = ""
            last_auth_exc: Exception | None = None
            while True:
                try:
                    login = requests.post(
                        f"{APP_URL}/api/auth/login",
                        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                        verify=VERIFY_TLS,
                        timeout=20,
                    )
                    login.raise_for_status()
                    token = login.json().get("token", "")
                    if token:
                        break
                    raise RuntimeError("login succeeded but token missing")
                except Exception as exc:
                    last_auth_exc = exc
                    if time.monotonic() >= auth_deadline:
                        raise
                    time.sleep(2)
            if not token:
                raise last_auth_exc or RuntimeError("login succeeded but token missing")

            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

            resp = requests.post(
                f"{APP_URL}/api/resolve",
                json={"name": "Boeing"},
                headers=headers,
                verify=VERIFY_TLS,
                timeout=90,
            )
            if resp.status_code == 200 and resp.json().get("count", 0) > 0:
                print(f"  PASS: Entity resolution ({resp.json()['count']} candidates)")
            else:
                print(f"  FAIL: Entity resolution: {resp.status_code}")
                issues.append("Entity resolution failed")

            resp = requests.post(
                f"{APP_URL}/api/cases",
                json={
                    "name": "DEPLOY_VERIFY",
                    "country": "US",
                    "ownership": {
                        "publicly_traded": True,
                        "state_owned": False,
                        "beneficial_owner_known": True,
                        "ownership_pct_resolved": 0.9,
                        "shell_layers": 0,
                        "pep_connection": False,
                    },
                    "data_quality": {
                        "has_lei": True,
                        "has_cage": True,
                        "has_duns": True,
                        "has_tax_id": True,
                        "has_audited_financials": True,
                        "years_of_records": 15,
                    },
                    "exec": {
                        "known_execs": 5,
                        "adverse_media": 0,
                        "pep_execs": 0,
                        "litigation_history": 0,
                    },
                    "program": "dod_unclassified",
                    "profile": "defense_acquisition",
                },
                headers=headers,
                verify=VERIFY_TLS,
                timeout=30,
            )
            if resp.status_code == 201:
                verify_case_id = resp.json().get("case_id", "")
                score = resp.json().get("composite_score", -1)
                print(f"  PASS: Scoring engine (clean vendor: {score}%)")
            else:
                print(f"  FAIL: Case creation: {resp.status_code}")
                issues.append("Scoring engine failed")
        except Exception as exc:  # pragma: no cover - deploy helper
            print(f"  FAIL: Auth/API verification failed: {exc}")
            issues.append(f"Auth/API verify failed: {exc}")
        finally:
            if verify_case_id:
                cleaned, detail = cleanup_remote_vendor(verify_case_id)
                if cleaned:
                    print(f"  PASS: Verification cleanup ({verify_case_id})")
                else:
                    print(f"  WARN: Verification cleanup failed for {verify_case_id}: {detail}")

    print(f"\n{'=' * 60}")
    if issues:
        print(f"  DEPLOY VERIFICATION: {len(issues)} ISSUE(S)")
        for issue in issues:
            print(f"    - {issue}")
        sys.exit(1)
    print("  DEPLOY VERIFICATION: ALL CHECKS PASSED")
    print(f"  Live at: {APP_URL}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xiphos Helios deploy helper")
    parser.add_argument("--verify-only", action="store_true", help="Just run verification")
    parser.add_argument("--backend-only", action="store_true", help="Skip frontend rebuild")
    args = parser.parse_args()

    if args.verify_only:
        verify()
    else:
        deploy(args)
