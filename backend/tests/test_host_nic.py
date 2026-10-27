import socket
from collections import namedtuple

import pytest

from app.traffic.host import HostNicError, HostNicSource

IO = namedtuple("IO", "bytes_sent bytes_recv packets_sent packets_recv")
STATS = namedtuple("STATS", "isup speed")
ADDR = namedtuple("ADDR", "family address")


class FakePsutil:
    def __init__(self, io, stats, addrs):
        self._io, self._stats, self._addrs = io, stats, addrs
        self.nowrap_requested = None

    def net_io_counters(self, pernic=False, nowrap=True):
        assert pernic is True
        self.nowrap_requested = nowrap
        return self._io

    def net_if_stats(self):
        return self._stats

    def net_if_addrs(self):
        return self._addrs


def fake():
    return FakePsutil(
        io={"lo": IO(1, 1, 1, 1), "eth0": IO(1000, 5000, 10, 50), "wlan0": IO(200, 300, 2, 3), "docker0": IO(9, 9, 9, 9)},
        stats={"lo": STATS(True, 0), "eth0": STATS(True, 1000), "wlan0": STATS(True, 0), "docker0": STATS(False, 0)},
        addrs={"lo": [ADDR(socket.AF_INET, "127.0.0.1")], "eth0": [ADDR(socket.AF_INET, "192.168.1.5")], "wlan0": [ADDR(socket.AF_INET, "10.0.0.7")], "docker0": []},
    )


def test_default_sums_up_non_loopback_interfaces_and_ignores_down_ones():
    ps = fake()
    reading = HostNicSource("", ps).read()
    assert reading.interfaces == ("eth0", "wlan0")
    c = reading.counters
    assert (c.rx_bytes, c.tx_bytes, c.rx_packets, c.tx_packets) == (5300, 1200, 53, 12)  # rx = bytes_recv, tx = bytes_sent
    assert c.bits == 64 and reading.speed_mbps is None  # several interfaces: no single speed
    assert ps.nowrap_requested is True  # psutil corrects wrapped OS counters for us


def test_a_chosen_interface_reports_its_own_speed():
    reading = HostNicSource("eth0", fake()).read()
    assert reading.label == "eth0" and reading.speed_mbps == 1000.0 and reading.counters.rx_bytes == 5000


def test_unknown_speed_is_none_not_zero():
    assert HostNicSource("wlan0", fake()).read().speed_mbps is None


def test_unknown_interface_is_a_clear_error():
    with pytest.raises(HostNicError, match="not found.*eth0"):
        HostNicSource("nope0", fake()).read()


def test_no_usable_interface_returns_none():
    ps = FakePsutil({"lo": IO(1, 1, 1, 1)}, {"lo": STATS(True, 0)}, {"lo": [ADDR(socket.AF_INET, "127.0.0.1")]})
    assert HostNicSource("", ps).read() is None


def test_loopback_is_detected_by_address_even_with_an_unusual_name():
    ps = FakePsutil({"weird0": IO(1, 1, 1, 1)}, {"weird0": STATS(True, 0)}, {"weird0": [ADDR(socket.AF_INET, "127.0.0.1")]})
    assert HostNicSource("", ps).read() is None


def test_real_psutil_returns_a_reading_or_none_without_crashing():
    reading = HostNicSource("").read()
    assert reading is None or (reading.counters.rx_bytes >= 0 and reading.counters.bits == 64)
