import asyncio
from collections import Counter
from ipaddress import IPv4Address, IPv4Network

from app.network_model.seed import seed_database
from tests.fakes import InMemoryNetworkStore


def seeded():
    store = InMemoryNetworkStore()
    report = asyncio.run(seed_database(store))
    return store, report


def test_seed_creates_expected_campus():
    store, report = seeded()
    assert (report.subnets_added, report.devices_added, report.links_total) == (4, 17, 16)
    devices = list(store.devices.values())
    assert Counter(d.block for d in devices) == {"backbone": 3, "cse": 6, "library": 4, "admin": 4}
    assert Counter(d.type for d in devices) == {
        "internet": 1, "edge_router": 1, "core_switch": 1, "switch": 3, "access_point": 3, "server": 1, "pc": 7,
    }


def test_every_device_ip_is_unique_and_inside_its_subnet():
    store, _ = seeded()
    ips = [d.ip for d in store.devices.values()]
    assert len(ips) == len(set(ips))
    for d in store.devices.values():
        if d.subnet_id is None:
            assert d.type == "internet"
            continue
        assert IPv4Address(d.ip) in IPv4Network(store.subnets[d.subnet_id].cidr)


def test_spec_addresses():
    store, _ = seeded()
    assert store.devices["edge-router"].ip == "10.0.0.1"
    assert store.devices["core-switch"].ip == "10.0.0.2"
    assert [store.devices[i].ip for i in ("cse-switch", "library-switch", "admin-switch")] == ["192.168.10.2", "192.168.20.2", "192.168.30.2"]
    assert store.subnets["cse-net"].gateway == "192.168.10.1"


def test_only_internet_node_is_real_by_default():
    store, _ = seeded()
    assert [d.id for d in store.devices.values() if d.monitoring_mode == "real"] == ["internet"]


def test_links_connect_each_device_to_its_parent():
    store, _ = seeded()
    for d in store.devices.values():
        if d.parent_id:
            link = store.links[f"{d.parent_id}--{d.id}"]
            assert (link.a_id, link.b_id) == (d.parent_id, d.id)
    assert store.links["internet--edge-router"].kind == "wan"
    assert store.links["core-switch--cse-switch"].kind == "uplink"


def test_seed_is_idempotent():
    store, _ = seeded()
    again = asyncio.run(seed_database(store))
    assert (again.subnets_added, again.devices_added) == (0, 0)
    assert (again.subnets_skipped, again.devices_skipped) == (4, 17)
    assert len(store.devices) == 17 and len(store.links) == 16


def test_reset_rebuilds_from_scratch():
    store, _ = seeded()
    del store.devices["cse-pc-3"]
    report = asyncio.run(seed_database(store, reset=True))
    assert report.devices_added == 17 and len(store.devices) == 17


def test_internet_target_is_configurable_and_validated():
    import pytest as _pytest

    from app.network_model.errors import InvalidNetworkData

    store = InMemoryNetworkStore()
    asyncio.run(seed_database(store, internet_target="8.8.8.8"))
    assert store.devices["internet"].probe_target == "8.8.8.8" and store.devices["internet"].ip == "8.8.8.8"
    with _pytest.raises(InvalidNetworkData):
        asyncio.run(seed_database(InMemoryNetworkStore(), internet_target="224.0.0.1"))


def test_internet_node_can_be_simulated_for_an_offline_demo():
    store = InMemoryNetworkStore()
    asyncio.run(seed_database(store, internet_real=False))
    internet = store.devices["internet"]
    assert internet.monitoring_mode == "simulated" and internet.probe_target is None and internet.base_rtt_ms == 15.0
    assert all(d.monitoring_mode == "simulated" for d in store.devices.values())  # nothing would be pinged for real
