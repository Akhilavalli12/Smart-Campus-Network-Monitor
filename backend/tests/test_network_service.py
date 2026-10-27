"""Contract tests: run against the in-memory store AND MongoNetworkStore (real driver)."""
import pytest

from app.network_model import service
from app.network_model.errors import ConflictError, InvalidNetworkData, NotFoundError
from app.network_model.models import DeviceCreate, Subnet
from app.network_model.seed import seed_database


def new_pc(**overrides) -> DeviceCreate:
    fields = dict(name="CSE PC 4", type="pc", ip="192.168.10.104", subnet_id="cse-net", block="cse", parent_id="cse-switch")
    fields.update(overrides)
    return DeviceCreate(**fields)


@pytest.fixture
async def seeded(store):
    await seed_database(store)
    return store


# ---------- device registration: happy paths ----------
async def test_register_device_creates_device_and_uplink(seeded):
    device = await service.register_device(seeded, new_pc())
    assert device.id == "cse-pc-4"  # derived from the name
    assert device.status == "unknown"
    assert device.mac.startswith("02:")
    assert device.base_rtt_ms == 5.0  # simulator default
    link = next(l for l in await seeded.list_links() if l.id == "cse-switch--cse-pc-4")
    assert (link.kind, link.capacity_mbps) == ("access", 100.0)


async def test_custom_uplink_capacity(seeded):
    await service.register_device(seeded, new_pc(uplink_capacity_mbps=1000))
    link = next(l for l in await seeded.list_links() if l.b_id == "cse-pc-4")
    assert link.capacity_mbps == 1000


async def test_real_device_needs_probe_target_and_keeps_modelled_ip(seeded):
    device = await service.register_device(seeded, new_pc(monitoring_mode="real", probe_target="192.168.43.7"))
    assert device.ip == "192.168.10.104" and device.probe_target == "192.168.43.7"
    assert device.base_rtt_ms is None


async def test_roundtrip_through_store_keeps_types(seeded):
    device = await seeded.get_device("cse-switch")
    assert device.created_at.tzinfo is not None
    assert device.type == "switch" and device.monitoring_mode == "simulated"
    assert [d.id for d in await seeded.list_devices(block="cse", type="pc")] == ["cse-pc-1", "cse-pc-2", "cse-pc-3"]


# ---------- device registration: rule violations ----------
async def test_duplicate_ip_conflicts(seeded):
    with pytest.raises(ConflictError, match="already assigned to CSE PC 1"):
        await service.register_device(seeded, new_pc(ip="192.168.10.101"))


async def test_duplicate_id_conflicts(seeded):
    with pytest.raises(ConflictError, match="already exists"):
        await service.register_device(seeded, new_pc(id="cse-pc-1"))


@pytest.mark.parametrize("ip", ["192.168.99.5", "192.168.10.0", "192.168.10.255", "10.0.0.50"])
async def test_ip_must_be_usable_host_of_subnet(seeded, ip):
    with pytest.raises(InvalidNetworkData, match="not a usable host address"):
        await service.register_device(seeded, new_pc(ip=ip))


async def test_gateway_address_is_reserved(seeded):
    with pytest.raises(InvalidNetworkData, match="reserved as the default gateway"):
        await service.register_device(seeded, new_pc(ip="192.168.10.1"))


async def test_unknown_subnet_and_parent_and_missing_fields(seeded):
    with pytest.raises(InvalidNetworkData, match="Unknown subnet"):
        await service.register_device(seeded, new_pc(subnet_id="nope-net"))
    with pytest.raises(InvalidNetworkData, match="Unknown parent"):
        await service.register_device(seeded, new_pc(parent_id="ghost"))
    with pytest.raises(InvalidNetworkData, match="subnet_id is required"):
        await service.register_device(seeded, new_pc(subnet_id=None))
    with pytest.raises(InvalidNetworkData, match="parent_id is required"):
        await service.register_device(seeded, new_pc(parent_id=None))


async def test_block_must_match_subnet(seeded):
    with pytest.raises(InvalidNetworkData, match="does not match subnet block"):
        await service.register_device(seeded, new_pc(block="library"))


