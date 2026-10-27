"""Inject or clear simulated faults from the command line (Stage 6 adds API + UI).

    python -m app.simulator list
    python -m app.simulator inject cse-switch offline
    python -m app.simulator inject cse-ap high_latency --param rtt_ms=300
    python -m app.simulator inject library-pc-1 packet_loss --param loss_pct=30
    python -m app.simulator inject core-switch congestion --param utilization_pct=97
    python -m app.simulator clear cse-switch
    python -m app.simulator clear --all
"""
import argparse
import asyncio
import sys

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db import MongoManager
from app.network_model.errors import NetworkModelError
from app.network_model.store import MongoNetworkStore
from app.simulator.faults import set_fault


async def _main(args: argparse.Namespace) -> int:
    mongo = MongoManager(get_settings())
    store = MongoNetworkStore(mongo.db)
    try:
        if args.command == "list":
            for device in await store.list_devices():
                if device.monitoring_mode == "simulated":
                    state = device.sim_state
                    detail = f" {state.params}" if state.params else ""
                    marker = "  <-- FAULT" if state.fault != "none" else ""
                    print(f"{device.id:<16} {state.fault}{detail}{marker}")
        elif args.command == "inject":
            params = {}
            for item in args.param:
                key, sep, value = item.partition("=")
                if not sep:
                    raise NetworkModelError(f"--param must look like KEY=VALUE, got {item!r}")
                params[key] = float(value)
            device = await set_fault(store, args.device, args.fault, params)
            print(f"{device.name}: fault '{args.fault}' injected {params or ''}".rstrip())
        elif args.command == "clear":
            targets = (
                [d.id for d in await store.list_devices() if d.monitoring_mode == "simulated" and d.sim_state.fault != "none"]
                if args.all
                else [args.device]
            )
            for device_id in targets:
                device = await set_fault(store, device_id, "none")
                print(f"{device.name}: fault cleared")
            if args.all and not targets:
                print("No faults were active.")
        return 0
    except (NetworkModelError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PyMongoError as exc:
        print(f"Cannot reach MongoDB ({type(exc).__name__}). Is it running?", file=sys.stderr)
        return 1
    finally:
        await mongo.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.simulator", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    inject = sub.add_parser("inject")
    inject.add_argument("device")
    inject.add_argument("fault")
    inject.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    clear = sub.add_parser("clear")
    clear.add_argument("device", nargs="?")
    clear.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.command == "clear" and not (args.device or args.all):
        parser.error("give a device id or --all")
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
