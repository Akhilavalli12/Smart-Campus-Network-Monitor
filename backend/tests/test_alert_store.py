from datetime import datetime, timedelta, timezone

import pytest

from app.alerts.models import Alert

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def alert(key="DEVICE_OFFLINE:cse-switch", minutes=0, **kw):
    fields = dict(type="DEVICE_OFFLINE", severity="critical", dedupe_key=key, device_id="cse-switch", device_name="CSE Switch", title="t", message="m",
                  metrics={"packet_loss_pct": 100.0, "peak": 100.0, "ip": "192.168.10.2"}, affected_device_ids=["cse-ap"], opened_at=T0 + timedelta(minutes=minutes),
                  updated_at=T0 + timedelta(minutes=minutes), last_response_at=T0)
    fields.update(kw)
    return Alert(**fields)


async def test_alerts_roundtrip_and_ordering(alert_store):
    a, b = alert(minutes=1), alert("HIGH_LATENCY:cse-ap", minutes=5, type="HIGH_LATENCY", severity="warning")
    await alert_store.insert_alerts([a, b])
    rows = await alert_store.list_alerts()
    assert [r.dedupe_key for r in rows] == ["HIGH_LATENCY:cse-ap", "DEVICE_OFFLINE:cse-switch"]  # newest first
    got = await alert_store.get_alert(a.id)
    assert got.metrics["peak"] == 100.0 and got.affected_device_ids == ["cse-ap"] and got.opened_at == a.opened_at and got.acknowledged is False
    assert await alert_store.get_alert("nope") is None


async def test_filters_and_update(alert_store):
    a, b = alert(minutes=1), alert("HIGH_LATENCY:x", minutes=2, type="HIGH_LATENCY", severity="warning")
    await alert_store.insert_alerts([a, b])
    assert await alert_store.update_alert(a.id, {"state": "resolved", "resolved_at": T0 + timedelta(minutes=9)})
    assert [r.id for r in await alert_store.list_alerts(state="open")] == [b.id]
    assert [r.id for r in await alert_store.list_alerts(state="resolved")] == [a.id]
    assert [r.id for r in await alert_store.list_alerts(type="HIGH_LATENCY")] == [b.id]
    assert len(await alert_store.list_alerts(limit=1)) == 1
    assert (await alert_store.get_alert(a.id)).resolved_at == T0 + timedelta(minutes=9)


async def test_update_refuses_identity_fields_and_unknown_ids(alert_store):
    a = alert()
    await alert_store.insert_alerts([a])
    for forbidden in ("dedupe_key", "type", "device_id", "opened_at", "_id", "id"):
        with pytest.raises(ValueError, match="not updatable"):
            await alert_store.update_alert(a.id, {forbidden: "x"})
    assert await alert_store.update_alert("ghost", {"state": "resolved"}) is False


async def test_indexes_on_the_real_driver(alert_store):
    from app.alerts.store import MongoAlertStore

    if not isinstance(alert_store, MongoAlertStore):
        pytest.skip("MongoDB only")
    await alert_store.ensure_indexes()
    assert {"state_opened", "dedupe_key"} <= set((await alert_store._alerts.index_information()).keys())
