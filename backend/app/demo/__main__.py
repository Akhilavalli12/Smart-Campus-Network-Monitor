"""Load 24 hours of demo history so every graph and the alert list are populated.

    python -m app.demo                 # generate and load (replaces measurements, traffic, events and alerts)
    python -m app.demo --if-empty      # only when there is no history yet (used by start.sh / start.bat)
    python -m app.demo --hours 12 --step 30
"""
import argparse
import asyncio
import sys
import time

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db import MongoManager
from app.demo.backfill import INCIDENTS, generate_history, write_history


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    mongo = MongoManager(settings)
    try:
        existing = await mongo.db["measurements"].count_documents({}) if args.if_empty else 0
        if args.if_empty and existing > 0:
            print(f"History already present ({existing} measurements): nothing to do.")
            return 0
        if await mongo.db["devices"].count_documents({}) == 0:
            print("No devices found. Run: python -m app.network_model.seed")
            return 1
        print(f"Generating {args.hours:g} h of history (one probe cycle every {args.step}s) with the real engines in fast-forward...")
        started = time.perf_counter()
        history = await generate_history(hours=args.hours, step_s=args.step)
        info = await write_history(mongo.db, history, retention_hours=settings.measurement_retention_hours)
        print(
            f"Done in {time.perf_counter() - started:.1f}s: {info['measurements']} measurements, {info['traffic_samples']} traffic samples, "
            f"{info['events']} status changes, {info['alerts']} alerts."
        )
        print("Incidents in the history:")
        for incident in INCIDENTS:
            print(f"  - {incident.hours_ago:g} h ago, {incident.minutes:g} min: {incident.story}")
        print("This history is GENERATED demo data (backend 'demo-backfill'). Live monitoring continues from now on.")
        return 0
    except PyMongoError as exc:
        print(f"Cannot reach MongoDB ({type(exc).__name__}). Is it running?", file=sys.stderr)
        return 1
    finally:
        await mongo.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.demo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--step", type=int, default=60, help="seconds between probe cycles in the generated history")
    parser.add_argument("--if-empty", action="store_true")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
