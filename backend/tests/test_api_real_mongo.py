"""End-to-end through the real FastAPI app and a real MongoDB-protocol server (skipped if none is running)."""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.main import create_app
from app.network_model.seed import seed_database
from app.network_model.store import MongoNetworkStore
from tests.conftest import TEST_MONGODB_URI, _mongo_reachable


@pytest.fixture
def mongo_client(monkeypatch):
    if not asyncio.run(_mongo_reachable()):
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("MONGODB_URI", TEST_MONGODB_URI)
    monkeypatch.setenv("MONGODB_DB_NAME", db_name)
    get_settings.cache_clear()

    async def prepare():
        client = AsyncMongoClient(TEST_MONGODB_URI, tz_aware=True)
        store = MongoNetworkStore(client[db_name])
        await store.ensure_indexes()
        await seed_database(store)
        await client.close()

    asyncio.run(prepare())
    with TestClient(create_app()) as client:
        yield client

    async def cleanup():
        client = AsyncMongoClient(TEST_MONGODB_URI)
        await client.drop_database(db_name)
        await client.close()

    asyncio.run(cleanup())
    get_settings.cache_clear()


def test_full_stack_read_register_delete(mongo_client):
    assert len(mongo_client.get("/api/devices").json()) == 17
    assert mongo_client.get("/api/health").json()["status"] == "ok"
    created = mongo_client.post("/api/devices", json={
        "name": "Admin PC 3", "type": "pc", "ip": "192.168.30.103",
        "subnet_id": "admin-net", "block": "admin", "parent_id": "admin-switch",
    })
    assert created.status_code == 201
    assert mongo_client.post("/api/devices", json={
        "name": "Dup", "type": "pc", "ip": "192.168.30.103",
        "subnet_id": "admin-net", "block": "admin", "parent_id": "admin-switch",
    }).status_code == 409
    topo = mongo_client.get("/api/topology").json()
    assert (len(topo["nodes"]), len(topo["edges"])) == (18, 17)
    assert mongo_client.delete("/api/devices/admin-pc-3").status_code == 204
    assert len(mongo_client.get("/api/links").json()) == 16
