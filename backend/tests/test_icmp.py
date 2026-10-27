import asyncio
import os
import shutil

import pytest
from icmplib import ICMPLibError

from app.probes.base import ProbeSettings
from app.probes.icmp import (
    BackendUnavailable,
    IcmplibBackend,
    RealIcmpProbe,
    SystemPingBackend,
    build_ping_command,
    parse_ping_output,
    parse_sent_count,
)
from tests.helpers import make_device

SETTINGS = ProbeSettings(count=3, timeout_s=0.5, interval_s=0.2)

# Captured from a real Linux iputils ping run.
LINUX_OK = """PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.
64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.023 ms
64 bytes from 127.0.0.1: icmp_seq=2 ttl=64 time=0.039 ms
64 bytes from 127.0.0.1: icmp_seq=3 ttl=64 time=0.037 ms

--- 127.0.0.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 407ms
rtt min/avg/max/mdev = 0.023/0.033/0.039/0.007 ms
"""
LINUX_TOTAL_LOSS = """PING 10.255.255.1 (10.255.255.1) 56(84) bytes of data.

--- 10.255.255.1 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 202ms

"""
# Typical Windows (English) output, written from the documented format; not captured on a Windows machine here.
WINDOWS_PARTIAL = """Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=12ms TTL=117
Request timed out.
Reply from 8.8.8.8: bytes=32 time<1ms TTL=117
Reply from 192.168.1.50: Destination host unreachable.

Ping statistics for 8.8.8.8:
    Packets: Sent = 4, Received = 2, Lost = 2 (50% loss),
"""
# Typical macOS output, written from the documented format; not captured on a Mac here.
MACOS_OK = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=12.345 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.9 ms

