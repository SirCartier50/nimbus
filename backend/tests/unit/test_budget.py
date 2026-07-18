import pytest

import budget


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    budget.clear_local_counts()
    monkeypatch.delenv("REDIS_URL", raising=False)  # exercise the in-process path
    yield
    budget.clear_local_counts()


@pytest.mark.asyncio
async def test_turns_are_allowed_until_the_daily_limit(monkeypatch):
    monkeypatch.setenv("DAILY_TURN_LIMIT", "2")

    assert await budget.consume_daily_turn("u1") == (True, 1, 2)
    assert await budget.consume_daily_turn("u1") == (True, 2, 2)
    allowed, used, limit = await budget.consume_daily_turn("u1")
    assert allowed is False and used == 2 and limit == 2


@pytest.mark.asyncio
async def test_budgets_are_per_user(monkeypatch):
    monkeypatch.setenv("DAILY_TURN_LIMIT", "1")

    assert (await budget.consume_daily_turn("u1"))[0] is True
    assert (await budget.consume_daily_turn("u1"))[0] is False
    assert (await budget.consume_daily_turn("u2"))[0] is True  # unaffected


@pytest.mark.asyncio
async def test_zero_limit_disables_the_cap(monkeypatch):
    monkeypatch.setenv("DAILY_TURN_LIMIT", "0")
    for _ in range(50):
        assert (await budget.consume_daily_turn("u1"))[0] is True


@pytest.mark.asyncio
async def test_new_utc_day_resets_the_budget(monkeypatch):
    monkeypatch.setenv("DAILY_TURN_LIMIT", "1")
    assert (await budget.consume_daily_turn("u1"))[0] is True
    assert (await budget.consume_daily_turn("u1"))[0] is False

    monkeypatch.setattr(budget, "_today", lambda: "29990101")
    assert (await budget.consume_daily_turn("u1"))[0] is True


def test_seconds_until_utc_midnight_is_sane():
    s = budget.seconds_until_utc_midnight()
    assert 1 <= s <= 86400
