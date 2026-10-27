"""The demo-history generator: real engines in fast-forward, then written to the database."""
import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.demo.backfill import INCIDENTS, generate_history, write_history
from app.main import create_app
from tests.conftest import TEST_MONGODB_URI, _mongo_reachable

END = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def history():
    return asyncio.run(generate_history(end=END, hours=10, step_s=60))


def test_history_covers_the_requested_period_with_regular_samples(history):
    assert history.cycles == 601 and history.end == END and (history.end - history.start).total_seconds() == 36000
    rows = [m for m in history.monitoring.measurements if m.device_id == "cse-switch"]
    assert len(rows) == 601
    gaps = {(b.ts - a.ts).total_seconds() for a, b in zip(rows, rows[1:])}
    assert gaps == {60.0}
    assert rows[0].ts == history.start and rows[-1].ts == END


def test_history_is_labelled_as_demo_data_never_as_real(history):
    sources = {(m.source, m.backend) for m in history.monitoring.measurements}
    assert sources == {("simulated", "simulator"), ("simulated", "demo-backfill")}  # even the Internet node is not claimed as REAL
    assert all(s.source == "simulated" for s in history.traffic.samples)


def test_incidents_inside_the_period_appear_as_alerts_and_all_are_resolved(history):
    alerts = list(history.alerts.alerts.values())
    offline = sorted(a.device_id for a in alerts if a.type == "DEVICE_OFFLINE")
    assert offline == ["cse-switch", "library-switch"]  # the two outages within the last 10 hours
    assert any(a.type == "HIGH_LATENCY" and a.device_id == "cse-server" for a in alerts)
    assert all(a.state == "resolved" for a in alerts)
    switch_alert = next(a for a in alerts if a.device_id == "cse-switch" and a.type == "DEVICE_OFFLINE")
    assert len(switch_alert.affected_device_ids) == 5 and switch_alert.metrics["peak"] == 100.0
    assert 10 <= (switch_alert.resolved_at - switch_alert.opened_at).total_seconds() / 60 <= 14  # injected for 12 minutes


def test_no_false_alarms_outside_the_incidents(history):
    expected_devices = {"cse-switch", "library-switch", "cse-server"}
    noisy = [a for a in history.alerts.alerts.values() if a.device_id not in expected_devices and a.type != "HIGH_UTILIZATION"]
    assert noisy == []


def test_the_network_ends_healthy_with_no_faults_left_behind(history):
    assert {d.status for d in history.network.devices.values()} == {"online"}
    assert all(d.sim_state.fault == "none" for d in history.network.devices.values())


def test_traffic_history_shows_daily_variation_and_all_links(history):
    by_link = Counter(s.ref_id for s in history.traffic.samples)
    assert len(by_link) == 16 and set(by_link.values()) == {600}
    rates = [s.rx_mbps for s in history.traffic.samples if s.ref_id == "internet--edge-router"]
    assert max(rates) > min(rates) * 1.1  # not a flat line


def test_generation_is_reproducible():
    a = asyncio.run(generate_history(end=END, hours=3, step_s=120))
    b = asyncio.run(generate_history(end=END, hours=3, step_s=120))
    assert [m.rtt_avg_ms for m in a.monitoring.measurements][:200] == [m.rtt_avg_ms for m in b.monitoring.measurements][:200]


def test_incident_timeline_is_sane():
    assert len(INCIDENTS) == 6 and {i.fault for i in INCIDENTS} == {"offline", "high_latency", "packet_loss", "congestion"}


# ---------- written to a real database and served by the real API ----------
@pytest.fixture
def database(monkeypatch):
    if not asyncio.run(_mongo_reachable()):
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("MONGODB_URI", TEST_MONGODB_URI)
    monkeypatch.setenv("MONGODB_DB_NAME", db_name)
    get_settings.cache_clear()
    yield db_name

    async def cleanup():
        client = AsyncMongoClient(TEST_MONGODB_URI)
        await client.drop_database(db_name)
        await client.close()

    asyncio.run(cleanup())
    get_settings.cache_clear()


def test_history_is_written_to_mongodb_and_served_by_the_api(database):
    history = asyncio.run(generate_history(hours=3, step_s=60))  # ends 'now' so the API's last-N-hours queries include it
    async def load():
        from app.network_model.seed import seed_database
        from app.network_model.store import MongoNetworkStore

        client = AsyncMongoClient(TEST_MONGODB_URI, tz_aware=True)
        try:
            await seed_database(MongoNetworkStore(client[database]))
            info = await write_history(client[database], history)
            info_again = await write_history(client[database], history)  # replacing, not appending
            return info, info_again, await client[database]["measurements"].count_documents({})
        finally:
            await client.close()

    info, again, stored = asyncio.run(load())
    assert info["measurements"] == stored == again["measurements"] and info["alerts"] == len(history.alerts.alerts)
    with TestClient(create_app()) as client:
        summary = client.get("/api/dashboard/summary").json()
        assert summary["devices"]["online"] == 17 and summary["demo_history_loaded_at"] is not None and summary["active_alerts"] == 0
        assert len(client.get("/api/alerts", params={"state": "resolved"}).json()) == info["alerts"]
        points = client.get("/api/devices/library-switch/history", params={"hours": 48, "bucket_s": 120}).json()
        assert len(points) > 50 and "offline" in {p["status"] for p in points}  # the 2-hours-ago outage survives bucketing
        blocks = client.get("/api/traffic/blocks/history", params={"hours": 48, "bucket_s": 600}).json()
        assert len(blocks) > 15 and set(blocks[0]["blocks"]) == {"cse", "library", "admin"}
        assert len(client.get("/api/events", params={"limit": 500}).json()) == len(history.monitoring.events)
