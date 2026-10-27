"""IPv4 addressing helpers built on Python's standard `ipaddress` module.

Everything here is pure computation: no database, no network I/O.
"""
import hashlib
import ipaddress
from ipaddress import IPv4Address, IPv4Network

from pydantic import BaseModel

from app.network_model.errors import InvalidNetworkData

# RFC 1918 private ranges. Campus subnets must come from these.
RFC1918_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


class SubnetInfo(BaseModel):
    cidr: str
    network_address: str
    netmask: str
    wildcard_mask: str
    prefix_length: int
    broadcast_address: str | None  # /31 and /32 have no broadcast address
    total_addresses: int
    usable_hosts: int
    first_host: str
    last_host: str
    is_private_rfc1918: bool


def parse_ipv4(value: str, label: str = "IP address") -> IPv4Address:
    """Parse a dotted-quad IPv4 address or raise InvalidNetworkData.

    Python rejects leading zeros ("01.2.3.4") and out-of-range octets, which is
    what we want before an address is ever used in a command or a query.
    """
    if not isinstance(value, str):
        raise InvalidNetworkData(f"{label} must be a string")
    try:
        return IPv4Address(value)
    except ValueError:
        raise InvalidNetworkData(f"{label} {value!r} is not a valid IPv4 address") from None


def parse_ipv4_network(cidr: str, *, strict: bool = True) -> IPv4Network:
    """Parse CIDR notation such as 192.168.10.0/24.

    strict=True rejects an address with host bits set (192.168.10.5/24), because
    a subnet definition must name the network address itself.
    """
    if not isinstance(cidr, str) or cidr.count("/") != 1:
        raise InvalidNetworkData("CIDR must look like 192.168.10.0/24")
    address_part, prefix_part = cidr.split("/")
    if not (prefix_part.isascii() and prefix_part.isdigit()):
        raise InvalidNetworkData("CIDR prefix length must be a number from 0 to 32")
    try:
        return IPv4Network(cidr, strict=strict)
    except ipaddress.NetmaskValueError:
        raise InvalidNetworkData("CIDR prefix length must be between 0 and 32") from None
    except ipaddress.AddressValueError:
        raise InvalidNetworkData(f"{address_part!r} is not a valid IPv4 address") from None
    except ValueError:
        suggestion = IPv4Network(cidr, strict=False)
        raise InvalidNetworkData(f"{cidr!r} has host bits set; the network address is {suggestion}") from None


def is_rfc1918(network: IPv4Network) -> bool:
    return any(network.subnet_of(private) for private in RFC1918_NETWORKS)


def usable_bounds(network: IPv4Network) -> tuple[IPv4Address, IPv4Address]:
    """First and last assignable host addresses.

    /32: the single address. /31: both addresses (RFC 3021 point-to-point).
    Otherwise the network address and the broadcast address are excluded.
    """
    if network.prefixlen == 32:
        return network.network_address, network.network_address
    if network.prefixlen == 31:
        return network.network_address, network.broadcast_address
    return network.network_address + 1, network.broadcast_address - 1


def is_usable_host(address: IPv4Address, network: IPv4Network) -> bool:
    first, last = usable_bounds(network)
    return first <= address <= last


def calculate_subnet(cidr: str, *, strict: bool = True) -> SubnetInfo:
    network = parse_ipv4_network(cidr, strict=strict)
    first, last = usable_bounds(network)
    if network.prefixlen == 32:
        usable = 1
    elif network.prefixlen == 31:
        usable = 2
    else:
        usable = network.num_addresses - 2
    return SubnetInfo(
        cidr=str(network),
        network_address=str(network.network_address),
        netmask=str(network.netmask),
        wildcard_mask=str(network.hostmask),
        prefix_length=network.prefixlen,
        broadcast_address=str(network.broadcast_address) if network.prefixlen < 31 else None,
        total_addresses=network.num_addresses,
        usable_hosts=usable,
        first_host=str(first),
        last_host=str(last),
        is_private_rfc1918=is_rfc1918(network),
    )


def generate_mac(seed: str) -> str:
    """Deterministic, SIMULATED MAC address derived from a device id.

    The first octet 0x02 sets the "locally administered" bit and clears the
    multicast bit, so the address can never collide with a vendor-assigned MAC.
    """
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    octets = [0x02, *digest[:5]]
    return ":".join(f"{octet:02x}" for octet in octets)


def validate_probe_target(value: str) -> IPv4Address:
    """An address we are willing to send ICMP to.

    Rejects multicast, unspecified (0.0.0.0), limited broadcast, link-local and
    reserved space. Pinging a broadcast address makes every host on that network
    answer (the "smurf" amplification pattern), so it must never be configurable.
    Loopback and private addresses are allowed on purpose (demo laptops, localhost).
    """
    address = parse_ipv4(value, "Probe target")
    if address.is_multicast or address.is_unspecified or address.is_link_local or address.is_reserved:
        raise InvalidNetworkData(f"Probe target {address} is not a valid unicast host address")
    if address == IPv4Address("255.255.255.255"):
        raise InvalidNetworkData("Probe target cannot be the limited broadcast address")
    return address
