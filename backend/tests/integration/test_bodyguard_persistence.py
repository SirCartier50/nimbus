"""Bodyguard's durable store against a real Postgres. The whole point of the
persistence rework: a user's alerts/logs/patrol bookkeeping must live in the DB
(and therefore survive restarts and cross process boundaries), never in RAM."""
import pytest
from sqlalchemy import select

from agents import bodyguard
from db.models import BodyguardAlert, BodyguardLog, BodyguardStatus, User
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]


async def _make_user(db, clerk_id="clerk-bg-test"):
    user = User(clerk_user_id=clerk_id)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _buffer_with_findings():
    buffer = bodyguard._new_patrol_buffer()
    bodyguard._log(buffer, "Patrol: 1 running Nimbus instance(s)")
    bodyguard._alert(buffer, "Non-free-tier instance running", "warning")
    buffer["instances_stopped"] = 1
    buffer["sub_resources"]["volumes"] = [{"volume_id": "vol-1"}]
    return buffer


async def test_persist_patrol_writes_alerts_logs_and_status(db_session):
    user = await _make_user(db_session)
    await bodyguard._persist_patrol(db_session, user.id, _buffer_with_findings())

    alerts = (await db_session.scalars(select(BodyguardAlert))).all()
    logs = (await db_session.scalars(select(BodyguardLog))).all()
    status = await db_session.get(BodyguardStatus, user.id)

    assert [a.message for a in alerts] == ["Non-free-tier instance running"]
    assert alerts[0].read is False and alerts[0].severity == "warning"
    assert [e.message for e in logs] == ["Patrol: 1 running Nimbus instance(s)"]
    assert status.instances_stopped == 1
    assert status.last_check is not None
    assert status.sub_resources["volumes"] == [{"volume_id": "vol-1"}]


async def test_instances_stopped_accumulates_across_patrols(db_session):
    user = await _make_user(db_session)
    await bodyguard._persist_patrol(db_session, user.id, _buffer_with_findings())
    await bodyguard._persist_patrol(db_session, user.id, _buffer_with_findings())

    status = await db_session.get(BodyguardStatus, user.id)
    assert status.instances_stopped == 2


async def test_get_status_reads_back_what_the_patrol_wrote(db_session):
    user = await _make_user(db_session)
    await bodyguard._persist_patrol(db_session, user.id, _buffer_with_findings())

    status = await bodyguard.get_status(db_session, user.id)

    # last_check is fresh, so the status must read as running even though this
    # process hosts no daemon — that's how the API stays truthful once the
    # patrol moves to its own worker.
    assert status["running"] is True
    assert status["instances_stopped_total"] == 1
    assert [e["message"] for e in status["recent_logs"]] == ["Patrol: 1 running Nimbus instance(s)"]
    assert len(status["unread_alerts"]) == 1
    assert status["all_alerts"][0]["message"] == "Non-free-tier instance running"
    assert status["sub_resources"]["volumes"] == [{"volume_id": "vol-1"}]


async def test_get_status_for_never_patrolled_user_is_empty_not_erroring(db_session):
    user = await _make_user(db_session)
    status = await bodyguard.get_status(db_session, user.id)

    assert status["running"] is False
    assert status["last_check"] is None
    assert status["instances_stopped_total"] == 0
    assert status["recent_logs"] == [] and status["all_alerts"] == []
    assert status["sub_resources"] == {"volumes": [], "elastic_ips": [], "snapshots": []}


async def test_alerts_and_read_marking_are_scoped_per_user(db_session):
    user_a = await _make_user(db_session, "clerk-user-a")
    user_b = await _make_user(db_session, "clerk-user-b")
    await bodyguard._persist_patrol(db_session, user_a.id, _buffer_with_findings())

    assert len(await bodyguard.get_alerts(db_session, user_a.id)) == 1
    assert await bodyguard.get_alerts(db_session, user_b.id) == []

    alert_id = (await bodyguard.get_alerts(db_session, user_a.id))[0]["id"]

    # Wrong user marking the right alert id must be a no-op.
    await bodyguard.mark_alert_read(db_session, user_b.id, alert_id)
    assert (await bodyguard.get_alerts(db_session, user_a.id))[0]["read"] is False

    await bodyguard.mark_alert_read(db_session, user_a.id, alert_id)
    assert (await bodyguard.get_alerts(db_session, user_a.id))[0]["read"] is True


async def test_mark_alert_read_tolerates_garbage_ids(db_session):
    user = await _make_user(db_session)
    # Pre-migration ids looked like "alert-1720000000000"; must not raise.
    await bodyguard.mark_alert_read(db_session, user.id, "alert-1720000000000")
    await bodyguard.mark_alert_read(db_session, user.id, None)


async def test_prune_drops_only_old_logs(db_session):
    from datetime import datetime, timedelta, timezone

    user = await _make_user(db_session)
    old = BodyguardLog(
        user_id=user.id, level="info", message="ancient",
        created_at=datetime.now(timezone.utc) - timedelta(days=bodyguard.LOG_RETENTION_DAYS + 1),
    )
    fresh = BodyguardLog(user_id=user.id, level="info", message="fresh")
    db_session.add_all([old, fresh])
    await db_session.commit()

    await bodyguard._prune_old_logs(db_session)

    remaining = (await db_session.scalars(select(BodyguardLog))).all()
    assert [e.message for e in remaining] == ["fresh"]
