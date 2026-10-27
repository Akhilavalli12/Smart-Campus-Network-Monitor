import pytest

from app.traffic.counters import CounterReading, compute_rate, counter_delta

MB = 1_000_000


def reading(rx=0, tx=0, rxp=0, txp=0, bits=64):
    return CounterReading(rx_bytes=rx, tx_bytes=tx, rx_packets=rxp, tx_packets=txp, bits=bits)


def test_delta_without_wrap():
    assert counter_delta(1000, 4000, 32) == (3000, False)
    assert counter_delta(5, 5, 32) == (0, False)


def test_delta_across_a_32_bit_wrap():
    top = 2**32
    assert counter_delta(top - 100, 50, 32) == (150, True)  # 100 bytes to the limit + 50 after
    assert counter_delta(top - 1, 0, 32) == (1, True)


def test_rate_formula_matches_the_worked_example():
    # 6,250,000 bytes in 5 s  ->  6,250,000 x 8 / 5 = 10,000,000 bit/s = 10 Mbit/s;  on a 100 Mbit/s link = 10 %
    sample = compute_rate(reading(), reading(rx=6_250_000, tx=1_250_000, rxp=5000, txp=1000), 5.0, 100)
    assert sample.rx_mbps == pytest.approx(10.0)
    assert sample.tx_mbps == pytest.approx(2.0)
    assert sample.rx_pps == pytest.approx(1000.0) and sample.tx_pps == pytest.approx(200.0)
    assert sample.util_pct == pytest.approx(10.0)
    assert sample.wrapped is False


def test_utilization_uses_the_busier_direction():
    sample = compute_rate(reading(), reading(rx=1_250_000, tx=6_250_000), 1.0, 100)  # rx 10, tx 50 Mbit/s
    assert sample.util_pct == pytest.approx(50.0)  # full duplex: capacity applies to each direction separately


def test_rate_is_correct_across_a_counter_wrap():
    top = 2**32
    before = reading(rx=top - 3_000_000, bits=32)
    after = reading(rx=3_250_000, bits=32)  # 6.25 MB really moved
    sample = compute_rate(before, after, 5.0, 100)
    assert sample.wrapped is True
    assert sample.rx_mbps == pytest.approx(10.0)  # not a huge negative or a huge positive number


def test_a_huge_apparent_wrap_is_a_counter_reset_and_is_discarded():
    # 32-bit counter drops from 4 GB to 100: wrapping would imply ~6.9 Gbit/s on a 100 Mbit/s link -> it was a reset
    assert compute_rate(reading(rx=4_000_000_000, bits=32), reading(rx=100, bits=32), 5.0, 100) is None


def test_a_decrease_of_a_64_bit_counter_is_always_a_reset():
    assert compute_rate(reading(rx=10 * MB), reading(rx=5 * MB), 5.0, None) is None
    assert compute_rate(reading(rx=10 * MB), reading(rx=5 * MB), 5.0, 1000) is None


def test_no_elapsed_time_gives_no_rate():
    assert compute_rate(reading(), reading(rx=100), 0.0, 100) is None
    assert compute_rate(reading(), reading(rx=100), -1.0, 100) is None


def test_mixed_counter_widths_give_no_rate():
    assert compute_rate(reading(bits=32), reading(bits=64), 5.0, 100) is None


def test_unknown_capacity_means_no_utilization_but_rates_still_work():
    sample = compute_rate(reading(), reading(rx=6_250_000), 5.0, None)
    assert sample.rx_mbps == pytest.approx(10.0) and sample.util_pct is None


def test_idle_link():
    sample = compute_rate(reading(rx=500, tx=500), reading(rx=500, tx=500), 5.0, 100)
    assert (sample.rx_mbps, sample.tx_mbps, sample.util_pct) == (0.0, 0.0, 0.0)


def test_rate_above_capacity_without_a_wrap_is_kept_not_hidden():
    sample = compute_rate(reading(), reading(rx=75_000_000), 5.0, 100)  # 120 Mbit/s measured on a 100 Mbit/s link
    assert sample.util_pct == pytest.approx(120.0)  # honest raw value; the dashboard decides how to show it
