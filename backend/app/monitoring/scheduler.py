"""Shared polling-loop machinery for the monitoring and traffic engines."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


@dataclass
class EngineStatus:
    running: bool = False
    cycles_completed: int = 0
    last_cycle_at: datetime | None = None
    last_cycle_duration_ms: float | None = None
    last_error: str | None = None
    interval_s: float | None = None


class PollingService:
    """A background task that runs `run_cycle()` at a fixed rate.

    * A cycle never overlaps the next one; a slow cycle delays the next start.
    * Anything a cycle raises is logged and the loop carries on (a database outage must not kill it).
    * Subclasses provide `run_cycle()` and `current_interval()`.
    """

    name = "polling-service"
    fallback_interval_s = 5.0  # used when the interval cannot be read (for example the database is down)

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.status = EngineStatus()

    async def current_interval(self) -> float:
        raise NotImplementedError

    async def run_cycle(self):
        raise NotImplementedError

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self.status.running = True
            self._task = asyncio.create_task(self.run_forever(), name=self.name)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.status.running = False

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            started = loop.time()
            interval = self.fallback_interval_s
            try:
                interval = await self.current_interval()
                await self.run_cycle()
                self.status.last_error = None
            except asyncio.CancelledError:
                raise
            except PyMongoError as exc:
                self.status.last_error = f"database unavailable ({type(exc).__name__})"
                logger.warning("%s cycle skipped: %s", self.name, self.status.last_error)
            except Exception as exc:  # the loop must survive anything a single cycle throws
                self.status.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("%s cycle failed", self.name)
            self.status.interval_s = interval
            delay = max(0.0, interval - (loop.time() - started))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