async def test_illegal_parent_child_type(seeded):
    with pytest.raises(InvalidNetworkData, match="cannot have a pc"):
        await service.register_device(seeded, new_pc(parent_id="core-switch"))


async def test_monitoring_mode_rules(seeded):
    with pytest.raises(InvalidNetworkData, match="probe_target .* required"):
        await service.register_device(seeded, new_pc(monitoring_mode="real"))
    with pytest.raises(InvalidNetworkData, match="only applies"):
        await service.register_device(seeded, new_pc(probe_target="192.168.43.7"))


async def test_only_one_internet_root(seeded):
    with pytest.raises(ConflictError, match="already has an Internet root"):
        await service.register_device(
            seeded,
            DeviceCreate(name="Second Internet", type="internet", ip="8.8.8.8", block="backbone", monitoring_mode="real", probe_target="8.8.8.8"),
        )


async def test_store_enforces_unique_ip_even_if_service_is_bypassed(seeded):
    clone = (await seeded.get_device("cse-pc-1")).model_copy(update={"id": "sneaky"})
    with pytest.raises(ConflictError):
        await seeded.insert_device(clone)


# ---------- deletion ----------
async def test_cannot_delete_device_with_downstream_devices(seeded):
    with pytest.raises(ConflictError, match="downstream"):
        await service.remove_device(seeded, "cse-switch")


async def test_delete_leaf_removes_device_and_its_link(seeded):
    await service.remove_device(seeded, "cse-pc-3")
    assert await seeded.get_device("cse-pc-3") is None
    assert "core-switch--cse-switch" in {l.id for l in await seeded.list_links()}
    assert "cse-switch--cse-pc-3" not in {l.id for l in await seeded.list_links()}
    assert len(await seeded.list_links()) == 15


async def test_delete_unknown_device_is_404(seeded):
    with pytest.raises(NotFoundError):
        await service.remove_device(seeded, "ghost")


# ---------- subnet registration ----------
def subnet(**overrides) -> Subnet:
    fields = dict(id="lab-net", name="Lab Network", cidr="192.168.40.0/24", block="cse", gateway="192.168.40.1")
    fields.update(overrides)
    return Subnet(**fields)


async def test_register_valid_subnet(seeded):
    created = await service.register_subnet(seeded, subnet())
    assert created.cidr == "192.168.40.0/24"
    assert (await seeded.get_subnet("lab-net")).gateway == "192.168.40.1"


async def test_overlapping_subnet_conflicts(seeded):
    with pytest.raises(ConflictError, match="overlaps"):
        await service.register_subnet(seeded, subnet(cidr="192.168.10.128/25", gateway=None))


@pytest.mark.parametrize(
    "overrides,message",
    [({"cidr": "8.8.8.0/24", "gateway": None}, "RFC 1918"),
     ({"cidr": "192.168.40.5/24"}, "host bits"),
     ({"cidr": "192.168.40.4/31", "gateway": None}, "at least 2 usable"),
     ({"gateway": "192.168.41.1"}, "not a usable host"),
     ({"gateway": "192.168.40.255"}, "not a usable host")],
)
async def test_invalid_subnets_rejected(seeded, overrides, message):
    with pytest.raises(InvalidNetworkData, match=message):
        await service.register_subnet(seeded, subnet(**overrides))


# ---------- derived views ----------
async def test_topology_and_path(seeded):
    topo = await service.build_topology(seeded)
    assert (len(topo.nodes), len(topo.edges)) == (17, 16)
    assert topo.nodes[0].id == "internet" and topo.nodes[0].depth == 0
    depths = {n.id: n.depth for n in topo.nodes}
    assert depths["core-switch"] == 2 and depths["admin-pc-2"] == 4
    path = await service.path_to_internet(seeded, "library-pc-1")
    assert [h.id for h in path.hops] == ["library-pc-1", "library-switch", "core-switch", "edge-router", "internet"]


@pytest.mark.parametrize("target", ["224.0.0.1", "255.255.255.255", "0.0.0.0"])
async def test_real_device_rejects_non_unicast_probe_target(seeded, target):
    with pytest.raises(InvalidNetworkData, match="Probe target"):
        await service.register_device(seeded, new_pc(monitoring_mode="real", probe_target=target))
