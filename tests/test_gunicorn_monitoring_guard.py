import importlib.util
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
GUNICORN_CONF = REPO_ROOT / "backend" / "gunicorn.conf.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gunicorn_conf_test", GUNICORN_CONF)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_post_fork_disables_scheduler_when_runtime_worker_count_is_multi(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("XIPHOS_ENABLE_PERIODIC_MONITORING", "true")

    started = {"called": False}

    class FakeLog:
        def __init__(self):
            self.messages = []

        def warning(self, message, *args):
            self.messages.append(message % args)

        def info(self, *_args, **_kwargs):
            started["called"] = True

    class FakeServer:
        def __init__(self):
            self.cfg = type("Cfg", (), {"workers": 2})()
            self.log = FakeLog()

    monkeypatch.setitem(
        __import__("sys").modules,
        "server",
        SimpleNamespace(_maybe_start_periodic_monitoring=lambda: started.update(called=True)),
    )

    module.post_fork(FakeServer(), type("Worker", (), {"pid": 999})())

    assert started["called"] is False


def test_post_fork_starts_scheduler_for_single_worker(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("XIPHOS_ENABLE_PERIODIC_MONITORING", "true")

    started = {"called": False}

    class FakeLog:
        def warning(self, *_args, **_kwargs):
            raise AssertionError("warning should not be called for single worker")

        def info(self, *_args, **_kwargs):
            pass

    class FakeServer:
        def __init__(self):
            self.cfg = type("Cfg", (), {"workers": 1})()
            self.log = FakeLog()

    monkeypatch.setitem(
        __import__("sys").modules,
        "server",
        SimpleNamespace(_maybe_start_periodic_monitoring=lambda: started.update(called=True)),
    )

    module.post_fork(FakeServer(), type("Worker", (), {"pid": 111})())

    assert started["called"] is True
