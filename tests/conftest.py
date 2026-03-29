"""
Xiphos test suite configuration.

Registers custom pytest markers for environment-aware testing:
  - live_db: Tests that produce different results when running against
    the live sanctions DB (31,596 entities) vs fallback DB (27 entries).
    Use `pytest -m "not live_db"` for a clean pass in all environments.
  - fallback_only: Tests that explicitly force fallback mode and should
    not be run with live DB expectations.

Usage:
    # Run all tests (may fail on VPS live mode for DB-sensitive cases)
    pytest tests/ -v

    # Run only environment-stable tests (clean pass everywhere)
    pytest tests/ -v -m "not live_db"

    # Run only live DB tests (VPS with live SQLite only)
    pytest tests/ -v -m "live_db"
"""



def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "live_db: marks tests that behave differently with live sanctions DB "
        "(deselect with '-m \"not live_db\"')"
    )
    config.addinivalue_line(
        "markers",
        "fallback_only: marks tests that force fallback DB mode"
    )
