"""In-memory implementations of the stores (same behaviour as the MongoDB ones).

Used by the tests and by the demo-data generator, which fast-forwards 24 hours of monitoring
in memory and then writes the result to MongoDB in one go.
"""
from copy import deepcopy
from datetime import datetime

from app.alerts.models import Alert
from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent
from app.network_model.errors import ConflictError
from app.network_model.models import Device, Link, Subnet
from app.traffic.models import TrafficSample


class InMemoryNetworkStore:
    """Implements the same contract as MongoNetworkStore, including uniqueness rules."""

    def __init__(self) -> None:
        self.subnets: dict[str, Subnet] = {}
        self.devices: dict[str, Device] = {}
        self.links: dict[str, Link] = {}

    async def list_subnets(self):
        return [deepcopy(self.subnets[k]) for k in sorted(self.subnets)]

    async def get_subnet(self, subnet_id):
        return deepcopy(self.subnets.get(subnet_id))

    async def insert_subnet(self, subnet):
        if subnet.id in self.subnets or any(s.cidr == subnet.cidr for s in self.subnets.values()):
            raise ConflictError("A subnet with this id or CIDR already exists")
        self.subnets[subnet.id] = deepcopy(subnet)

    async def list_devices(self, *, block=None, type=None, subnet_id=None):
        result = []
        for key in sorted(self.devices):
            d = self.devices[key]
            if block is not None and d.block != block:
                continue
            if type is not None and d.type != type:
                continue
            if subnet_id is not None and d.subnet_id != subnet_id:
                continue
            result.append(deepcopy(d))
        return result

    async def get_device(self, device_id):
        return deepcopy(self.devices.get(device_id))

    async def insert_device(self, device):
        if device.id in self.devices or any(d.ip == device.ip for d in self.devices.values()):
            raise ConflictError("A device with this id or IP address already exists")
        self.devices[device.id] = deepcopy(device)

    async def delete_device(self, device_id):
        return self.devices.pop(device_id, None) is not None

    async def update_device_fields(self, device_id, fields):
        from app.network_model.store import check_updatable

        check_updatable(fields)
        if device_id not in self.devices:
            return False
        data = self.devices[device_id].model_dump()
        data.update(deepcopy(fields))
        self.devices[device_id] = Device.model_validate(data)
        return True

    async def list_links(self):
        return [deepcopy(self.links[k]) for k in sorted(self.links)]

    async def insert_link(self, link):
        if link.id in self.links or any((l.a_id, l.b_id) == (link.a_id, link.b_id) for l in self.links.values()):
            raise ConflictError("This link already exists")
        self.links[link.id] = deepcopy(link)

    async def update_link_fields(self, link_id, fields):
        from app.network_model.store import check_link_updatable

        check_link_updatable(fields)
        if link_id not in self.links:
            return False
        data = self.links[link_id].model_dump()
        data.update(deepcopy(fields))
        self.links[link_id] = Link.model_validate(data)
        return True

    async def delete_links_of_device(self, device_id):
        doomed = [k for k, l in self.links.items() if device_id in (l.a_id, l.b_id)]
        for key in doomed:
            del self.links[key]
        return len(doomed)

    async def clear_network(self):
        self.links.clear()
        self.devices.clear()
        self.subnets.clear()


class InMemoryMonitoringStore:
    """Implements the same contract as MongoMonitoringStore."""

    def __init__(self) -> None:
        self.measurements: list[Measurement] = []
        self.events: list[StatusEvent] = []
        self.config: MonitoringConfig | None = None

    async def insert_measurements(self, measurements):
        self.measurements.extend(deepcopy(measurements))

    async def list_measurements(self, device_id, *, since=None, limit=500):
        rows = [m for m in self.measurements if m.device_id == device_id and (since is None or m.ts >= since)]
        rows.sort(key=lambda m: m.ts)
        return deepcopy(rows[-limit:])  # the most recent `limit` rows, oldest first

    async def insert_events(self, events):
        self.events.extend(deepcopy(events))

    async def list_events(self, *, limit=50, device_id=None):
        rows = [e for e in self.events if device_id is None or e.device_id == device_id]
        rows.sort(key=lambda e: e.ts, reverse=True)
        return deepcopy(rows[:limit])

    async def get_demo_info(self):
        return getattr(self, "demo_info", None)

    async def save_demo_info(self, info):
        self.demo_info = deepcopy(info)

    async def get_config(self):
        return deepcopy(self.config)

    async def save_config(self, config):
        self.config = deepcopy(config)


class InMemoryTrafficStore:
    """Implements the same contract as MongoTrafficStore."""

    def __init__(self) -> None:
        self.samples: list[TrafficSample] = []

    async def insert_samples(self, samples):
        self.samples.extend(deepcopy(samples))

    async def list_samples(self, scope, ref_ids=None, *, since=None, limit=1000):
        rows = [s for s in self.samples if s.scope == scope and (ref_ids is None or s.ref_id in ref_ids) and (since is None or s.ts >= since)]
        rows.sort(key=lambda s: s.ts)
        return deepcopy(rows[-limit:])


class InMemoryAlertStore:
    """Implements the same contract as MongoAlertStore."""

    def __init__(self) -> None:
        self.alerts: dict[str, Alert] = {}

    async def insert_alerts(self, alerts):
        for alert in alerts:
            self.alerts[alert.id] = deepcopy(alert)

    async def update_alert(self, alert_id, fields):
        from app.alerts.store import check_alert_updatable

        check_alert_updatable(fields)
        if alert_id not in self.alerts:
            return False
        data = self.alerts[alert_id].model_dump()
        data.update(deepcopy(fields))
        self.alerts[alert_id] = Alert.model_validate(data)
        return True

    async def get_alert(self, alert_id):
        return deepcopy(self.alerts.get(alert_id))

    async def list_alerts(self, *, state=None, type=None, limit=100):
        rows = [a for a in self.alerts.values() if (state is None or a.state == state) and (type is None or a.type == type)]
        rows.sort(key=lambda a: a.opened_at, reverse=True)
        return deepcopy(rows[:limit])
