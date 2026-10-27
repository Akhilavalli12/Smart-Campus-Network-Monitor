"""Seed the database with the demo campus.

    python -m app.network_model.seed            # add anything missing (idempotent)
    python -m app.network_model.seed --reset    # wipe subnets/devices/links, then seed
    python -m app.network_model.seed --reset --internet-target 8.8.8.8   # real host the Internet node pings
    python -m app.network_model.seed --reset --internet-simulated        # no real pings at all (demo without internet access)

Seeding goes through the same service functions as the API, so the seed data is
validated by exactly the same rules as user input.
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db import MongoManager
from app.network_model import seed_data, service
from app.network_model.errors import ConflictError, NetworkModelError
from app.network_model.store import MongoNetworkStore, NetworkStore


@dataclass
class SeedReport:
    subnets_added: int = 0
    subnets_skipped: int = 0
    devices_added: int = 0
    devices_skipped: int = 0
    links_total: int = 0


async def seed_database(
    store: NetworkStore, *, reset: bool = False, internet_target: str = seed_data.DEFAULT_INTERNET_TARGET, internet_real: bool = True
) -> SeedReport:
    report = SeedReport()
    if reset:
        await store.clear_network()
    for subnet in seed_data.SUBNETS:
        try:
            await service.register_subnet(store, subnet)
            report.subnets_added += 1
        except ConflictError:
            report.subnets_skipped += 1
    for payload in seed_data.build_devices(internet_target, internet_real):
        try:
            await service.register_device(store, payload)
            report.devices_added += 1
        except ConflictError:
            report.devices_skipped += 1
    report.links_total = len(await store.list_links())
    return report


async def _main(reset: bool, internet_target: str, internet_real: bool) -> int:
    settings = get_settings()
    mongo = MongoManager(settings)
    store = MongoNetworkStore(mongo.db)
    try:
        await store.ensure_indexes()
        report = await seed_database(store, reset=reset, internet_target=internet_target, internet_real=internet_real)
    except (NetworkModelError, ValueError) as exc:
        print(f"Invalid seed option: {exc}")
        return 2
    except PyMongoError as exc:
        print(f"Cannot reach MongoDB ({type(exc).__name__}). Check MONGODB_URI in backend/.env and that the server is running.")
        return 1
    finally:
        await mongo.close()
    print(
        f"Seed complete: subnets +{report.subnets_added} (skipped {report.subnets_skipped}), "
        f"devices +{report.devices_added} (skipped {report.devices_skipped}), links total {report.links_total}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo campus network")
    parser.add_argument("--reset", action="store_true", help="delete subnets, devices and links first")
    parser.add_argument("--internet-target", default=seed_data.DEFAULT_INTERNET_TARGET, metavar="IPV4",
                        help="real host the Internet node pings (default %(default)s)")
    parser.add_argument("--internet-simulated", action="store_true", help="make the Internet node SIMULATED too, so nothing is pinged for real")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.reset, args.internet_target, not args.internet_simulated)))


if __name__ == "__main__":
    main()
