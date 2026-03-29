import importlib
import importlib.util
import os
import sys


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_local_model_auto_detects_without_env(monkeypatch):
    monkeypatch.delenv("XIPHOS_ML_MODEL_DIR", raising=False)

    import ml.inference as inference

    inference = importlib.reload(inference)
    assert inference.is_model_available() is True
    assert inference.MODEL_DIR.endswith(os.path.join("ml", "model"))


def test_media_connectors_enable_ml_with_local_package(monkeypatch):
    monkeypatch.delenv("XIPHOS_ML_MODEL_DIR", raising=False)

    google_news = importlib.import_module("osint.google_news")
    gdelt_media = importlib.import_module("osint.gdelt_media")

    google_news = importlib.reload(google_news)
    gdelt_media = importlib.reload(gdelt_media)

    assert google_news._ml_available is True
    assert gdelt_media._ml_available is True


def test_media_connectors_disable_ml_when_runtime_dependencies_missing(monkeypatch):
    monkeypatch.delenv("XIPHOS_ML_MODEL_DIR", raising=False)

    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name, package=None):
        if name in {"torch", "transformers", "safetensors"}:
            return None
        return original_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    import ml.inference as inference
    inference = importlib.reload(inference)
    assert inference.is_model_available() is False
    assert inference.get_runtime_status()["runtime_deps_available"] is False

    google_news = importlib.import_module("osint.google_news")
    gdelt_media = importlib.import_module("osint.gdelt_media")

    google_news = importlib.reload(google_news)
    gdelt_media = importlib.reload(gdelt_media)

    assert google_news._ml_available is False
    assert gdelt_media._ml_available is False
