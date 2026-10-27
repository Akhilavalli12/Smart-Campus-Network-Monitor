"""MonitoringStore + device-update contract: in-memory AND the real driver."""
from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent, Thresholds
from app.network_model.seed import seed_database
from app.network_model.store import MongoNetworkStore

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def measurement(device_id="cse-switch", minutes=0, **kw):
    fields = dict(device_id=device_id, ts=T0 + timedelta(minutes=minutes), source="simulated", backend="simulator", target="simulated",
                  sent=5, received=5, loss_pct=0.0, rtt_min_ms=7.0, rtt_avg_ms=8.0, rtt_max_ms=9.0, jitter_ms=1.0, status="online")
    fields.update(kw)
    return Measurement(**fields)


def event(device_id="cse-switch", minutes=0, **kw):
    fields = dict(ts=T0 + timedelta(minutes=minutes), device_id=device_id, device_name="CSE Switch",
                  from_status="online", to_status="offline", reason="no reply for 3 consecutive probe cycles")
    fields.update(kw)
    return StatusEvent(**fields)


async def test_measurements_come_back_oldest_first_and_are_filtered_by_device(monitoring_store):
    await monitoring_store.insert_measurements([measurement(minutes=m) for m in (3, 1, 2)] + [measurement("cse-ap", minutes=0)])
    rows = await monitoring_store.list_measurements("cse-switch")
    assert [r.ts for r in rows] == [T0 + timedelta(minutes=m) for m in (1, 2, 3)]
    assert all(r.device_id == "cse-switch" for r in rows)
    assert rows[0].rtt_avg_ms == 8.0 and rows[0].status == "online"


async def test_measurement_limit_keeps_the_most_recent_rows(monitoring_store):
    await monitoring_store.insert_measurements([measurement(minutes=m) for m in range(10)])
    rows = await monitoring_store.list_measurements("cse-switch", limit=3)
    assert [r.ts for r in rows] == [T0 + timedelta(minutes=m) for m in (7, 8, 9)]


async def test_measurement_since_filter(monitoring_store):
    await monitoring_store.insert_measurements([measurement(minutes=m) for m in range(10)])
    rows = await monitoring_store.list_measurements("cse-switch", since=T0 + timedelta(minutes=6))
    assert len(rows) == 4 and rows[0].ts == T0 + timedelta(minutes=6)


async def test_measurement_with_null_values_roundtrips(monitoring_store):
    dead = measurement(received=0, loss_pct=100.0, rtt_min_ms=None, rtt_avg_ms=None, rtt_max_ms=None, jitter_ms=None, status="offline")
    failed = measurement(minutes=1, sent=0, received=0, loss_pct=None, rtt_min_ms=None, rtt_avg_ms=None, rtt_max_ms=None, jitter_ms=None, error="tool failure")
    await monitoring_store.insert_measurements([dead, failed])
    rows = await monitoring_store.list_measurements("cse-switch")
    assert rows[0].rtt_avg_ms is None and rows[0].loss_pct == 100.0
    assert rows[1].error == "tool failure" and rows[1].loss_pct is None


async def test_inserting_nothing_is_fine(monitoring_store):
    await monitoring_store.insert_measurements([])
    await monitoring_store.insert_events([])


async def test_events_newest_first_with_device_filter_and_limit(monitoring_store):
    await monitoring_store.insert_events([event(minutes=m) for m in (1, 3, 2)] + [event("cse-ap", minutes=9, to_status="unreachable", caused_by="cse-switch")])
    everything = await monitoring_store.list_events()
    assert [e.device_id for e in everything][0] == "cse-ap"
    only_switch = await monitoring_store.list_events(device_id="cse-switch")
    assert [e.ts for e in only_switch] == [T0 + timedelta(minutes=m) for m in (3, 2, 1)]
    assert len(await monitoring_store.list_events(limit=2)) == 2
    ap = (await monitoring_store.list_events(device_id="cse-ap"))[0]
    assert ap.caused_by == "cse-switch" and ap.id  # ids survive the roundtrip


async def test_config_defaults_then_roundtrip_and_replace(monitoring_store):
    assert await monitoring_store.get_config() is None
    first = MonitoringConfig(poll_interval_s=7, failure_confirmations=4, thresholds=Thresholds(latency_warn_ms=50, latency_crit_ms=120))
    await monitoring_store.save_config(first)
    assert await monitoring_store.get_config() == first
    second = MonitoringConfig(poll_interval_s=9)
    await monitoring_store.save_config(second)
    assert await monitoring_store.get_config() == second  # replaced, not merged


# ---------- NetworkStore.update_device_fields contract ----------
async def test_update_device_fields_sets_nested_and_null_values(store):
    await seed_database(store)
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    latest = {"at": now, "source": "simulated", "sent": 5, "received": 5, "rtt_avg_ms": 8.5}
    assert await store.update_device_fields("cse-switch", {"status": "online", "last_seen": now, "latest": latest, "caused_by": None, "consecutive_failures": 2})
    device = await store.get_device("cse-switch")
    assert device.status == "online" and device.consecutive_failures == 2
    assert device.last_seen == now and device.latest.rtt_avg_ms == 8.5 and device.latest.at == now
    await store.update_device_fields("cse-switch", {"up_since": now})
    await store.update_device_fields("cse-switch", {"up_since": None})
    assert (await store.get_device("cse-switch")).up_since is None


async def test_update_device_fields_refuses_identity_fields(store):
    await seed_database(store)
    for forbidden in ("ip", "id", "_id", "parent_id", "type", "name"):
        with pytest.raises(ValueError, match="not updatable"):
            await store.update_device_fields("cse-switch", {forbidden: "x"})
    assert (await store.get_device("cse-switch")).ip == "192.168.10.2"


async def test_update_unknown_device_returns_false(store):
    await seed_database(store)
    assert await store.update_device_fields("ghost", {"status": "online"}) is False


async def test_sim_state_roundtrips_through_update(store):
    await seed_database(store)
    await store.update_device_fields("cse-ap", {"sim_state": {"fault": "high_latency", "params": {"rtt_ms": 300.0}}})
    state = (await store.get_device("cse-ap")).sim_state
    assert (state.fault, state.params) == ("high_latency", {"rtt_ms": 300.0})


# ---------- real-driver only: index creation ----------
async def test_monitoring_indexes_are_created_on_the_real_driver(monitoring_store):
    from app.monitoring.store import MongoMonitoringStore

    if not isinstance(monitoring_store, MongoMonitoringStore):
        pytest.skip("index creation only applies to MongoDB")
    await monitoring_store.ensure_indexes()  # must not raise even if the server lacks TTL support
    names = set((await monitoring_store._measurements.index_information()).keys())
    assert "device_ts" in names
    if "ttl_measurement_ts" in names:
        info = (await monitoring_store._measurements.index_information())["ttl_measurement_ts"]
        assert info["expireAfterSeconds"] == 26 * 3600
    await monitoring_store.ensure_indexes()  # idempotent
