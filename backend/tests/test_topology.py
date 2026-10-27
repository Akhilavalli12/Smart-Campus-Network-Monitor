import asyncio

import pytest

from app.network_model import topology
from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device
from app.network_model.seed import seed_database
from tests.fakes import InMemoryNetworkStore


def dev(id, type, parent=None, ip=None):
    return Device(id=id, name=id, type=type, ip=ip or f"10.9.9.{abs(hash(id)) % 200 + 1}", block="backbone", parent_id=parent, monitoring_mode="simulated")


@pytest.fixture(scope="module")
def seeded_devices():
    store = InMemoryNetworkStore()
    asyncio.run(seed_database(store))
    return asyncio.run(store.list_devices())


def test_seed_topology_is_valid(seeded_devices):
    topology.validate_tree(seeded_devices)


def test_path_to_root_for_a_pc(seeded_devices):
    by_id = {d.id: d for d in seeded_devices}
    assert topology.path_to_root(by_id, "cse-pc-1") == ["cse-pc-1", "cse-switch", "core-switch", "edge-router", "internet"]
    assert topology.depth_of(by_id, "cse-pc-1") == 4
    assert topology.depth_of(by_id, "internet") == 0


def test_descendants_of_switch_and_core(seeded_devices):
    assert set(topology.descendants(seeded_devices, "cse-switch")) == {"cse-ap", "cse-server", "cse-pc-1", "cse-pc-2", "cse-pc-3"}
    assert topology.descendants(seeded_devices, "cse-pc-1") == []
    # Core failure takes down all three blocks: 3 switches + 3 APs + 1 server + 7 PCs = 14
    assert len(topology.descendants(seeded_devices, "core-switch")) == 14


def test_two_roots_rejected():
    with pytest.raises(InvalidNetworkData, match="exactly one root"):
        topology.validate_tree([dev("a", "internet"), dev("b", "internet")])


def test_root_must_be_internet():
    with pytest.raises(InvalidNetworkData, match="exactly one root"):
        topology.validate_tree([dev("r", "edge_router")])


def test_missing_parent_rejected():
    with pytest.raises(InvalidNetworkData, match="does not exist"):
        topology.validate_tree([dev("net", "internet"), dev("r", "edge_router", parent="ghost")])


def test_cycle_rejected():
    a, b = dev("a", "switch", parent="b"), dev("b", "switch", parent="a")
    with pytest.raises(InvalidNetworkData, match="Cycle"):
        topology.path_to_root({"a": a, "b": b}, "a")


def test_illegal_parent_child_pairing_rejected():
    with pytest.raises(InvalidNetworkData, match="cannot have"):
        topology.validate_tree([dev("net", "internet"), dev("pc", "pc", parent="net")])


@pytest.mark.parametrize(
    "parent,child,ok",
    [("internet", "edge_router", True), ("edge_router", "core_switch", True), ("core_switch", "switch", True),
     ("switch", "pc", True), ("switch", "access_point", True), ("access_point", "pc", True),
     ("pc", "switch", False), ("switch", "switch", False), ("internet", "pc", False), ("server", "pc", False)],
)
def test_parent_child_rules(parent, child, ok):
    if ok:
        topology.check_parent_child(parent, child)
    else:
        with pytest.raises(InvalidNetworkData):
            topology.check_parent_child(parent, child)


def test_reachability_path_from_the_core_switch(seeded_devices):
    by_id = {d.id: d for d in seeded_devices}
    path = lambda target: topology.reachability_path(by_id, "core-switch", target)
    assert path("cse-pc-1") == ["core-switch", "cse-switch"]
    assert path("cse-switch") == ["core-switch"]
    assert path("library-ap") == ["core-switch", "library-switch"]
    assert path("edge-router") == ["core-switch"]
    assert path("internet") == ["core-switch", "edge-router"]
    assert path("core-switch") == []


def test_internet_outage_does_not_isolate_the_campus_lan(seeded_devices):
    by_id = {d.id: d for d in seeded_devices}
    for device in seeded_devices:
        assert "internet" not in topology.reachability_path(by_id, "core-switch", device.id)
        if device.id not in ("internet", "edge-router"):
            assert "edge-router" not in topology.reachability_path(by_id, "core-switch", device.id)


def test_reachability_path_from_a_different_vantage_point(seeded_devices):
    by_id = {d.id: d for d in seeded_devices}
    # A station plugged into the CSE switch reaches the Library through the core.
    assert topology.reachability_path(by_id, "cse-switch", "library-pc-1") == ["cse-switch", "core-switch", "library-switch"]
    assert topology.reachability_path(by_id, "cse-switch", "cse-pc-2") == ["cse-switch"]


def test_reachability_path_unknown_vantage_rejected(seeded_devices):
    by_id = {d.id: d for d in seeded_devices}
    with pytest.raises(InvalidNetworkData, match="vantage"):
        topology.reachability_path(by_id, "ghost", "cse-pc-1")
