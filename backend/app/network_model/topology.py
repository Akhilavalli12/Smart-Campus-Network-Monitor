"""Pure graph logic over the device tree (no I/O).

The campus is modelled as a tree rooted at the Internet node: every device has
exactly one upstream parent. That is what lets the monitoring engine later say
"this PC is unreachable BECAUSE its switch failed" instead of raising a false
failure for every child.
"""
from collections import deque
from collections.abc import Iterable

from app.network_model.enums import DeviceType, LinkKind
from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device

# Which device types may sit directly below which. Mirrors the campus design.
ALLOWED_CHILDREN: dict[DeviceType, frozenset[DeviceType]] = {
    DeviceType.INTERNET: frozenset({DeviceType.EDGE_ROUTER}),
    DeviceType.EDGE_ROUTER: frozenset({DeviceType.CORE_SWITCH}),
    DeviceType.CORE_SWITCH: frozenset({DeviceType.SWITCH, DeviceType.SERVER}),
    DeviceType.SWITCH: frozenset({DeviceType.ACCESS_POINT, DeviceType.SERVER, DeviceType.PC}),
    DeviceType.ACCESS_POINT: frozenset({DeviceType.PC}),
    DeviceType.SERVER: frozenset(),
    DeviceType.PC: frozenset(),
}


def check_parent_child(parent_type: str, child_type: str) -> None:
    allowed = ALLOWED_CHILDREN[DeviceType(parent_type)]
    if DeviceType(child_type) not in allowed:
        names = ", ".join(sorted(t.value for t in allowed)) or "nothing"
        raise InvalidNetworkData(f"A {parent_type} cannot have a {child_type} directly below it (allowed: {names})")


def link_kind_for(parent_type: str) -> LinkKind:
    parent = DeviceType(parent_type)
    if parent is DeviceType.INTERNET:
        return LinkKind.WAN
    if parent is DeviceType.EDGE_ROUTER:
        return LinkKind.BACKBONE
    if parent is DeviceType.CORE_SWITCH:
        return LinkKind.UPLINK
    return LinkKind.ACCESS


def children_map(devices: Iterable[Device]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for device in devices:
        result.setdefault(device.id, [])
        if device.parent_id is not None:
            result.setdefault(device.parent_id, []).append(device.id)
    return result


def path_to_root(by_id: dict[str, Device], device_id: str) -> list[str]:
    """[device, parent, grandparent, ..., root]. Raises on a cycle or a missing parent."""
    path: list[str] = []
    seen: set[str] = set()
    current: str | None = device_id
    while current is not None:
        if current in seen:
            raise InvalidNetworkData(f"Cycle detected in topology at {current!r}")
        if current not in by_id:
            raise InvalidNetworkData(f"Device {current!r} referenced as a parent does not exist")
        seen.add(current)
        path.append(current)
        current = by_id[current].parent_id
    return path


def descendants(devices: Iterable[Device], device_id: str) -> list[str]:
    """All devices downstream of `device_id`, nearest first (breadth-first)."""
    kids = children_map(devices)
    order: list[str] = []
    queue = deque(kids.get(device_id, []))
    while queue:
        current = queue.popleft()
        order.append(current)
        queue.extend(kids.get(current, []))
    return order


def validate_tree(devices: Iterable[Device]) -> None:
    """Check the whole topology: one Internet root, valid parents, no cycles."""
    devices = list(devices)
    by_id = {d.id: d for d in devices}
    if len(by_id) != len(devices):
        raise InvalidNetworkData("Duplicate device ids in topology")
    roots = [d for d in devices if d.parent_id is None]
    if len(roots) != 1 or roots[0].type != DeviceType.INTERNET:
        raise InvalidNetworkData("Topology must have exactly one root, and it must be the Internet node")
    for device in devices:
        path_to_root(by_id, device.id)  # raises on cycle / missing parent
        if device.parent_id is not None:
            check_parent_child(by_id[device.parent_id].type, device.type)


def depth_of(by_id: dict[str, Device], device_id: str) -> int:
    return len(path_to_root(by_id, device_id)) - 1


def reachability_path(by_id: dict[str, Device], vantage_id: str, target_id: str) -> list[str]:
    """Devices a probe from the monitoring station must traverse to reach `target_id`.

    The monitoring station is plugged into `vantage_id` (default: the core switch),
    NOT into the Internet. So the dependency chain is the tree path between the
    vantage device and the target: vantage first, target excluded.
        core-switch -> cse-pc-1    : [core-switch, cse-switch]
        core-switch -> internet    : [core-switch, edge-router]
        core-switch -> core-switch : []   (the station's own attachment point)
    A failure of any listed device makes the target unreachable from the station.
    The Internet node being down does NOT make the campus LAN unreachable.
    """
    if vantage_id not in by_id:
        raise InvalidNetworkData(f"Monitoring vantage device {vantage_id!r} does not exist")
    if target_id == vantage_id:
        return []
    chain_from_vantage = path_to_root(by_id, vantage_id)  # [vantage, ..., root]
    chain_from_target = path_to_root(by_id, target_id)  # [target, ..., root]
    on_vantage_chain = set(chain_from_vantage)

    # Climb from the target until we reach a device that is also above the vantage point:
    # that device is the meeting point (lowest common ancestor) of the two chains.
    below_meeting: list[str] = []  # target side, nearest the target first
    meeting = chain_from_target[-1]
    for node in chain_from_target:
        if node in on_vantage_chain:
            meeting = node
            break
        below_meeting.append(node)

    up_to_meeting = chain_from_vantage[: chain_from_vantage.index(meeting) + 1]  # vantage ... meeting
    full_path = [*up_to_meeting, *reversed(below_meeting)]  # vantage ... meeting ... target
    return full_path[:-1]  # the target itself is not a dependency of its own reachability
