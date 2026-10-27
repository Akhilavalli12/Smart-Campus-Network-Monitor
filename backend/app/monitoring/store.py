"""Persistence for measurements, status events and runtime monitoring configuration."""
import logging
from datetime import datetime
from typing import Protocol

from pymongo.asynchronous.database import AsyncDatabase

from app.db.ttl import ensure_ttl_index
from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent

logger = logging.getLogger(__name__)

CONFIG_DOC_ID = "monitoring"
TTL_INDEX_NAME = "ttl_measurement_ts"


class MonitoringStore(Protocol):
    async def insert_measurements(self, measurements: list[Measurement]) -> None: ...
    async def list_measurements(self, device_id: str, *, since: datetime | None = None, limit: int = 500) -> list[Measurement]: ...
    async def insert_events(self, events: list[StatusEvent]) -> None: ...
    async def list_events(self, *, limit: int = 50, device_id: str | None = None) -> list[StatusEvent]: ...
    async def get_config(self) -> MonitoringConfig | None: ...
    async def save_config(self, config: MonitoringConfig) -> None: ...
    async def get_demo_info(self) -> dict | None: ...
    async def save_demo_info(self, info: dict) -> None: ...


class MongoMonitoringStore:
    def __init__(self, db: AsyncDatabase, retention_hours: int = 26) -> None:
        self._db = db
        self._measurements = db["measurements"]
        self._events = db["events"]
        self._settings = db["settings"]
        self._retention_seconds = retention_hours * 3600

    async def ensure_indexes(self) -> None:
        await self._measurements.create_index([("device_id", 1), ("ts", -1)], name="device_ts")
        await self._events.create_index([("ts", -1)], name="event_ts")
        await self._ensure_ttl_index()

    async def _ensure_ttl_index(self) -> None:
        await ensure_ttl_index(self._db, self._measurements, "ts", TTL_INDEX_NAME, self._retention_seconds)

    # --- measurements ---
    async def insert_measurements(self, measurements: list[Measurement]) -> None:
        if measurements:
            await self._measurements.insert_many([m.model_dump() for m in measurements])

    async def list_measurements(self, device_id: str, *, since: datetime | None = None, limit: int = 500) -> list[Measurement]:
        query: dict = {"device_id": device_id}
        if since is not None:
            query["ts"] = {"$gte": since}
        docs = await self._measurements.find(query).sort("ts", -1).limit(limit).to_list(length=None)
        docs.reverse()  # oldest first, ready for a time-series chart
        return [Measurement.model_validate({k: v for k, v in d.items() if k != "_id"}) for d in docs]

    # --- events ---
    async def insert_events(self, events: list[StatusEvent]) -> None:
        if events:
            docs = []
            for event in events:
                doc = event.model_dump()
                doc["_id"] = doc.pop("id")
                docs.append(doc)
            await self._events.insert_many(docs)

    async def list_events(self, *, limit: int = 50, device_id: str | None = None) -> list[StatusEvent]:
        query = {"device_id": device_id} if device_id else {}
        docs = await self._events.find(query).sort("ts", -1).limit(limit).to_list(length=None)
        result = []
        for doc in docs:
            data = dict(doc)
            data["id"] = data.pop("_id")
            result.append(StatusEvent.model_validate(data))
        return result

    # --- runtime configuration ---
    async def get_config(self) -> MonitoringConfig | None:
        doc = await self._settings.find_one({"_id": CONFIG_DOC_ID})
        if doc is None:
            return None
        return MonitoringConfig.model_validate({k: v for k, v in doc.items() if k != "_id"})

    async def save_config(self, config: MonitoringConfig) -> None:
        await self._settings.replace_one({"_id": CONFIG_DOC_ID}, {"_id": CONFIG_DOC_ID, **config.model_dump()}, upsert=True)

    # --- demo-data marker (set by `python -m app.demo`) ---
    async def get_demo_info(self) -> dict | None:
        doc = await self._settings.find_one({"_id": "demo"})
        return {k: v for k, v in doc.items() if k != "_id"} if doc else None

    async def save_demo_info(self, info: dict) -> None:
        await self._settings.replace_one({"_id": "demo"}, {"_id": "demo", **info}, upsert=True)
