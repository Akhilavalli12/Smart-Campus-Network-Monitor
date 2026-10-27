"""The ~17-device campus used for development and the demo.

IP plan (all RFC 1918 except the Internet node):
  10.0.0.0/30       Edge router <-> core switch point-to-point link
  192.168.10.0/24   CSE block      (gateway .1 on the core L3 switch)
  192.168.20.0/24   Library        (gateway .1 on the core L3 switch)
  192.168.30.0/24   Admin block    (gateway .1 on the core L3 switch)
Host numbering inside a block: .2 switch, .3 access point, .10 server, .101+ PCs.

`base_rtt_ms` is a simulator parameter (typical RTT seen from the monitoring
host), not a measurement. Link capacities are demo-scaled defaults.
"""
from app.network_model.enums import CampusBlock as B
from app.network_model.enums import DeviceType as T
from app.network_model.enums import MonitoringMode as M
from app.network_model.models import DeviceCreate, Subnet

SUBNETS: list[Subnet] = [
    Subnet(id="p2p-edge-core", name="Edge-Core Link", cidr="10.0.0.0/30", block=B.BACKBONE,
           purpose="Point-to-point link between edge router and core L3 switch"),
    Subnet(id="cse-net", name="CSE Network", cidr="192.168.10.0/24", block=B.CSE,
           gateway="192.168.10.1", gateway_device_id="core-switch", purpose="CSE block LAN"),
    Subnet(id="library-net", name="Library Network", cidr="192.168.20.0/24", block=B.LIBRARY,
           gateway="192.168.20.1", gateway_device_id="core-switch", purpose="Library LAN"),
    Subnet(id="admin-net", name="Admin Network", cidr="192.168.30.0/24", block=B.ADMIN,
           gateway="192.168.30.1", gateway_device_id="core-switch", purpose="Administration block LAN"),
]


def _device(id, name, type, ip, subnet_id, block, parent_id, location, rtt, **extra) -> DeviceCreate:
    return DeviceCreate(id=id, name=name, type=type, ip=ip, subnet_id=subnet_id, block=block,
                        parent_id=parent_id, location=location, base_rtt_ms=rtt, **extra)


DEFAULT_INTERNET_TARGET = "1.1.1.1"


def build_devices(internet_target: str = DEFAULT_INTERNET_TARGET, internet_real: bool = True) -> list[DeviceCreate]:
    """The campus devices. `internet_target` is the real host the Internet node pings
    (some networks block ICMP to public addresses, so it must be changeable).
    With `internet_real=False` the Internet node is SIMULATED too (for a demo without internet access)."""
    if internet_real:
        internet = DeviceCreate(id="internet", name="Internet (ISP)", type=T.INTERNET, ip=internet_target, block=B.BACKBONE,
                                location="ISP / upstream", monitoring_mode=M.REAL, probe_target=internet_target)
    else:
        internet = DeviceCreate(id="internet", name="Internet (ISP)", type=T.INTERNET, ip=internet_target, block=B.BACKBONE,
                                location="ISP / upstream", monitoring_mode=M.SIMULATED, base_rtt_ms=15.0)
    return [internet, *_CAMPUS_DEVICES]


# Order matters: a parent must be registered before its children.
_CAMPUS_DEVICES: list[DeviceCreate] = [
    _device("edge-router", "Edge Router", T.EDGE_ROUTER, "10.0.0.1", "p2p-edge-core", B.BACKBONE, "internet", "Main Server Room", 3),
    _device("core-switch", "Core L3 Switch", T.CORE_SWITCH, "10.0.0.2", "p2p-edge-core", B.BACKBONE, "edge-router", "Main Server Room", 4),
    # CSE block
    _device("cse-switch", "CSE Switch", T.SWITCH, "192.168.10.2", "cse-net", B.CSE, "core-switch", "CSE Block - Network Room", 8),
    _device("cse-ap", "CSE Access Point", T.ACCESS_POINT, "192.168.10.3", "cse-net", B.CSE, "cse-switch", "CSE Block - Corridor", 11),
    _device("cse-server", "CSE Lab Server", T.SERVER, "192.168.10.10", "cse-net", B.CSE, "cse-switch", "CSE Block - Server Rack", 9),
    _device("cse-pc-1", "CSE PC 1", T.PC, "192.168.10.101", "cse-net", B.CSE, "cse-switch", "CSE Block - Lab 1", 12),
    _device("cse-pc-2", "CSE PC 2", T.PC, "192.168.10.102", "cse-net", B.CSE, "cse-switch", "CSE Block - Lab 1", 12),
    _device("cse-pc-3", "CSE PC 3", T.PC, "192.168.10.103", "cse-net", B.CSE, "cse-switch", "CSE Block - Lab 2", 12),
    # Library
    _device("library-switch", "Library Switch", T.SWITCH, "192.168.20.2", "library-net", B.LIBRARY, "core-switch", "Library - Network Closet", 8),
    _device("library-ap", "Library Access Point", T.ACCESS_POINT, "192.168.20.3", "library-net", B.LIBRARY, "library-switch", "Library - Reading Hall", 11),
    _device("library-pc-1", "Library PC 1", T.PC, "192.168.20.101", "library-net", B.LIBRARY, "library-switch", "Library - Reference Desk", 12),
    _device("library-pc-2", "Library PC 2", T.PC, "192.168.20.102", "library-net", B.LIBRARY, "library-switch", "Library - Digital Section", 12),
    # Admin block
    _device("admin-switch", "Admin Switch", T.SWITCH, "192.168.30.2", "admin-net", B.ADMIN, "core-switch", "Admin Block - Network Closet", 8),
    _device("admin-ap", "Admin Access Point", T.ACCESS_POINT, "192.168.30.3", "admin-net", B.ADMIN, "admin-switch", "Admin Block - Lobby", 11),
    _device("admin-pc-1", "Admin PC 1", T.PC, "192.168.30.101", "admin-net", B.ADMIN, "admin-switch", "Admin Block - Accounts", 12),
    _device("admin-pc-2", "Admin PC 2", T.PC, "192.168.30.102", "admin-net", B.ADMIN, "admin-switch", "Admin Block - Registrar", 12),
]

DEVICES: list[DeviceCreate] = build_devices()
