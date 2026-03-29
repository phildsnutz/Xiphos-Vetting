#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE_BUCKETS = ROOT / "docs/reports/SCOPE_BUCKETS_2026-03-29.md"
WORKSPACE_PREFIX = f"{ROOT}/"

TRACKED_SECTION_KEYS = {
    "Shipping Scope": "shipping_tracked",
    "Ops Scope": "ops_tracked",
    "Ambient Docs": "ambient_docs",
}

UNTRACKED_GROUPS = [
    (
        "counterparty_intel",
        "Counterparty, dossier, supplier passport, OSINT connectors, and ownership intelligence",
        [
            "backend/ai_control_plane.py",
            "backend/analyst_feedback.py",
            "backend/artifact_vault.py",
            "backend/bulk_ingest.py",
            "backend/feedback_api.py",
            "backend/profile_api.py",
            "backend/supplier_passport.py",
            "backend/threat_intel_substrate.py",
            "backend/osint/*",
            "tests/test_ai_config_migration.py",
            "tests/test_ai_control_plane.py",
            "tests/test_artifact_vault.py",
            "tests/test_*connector.py",
            "tests/test_connector_registry_sync.py",
            "tests/test_counterparty_*.py",
            "tests/test_customer_demo_gate.py",
            "tests/test_dossier_context.py",
            "tests/test_enrichment*.py",
            "tests/test_intel_summary_flow.py",
            "tests/test_openownership_bods_public.py",
            "tests/test_osint_*.py",
            "tests/test_ownership_control_benchmark.py",
            "tests/test_profile_api_local.py",
            "tests/test_public_*.py",
            "tests/test_sam_subaward_reporting.py",
            "tests/test_scoring_policy_metadata.py",
            "tests/test_standards_fixture_connectors.py",
            "tests/test_supplier_passport_official_corroboration.py",
            "tests/test_threat_intel_substrate.py",
        ],
    ),
    (
        "graph_decision_surface",
        "Graph, decision, screening, storyline, and graph-facing analyst surfaces",
        [
            "backend/blueprint_registry.py",
            "backend/decision_*.py",
            "backend/graph_*.py",
            "backend/link_prediction_api.py",
            "backend/neo4j_*.py",
            "backend/network_risk.py",
            "backend/person_screening.py",
            "backend/screening_api.py",
            "backend/semantic_search.py",
            "backend/storyline.py",
            "backend/test_knowledge_graph.py",
            "backend/test_network_risk.py",
            "backend/workflow_*.py",
            "tests/test_db_delete_vendor.py",
            "tests/test_decision_*.py",
            "tests/test_graph_*.py",
            "tests/test_monitor_graph_parity.py",
            "tests/test_neo4j_*.py",
            "tests/test_profile_registry.py",
            "tests/test_screen_name_false_negatives.py",
            "tests/test_screening_api.py",
            "tests/test_storyline.py",
            "frontend/src/components/xiphos/entity-graph.tsx",
            "frontend/src/components/xiphos/graph-intelligence-dashboard.tsx",
            "frontend/src/components/xiphos/risk-storyline*.tsx",
            "frontend/src/lib/workflow-copy.ts",
        ],
    ),
    (
        "export_authorization",
        "Export lane, ITAR, FOCI, transaction authorization, and export-specific UI",
        [
            "backend/batch_itar_scorer.py",
            "backend/bis_csl.py",
            "backend/export_*.py",
            "backend/foci_*.py",
            "backend/itar_module.py",
            "backend/license_exception_engine.py",
            "backend/test_backend_regulatory_gates.py",
            "backend/transaction_authorization.py",
            "tests/itar_validation_cases.csv",
            "tests/test_export_*.py",
            "tests/test_foci_*.py",
            "tests/test_itar_module.py",
            "tests/test_regulatory_gates.py",
            "tests/test_transaction_authorization_parallel.py",
            "frontend/src/components/xiphos/transaction-authorization-panel.tsx",
        ],
    ),
    (
        "cyber_supply_chain",
        "Cyber evidence, supply-chain assurance, compliance dashboards, and adversarial safety work",
        [
            "backend/adversarial_gym.py",
            "backend/compliance_*.py",
            "backend/cyber_*.py",
            "backend/nvd_overlay.py",
            "backend/oscal_intake.py",
            "backend/sprs_import_intake.py",
            "backend/supply_chain_assurance_*.py",
            "tests/test_adversarial_gym.py",
            "tests/test_cyber_*.py",
            "tests/test_nvd_overlay.py",
            "tests/test_open_source_assurance_connectors.py",
            "tests/test_oscal_intake.py",
            "tests/test_security_hygiene.py",
            "tests/test_sprs_import_intake.py",
            "tests/test_supply_chain_assurance_*.py",
            "tests/test_usaspending_supply_chain.py",
            "frontend/src/components/xiphos/compliance-dashboard.tsx",
        ],
    ),
    (
        "ops_readiness_harness",
        "Readiness, hardening, training, migration, verification, and operator utilities",
        [
            "backend/db_postgres.py",
            "backend/migrate_sqlite_to_postgres.py",
            "backend/monitor_core.py",
            "backend/pytest.ini",
            "backend/sof_week_2024_exhibitors.json",
            "backend/stopwords.json",
            "backend/test_backend_integration.py",
            "backend/test_fgamlogit.py",
            "backend/test_fixtures.py",
            "scripts/*",
            "ml/requirements.txt",
            "backup_helios_db.sh",
            "helios-check.sh",
            "ingest_international_exhibitors.py",
            "international_exhibitors.py",
            "restore_helios_db.sh",
            "tests/conftest.py",
            "tests/test_build_predemo_readiness_packet.py",
            "tests/test_evaluate_prime_time_readiness.py",
            "tests/test_gunicorn_monitoring_guard.py",
            "tests/test_helios_readiness_report.py",
            "tests/test_international_exhibitors_fixture.py",
            "tests/test_layer_integration.py",
            "tests/test_live_*.py",
            "tests/test_sprint9_audit_fixes.py",
            "tests/test_training_*.py",
            "tests/test_validation_harness.py",
        ],
    ),
    (
        "shared_fixtures_and_ui",
        "Shared frontend support, e2e harnesses, and reusable fixture packs",
        [
            "frontend/src/components/xiphos/error-boundary.tsx",
            "frontend/src/components/xiphos/loader.tsx",
            "frontend/src/components/xiphos/portfolio-utils.ts",
            "tests/e2e/",
            "fixtures/adversarial_gym/",
            "fixtures/customer_demo/",
            "fixtures/international_exhibitors/",
            "fixtures/public_html_ownership/",
            "fixtures/public_search_ownership/",
            "fixtures/rss_public_ownership/",
            "fixtures/standards/",
            "fixtures/training_run/*",
        ],
    ),
    (
        "scope_governance",
        "Repo governance and scope-control files",
        [
            "docs/reports/SCOPE_BUCKETS_2026-03-29.md",
            "docs/reports/SCOPE_MANIFEST_2026-03-29.md",
            "docs/reports/ZERO_KNOWN_PROBLEMS_CHECKLIST_2026-03-29.md",
            "docs/reports/COMMIT_SCOPE_2026-03-29.md",
            "scripts/commit_scope_tool.py",
        ],
    ),
]


