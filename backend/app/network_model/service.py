"""Business rules for registering subnets and devices.

All networking validation lives here so the HTTP routes and the seed script
share exactly the same rules.
"""
import re
from ipaddress import IPv4Network

from app.network_model import topology
from app.network_model.addressing import (
    generate_mac,
    is_rfc1918,
    is_usable_host,
    parse_ipv4,
    parse_ipv4_network,
    usable_bounds,
    validate_probe_target,
)
from app.network_model.enums import DeviceType, LinkKind, MonitoringMode
from app.network_model.errors import ConflictError, InvalidNetworkData, NotFoundError
from app.network_model.models import (
    Device,
    DeviceCreate,
    DevicePath,
    Link,
    PathHop,
    SLUG_PATTERN,
    Subnet,
    Topology,
    TopologyEdge,
    TopologyNode,
)
from app.network_model.store import NetworkStore

# Demo-scaled link capacities (Mbps), used when a device does not specify its own.
# Capacity is plain data: change it per device with `uplink_capacity_mbps`.
DEFAULT_CAPACITY_MBPS = {
    LinkKind.WAN: 200.0,
    LinkKind.BACKBONE: 1000.0,
    LinkKind.UPLINK: 100.0,
    LinkKind.ACCESS: 100.0,
}
DEFAULT_SIMULATED_BASE_RTT_MS = 5.0


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not re.match(SLUG_PATTERN, slug):
        raise InvalidNetworkData(f"Cannot derive a valid id from name {text!r}; supply an explicit id (2-40 chars: a-z, 0-9, -)")
    return slug


async def register_subnet(store: NetworkStore, subnet: Subnet) -> Subnet:
    network = parse_ipv4_network(subnet.cidr, strict=True)
    if not is_rfc1918(network):
        raise InvalidNetworkData(f"{network} is not an RFC 1918 private range (10/8, 172.16/12, 192.168/16)")
    if network.prefixlen > 30:
        raise InvalidNetworkData("A campus subnet needs at least 2 usable host addresses (prefix /30 or shorter)")

    if subnet.gateway is not None:
        gateway = parse_ipv4(subnet.gateway, "Gateway")
        if not is_usable_host(gateway, network):
            raise InvalidNetworkData(f"Gateway {gateway} is not a usable host address in {network}")

    for existing in await store.list_subnets():
        if existing.id == subnet.id:
            raise ConflictError(f"Subnet id {subnet.id!r} already exists")
        if network.overlaps(IPv4Network(existing.cidr)):
            raise ConflictError(f"{network} overlaps existing subnet {existing.name} ({existing.cidr})")

    normalised = subnet.model_copy(update={"cidr": str(network)})
    await store.insert_subnet(normalised)
    return normalised


