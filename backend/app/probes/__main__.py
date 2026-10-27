"""Manual probe tool: see a real (or simulated) probe with your own eyes.

    python -m app.probes 127.0.0.1                       # real ICMP, 5 echo requests
    python -m app.probes 1.1.1.1 --count 10 --backend system
    python -m app.probes --simulate --base-rtt 8 --fault offline
    python -m app.probes --simulate --fault congestion --param utilization_pct=95 --count 20
"""
import argparse
import asyncio
import sys

from app.config import get_settings
from app.network_model.enums import FaultType
from app.network_model.models import Device, SimState
from app.probes.base import ProbeResult, ProbeSettings
from app.probes.icmp import RealIcmpProbe
from app.simulator import SimulatedProbe, SimulatorConfig


def _device(address: str, simulated: bool, base_rtt: float, fault: str, params: dict[str, float]) -> Device:
    return Device(
        id="cli",
        name="cli",
        type="pc",
        ip=address,
        block="backbone",
        monitoring_mode="simulated" if simulated else "real",
        probe_target=None if simulated else address,
        base_rtt_ms=base_rtt if simulated else None,
        sim_state=SimState(fault=FaultType(fault), params=params),
    )


def format_result(result: ProbeResult) -> str:
    badge = result.source.upper()
    lines = [f"[{badge}] target={result.target} backend={result.backend}"]
    if not result.ok:
        lines.append(f"PROBE ERROR (this is not packet loss): {result.error}")
        return "\n".join(lines)
    for index, rtt in enumerate(result.rtts_ms, start=1):
        lines.append(f"  reply {index}: {rtt:.3f} ms")
    lines.append(f"sent={result.sent} received={result.received} loss={result.loss_pct:.1f}%")
    if result.rtts_ms:
        jitter = f"{result.jitter_ms:.3f} ms" if result.jitter_ms is not None else "n/a (needs 2+ replies)"
        lines.append(f"rtt min/avg/max = {result.rtt_min_ms:.3f}/{result.rtt_avg_ms:.3f}/{result.rtt_max_ms:.3f} ms  jitter={jitter}")
    lines.append("reachable" if result.reachable else "NO REPLY")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    probe_settings = ProbeSettings(count=args.count, timeout_s=args.timeout, interval_s=args.interval)
    if args.simulate:
        params = {}
        for item in args.param:
            key, _, value = item.partition("=")
            params[key] = float(value)
        device = _device("0.0.0.0", True, args.base_rtt, args.fault, params)
        result = await SimulatedProbe(SimulatorConfig(seed=settings.simulator_seed)).probe(device, probe_settings)
    else:
        if not args.target:
            print("error: give a target IPv4 address, or use --simulate", file=sys.stderr)
            return 2
        device = _device(args.target, False, 0, "none", {})
        result = await RealIcmpProbe(args.backend).probe(device, probe_settings)
    print(format_result(result))
    return 0 if result.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.probes", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="IPv4 address to ping (real mode)")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--backend", choices=["auto", "icmplib", "system"], default="auto")
    parser.add_argument("--simulate", action="store_true", help="use the simulator instead of real ICMP")
    parser.add_argument("--base-rtt", type=float, default=8.0)
    parser.add_argument("--fault", choices=[f.value for f in FaultType], default="none")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
