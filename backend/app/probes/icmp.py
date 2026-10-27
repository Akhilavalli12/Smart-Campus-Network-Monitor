"""Real ICMP probing.

Two interchangeable backends send genuine ICMP Echo Requests (type 8) and wait
for Echo Replies (type 0):

* IcmplibBackend  - builds ICMP packets itself via the `icmplib` package.
  Needs raw sockets (root / Administrator / CAP_NET_RAW) or, on Linux/macOS, the
  OS setting that allows unprivileged ICMP datagram sockets.
* SystemPingBackend - runs the operating system's own `ping` program (which is
  already privileged) with an argument list (never a shell) and parses its output.

`RealIcmpProbe` picks a backend ("auto" tries icmplib, then falls back to the
system ping if icmplib lacks permission).
"""
import asyncio
import math
import re
import shutil
import sys
from collections.abc import Sequence
from typing import Protocol

from icmplib import ICMPLibError, SocketPermissionError, async_ping

from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device
from app.network_model.addressing import validate_probe_target
from app.probes.base import ProbeResult, ProbeSettings, probe_error


class IcmpBackend(Protocol):
    name: str

    async def ping(self, address: str, settings: ProbeSettings) -> tuple[int, list[float]]:
        """Send `settings.count` echo requests; return (packets_sent, rtts_ms of replies)."""
        ...


class BackendUnavailable(Exception):
    """This backend cannot run here (missing permission or program)."""


def overall_timeout(settings: ProbeSettings) -> float:
    """Upper bound for a whole probe: every request waits at most `timeout_s`, plus the gaps."""
    return settings.count * settings.timeout_s + (settings.count - 1) * settings.interval_s + 2.0


class IcmplibBackend:
    """icmplib ping with automatic socket-mode selection.

    Windows: raw sockets only (needs Administrator). Linux/macOS: try an unprivileged
    ICMP datagram socket first (works without root if the OS allows it), then a raw
    socket (works as root / with CAP_NET_RAW). The mode that works is remembered.
    """

    name = "icmplib"

    def __init__(self, privileged: bool | None = None) -> None:
        if privileged is not None:
            self._modes = [privileged]
        elif sys.platform == "win32":
            self._modes = [True]
        else:
            self._modes = [False, True]

    async def ping(self, address: str, settings: ProbeSettings) -> tuple[int, list[float]]:
        for privileged in list(self._modes):
            try:
                host = await asyncio.wait_for(
                    async_ping(
                        address,
                        count=settings.count,
                        interval=settings.interval_s,
                        timeout=settings.timeout_s,
                        privileged=privileged,
                    ),
                    timeout=overall_timeout(settings),
                )
            except SocketPermissionError:
                continue  # try the next socket mode
            self._modes = [privileged]  # remember what works
            return host.packets_sent, list(host.rtts)
        raise BackendUnavailable("icmplib has no permission to open an ICMP socket (needs root/Administrator or an OS setting)")


# One reply line looks like (Linux/macOS): "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms"
# or (Windows):                            "Reply from 1.1.1.1: bytes=32 time=12ms TTL=117" / "time<1ms".
# We key on "<number> ms followed by TTL" (Windows) or "ttl=... time=<number> ms" (Unix) so that
# error lines such as "Destination host unreachable" never count as replies.
_UNIX_REPLY = re.compile(r"ttl=\d+\s+time[=<]?\s*([\d.]+)\s*ms", re.IGNORECASE)
_WINDOWS_REPLY = re.compile(r"[=<]\s*([\d.]+)\s*ms\s+TTL=\d+", re.IGNORECASE)


def parse_ping_output(output: str) -> list[float]:
    """Extract per-reply RTTs (ms) from the text printed by `ping`. Order is preserved."""
    rtts: list[float] = []
    for line in output.splitlines():
        match = _UNIX_REPLY.search(line) or _WINDOWS_REPLY.search(line)
        if match:
            value = float(match.group(1))
            # Windows prints "time<1ms" for sub-millisecond replies; we record that as the bound (1 ms).
            rtts.append(value)
    return rtts


def parse_sent_count(output: str) -> int | None:
    """Packets transmitted according to the summary line (English `ping` only)."""
    unix = re.search(r"(\d+)\s+packets transmitted", output)
    if unix:
        return int(unix.group(1))
    windows = re.search(r"Packets:\s*Sent\s*=\s*(\d+)", output, re.IGNORECASE)
    return int(windows.group(1)) if windows else None


