import importlib.util
from pathlib import Path

import requests


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_training_cohort.py"
SPEC = importlib.util.spec_from_file_location("run_training_cohort", SCRIPT_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(runner)


class DummyResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class DummySession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.headers = {}

    def request(self, method, url, **kwargs):
        assert self._responses, "No more dummy responses configured"
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


def _make_client(responses):
    client = runner.TrainingClient.__new__(runner.TrainingClient)
    client.host = "http://example.test"
    client.session = DummySession(responses)
    client._email = "analyst@example.test"
    client._password = "secret"
    client._token = ""
    return client


def test_training_client_reauths_and_retries_on_401():
    client = _make_client(
        [
            DummyResponse(401),
            DummyResponse(200, {"cases": [{"id": "c-1", "vendor_name": "Vendor A"}]}),
        ]
    )
    login_calls = []

    def fake_login(email, password):
        login_calls.append((email, password))

    client._login = fake_login

    cases = client.list_cases()

    assert login_calls == [("analyst@example.test", "secret")]
    assert cases[0]["vendor_name"] == "Vendor A"


def test_training_client_raises_if_retry_still_unauthorized():
    client = _make_client([DummyResponse(401), DummyResponse(401)])
    login_calls = []

    def fake_login(email, password):
        login_calls.append((email, password))

    client._login = fake_login

    try:
        client.create_case("Vendor A", "US")
        raise AssertionError("Expected HTTPError")
    except requests.HTTPError as exc:
        assert exc.response.status_code == 401

    assert login_calls == [("analyst@example.test", "secret")]


def test_canonicalize_seed_name_splits_pipe_delimited_aliases():
    canonical, aliases = runner.canonicalize_seed_name(
        "Avon Protection | Team Wendy Ceradyne | Team Wendy"
    )

    assert canonical == "Avon Protection"
    assert aliases == ["Team Wendy Ceradyne", "Team Wendy"]


def test_create_case_uses_canonical_name_and_seed_metadata():
    client = runner.TrainingClient.__new__(runner.TrainingClient)
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return DummyResponse(201, {"case_id": "c-1234"})

    client._request = fake_request

    payload = client.create_case(
        "Avon Protection | Team Wendy Ceradyne | Team Wendy",
        "US",
        seed_metadata={"cohort_name": "Avon Protection | Team Wendy Ceradyne | Team Wendy"},
    )

    assert payload["case_id"] == "c-1234"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/cases"
    assert captured["json"]["name"] == "Avon Protection"
    assert captured["json"]["seed_metadata"]["raw_name"] == "Avon Protection | Team Wendy Ceradyne | Team Wendy"
    assert captured["json"]["seed_metadata"]["aliases"] == ["Team Wendy Ceradyne", "Team Wendy"]


def test_training_client_login_uses_bearer_token_when_provided():
    client = runner.TrainingClient.__new__(runner.TrainingClient)
    client.session = DummySession([])
    client._token = "token-123"

    client._login("analyst@example.test", "secret")

    assert client.token == "token-123"
    assert client.session.headers["Authorization"] == "Bearer token-123"


def test_training_client_retries_transient_connection_failures(monkeypatch):
    client = _make_client(
        [
            requests.ConnectionError("connection reset by peer"),
            DummyResponse(200, {"cases": [{"id": "c-1", "vendor_name": "Vendor A"}]}),
        ]
    )
    client._login = lambda *_: None
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    cases = client.list_cases()

    assert cases[0]["vendor_name"] == "Vendor A"
