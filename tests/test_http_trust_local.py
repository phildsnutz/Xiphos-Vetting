import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import http_trust  # type: ignore  # noqa: E402


def test_http_trust_prefers_explicit_bundle(monkeypatch):
    monkeypatch.setenv("XIPHOS_USASPENDING_CA_BUNDLE", "~/custom-chain.pem")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(http_trust, "_install_system_truststore_if_available", lambda: calls.append("truststore") or True)

    verify_target = http_trust.resolve_verify_target(
        verify_env="XIPHOS_USASPENDING_VERIFY_SSL",
        bundle_envs=("XIPHOS_USASPENDING_CA_BUNDLE",),
    )

    assert verify_target.endswith("/custom-chain.pem")
    assert calls == []


def test_http_trust_uses_system_store_when_no_bundle_is_configured(monkeypatch):
    monkeypatch.delenv("XIPHOS_USASPENDING_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(http_trust, "_install_system_truststore_if_available", lambda: calls.append("truststore") or True)

    verify_target = http_trust.resolve_verify_target(
        verify_env="XIPHOS_USASPENDING_VERIFY_SSL",
        bundle_envs=("XIPHOS_USASPENDING_CA_BUNDLE",),
    )

    assert verify_target is True
    assert calls == ["truststore"]


def test_http_trust_can_disable_verification_explicitly(monkeypatch):
    monkeypatch.setenv("XIPHOS_USASPENDING_VERIFY_SSL", "false")

    verify_target = http_trust.resolve_verify_target(
        verify_env="XIPHOS_USASPENDING_VERIFY_SSL",
        bundle_envs=("XIPHOS_USASPENDING_CA_BUNDLE",),
    )

    assert verify_target is False