def build_ping_command(platform: str, address: str, settings: ProbeSettings) -> list[str]:
    """Argument list for the OS `ping`. `address` must already be a validated IPv4 literal."""
    if platform == "win32":
        # Windows ping cannot set the gap between requests (it uses ~1 s); -w is milliseconds.
        return ["ping", "-n", str(settings.count), "-w", str(int(settings.timeout_s * 1000)), address]
    if platform == "darwin":
        # macOS: -i seconds between packets, -W milliseconds to wait for a reply.
        return ["ping", "-n", "-c", str(settings.count), "-i", f"{settings.interval_s:g}", "-W", str(int(settings.timeout_s * 1000)), address]
    # Linux (iputils): -W is whole seconds, rounded up so we never wait less than asked.
    return ["ping", "-n", "-c", str(settings.count), "-i", f"{settings.interval_s:g}", "-W", str(max(1, math.ceil(settings.timeout_s))), address]


class SystemPingBackend:
    name = "system-ping"

    def __init__(self, platform: str | None = None) -> None:
        self._platform = platform or sys.platform

    async def ping(self, address: str, settings: ProbeSettings) -> tuple[int, list[float]]:
        if shutil.which("ping") is None:
            raise BackendUnavailable("the system `ping` program was not found")
        command = build_ping_command(self._platform, address, settings)
        # create_subprocess_exec passes the list straight to the OS: no shell, so no injection.
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=overall_timeout(settings) + settings.count)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        text = stdout.decode("utf-8", errors="replace")
        rtts = parse_ping_output(text)
        sent = parse_sent_count(text)
        if sent is None:
            # No summary line: either ping failed to run, or its output is in a language we
            # cannot read. With replies we assume all requests were sent; without, report
            # "nothing sent" so the caller flags a probe ERROR instead of a false 100% loss.
            sent = settings.count if rtts else 0
        return max(sent, len(rtts)), rtts


class RealIcmpProbe:
    """Probe a real host with genuine ICMP Echo Requests."""

    def __init__(
        self,
        backend: str = "auto",
        *,
        icmplib_backend: IcmpBackend | None = None,
        system_backend: IcmpBackend | None = None,
    ) -> None:
        if backend not in ("auto", "icmplib", "system"):
            raise ValueError("backend must be 'auto', 'icmplib' or 'system'")
        self._mode = backend
        self._icmplib = icmplib_backend or IcmplibBackend()
        self._system = system_backend or SystemPingBackend()
        self._sticky: IcmpBackend | None = None  # once a backend works (or fails permanently), reuse the decision

    def _candidates(self) -> list[IcmpBackend]:
        if self._sticky is not None:
            return [self._sticky]
        if self._mode == "icmplib":
            return [self._icmplib]
        if self._mode == "system":
            return [self._system]
        return [self._icmplib, self._system]

    async def probe(self, device: Device, settings: ProbeSettings, *, upstream: Sequence[Device] = ()) -> ProbeResult:
        # 1. Validate BEFORE anything reaches a socket or a subprocess.
        try:
            target = str(validate_probe_target(device.probe_target or ""))
        except InvalidNetworkData as exc:
            return probe_error(device, "real", device.probe_target or "", "none", f"invalid probe target: {exc}")

        problems: list[str] = []
        for backend in self._candidates():
            try:
                sent, rtts = await backend.ping(target, settings)
            except BackendUnavailable as exc:
                problems.append(f"{backend.name}: {exc}")
                continue
            except asyncio.TimeoutError:
                return probe_error(device, "real", target, backend.name, "probe exceeded its overall time limit")
            except ICMPLibError as exc:
                return probe_error(device, "real", target, backend.name, f"{type(exc).__name__}: {exc}")
            except OSError as exc:
                return probe_error(device, "real", target, backend.name, f"OS error: {exc}")

            self._sticky = backend
            if sent == 0:
                # Nothing could even be sent (for example "network is unreachable"): not packet loss.
                return probe_error(device, "real", target, backend.name, "no echo request could be sent or the ping output could not be read (no route, network down, or non-English ping output)")
            return ProbeResult(
                device_id=device.id,
                source="real",
                target=target,
                sent=sent,
                received=len(rtts),
                rtts_ms=tuple(rtts),
                backend=backend.name,
            )
        return probe_error(device, "real", target, "none", "no ICMP backend available: " + "; ".join(problems))
