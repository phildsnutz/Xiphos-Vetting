import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import contract_vehicle_search  # noqa: E402


def test_search_contract_vehicle_caches_identical_requests(monkeypatch):
    contract_vehicle_search.clear_contract_vehicle_search_cache()
    calls = {"prime": 0, "sub": 0, "idv": 0}

    def fake_prime(term, limit, *, verify_ssl):
        calls["prime"] += 1
        return (
            [
                {
                    "vendor_name": "Amentum Services, Inc.",
                    "award_id": "IDV-001",
                    "award_amount": 125000000,
                    "awarding_agency": "Department of the Army",
                    "role": "prime",
                    "source": "usaspending",
                }
            ],
            {"IDV-001"},
            [],
        )

    def fake_sub(term, limit, *, verify_ssl):
        calls["sub"] += 1
        return (
            [
                {
                    "vendor_name": "Torch Technologies, Inc.",
                    "award_id": "SUB-001",
                    "award_amount": 21000000,
                    "prime_recipient": "Amentum Services, Inc.",
                    "role": "subcontractor",
                    "source": "usaspending",
                }
            ],
            [],
        )

    def fake_idv(award_id, limit, *, verify_ssl):
        calls["idv"] += 1
        return (
            [
                {
                    "vendor_name": "Amentum Services, Inc.",
                    "award_id": award_id,
                    "award_amount": 188000000,
                    "awarding_agency": "Department of the Army",
                    "role": "prime",
                    "source": "usaspending_idv",
                }
            ],
            [],
        )

    monkeypatch.setattr(contract_vehicle_search, "_search_prime_awards", fake_prime)
    monkeypatch.setattr(contract_vehicle_search, "_search_subawards", fake_sub)
    monkeypatch.setattr(contract_vehicle_search, "_search_idv_children", fake_idv)
    monkeypatch.setattr(contract_vehicle_search, "_verify_ssl", lambda: True)

    first = contract_vehicle_search.search_contract_vehicle("ITEAMS", include_subs=True, limit=8)
    second = contract_vehicle_search.search_contract_vehicle("ITEAMS", include_subs=True, limit=8)

    assert first == second
    assert calls == {"prime": 1, "sub": 1, "idv": 1}
    assert first["total_primes"] == 1
    assert first["total_subs"] == 1
    assert first["unique_vendors"][0]["vendor_name"] == "Amentum Services, Inc."


def test_search_contract_vehicle_cache_key_varies_by_request_shape(monkeypatch):
    contract_vehicle_search.clear_contract_vehicle_search_cache()
    calls = {"prime": 0}

    def fake_prime(term, limit, *, verify_ssl):
        calls["prime"] += 1
        return (
            [
                {
                    "vendor_name": f"{term} Prime",
                    "award_id": f"{term}-001",
                    "award_amount": 1,
                    "role": "prime",
                    "source": "usaspending",
                }
            ],
            set(),
            [],
        )

    monkeypatch.setattr(contract_vehicle_search, "_search_prime_awards", fake_prime)
    monkeypatch.setattr(contract_vehicle_search, "_search_subawards", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(contract_vehicle_search, "_search_idv_children", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(contract_vehicle_search, "_verify_ssl", lambda: True)

    contract_vehicle_search.search_contract_vehicle("OASIS", include_subs=True, limit=8)
    after_first = calls["prime"]
    contract_vehicle_search.search_contract_vehicle("OASIS", include_subs=False, limit=8)

    assert after_first > 0
    assert calls["prime"] == after_first * 2
