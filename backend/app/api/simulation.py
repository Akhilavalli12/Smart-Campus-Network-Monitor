"""Fault-injection control for the demo. Only SIMULATED devices can be faulted; real measurements are never altered."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_store
from app.config import Settings, get_settings
from app.network_model.enums import FaultType
from app.network_model.errors import NetworkModelError, NotFoundError
from app.network_model.store import NetworkStore
from app.simulator.faults import FAULT_PARAMETERS, set_fault
from app.simulator.scenarios import SCENARIOS, get_scenario

router = APIRouter(prefix="/simulation", tags=["simulation"])


class SimulationDisabled(NetworkModelError):
    status_code = 403


def require_simulation(settings: Settings = Depends(get_settings)) -> None:
    if not settings.simulation_enabled:
        raise SimulationDisabled("Fault injection is disabled (SIMULATION_ENABLED=false)")


class FaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=64)
    fault: FaultType
    params: dict[str, float] = Field(default_factory=dict)


class SimDevice(BaseModel):
    id: str
    name: str
    type: str
    block: str
    ip: str
    fault: str
    params: dict[str, float]


class ScenarioOut(BaseModel):
    id: str
    name: str
    description: str
    expect: str
    faults: list[dict]


class SimulationState(BaseModel):
    enabled: bool
    devices: list[SimDevice]
    active: list[SimDevice]
    fault_catalog: dict[str, dict[str, list[float]]]  # fault -> parameter -> [min, max]
    scenarios: list[ScenarioOut]


async def _clear_all(store: NetworkStore) -> int:
    cleared = 0
    for device in await store.list_devices():
        if device.monitoring_mode == "simulated" and device.sim_state.fault != "none":
            await set_fault(store, device.id, "none")
            cleared += 1
    return cleared


@router.get("/state", response_model=SimulationState)
async def simulation_state(store: NetworkStore = Depends(get_store), settings: Settings = Depends(get_settings)) -> SimulationState:
    devices = [
        SimDevice(id=d.id, name=d.name, type=d.type, block=d.block, ip=d.ip, fault=d.sim_state.fault, params=d.sim_state.params)
        for d in await store.list_devices()
        if d.monitoring_mode == "simulated"
    ]
    return SimulationState(
        enabled=settings.simulation_enabled,
        devices=devices,
        active=[d for d in devices if d.fault != "none"],
        fault_catalog={f: {k: list(v) for k, v in params.items()} for f, params in FAULT_PARAMETERS.items() if f != "none"},
        scenarios=[ScenarioOut(id=s.id, name=s.name, description=s.description, expect=s.expect,
                               faults=[{"device_id": d, "fault": f, "params": p} for d, f, p in s.faults]) for s in SCENARIOS],
    )


@router.post("/faults", response_model=SimDevice, dependencies=[Depends(require_simulation)])
async def inject_fault(request: FaultRequest, store: NetworkStore = Depends(get_store)) -> SimDevice:
    """Inject a fault. The monitoring engine detects it on its own in the next cycles."""
    device = await set_fault(store, request.device_id, request.fault.value, request.params)
    return SimDevice(id=device.id, name=device.name, type=device.type, block=device.block, ip=device.ip, fault=device.sim_state.fault, params=device.sim_state.params)


@router.delete("/faults/{device_id}", dependencies=[Depends(require_simulation)])
async def clear_fault(device_id: str, store: NetworkStore = Depends(get_store)) -> dict:
    await set_fault(store, device_id, "none")
    return {"cleared": [device_id]}


@router.delete("/faults", dependencies=[Depends(require_simulation)])
async def clear_all_faults(store: NetworkStore = Depends(get_store)) -> dict:
    """Recover everything."""
    return {"cleared_count": await _clear_all(store)}


@router.post("/scenarios/{scenario_id}/run", dependencies=[Depends(require_simulation)])
async def run_scenario(scenario_id: str, store: NetworkStore = Depends(get_store)) -> dict:
    """Clear every fault, then apply the scenario's faults."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise NotFoundError(f"Scenario {scenario_id!r} not found")
    await _clear_all(store)
    for device_id, fault, params in scenario.faults:
        await set_fault(store, device_id, fault, params)
    return {"scenario": scenario.id, "applied": [{"device_id": d, "fault": f, "params": p} for d, f, p in scenario.faults]}
