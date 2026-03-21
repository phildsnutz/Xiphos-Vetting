#!/usr/bin/env python3
"""
Xiphos Helios deploy helper.

This script supports two modes:
  1. Password or key-based patch deploys via SFTP/SSH
  2. Post-deploy verification against a live URL

Preferred env names match deploy.sh and deploy-ssl.sh.
Legacy names are still accepted for backward compatibility.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shlex
import sys
import time
import warnings
from typing import Any

warnings.filterwarnings("ignore")


def load_env_file() -> None:
    env_path = os.environ.get("XIPHOS_DEPLOY_ENV_FILE", "deploy.env").strip()
    if not env_path:
        return

    path = pathlib.Path(env_path).expanduser()
    if not path.exists():
        return

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

if not APP_URL and SERVER:
    APP_URL = f"http://{SERVER}:{DOCKER_PORT}"
if not env("XIPHOS_DEPLOY_VERIFY_TLS") and APP_URL.startswith("https://"):
    VERIFY_TLS = True


BACKEND_FILES = [
    "backend/fgamlogit.py",
    "backend/server.py",
    "backend/osint_scoring.py",
    "backend/entity_resolver.py",
    "backend/entity_rerank.py",
    "backend/contract_vehicle_search.py",
    "backend/regulatory_gates.py",
    "backend/dossier.py",
    "backend/dossier_pdf.py",
    "backend/ai_analysis.py",
    "backend/osint/enrichment.py",
    "backend/osint/ofac_sdn.py",
    "backend/osint/eu_sanctions.py",
    "backend/osint/sbir_awards.py",
    "backend/osint/sec_xbrl.py",
    "backend/osint/uk_hmt_sanctions.py",
    "backend/osint/google_news.py",
    "backend/osint/dod_sam_exclusions.py",
    "backend/osint/gdelt_media.py",
    "backend/requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
]

FRONTEND_FILES = [
    "frontend/src/App.tsx",
    "frontend/src/components/xiphos/helios-landing.tsx",
    "frontend/src/components/xiphos/case-detail.tsx",
    "frontend/src/components/xiphos/portfolio-screen.tsx",
    "frontend/src/components/xiphos/login-screen.tsx",
    "frontend/src/components/xiphos/admin-panel.tsx",
    "frontend/src/components/xiphos/action-panel.tsx",
    "frontend/src/components/xiphos/enrichment-panel.tsx",
    "frontend/src/components/xiphos/ai-analysis-panel.tsx",
    "frontend/src/components/xiphos/supply-chain-graph.tsx",
    "frontend/src/components/xiphos/corporate-tree.tsx",
    "frontend/src/components/xiphos/case-row.tsx",
    "frontend/src/components/xiphos/badges.tsx",
    "frontend/src/components/xiphos/demo-compare.tsx",
    "frontend/src/components/xiphos/enrichment-stream.tsx",
    "frontend/src/components/xiphos/charts.tsx",
    "frontend/src/components/xiphos/gauge.tsx",
    "frontend/src/components/xiphos/ai-settings.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/lib/scoring.ts",
    "frontend/src/lib/tokens.ts",
    "frontend/src/lib/types.ts",
    "frontend/src/lib/auth.ts",
    "frontend/src/lib/dossier.ts",
]

BUNDLE_FILE = "backend/static/index.html"

REMOTE_DELETE_FILES = [
    "frontend/src/components/xiphos/dashboard-screen.tsx",
    "frontend/src/components/xiphos/exec-dashboard.tsx",
    "frontend/src/components/xiphos/portfolio-view.tsx",
    "frontend/src/components/xiphos/risk-matrix.tsx",
    "frontend/src/components/xiphos/stat-card.tsx",
    "frontend/src/components/xiphos/screen-vendor.tsx",
    "frontend/src/components/xiphos/batch-import.tsx",
    "frontend/src/components/xiphos/connector-health.tsx",
    "frontend/src/components/xiphos/onboarding-wizard.tsx",
    "frontend/src/components/xiphos/profile-compare.tsx",
]

BUNDLE_MUST_HAVE = ["Helios | Xiphos", "What do you want to assess?", "Create draft cases", "Begin Assessment"]
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
    except ModuleNotFoundError as exc:
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
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode(), stderr.read().decode()


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


def upload_files(ssh: Any, files: list[str], local_base: str = ".") -> int:
    sftp = ssh.open_sftp()
    uploaded = 0
    for rel_path in files:
        local = pathlib.Path(local_base) / rel_path
        remote = f"{REMOTE_DIR}/{rel_path}"
        try:
            ensure_remote_parent(sftp, remote)
            sftp.put(str(local), remote)
            uploaded += 1
        except Exception as exc:  # pragma: no cover - deploy helper
            print(f"  WARN: Failed to upload {rel_path}: {exc}")
    sftp.close()
    return uploaded


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

    step("UPLOADING FILES")
    all_files = BACKEND_FILES + ([] if args.backend_only else FRONTEND_FILES)
    count = upload_files(ssh, all_files)
    print(f"  Uploaded {count}/{len(all_files)} files")

    if not args.backend_only:
        step("DEPLOYING FRONTEND BUNDLE")
        sftp = ssh.open_sftp()
        try:
            ensure_remote_parent(sftp, f"{REMOTE_DIR}/{BUNDLE_FILE}")
            sftp.put(BUNDLE_FILE, f"{REMOTE_DIR}/{BUNDLE_FILE}")
            print(f"  Uploaded pre-built bundle ({BUNDLE_FILE})")
        except Exception as exc:  # pragma: no cover - deploy helper
            print(f"  WARN: Bundle upload failed ({exc}), building on server...")
            code, out, err = run_cmd(ssh, f"cd {shlex.quote(REMOTE_DIR)}/frontend && npm run build 2>&1", timeout=240)
            if code != 0 or "error TS" in out:
                print("  FAILED: TypeScript/server-side build errors:")
                print(out or err)
                ssh.close()
                sys.exit(1)
            print("  Frontend build OK (server-side)")
        finally:
            sftp.close()

        step("VERIFYING BUNDLE OUTPUT")
        _, out, _ = run_cmd(ssh, f"wc -c {shlex.quote(f'{REMOTE_DIR}/{BUNDLE_FILE}')}")
        print(f"  Bundle: {out.strip()}")

        step("CLEANING DEAD COMPONENTS")
        for dead_file in REMOTE_DELETE_FILES:
            run_cmd(ssh, f"rm -f {shlex.quote(f'{REMOTE_DIR}/{dead_file}')}")
        print(f"  Removed {len(REMOTE_DELETE_FILES)} obsolete component files")

    step("REBUILDING DOCKER")
    code, out, err = run_cmd(ssh, f"cd {shlex.quote(REMOTE_DIR)} && docker compose build --no-cache xiphos 2>&1", timeout=600)
    if code == 0:
        print("  Docker build OK")
    else:
        print(out or err)
        ssh.close()
        sys.exit(1)

    step("RESTARTING CONTAINER")
    _, out, err = run_cmd(ssh, f"cd {shlex.quote(REMOTE_DIR)} && docker compose up -d 2>&1", timeout=120)
    print((out or err).strip().splitlines()[-1])
    ssh.close()

    print("\n  Waiting 8s for startup...")
    time.sleep(8)
    verify()


def verify() -> None:
    requests = require_requests()
    ensure_env()
    step("POST-DEPLOY VERIFICATION")
    issues: list[str] = []

    ssh = ssh_connect()
    _, out, _ = run_cmd(ssh, f"cd {shlex.quote(REMOTE_DIR)} && docker compose ps --format json")
    if "healthy" in out.lower():
        print("  PASS: Container healthy")
    else:
        print(f"  FAIL: Container status: {out.strip()}")
        issues.append("Container not healthy")

    for term in BUNDLE_MUST_HAVE:
        escaped = term.replace('"', '\\"')
        _, out, _ = run_cmd(
            ssh,
            f"cd {shlex.quote(REMOTE_DIR)} && docker compose exec -T xiphos grep -c \"{escaped}\" /app/backend/static/index.html",
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
            f"cd {shlex.quote(REMOTE_DIR)} && docker compose exec -T xiphos grep -c \"{escaped}\" /app/backend/static/index.html",
        )
        if int((out.strip() or "0")) == 0:
            print(f"  PASS: '{term}' absent from bundle")
        else:
            print(f"  FAIL: '{term}' still present in bundle")
            issues.append(f"Stale bundle text: {term}")

    ssh.close()

    try:
        health = requests.get(f"{APP_URL}/api/health", verify=VERIFY_TLS, timeout=20)
        health.raise_for_status()
        health_data = health.json()
        connector_count = health_data.get("osint_connector_count", 0)
        if connector_count == 27:
            print(f"  PASS: {connector_count} connectors")
        else:
            print(f"  FAIL: {connector_count} connectors (expected 27)")
            issues.append(f"Connector count mismatch: {connector_count}")
    except Exception as exc:  # pragma: no cover - deploy helper
        print(f"  FAIL: API health check failed: {exc}")
        issues.append(f"API health failed: {exc}")
        health_data = {}

    if not (ADMIN_EMAIL and ADMIN_PASS):
        print("  WARN: Skipping auth-verified API checks (set XIPHOS_DEPLOY_ADMIN_EMAIL/PASSWORD)")
    else:
        try:
            login = requests.post(
                f"{APP_URL}/api/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                verify=VERIFY_TLS,
                timeout=20,
            )
            login.raise_for_status()
            token = login.json().get("token", "")
            if not token:
                raise RuntimeError("login succeeded but token missing")

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
                score = resp.json().get("composite_score", -1)
                print(f"  PASS: Scoring engine (clean vendor: {score}%)")
            else:
                print(f"  FAIL: Case creation: {resp.status_code}")
                issues.append("Scoring engine failed")
        except Exception as exc:  # pragma: no cover - deploy helper
            print(f"  FAIL: Auth/API verification failed: {exc}")
            issues.append(f"Auth/API verify failed: {exc}")

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
