"""Fault injection into SIMULATED devices.

Writes `sim_state` on the device document; the simulator reads it on the next probe, so the
monitoring engine detects the fault by itself, exactly as it would a real one.
(Stage 6 adds the REST API and the dashboard control panel on top of this function.)
"""
from app.network_model.enums import FaultType, MonitoringMode
from app.network_model.errors import InvalidNetworkData, NotFoundError
from app.network_model.models import Device, SimState
from app.network_model.store import NetworkStore

# fault -> {parameter name: (minimum, maximum)}
FAULT_PARAMETERS: dict[str, dict[str, tuple[float, float]]] = {
    FaultType.NONE.value: {},
    FaultType.OFFLINE.value: {},
    FaultType.HIGH_LATENCY.value: {"rtt_ms": (1.0, 10_000.0)},
    FaultType.PACKET_LOSS.value: {"loss_pct": (0.0, 100.0)},
    FaultType.CONGESTION.value: {"utilization_pct": (0.0, 100.0)},
}


def validate_fault(fault: str, params: dict[str, float]) -> SimState:
    try:
        fault_type = FaultType(fault)
    except ValueError:
        raise InvalidNetworkData(f"Unknown fault {fault!r}; choose one of {[f.value for f in FaultType]}") from None
    allowed = FAULT_PARAMETERS[fault_type.value]
    for name, value in params.items():
        if name not in allowed:
            raise InvalidNetworkData(f"Fault {fault_type.value!r} does not take parameter {name!r} (allowed: {sorted(allowed) or 'none'})")
        low, high = allowed[name]
        if not low <= value <= high:
            raise InvalidNetworkData(f"Parameter {name} must be between {low:g} and {high:g}")
    return SimState(fault=fault_type, params={k: float(v) for k, v in params.items()})


async def set_fault(store: NetworkStore, device_id: str, fault: str, params: dict[str, float] | None = None) -> Device:
    state = validate_fault(fault, params or {})
    device = await store.get_device(device_id)
    if device is None:
        raise NotFoundError(f"Device {device_id!r} not found")
    if device.monitoring_mode != MonitoringMode.SIMULATED:
        raise InvalidNetworkData(f"{device.name} is monitored for real; faults can only be injected into simulated devices")
    await store.update_device_fields(device_id, {"sim_state": state.model_dump()})
    return device.model_copy(update={"sim_state": state})
