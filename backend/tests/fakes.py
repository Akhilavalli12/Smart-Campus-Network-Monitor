"""Test doubles: an in-memory NetworkStore and a store that behaves like a dead database."""
from copy import deepcopy

from pymongo.errors import ServerSelectionTimeoutError

from app.network_model.errors import ConflictError
from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent
from app.demo.memory import InMemoryAlertStore, InMemoryMonitoringStore, InMemoryNetworkStore, InMemoryTrafficStore  # noqa: F401
from app.network_model.models import Device, Link, Subnet
from app.traffic.models import TrafficSample


class DownStore:
    """Every operation fails the way a driver does when MongoDB is unreachable."""

    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise ServerSelectionTimeoutError("MongoDB unreachable")

        return _fail


class DownMonitoringStore:
    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise ServerSelectionTimeoutError("MongoDB unreachable")

        return _fail


class DownTrafficStore:
    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise ServerSelectionTimeoutError("MongoDB unreachable")

        return _fail


class DownAlertStore:
    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise ServerSelectionTimeoutError("MongoDB unreachable")

        return _fail
