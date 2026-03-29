import importlib.util
import pathlib


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND_CONNECTORS = REPO_ROOT / "frontend" / "src" / "lib" / "connectors.ts"
GENERATOR_SCRIPT = REPO_ROOT / "scripts" / "generate_frontend_connectors.py"


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontend_connector_registry_covers_backend_connectors():
    generator = _load_module(GENERATOR_SCRIPT)
    expected = generator.render_frontend_connector_ts()
    actual = FRONTEND_CONNECTORS.read_text(encoding="utf-8")
    assert actual == expected, "Frontend connector registry is out of sync with the canonical backend registry"
