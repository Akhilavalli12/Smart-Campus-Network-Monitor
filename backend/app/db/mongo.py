"""MongoDB connection management using PyMongo's native async API."""
import time
from dataclasses import dataclass

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings


@dataclass(frozen=True)
class DatabaseStatus:
    reachable: bool
    latency_ms: float | None = None
    error: str | None = None


class MongoManager:
    """Owns the single AsyncMongoClient for the process.

    Creating the client does not contact the server (the driver connects lazily),
    so the API still starts when MongoDB is down and can report that honestly
    through the health endpoint.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncMongoClient = AsyncMongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
            tz_aware=True,  # datetimes come back timezone-aware (UTC)
        )

    @property
    def db(self) -> AsyncDatabase:
        return self._client[self._settings.mongodb_db_name]

    async def ping(self) -> DatabaseStatus:
        """Round-trip a `ping` command to the server and time it."""
        started = time.perf_counter()
        try:
            await self._client.admin.command("ping")
        except Exception as exc:  # driver raises several error types; isolate all of them
            return DatabaseStatus(reachable=False, error=type(exc).__name__)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return DatabaseStatus(reachable=True, latency_ms=round(elapsed_ms, 2))

    async def close(self) -> None:
        await self._client.close()
