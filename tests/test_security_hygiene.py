import importlib.util
from pathlib import Path


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("check_security_hygiene", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_workspace_security_hygiene_guard():
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(repo_root / "scripts" / "check_security_hygiene.py")

    violations = module.check_workspace()
    assert violations == []