def _run_git(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _current_status() -> tuple[list[str], list[str]]:
    output = _run_git("status", "--short")
    tracked: list[str] = []
    untracked: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if code == "??":
            untracked.append(path)
        else:
            tracked.append(path)
    return tracked, untracked


def _parse_tracked_sets() -> dict[str, list[str]]:
    if not SCOPE_BUCKETS.exists():
        raise FileNotFoundError(f"Missing scope bucket file: {SCOPE_BUCKETS}")

    results = {value: [] for value in TRACKED_SECTION_KEYS.values()}
    current_key: str | None = None
    for raw_line in SCOPE_BUCKETS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^### (Shipping Scope|Ops Scope|Ambient Docs)", line)
        if heading_match:
            current_key = TRACKED_SECTION_KEYS[heading_match.group(1)]
            continue
        if line.startswith("#"):
            current_key = None
            continue
        if not current_key:
            continue
        path_match = re.match(r"^- `(.+?)`$", line)
        if not path_match:
            continue
        path = path_match.group(1)
        if path.startswith(WORKSPACE_PREFIX):
            path = path[len(WORKSPACE_PREFIX):]
        results[current_key].append(path)
    return results


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def resolve_scopes() -> dict[str, object]:
    tracked_paths, untracked_paths = _current_status()
    tracked_sets = _parse_tracked_sets()

    tracked_union = set()
    for paths in tracked_sets.values():
        tracked_union.update(paths)

    tracked_actual = set(tracked_paths)
    tracked_missing = sorted(tracked_union - tracked_actual)
    tracked_extras = sorted(tracked_actual - tracked_union)

    remaining_untracked = set(untracked_paths)
    resolved_untracked: dict[str, list[str]] = {}
    overlaps: dict[str, list[str]] = {}

    for group_name, _description, patterns in UNTRACKED_GROUPS:
        matched = sorted(path for path in remaining_untracked if _matches_any(path, patterns))
        resolved_untracked[group_name] = matched
        for path in matched:
            overlaps.setdefault(path, []).append(group_name)
        remaining_untracked.difference_update(matched)

    duplicate_matches = {
        path: groups for path, groups in overlaps.items() if len(groups) > 1
    }

    return {
        "tracked_sets": tracked_sets,
        "tracked_missing": tracked_missing,
        "tracked_extras": tracked_extras,
        "untracked_groups": resolved_untracked,
        "untracked_unassigned": sorted(remaining_untracked),
        "untracked_duplicates": duplicate_matches,
    }


def _stage_paths(paths: list[str]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(prefix="helios-scope-", suffix=".index", delete=False) as handle:
        index_path = handle.name

    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = index_path
    try:
        _run_git("read-tree", "HEAD", env=env)
        if paths:
            _run_git(
                "add",
                "--all",
                "--pathspec-from-file=-",
                input_text="".join(f"{path}\n" for path in paths),
                env=env,
            )
        name_status = _run_git("diff", "--cached", "--name-status", env=env).splitlines()
        stat = _run_git("diff", "--cached", "--stat", env=env).strip()
        return {
            "file_count": len(name_status),
            "name_status": name_status,
            "stat": stat,
        }
    finally:
        try:
            os.remove(index_path)
        except FileNotFoundError:
            pass


def _verification_payload() -> dict[str, object]:
    resolved = resolve_scopes()
    verification: dict[str, object] = {
        "tracked_missing": resolved["tracked_missing"],
        "tracked_extras": resolved["tracked_extras"],
        "untracked_unassigned": resolved["untracked_unassigned"],
        "untracked_duplicates": resolved["untracked_duplicates"],
        "groups": {},
    }

    all_groups: dict[str, list[str]] = {}
    all_groups.update(resolved["tracked_sets"])  # type: ignore[arg-type]
    all_groups.update(resolved["untracked_groups"])  # type: ignore[arg-type]

    for name, paths in all_groups.items():
        verification["groups"][name] = {
            "declared_count": len(paths),
            "stage_result": _stage_paths(paths),
        }

    return verification


def _print_summary(resolved: dict[str, object]) -> None:
    print("Tracked sets:")
    tracked_sets: dict[str, list[str]] = resolved["tracked_sets"]  # type: ignore[assignment]
    for name in ("shipping_tracked", "ops_tracked", "ambient_docs"):
        print(f"  {name}: {len(tracked_sets.get(name, []))}")
    if resolved["tracked_missing"]:
        print("  tracked missing:")
        for path in resolved["tracked_missing"]:  # type: ignore[index]
            print(f"    {path}")
    if resolved["tracked_extras"]:
        print("  tracked extras:")
        for path in resolved["tracked_extras"]:  # type: ignore[index]
            print(f"    {path}")

    print("Untracked groups:")
    untracked_groups: dict[str, list[str]] = resolved["untracked_groups"]  # type: ignore[assignment]
    for group_name, description, _patterns in UNTRACKED_GROUPS:
        print(f"  {group_name}: {len(untracked_groups.get(group_name, []))}  {description}")
    if resolved["untracked_unassigned"]:
        print("  untracked unassigned:")
        for path in resolved["untracked_unassigned"]:  # type: ignore[index]
            print(f"    {path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Resolve and verify deliberate Helios commit scopes.")
    parser.add_argument(
        "command",
        choices=("list", "verify", "stage"),
        help="List resolved scopes, verify staging with alternate indexes, or stage one scope to a temp index.",
    )
    parser.add_argument("--scope", help="Scope name for the stage command.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text.")
    args = parser.parse_args(argv)

    resolved = resolve_scopes()

    if args.command == "list":
        if args.json:
            print(json.dumps(resolved, indent=2, sort_keys=True))
        else:
            _print_summary(resolved)
        return 0

    if args.command == "verify":
        payload = _verification_payload()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if payload["tracked_missing"] or payload["tracked_extras"] or payload["untracked_unassigned"] or payload["untracked_duplicates"]:
                print("Scope verification found unresolved scope drift.")
            else:
                print("Scope verification is clean.")
            for name, group_payload in payload["groups"].items():  # type: ignore[union-attr]
                stage_result = group_payload["stage_result"]
                print(f"{name}: declared={group_payload['declared_count']} staged={stage_result['file_count']}")
                if stage_result["stat"]:
                    print(stage_result["stat"])
        return 0

    if args.command == "stage":
        if not args.scope:
            parser.error("--scope is required for the stage command")
        all_groups: dict[str, list[str]] = {}
        all_groups.update(resolved["tracked_sets"])  # type: ignore[arg-type]
        all_groups.update(resolved["untracked_groups"])  # type: ignore[arg-type]
        if args.scope not in all_groups:
            parser.error(f"Unknown scope: {args.scope}")
        payload = _stage_paths(all_groups[args.scope])
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"{args.scope}: staged={payload['file_count']}")
            if payload["stat"]:
                print(payload["stat"])
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
