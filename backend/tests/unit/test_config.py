import pytest

from config import validate_environment


def test_valid_environment_passes(monkeypatch):
    # conftest already sets the required vars; a clean pass must not raise.
    validate_environment("api")
    validate_environment("worker")


def test_missing_required_vars_are_all_reported_at_once(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CLERK_ISSUER", raising=False)

    with pytest.raises(RuntimeError) as exc:
        validate_environment("api")

    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "CLERK_ISSUER" in message  # aggregated — not just the first failure


def test_worker_does_not_require_clerk(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    validate_environment("worker")  # must not raise — the worker serves no HTTP


def test_malformed_numeric_tunable_fails_loudly(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_TURNS", "eight")

    with pytest.raises(RuntimeError) as exc:
        validate_environment("api")

    assert "MAX_CONCURRENT_TURNS" in str(exc.value)
