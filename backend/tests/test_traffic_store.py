"""TrafficStore + link-update contract: in-memory AND the real driver."""
from datetime import datetime, timedelta, timezone

import pytest

from app.network_model.seed import seed_database
from app.traffic.models import TrafficSample

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def sample(ref="core-switch--cse-switch", minutes=0, scope="link", **kw):
    fields = dict(scope=scope, ref_id=ref, ts=T0 + timedelta(minutes=minutes), source="simulated", dt_s=5.0, capacity_mbps=100.0,
                  rx_bytes=4_000_000_000, tx_bytes=123, rx_packets=7, tx_packets=8, rx_mbps=42.5, tx_mbps=10.0, rx_pps=100.0, tx_pps=50.0,
                  util_pct=42.5, wrapped=True, proto_bytes={"tcp": 10, "udp": 5, "dns": 1, "icmp": 0, "other": 2})
    fields.update(kw)
    return TrafficSample(**fields)


async def test_samples_roundtrip_oldest_first_filtered_by_scope_and_ref(traffic_store):
    await traffic_store.insert_samples([sample(minutes=m) for m in (3, 1, 2)] + [sample("other-link", minutes=0)] + [sample("host", scope="host", source="real", proto_bytes=None, label="eth0", capacity_mbps=None, util_pct=None)])
    rows = await traffic_store.list_samples("link", ["core-switch--cse-switch"])
    assert [r.ts for r in rows] == [T0 + timedelta(minutes=m) for m in (1, 2, 3)]
    assert rows[0].rx_bytes == 4_000_000_000 and rows[0].wrapped is True and rows[0].proto_bytes["tcp"] == 10
    both = await traffic_store.list_samples("link", ["core-switch--cse-switch", "other-link"])
    assert len(both) == 4
    host = await traffic_store.list_samples("host", ["host"])
    assert len(host) == 1 and host[0].source == "real" and host[0].util_pct is None and host[0].proto_bytes is None and host[0].label == "eth0"


async def test_limit_keeps_the_most_recent_and_since_filters(traffic_store):
    await traffic_store.insert_samples([sample(minutes=m) for m in range(10)])
    assert [r.ts for r in await traffic_store.list_samples("link", limit=3)] == [T0 + timedelta(minutes=m) for m in (7, 8, 9)]
    assert len(await traffic_store.list_samples("link", since=T0 + timedelta(minutes=6))) == 4
    assert len(await traffic_store.list_samples("link", None)) == 10  # ref_ids=None means every reference


async def test_inserting_nothing_is_fine(traffic_store):
    await traffic_store.insert_samples([])
    assert await traffic_store.list_samples("link") == []


async def test_link_latest_roundtrips_through_update_link_fields(store):
    await seed_database(store)
    latest = {"ts": T0, "source": "simulated", "rx_mbps": 12.5, "tx_mbps": 3.0, "rx_pps": 100.0, "tx_pps": 40.0, "util_pct": 12.5}
    assert await store.update_link_fields("core-switch--cse-switch", {"latest": latest})
    link = next(l for l in await store.list_links() if l.id == "core-switch--cse-switch")
    assert link.latest.rx_mbps == 12.5 and link.latest.ts == T0 and link.latest.util_pct == 12.5
    assert next(l for l in await store.list_links() if l.id == "core-switch--library-switch").latest is None


async def test_link_updates_refuse_identity_fields_and_unknown_links(store):
    await seed_database(store)
    for forbidden in ("capacity_mbps", "a_id", "b_id", "kind", "_id"):
        with pytest.raises(ValueError, match="not updatable"):
            await store.update_link_fields("core-switch--cse-switch", {forbidden: 1})
    assert await store.update_link_fields("ghost", {"latest": None}) is False


async def test_traffic_indexes_on_the_real_driver(traffic_store):
    from app.traffic.store import MongoTrafficStore

    if not isinstance(traffic_store, MongoTrafficStore):
        pytest.skip("index creation only applies to MongoDB")
    await traffic_store.ensure_indexes()
    names = set((await traffic_store._samples.index_information()).keys())
    assert "scope_ref_ts" in names
    await traffic_store.ensure_indexes()  # idempotent
