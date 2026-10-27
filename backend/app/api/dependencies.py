from fastapi import Depends, Request

from app.alerts.engine import AlertEngine
from app.alerts.store import AlertStore, MongoAlertStore
from app.config import Settings, get_settings
from app.db import MongoManager
from app.monitoring.engine import MonitoringEngine
from app.monitoring.store import MongoMonitoringStore, MonitoringStore
from app.network_model.store import MongoNetworkStore, NetworkStore
from app.traffic.engine import TrafficEngine
from app.traffic.store import MongoTrafficStore, TrafficStore


def get_mongo(request: Request) -> MongoManager:
    """Return the process-wide MongoManager created in the app lifespan."""
    return request.app.state.mongo


def get_store(mongo: MongoManager = Depends(get_mongo)) -> NetworkStore:
    """Network-model persistence for the current request (cheap to construct)."""
    return MongoNetworkStore(mongo.db)


def get_monitoring_store(mongo: MongoManager = Depends(get_mongo), settings: Settings = Depends(get_settings)) -> MonitoringStore:
    return MongoMonitoringStore(mongo.db, settings.measurement_retention_hours)


def get_engine(request: Request) -> MonitoringEngine | None:
    """The running monitoring engine, or None when MONITORING_ENABLED=false."""
    return getattr(request.app.state, "engine", None)


def get_traffic_store(mongo: MongoManager = Depends(get_mongo), settings: Settings = Depends(get_settings)) -> TrafficStore:
    return MongoTrafficStore(mongo.db, settings.measurement_retention_hours)


def get_traffic_engine(request: Request) -> TrafficEngine | None:
    return getattr(request.app.state, "traffic_engine", None)


def get_alert_store(mongo: MongoManager = Depends(get_mongo)) -> AlertStore:
    return MongoAlertStore(mongo.db)


def get_alert_engine(request: Request) -> AlertEngine | None:
    return getattr(request.app.state, "alert_engine", None)
