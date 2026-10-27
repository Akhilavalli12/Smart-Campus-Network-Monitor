"""Persistence for traffic samples."""
from datetime import datetime
from typing import Protocol

from pymongo.asynchronous.database import AsyncDatabase

from app.db.ttl import ensure_ttl_index
from app.traffic.models import TrafficSample

TTL_INDEX_NAME = "ttl_traffic_ts"


class TrafficStore(Protocol):
    async def insert_samples(self, samples: list[TrafficSample]) -> None: ...
    async def list_samples(self, scope: str, ref_ids: list[str] | None = None, *, since: datetime | None = None, limit: int = 1000) -> list[TrafficSample]: ...


class MongoTrafficStore:
    def __init__(self, db: AsyncDatabase, retention_hours: int = 26) -> None:
        self._db = db
        self._samples = db["traffic_samples"]
        self._retention_seconds = retention_hours * 3600

    async def ensure_indexes(self) -> None:
        await self._samples.create_index([("scope", 1), ("ref_id", 1), ("ts", -1)], name="scope_ref_ts")
        await ensure_ttl_index(self._db, self._samples, "ts", TTL_INDEX_NAME, self._retention_seconds)

    async def insert_samples(self, samples: list[TrafficSample]) -> None:
        if samples:
            await self._samples.insert_many([s.model_dump() for s in samples])

    async def list_samples(self, scope: str, ref_ids: list[str] | None = None, *, since: datetime | None = None, limit: int = 1000) -> list[TrafficSample]:
        """Most recent `limit` samples, returned oldest first (ready for a time-series chart)."""
        query: dict = {"scope": scope}
        if ref_ids is not None:
            query["ref_id"] = {"$in": ref_ids}
        if since is not None:
            query["ts"] = {"$gte": since}
        docs = await self._samples.find(query).sort("ts", -1).limit(limit).to_list(length=None)
        docs.reverse()
        return [TrafficSample.model_validate({k: v for k, v in d.items() if k != "_id"}) for d in docs]
