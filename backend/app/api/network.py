"""Read/registration endpoints for the network model.

Routes stay thin: validation and rules live in app.network_model.service.
"""
from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_store
from app.network_model import service
from app.network_model.addressing import SubnetInfo, calculate_subnet
from app.network_model.enums import CampusBlock, DeviceType
from app.network_model.models import Device, DeviceCreate, DevicePath, Link, SubnetOut, Topology
from app.network_model.store import NetworkStore

router = APIRouter(tags=["network"])


@router.get("/subnets/calculate", response_model=SubnetInfo)
async def calculate(cidr: str = Query(..., description="e.g. 192.168.10.0/24 or 192.168.10.77/24")) -> SubnetInfo:
    """Subnet calculator. Host bits are allowed here and reduced to the network address."""
    return calculate_subnet(cidr, strict=False)


@router.get("/subnets", response_model=list[SubnetOut])
async def list_subnets(store: NetworkStore = Depends(get_store)) -> list[SubnetOut]:
    return [SubnetOut(**s.model_dump(), info=calculate_subnet(s.cidr)) for s in await store.list_subnets()]


@router.get("/subnets/{subnet_id}", response_model=SubnetOut)
async def get_subnet(subnet_id: str, store: NetworkStore = Depends(get_store)) -> SubnetOut:
    subnet = await service.get_subnet_or_404(store, subnet_id)
    return SubnetOut(**subnet.model_dump(), info=calculate_subnet(subnet.cidr))


@router.get("/devices", response_model=list[Device])
async def list_devices(
    block: CampusBlock | None = None,
    type: DeviceType | None = None,
    subnet_id: str | None = None,
    store: NetworkStore = Depends(get_store),
) -> list[Device]:
    devices = await store.list_devices(
        block=block.value if block else None,
        type=type.value if type else None,
        subnet_id=subnet_id,
    )
    return service.sort_by_ip(devices)


@router.post("/devices", response_model=Device, status_code=status.HTTP_201_CREATED)
async def register_device(payload: DeviceCreate, store: NetworkStore = Depends(get_store)) -> Device:
    return await service.register_device(store, payload)


@router.get("/devices/{device_id}", response_model=Device)
async def get_device(device_id: str, store: NetworkStore = Depends(get_store)) -> Device:
    return await service.get_device_or_404(store, device_id)


@router.get("/devices/{device_id}/path", response_model=DevicePath)
async def device_path(device_id: str, store: NetworkStore = Depends(get_store)) -> DevicePath:
    """Upstream chain from the device to the Internet (each hop is a possible point of failure)."""
    return await service.path_to_internet(store, device_id)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: str, store: NetworkStore = Depends(get_store)) -> Response:
    await service.remove_device(store, device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/links", response_model=list[Link])
async def list_links(store: NetworkStore = Depends(get_store)) -> list[Link]:
    return await store.list_links()


@router.get("/topology", response_model=Topology)
async def topology(store: NetworkStore = Depends(get_store)) -> Topology:
    return await service.build_topology(store)
