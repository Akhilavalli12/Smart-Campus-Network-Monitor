import asyncio
import os
import uuid

# Must be set before the app reads settings: keep tests from touching a real database at startup.
os.environ.setdefault("ENSURE_INDEXES_ON_STARTUP", "false")
os.environ.setdefault("MONITORING_ENABLED", "false")  # tests drive the engines by hand
os.environ.setdefault("TRAFFIC_ENABLED", "false")
os.environ.setdefault("ALERTS_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.api.dependencies import get_alert_store, get_monitoring_store, get_mongo, get_store, get_traffic_store
from app.db import DatabaseStatus
from app.main import create_app
from app.network_model.seed import seed_database
from app.network_model.store import MongoNetworkStore
from app.monitoring.store import MongoMonitoringStore
from app.alerts.store import MongoAlertStore
from app.traffic.store import MongoTrafficStore
from tests.fakes import InMemoryAlertStore, DownAlertStore, DownMonitoringStore, DownStore, DownTrafficStore, InMemoryMonitoringStore, InMemoryNetworkStore, InMemoryTrafficStore

TEST_MONGODB_URI = os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017")


class FakeMongo:
    """Stands in for MongoManager so API tests do not need a database."""

    def __init__(self, status: DatabaseStatus) -> None:
        self._status = status

    async def ping(self) -> DatabaseStatus:
        return self._status


@pytest.fixture
def make_client():
    clients: list[TestClient] = []

    def _make(status: DatabaseStatus) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_mongo] = lambda: FakeMongo(status)
        client = TestClient(app)
        client.__enter__()  # runs the lifespan
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


_REACHABLE_CACHE: dict[str, bool] = {}


async def _mongo_reachable() -> bool:
    """Probe once per test session so skipped tests do not each wait for a timeout."""
    if TEST_MONGODB_URI not in _REACHABLE_CACHE:
        _REACHABLE_CACHE[TEST_MONGODB_URI] = await _probe_mongo()
    return _REACHABLE_CACHE[TEST_MONGODB_URI]


async def _probe_mongo() -> bool:
    client = AsyncMongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=500)
    try:
        await client.admin.command("ping")
        return True
    except Exception:
        return False
    finally:
        await client.close()


@pytest.fixture(params=["memory", "mongo"])
async def store(request):
    """Runs each contract test against the in-memory store AND a real MongoDB-protocol server."""
    if request.param == "memory":
        yield InMemoryNetworkStore()
        return
    if not await _mongo_reachable():
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    client = AsyncMongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2000, tz_aware=True)
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    mongo_store = MongoNetworkStore(client[db_name])
    await mongo_store.ensure_indexes()
    try:
        yield mongo_store
    finally:
        await client.drop_database(db_name)
        await client.close()


@pytest.fixture(params=["memory", "mongo"])
async def monitoring_store(request):
    """MonitoringStore contract: in-memory AND the real driver (skipped when no server is reachable)."""
    if request.param == "memory":
        yield InMemoryMonitoringStore()
        return
    if not await _mongo_reachable():
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    client = AsyncMongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2000, tz_aware=True)
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    mongo_store = MongoMonitoringStore(client[db_name], retention_hours=26)
    try:
        yield mongo_store
    finally:
        await client.drop_database(db_name)
        await client.close()


@pytest.fixture(params=["memory", "mongo"])
async def traffic_store(request):
    """TrafficStore contract: in-memory AND the real driver (skipped when no server is reachable)."""
    if request.param == "memory":
        yield InMemoryTrafficStore()
        return
    if not await _mongo_reachable():
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    client = AsyncMongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2000, tz_aware=True)
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    mongo_store = MongoTrafficStore(client[db_name], retention_hours=26)
    try:
        yield mongo_store
    finally:
        await client.drop_database(db_name)
        await client.close()


@pytest.fixture(params=["memory", "mongo"])
async def alert_store(request):
    """AlertStore contract: in-memory AND the real driver (skipped when no server is reachable)."""
    if request.param == "memory":
        yield InMemoryAlertStore()
        return
    if not await _mongo_reachable():
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    client = AsyncMongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2000, tz_aware=True)
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    mongo_store = MongoAlertStore(client[db_name])
    try:
        yield mongo_store
    finally:
        await client.drop_database(db_name)
        await client.close()


@pytest.fixture
def seeded_client():
    """API client backed by an in-memory store pre-loaded with the demo campus."""
    memory = InMemoryNetworkStore()
    asyncio.run(seed_database(memory))
    app = create_app()
    app.dependency_overrides[get_store] = lambda: memory
    client = TestClient(app)
    client.__enter__()
    client.store = memory
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def down_client():
    app = create_app()
    app.dependency_overrides[get_store] = lambda: DownStore()
    app.dependency_overrides[get_monitoring_store] = lambda: DownMonitoringStore()
    app.dependency_overrides[get_traffic_store] = lambda: DownTrafficStore()
    app.dependency_overrides[get_alert_store] = lambda: DownAlertStore()
    client = TestClient(app)
    client.__enter__()
    yield client
    client.__exit__(None, None, None)
