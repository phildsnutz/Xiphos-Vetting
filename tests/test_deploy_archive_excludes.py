import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_PATH = ROOT / "deploy.py"
SPEC = importlib.util.spec_from_file_location("helios_deploy", DEPLOY_PATH)
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def test_should_exclude_git_and_env_paths():
    assert deploy.should_exclude(".git") is True
    assert deploy.should_exclude("./.git") is True
    assert deploy.should_exclude(".git/config") is True
    assert deploy.should_exclude("./.env") is True
    assert deploy.should_exclude("frontend/node_modules/react/index.js") is True


def test_should_not_exclude_normal_source_paths():
    assert deploy.should_exclude("backend/server.py") is False
    assert deploy.should_exclude("frontend/src/App.tsx") is False
    assert deploy.should_exclude("fixtures/mission_threads/contested_sustainment_threads_v1.json") is False
