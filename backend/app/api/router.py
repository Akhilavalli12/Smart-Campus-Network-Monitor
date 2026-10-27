from fastapi import APIRouter

from app.api import alerts, dashboard, health, monitoring, network, simulation, traffic

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(network.router)
api_router.include_router(monitoring.router)
api_router.include_router(traffic.router)
api_router.include_router(alerts.router)
api_router.include_router(simulation.router)
api_router.include_router(dashboard.router)
