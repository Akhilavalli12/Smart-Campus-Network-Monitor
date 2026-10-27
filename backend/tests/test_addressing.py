from ipaddress import IPv4Address, IPv4Network

import pytest

from app.network_model.addressing import (
    calculate_subnet,
    generate_mac,
    is_rfc1918,
    is_usable_host,
    parse_ipv4,
    parse_ipv4_network,
    validate_probe_target,
)
from app.network_model.errors import InvalidNetworkData


def test_slash_24():
    info = calculate_subnet("192.168.10.0/24")
    assert info.network_address == "192.168.10.0"
    assert info.netmask == "255.255.255.0"
    assert info.wildcard_mask == "0.0.0.255"
    assert info.broadcast_address == "192.168.10.255"
    assert info.total_addresses == 256
    assert info.usable_hosts == 254
    assert (info.first_host, info.last_host) == ("192.168.10.1", "192.168.10.254")
    assert info.is_private_rfc1918 is True


def test_slash_30_point_to_point():
    info = calculate_subnet("10.0.0.0/30")
    assert info.netmask == "255.255.255.252"
    assert info.broadcast_address == "10.0.0.3"
    assert info.total_addresses == 4
    assert info.usable_hosts == 2
    assert (info.first_host, info.last_host) == ("10.0.0.1", "10.0.0.2")


def test_slash_31_and_32_special_cases():
    p2p = calculate_subnet("10.0.0.0/31")
    assert p2p.usable_hosts == 2 and p2p.broadcast_address is None
    assert (p2p.first_host, p2p.last_host) == ("10.0.0.0", "10.0.0.1")
    host = calculate_subnet("10.0.0.5/32")
    assert host.usable_hosts == 1 and host.first_host == host.last_host == "10.0.0.5"


def test_non_strict_reduces_host_address_to_network():
    assert calculate_subnet("192.168.10.77/24", strict=False).network_address == "192.168.10.0"


def test_strict_rejects_host_bits_and_suggests_network():
    with pytest.raises(InvalidNetworkData, match=r"host bits set.*192\.168\.10\.0/24"):
        parse_ipv4_network("192.168.10.5/24")


@pytest.mark.parametrize(
    "bad",
    ["", "192.168.10.0", "192.168.10.0/33", "192.168.10.0/abc", "300.1.1.0/24", "::1/64",
     "192.168.10.0/255.255.255.0", "192.168.10.0/24/1", "192.168.10.0/-1"],
)
def test_invalid_cidr_rejected(bad):
    with pytest.raises(InvalidNetworkData):
        parse_ipv4_network(bad)


@pytest.mark.parametrize(
    "cidr,expected",
    [("10.1.2.0/24", True), ("172.16.0.0/12", True), ("172.31.255.0/24", True), ("192.168.0.0/16", True),
     ("172.32.0.0/16", False), ("192.169.0.0/24", False), ("8.8.8.0/24", False), ("100.64.0.0/10", False)],
)
def test_rfc1918_detection(cidr, expected):
    assert is_rfc1918(IPv4Network(cidr)) is expected


def test_usable_host_excludes_network_and_broadcast():
    net = IPv4Network("192.168.10.0/24")
    assert not is_usable_host(IPv4Address("192.168.10.0"), net)
    assert not is_usable_host(IPv4Address("192.168.10.255"), net)
    assert is_usable_host(IPv4Address("192.168.10.1"), net)
    assert is_usable_host(IPv4Address("192.168.10.254"), net)
    assert not is_usable_host(IPv4Address("192.168.11.1"), net)


def test_slash_30_has_exactly_two_usable_hosts():
    net = IPv4Network("10.0.0.0/30")
    assert [is_usable_host(IPv4Address(f"10.0.0.{i}"), net) for i in range(4)] == [False, True, True, False]


@pytest.mark.parametrize("bad", ["256.1.1.1", "1.1.1", "01.1.1.1", "", "1.1.1.1 ", "::1", "1.1.1.1; rm -rf /", 12345])
def test_parse_ipv4_rejects_malformed(bad):
    with pytest.raises(InvalidNetworkData):
        parse_ipv4(bad)


def test_generated_mac_is_deterministic_and_locally_administered():
    mac = generate_mac("cse-switch")
    assert mac == generate_mac("cse-switch")
    assert mac != generate_mac("cse-ap")
    octets = [int(part, 16) for part in mac.split(":")]
    assert len(octets) == 6
    assert octets[0] & 0b10  # locally administered bit set
    assert not octets[0] & 0b01  # unicast


@pytest.mark.parametrize("ok", ["1.1.1.1", "127.0.0.1", "192.168.43.7", "10.0.0.2"])
def test_probe_target_accepts_unicast_hosts(ok):
    assert str(validate_probe_target(ok)) == ok


@pytest.mark.parametrize("bad", ["0.0.0.0", "255.255.255.255", "224.0.0.1", "239.255.255.250", "169.254.10.10", "240.0.0.1", "not-an-ip", ""])
def test_probe_target_rejects_non_unicast_and_garbage(bad):
    with pytest.raises(InvalidNetworkData):
        validate_probe_target(bad)
