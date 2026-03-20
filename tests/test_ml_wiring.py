import importlib
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
