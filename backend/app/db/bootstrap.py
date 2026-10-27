"""Background tasks that run at application startup."""
import asyncio
import logging

from app.alerts.store import MongoAlertStore
from app.db.mongo import MongoManager
from app.monitoring.store import MongoMonitoringStore
from app.network_model.store import MongoNetworkStore
from app.traffic.store import MongoTrafficStore

logger = logging.getLogger(__name__)


async def ensure_indexes_with_retry(mongo: MongoManager, interval_seconds: float = 5.0, retention_hours: int = 26) -> None:
    """Create indexes as soon as MongoDB is reachable.

    Running this as a background task means the API starts even when MongoDB is
    down, and the indexes still get created once it comes up.
    """
    network_store = MongoNetworkStore(mongo.db)
    monitoring_store = MongoMonitoringStore(mongo.db, retention_hours)
    traffic_store = MongoTrafficStore(mongo.db, retention_hours)
    alert_store = MongoAlertStore(mongo.db)
    while True:
        try:
            await network_store.ensure_indexes()
            await monitoring_store.ensure_indexes()
            await traffic_store.ensure_indexes()
            await alert_store.ensure_indexes()
            logger.info("MongoDB indexes ensured")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Could not ensure MongoDB indexes (%s); retrying in %ss", type(exc).__name__, interval_seconds)
            await asyncio.sleep(interval_seconds)
