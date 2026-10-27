"""REAL traffic counters of the computer running the monitor, read with psutil.

This is genuine data about THIS machine's network interfaces. It is not campus traffic and is
never mixed into the simulated campus numbers.
"""
import socket
from dataclasses import dataclass

import psutil

from app.traffic.counters import CounterReading


class HostNicError(Exception):
    """The requested interface cannot be read."""


@dataclass(frozen=True)
class HostReading:
    label: str
    interfaces: tuple[str, ...]
    counters: CounterReading
    speed_mbps: float | None  # link speed reported by the OS; None when unknown (Wi-Fi, virtual NICs, several NICs)


def _is_loopback(name: str, addresses: dict[str, list]) -> bool:
    if name.lower() in ("lo", "lo0") or name.lower().startswith("loopback"):
        return True
    return any(a.address.startswith("127.") for a in addresses.get(name, []) if a.family == socket.AF_INET)


class HostNicSource:
    """`nic` empty = sum of all interfaces that are up and not loopback; otherwise exactly that interface."""

    source = "real"

    def __init__(self, nic: str = "", psutil_module=psutil) -> None:
        self._nic = nic.strip()
        self._psutil = psutil_module

    def read(self) -> HostReading | None:
        io = self._psutil.net_io_counters(pernic=True, nowrap=True)  # nowrap: psutil already corrects wrapped OS counters
        stats = self._psutil.net_if_stats()
        addrs = self._psutil.net_if_addrs()

        if self._nic:
            if self._nic not in io:
                raise HostNicError(f"interface {self._nic!r} not found; available: {sorted(io)}")
            names = [self._nic]
        else:
            names = sorted(n for n in io if stats.get(n) is not None and stats[n].isup and not _is_loopback(n, addrs))
        if not names:
            return None

        rx = sum(io[n].bytes_recv for n in names)
        tx = sum(io[n].bytes_sent for n in names)
        rxp = sum(io[n].packets_recv for n in names)
        txp = sum(io[n].packets_sent for n in names)
        speed = None
        if len(names) == 1 and stats.get(names[0]) is not None and stats[names[0]].speed > 0:
            speed = float(stats[names[0]].speed)
        label = names[0] if len(names) == 1 else f"all non-loopback interfaces ({', '.join(names)})"
        return HostReading(label, tuple(names), CounterReading(rx, tx, rxp, txp, bits=64), speed)
