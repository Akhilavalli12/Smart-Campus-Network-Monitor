import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.api.router import api_router
from app.config import get_settings
from app.db import MongoManager
from app.alerts.engine import AlertEngine
from app.alerts.store import MongoAlertStore
from app.db.bootstrap import ensure_indexes_with_retry
from app.monitoring.engine import MonitoringEngine
from app.monitoring.store import MongoMonitoringStore
from app.network_model.store import MongoNetworkStore
from app.probes.dispatcher import build_probe_dispatcher
from app.simulator.traffic import SimulatedTraffic, TrafficModelConfig
from app.traffic.engine import TrafficEngine
from app.traffic.host import HostNicSource
from app.traffic.store import MongoTrafficStore
from app.network_model.errors import NetworkModelError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.mongo = MongoManager(settings)
    index_task = None
    if settings.ensure_indexes_on_startup:
        index_task = asyncio.create_task(
            ensure_indexes_with_retry(app.state.mongo, retention_hours=settings.measurement_retention_hours)
        )
    app.state.engine = None
    if settings.monitoring_enabled:
        app.state.engine = MonitoringEngine(
            network=MongoNetworkStore(app.state.mongo.db),
            monitoring=MongoMonitoringStore(app.state.mongo.db, settings.measurement_retention_hours),
            prober=build_probe_dispatcher(settings),
            settings=settings,
        )
        await app.state.engine.start()
    app.state.traffic_engine = None
    if settings.traffic_enabled:
        app.state.traffic_engine = TrafficEngine(
            network=MongoNetworkStore(app.state.mongo.db),
            traffic=MongoTrafficStore(app.state.mongo.db, settings.measurement_retention_hours),
            simulated=SimulatedTraffic(TrafficModelConfig(seed=settings.simulator_seed), vantage=settings.monitor_attached_to),
            host=HostNicSource(settings.host_nic),
            settings=settings,
        )
        await app.state.traffic_engine.start()
    app.state.alert_engine = None
    if settings.alerts_enabled:
        app.state.alert_engine = AlertEngine(
            network=MongoNetworkStore(app.state.mongo.db),
            alerts=MongoAlertStore(app.state.mongo.db),
            monitoring=MongoMonitoringStore(app.state.mongo.db, settings.measurement_retention_hours),
            settings=settings,
        )
        await app.state.alert_engine.start()
    yield
    if app.state.alert_engine is not None:
        await app.state.alert_engine.stop()
    if app.state.traffic_engine is not None:
        await app.state.traffic_engine.stop()
    if app.state.engine is not None:
        await app.state.engine.stop()
    if index_task is not None:
        index_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await index_task
    await app.state.mongo.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(NetworkModelError)
    async def network_model_error_handler(_: Request, exc: NetworkModelError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(PyMongoError)
    async def database_error_handler(_: Request, exc: PyMongoError) -> JSONResponse:
        logger.error("Database error: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    app.include_router(api_router)
    return app


app = create_app()