--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 packets received, 0.0% packet loss
"""


# ---------- output parsing ----------
def test_parse_linux_output():
    assert parse_ping_output(LINUX_OK) == [0.023, 0.039, 0.037]
    assert parse_sent_count(LINUX_OK) == 3


def test_parse_total_loss_has_no_replies_but_knows_how_many_were_sent():
    assert parse_ping_output(LINUX_TOTAL_LOSS) == []
    assert parse_sent_count(LINUX_TOTAL_LOSS) == 2


def test_parse_windows_ignores_timeouts_and_destination_unreachable():
    assert parse_ping_output(WINDOWS_PARTIAL) == [12.0, 1.0]  # "<1ms" is recorded as its 1 ms upper bound
    assert parse_sent_count(WINDOWS_PARTIAL) == 4


def test_parse_macos_output():
    assert parse_ping_output(MACOS_OK) == [12.345, 11.9]
    assert parse_sent_count(MACOS_OK) == 2


def test_parse_garbage_finds_nothing():
    assert parse_ping_output("ping: connect: Network is unreachable") == []
    assert parse_sent_count("ping: connect: Network is unreachable") is None


# ---------- command construction ----------
@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_command_is_an_argument_list_ending_with_the_target(platform):
    command = build_ping_command(platform, "10.0.0.2", SETTINGS)
    assert isinstance(command, list) and command[0] == "ping" and command[-1] == "10.0.0.2"
    assert all(isinstance(part, str) for part in command)


def test_command_flags_per_platform():
    linux = build_ping_command("linux", "10.0.0.2", ProbeSettings(count=4, timeout_s=1.5, interval_s=0.2))
    assert linux == ["ping", "-n", "-c", "4", "-i", "0.2", "-W", "2", "10.0.0.2"]  # -W is whole seconds, rounded up
    mac = build_ping_command("darwin", "10.0.0.2", ProbeSettings(count=4, timeout_s=1.5, interval_s=0.2))
    assert mac[mac.index("-W") + 1] == "1500"  # macOS -W is milliseconds
    win = build_ping_command("win32", "10.0.0.2", ProbeSettings(count=4, timeout_s=1.5, interval_s=0.2))
    assert win == ["ping", "-n", "4", "-w", "1500", "10.0.0.2"]  # Windows: -n count, -w milliseconds


# ---------- RealIcmpProbe logic with fake backends ----------
class FakeBackend:
    def __init__(self, name="fake", result=(5, [1.0, 2.0, 3.0, 4.0]), raises=None):
        self.name, self._result, self._raises, self.calls = name, result, raises, []

    async def ping(self, address, settings):
        self.calls.append(address)
        if self._raises:
            raise self._raises
        return self._result


def real_device(target="192.168.43.7"):
    return make_device("laptop", mode="real", probe_target=target)


def probe_with(icmplib=None, system=None, mode="auto"):
    return RealIcmpProbe(mode, icmplib_backend=icmplib or FakeBackend("icmplib"), system_backend=system or FakeBackend("system-ping"))


def run(probe, device):
    return asyncio.run(probe.probe(device, SETTINGS))


def test_success_computes_loss_from_sent_and_received():
    result = run(probe_with(), real_device())
    assert (result.source, result.sent, result.received, result.backend) == ("real", 5, 4, "icmplib")
    assert result.loss_pct == pytest.approx(20.0)
    assert result.target == "192.168.43.7"


def test_nothing_sent_is_a_probe_error_not_packet_loss():
    result = run(probe_with(icmplib=FakeBackend("icmplib", result=(0, []))), real_device())
    assert not result.ok and result.loss_pct is None and "no echo request" in result.error


def test_auto_falls_back_to_system_ping_and_remembers_the_choice():
    icmplib = FakeBackend("icmplib", raises=BackendUnavailable("no permission"))
    system = FakeBackend("system-ping", result=(3, [5.0, 6.0, 7.0]))
    probe = probe_with(icmplib, system)
    first = run(probe, real_device())
    second = run(probe, real_device())
    assert first.backend == second.backend == "system-ping" and first.received == 3
    assert len(icmplib.calls) == 1 and len(system.calls) == 2  # icmplib not retried every cycle


def test_forced_backend_does_not_fall_back():
    icmplib = FakeBackend("icmplib", raises=BackendUnavailable("no permission"))
    system = FakeBackend("system-ping")
    result = run(probe_with(icmplib, system, mode="icmplib"), real_device())
    assert not result.ok and system.calls == []


def test_both_backends_unavailable_reports_both_reasons():
    probe = probe_with(
        FakeBackend("icmplib", raises=BackendUnavailable("no permission")),
        FakeBackend("system-ping", raises=BackendUnavailable("ping not found")),
    )
    result = run(probe, real_device())
    assert not result.ok and "no permission" in result.error and "ping not found" in result.error


@pytest.mark.parametrize(
    "target",
    ["1.1.1.1; rm -rf /", "$(reboot)", "-f", "", "localhost", "255.255.255.255", "224.0.0.1", "0.0.0.0", "169.254.1.1", "256.1.1.1"],
)
def test_unsafe_or_invalid_targets_never_reach_a_backend(target):
    icmplib, system = FakeBackend("icmplib"), FakeBackend("system-ping")
    result = run(probe_with(icmplib, system), real_device(target))
    assert not result.ok and "invalid probe target" in result.error
    assert icmplib.calls == [] and system.calls == []


def test_missing_probe_target_is_an_error():
    result = run(probe_with(), make_device("laptop", mode="real", probe_target=None))
    assert not result.ok


@pytest.mark.parametrize("exc", [asyncio.TimeoutError(), ICMPLibError("boom"), OSError("network down")])
def test_backend_failures_are_isolated_into_error_results(exc):
    result = run(probe_with(icmplib=FakeBackend("icmplib", raises=exc)), real_device())
    assert not result.ok and result.loss_pct is None


def test_unknown_backend_name_rejected():
    with pytest.raises(ValueError):
        RealIcmpProbe("telepathy")


def test_system_backend_reports_missing_ping_program(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BackendUnavailable, match="not found"):
        asyncio.run(SystemPingBackend().ping("127.0.0.1", SETTINGS))


# ---------- genuine ICMP against localhost (skipped where the OS forbids it) ----------
def test_real_icmplib_ping_to_localhost():
    try:
        sent, rtts = asyncio.run(IcmplibBackend().ping("127.0.0.1", SETTINGS))
    except BackendUnavailable as exc:
        pytest.skip(str(exc))
    assert sent == 3 and len(rtts) == 3 and all(0 < r < 50 for r in rtts)


@pytest.mark.skipif(shutil.which("ping") is None, reason="system ping not installed")
def test_real_system_ping_to_localhost():
    sent, rtts = asyncio.run(SystemPingBackend().ping("127.0.0.1", SETTINGS))
    assert sent == 3 and len(rtts) == 3 and all(0 < r < 50 for r in rtts)


def test_full_real_probe_of_localhost_end_to_end():
    result = run(RealIcmpProbe("auto"), real_device("127.0.0.1"))
    if not result.ok:
        pytest.skip(f"no ICMP backend usable here: {result.error}")
    assert result.source == "real" and result.received == 3 and result.loss_pct == 0.0
    assert result.rtt_avg_ms < 50


@pytest.mark.skipif(not os.getenv("TEST_UNREACHABLE_IP"), reason="set TEST_UNREACHABLE_IP to an address that never answers on your network")
def test_real_probe_of_silent_address_is_total_loss():
    result = run(RealIcmpProbe("auto"), real_device(os.environ["TEST_UNREACHABLE_IP"]))
    if not result.ok:
        pytest.skip(result.error)
    assert result.received == 0 and result.loss_pct == 100.0