async def register_device(store: NetworkStore, payload: DeviceCreate) -> Device:
    device_id = payload.id or slugify(payload.name)
    device_type = DeviceType(payload.type)

    existing = await store.list_devices()
    by_id = {d.id: d for d in existing}
    if device_id in by_id:
        raise ConflictError(f"Device id {device_id!r} already exists")
    for other in existing:
        if other.ip == payload.ip:
            raise ConflictError(f"IP {payload.ip} is already assigned to {other.name}")

    parent: Device | None = None
    if device_type is DeviceType.INTERNET:
        if payload.parent_id is not None or payload.subnet_id is not None:
            raise InvalidNetworkData("The Internet node has no parent and sits outside campus subnets")
        if any(d.type == DeviceType.INTERNET for d in existing):
            raise ConflictError("The topology already has an Internet root")
    else:
        if payload.subnet_id is None:
            raise InvalidNetworkData("subnet_id is required for campus devices")
        subnet = await store.get_subnet(payload.subnet_id)
        if subnet is None:
            raise InvalidNetworkData(f"Unknown subnet {payload.subnet_id!r}")
        network = parse_ipv4_network(subnet.cidr)
        address = parse_ipv4(payload.ip)
        if not is_usable_host(address, network):
            first, last = usable_bounds(network)
            raise InvalidNetworkData(f"{address} is not a usable host address in {network} (usable range {first} - {last})")
        if payload.block != subnet.block:
            raise InvalidNetworkData(f"Device block {payload.block!r} does not match subnet block {subnet.block!r}")
        if subnet.gateway == payload.ip and device_id != subnet.gateway_device_id:
            raise InvalidNetworkData(f"{payload.ip} is reserved as the default gateway of {subnet.name}")

        if payload.parent_id is None:
            raise InvalidNetworkData("parent_id is required for campus devices")
        parent = by_id.get(payload.parent_id)
        if parent is None:
            raise InvalidNetworkData(f"Unknown parent device {payload.parent_id!r}")
        topology.check_parent_child(parent.type, payload.type)

    if payload.monitoring_mode == MonitoringMode.REAL and payload.probe_target is None:
        raise InvalidNetworkData("probe_target (the real host to ping) is required when monitoring_mode is 'real'")
    if payload.probe_target is not None:
        validate_probe_target(payload.probe_target)
    if payload.monitoring_mode == MonitoringMode.SIMULATED and payload.probe_target is not None:
        raise InvalidNetworkData("probe_target only applies when monitoring_mode is 'real'")

    base_rtt = payload.base_rtt_ms
    if base_rtt is None and payload.monitoring_mode == MonitoringMode.SIMULATED:
        base_rtt = DEFAULT_SIMULATED_BASE_RTT_MS

    device = Device(
        id=device_id,
        name=payload.name,
        type=payload.type,
        ip=payload.ip,
        subnet_id=payload.subnet_id,
        block=payload.block,
        location=payload.location,
        parent_id=payload.parent_id,
        monitoring_mode=payload.monitoring_mode,
        probe_target=payload.probe_target,
        mac=payload.mac or generate_mac(device_id),
        base_rtt_ms=base_rtt,
    )

    link: Link | None = None
    if parent is not None:
        kind = topology.link_kind_for(parent.type)
        link = Link(
            id=f"{parent.id}--{device_id}",
            a_id=parent.id,
            b_id=device_id,
            kind=kind,
            capacity_mbps=payload.uplink_capacity_mbps or DEFAULT_CAPACITY_MBPS[kind],
        )

    await store.insert_device(device)
    if link is not None:
        try:
            await store.insert_link(link)
        except Exception:
            # No multi-document transactions on a standalone MongoDB: undo by hand.
            await store.delete_device(device_id)
            raise
    return device


async def remove_device(store: NetworkStore, device_id: str) -> None:
    device = await store.get_device(device_id)
    if device is None:
        raise NotFoundError(f"Device {device_id!r} not found")
    downstream = topology.descendants(await store.list_devices(), device_id)
    if downstream:
        raise ConflictError(f"{device.name} still has {len(downstream)} downstream device(s); remove those first")
    await store.delete_links_of_device(device_id)
    await store.delete_device(device_id)


async def get_device_or_404(store: NetworkStore, device_id: str) -> Device:
    device = await store.get_device(device_id)
    if device is None:
        raise NotFoundError(f"Device {device_id!r} not found")
    return device


async def get_subnet_or_404(store: NetworkStore, subnet_id: str) -> Subnet:
    subnet = await store.get_subnet(subnet_id)
    if subnet is None:
        raise NotFoundError(f"Subnet {subnet_id!r} not found")
    return subnet


def sort_by_ip(devices: list[Device]) -> list[Device]:
    """Numeric IP order: Internet, backbone (10.x), then the campus blocks."""
    return sorted(devices, key=lambda d: int(parse_ipv4(d.ip)))


async def build_topology(store: NetworkStore) -> Topology:
    devices = sort_by_ip(await store.list_devices())
    by_id = {d.id: d for d in devices}
    nodes = [
        TopologyNode(
            id=d.id,
            name=d.name,
            type=d.type,
            block=d.block,
            ip=d.ip,
            status=d.status,
            monitoring_mode=d.monitoring_mode,
            parent_id=d.parent_id,
            depth=topology.depth_of(by_id, d.id),
        )
        for d in devices
    ]
    edges = [
        TopologyEdge(id=link.id, source=link.a_id, target=link.b_id, kind=link.kind, capacity_mbps=link.capacity_mbps)
        for link in await store.list_links()
    ]
    return Topology(nodes=nodes, edges=edges)


async def path_to_internet(store: NetworkStore, device_id: str) -> DevicePath:
    await get_device_or_404(store, device_id)
    by_id = {d.id: d for d in await store.list_devices()}
    hops = [
        PathHop(id=by_id[i].id, name=by_id[i].name, type=by_id[i].type, ip=by_id[i].ip)
        for i in topology.path_to_root(by_id, device_id)
    ]
    return DevicePath(device_id=device_id, hops=hops)
