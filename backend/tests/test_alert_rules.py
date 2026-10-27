from datetime import datetime, timedelta, timezone

import pytest

from app.alerts import rules
from app.alerts.models import Alert
from app.monitoring.models import Thresholds
from app.network_model.models import Device, LatestMetrics, Link, LinkLatest
from tests.helpers import make_device

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
T = Thresholds()  # latency 100/250 ms, loss 5/20 %, utilization 80/90 %


def with_metrics(device: Device, *, avg=8.0, loss=0.0, sent=25, received=None, status="online", failures=0, parent=None) -> Device:
    received = sent - round(sent * loss / 100) if received is None else received
    latest = LatestMetrics(at=NOW, source="simulated", sent=5, received=5, loss_pct=0.0, rtt_avg_ms=avg, window_loss_pct=loss, window_rtt_avg_ms=avg,
                           window_sent=sent, window_received=received)
    return device.model_copy(update={"latest": latest, "status": status, "consecutive_failures": failures, "last_seen": NOW, "parent_id": parent or device.parent_id})


def conds(devices, links=(), open_severity=None, hysteresis=10.0):
    return rules.active_conditions(list(devices), list(links), T, hysteresis, open_severity or {}, "core")


def tree():
    core = make_device("core").model_copy(update={"parent_id": None, "type": "core_switch"})
    sw = make_device("sw", ip="192.168.10.2").model_copy(update={"parent_id": "core", "type": "switch"})
    pc = make_device("pc", ip="192.168.10.101").model_copy(update={"parent_id": "sw"})
    return core, sw, pc


# ---------- grade ----------
def test_grade_levels():
    assert rules.grade(50, 100, 250, None, 10) is None
    assert rules.grade(100, 100, 250, None, 10) == "warning"
    assert rules.grade(250, 100, 250, None, 10) == "critical"
    assert rules.grade(None, 100, 250, None, 10) is None


def test_hysteresis_keeps_an_open_alert_until_clearly_below_the_threshold():
    assert rules.grade(95, 100, 250, None, 10) is None  # would not open
    assert rules.grade(95, 100, 250, "warning", 10) == "warning"  # but an open alert holds (95 >= 90)
    assert rules.grade(89, 100, 250, "warning", 10) is None  # and clears below 90
    assert rules.grade(230, 100, 250, "critical", 10) == "critical"  # critical holds down to 225
    assert rules.grade(220, 100, 250, "critical", 10) == "warning"  # then de-escalates
    assert rules.grade(95, 100, 250, "warning", 0) is None  # no hysteresis: plain threshold


# ---------- offline ----------
def test_offline_device_gets_one_critical_alert_listing_what_it_cuts_off():
    core, sw, pc = tree()
    sw = with_metrics(sw, status="offline", failures=4)
    pc = with_metrics(pc, status="unreachable", failures=4).model_copy(update={"caused_by": "sw"})
    found = conds([core, sw, pc])
    assert set(found) == {"DEVICE_OFFLINE:sw"}  # the unreachable child has no alert of its own
    alert = found["DEVICE_OFFLINE:sw"]
    assert alert.severity == "critical" and alert.affected == ("pc",)
    assert "unreachable" in alert.message and "Packet loss: 100%" in alert.message and "1 downstream device" in alert.message


# ---------- latency / loss ----------
def test_latency_alert_severity_follows_thresholds():
    core, sw, pc = tree()
    assert set(conds([core, with_metrics(sw, avg=120)])) == {"HIGH_LATENCY:sw"}
    assert conds([core, with_metrics(sw, avg=120)])["HIGH_LATENCY:sw"].severity == "warning"
    assert conds([core, with_metrics(sw, avg=300)])["HIGH_LATENCY:sw"].severity == "critical"
    assert conds([core, with_metrics(sw, avg=40)]) == {}


def test_open_latency_alert_survives_a_dip_just_below_the_threshold():
    core, sw, _ = tree()
    dipped = with_metrics(sw, avg=95)
    assert conds([core, dipped]) == {}
    assert "HIGH_LATENCY:sw" in conds([core, dipped], open_severity={"HIGH_LATENCY:sw": "warning"})


def test_packet_loss_needs_real_evidence_not_one_or_two_lost_echoes():
    core, sw, _ = tree()
    assert conds([core, with_metrics(sw, loss=8, sent=25, received=23)]) == {}  # 8 % but only 2 echoes lost: noise
    found = conds([core, with_metrics(sw, loss=12, sent=25, received=22)])  # 3 lost: evidence
    assert found["HIGH_PACKET_LOSS:sw"].severity == "warning"
    assert conds([core, with_metrics(sw, loss=40, sent=25, received=15)])["HIGH_PACKET_LOSS:sw"].severity == "critical"


def test_a_device_that_just_stopped_answering_gets_no_loss_alert():
    core, sw, _ = tree()
    assert conds([core, with_metrics(sw, loss=40, sent=25, received=15, failures=1)]) == {}  # outage beginning, wait for the state machine


def test_slow_switch_explains_slow_children():
    core, sw, pc = tree()
    slow_switch, slow_pc = with_metrics(sw, avg=300), with_metrics(pc, avg=310)
    found = conds([core, slow_switch, slow_pc])
    assert set(found) == {"HIGH_LATENCY:sw"}  # the child's alert is suppressed: the switch is the root cause


def test_slow_child_with_a_healthy_switch_keeps_its_alert():
    core, sw, pc = tree()
    assert set(conds([core, with_metrics(sw, avg=8), with_metrics(pc, avg=300)])) == {"HIGH_LATENCY:pc"}


def test_degraded_upstream_suppresses_downstream_alerts_even_for_other_metrics():
    core, sw, pc = tree()
    degraded_sw = with_metrics(sw, avg=8, status="degraded")
    assert conds([core, degraded_sw, with_metrics(pc, loss=40, sent=25, received=15)]) == {}


# ---------- utilization ----------
def link(a="core", b="sw", util=95.0, capacity=100.0):
    latest = LinkLatest(ts=NOW, source="simulated", rx_mbps=util, tx_mbps=10.0, rx_pps=1, tx_pps=1, util_pct=util)
    return Link(id=f"{a}--{b}", a_id=a, b_id=b, kind="uplink", capacity_mbps=capacity, latest=latest)


def test_utilization_alert_names_the_block_and_the_numbers():
    core, sw, _ = tree()
    sw = sw.model_copy(update={"block": "cse"})
    found = conds([core, with_metrics(sw)], [link(util=92)])
    alert = found["HIGH_UTILIZATION:core--sw"]
    assert alert.severity == "critical" and "CSE Block network" in alert.message and "92%" in alert.message
    assert alert.link_id == "core--sw" and alert.device_id == "sw"
    assert conds([core, with_metrics(sw)], [link(util=85)])["HIGH_UTILIZATION:core--sw"].severity == "warning"
    assert conds([core, with_metrics(sw)], [link(util=50)]) == {}


def test_no_utilization_alert_while_an_end_of_the_link_is_down():
    core, sw, _ = tree()
    assert conds([core, with_metrics(sw, status="offline", failures=5)], [link(util=99)]).keys() == {"DEVICE_OFFLINE:sw"}


# ---------- plan ----------
def alert_from(cond, **kw):
    return Alert(type=cond.type, severity=cond.severity, dedupe_key=cond.key, device_id=cond.device_id, title=cond.title, message=cond.message,
                 metrics=rules.with_peak(cond.metrics, None, cond.type), opened_at=NOW - timedelta(minutes=5), **kw)


def test_plan_opens_new_alerts_once_and_deduplicates():
    core, sw, _ = tree()
    found = conds([core, with_metrics(sw, avg=300)])
    first = rules.plan([], found, NOW)
    assert len(first.opened) == 1 and first.updated == [] and first.resolved == []
    again = rules.plan(first.opened, found, NOW + timedelta(seconds=5))
    assert again.opened == [] and len(again.updated) == 1 and again.resolved == []  # same key: updated, never duplicated


def test_plan_resolves_alerts_whose_condition_cleared():
    core, sw, _ = tree()
    open_alert = alert_from(conds([core, with_metrics(sw, avg=300)])["HIGH_LATENCY:sw"])
    actions = rules.plan([open_alert], conds([core, with_metrics(sw, avg=8)]), NOW, clear_cycles=1)
    assert actions.resolved == [open_alert.id] and actions.opened == []


def test_clear_delay_keeps_a_flickering_alert_open_until_it_stays_gone():
    core, sw, _ = tree()
    alert = alert_from(conds([core, with_metrics(sw, avg=300)])["HIGH_LATENCY:sw"])
    healthy = conds([core, with_metrics(sw, avg=8)])
    first = rules.plan([alert], healthy, NOW, clear_cycles=3)
    assert first.resolved == [] and first.updated[0][1]["quiet_cycles"] == 1
    second = rules.plan([alert.model_copy(update={"quiet_cycles": 1})], healthy, NOW, clear_cycles=3)
    assert second.resolved == [] and second.updated[0][1]["quiet_cycles"] == 2
    third = rules.plan([alert.model_copy(update={"quiet_cycles": 2})], healthy, NOW, clear_cycles=3)
    assert third.resolved == [alert.id]
    # the condition coming back resets the countdown and does not open a second alert
    back = rules.plan([alert.model_copy(update={"quiet_cycles": 2})], conds([core, with_metrics(sw, avg=300)]), NOW, clear_cycles=3)
    assert back.opened == [] and back.resolved == [] and back.updated[0][1]["quiet_cycles"] == 0


def test_offline_alerts_resolve_immediately_without_a_clear_delay():
    core, sw, _ = tree()
    alert = alert_from(conds([core, with_metrics(sw, status="offline", failures=4)])["DEVICE_OFFLINE:sw"])
    assert rules.plan([alert], {}, NOW, clear_cycles=3).resolved == [alert.id]


def test_plan_tracks_the_peak_value():
    core, sw, _ = tree()
    peak = alert_from(conds([core, with_metrics(sw, avg=400)])["HIGH_LATENCY:sw"])
    actions = rules.plan([peak], conds([core, with_metrics(sw, avg=120)], open_severity={peak.dedupe_key: "critical"}), NOW)
    _, fields = actions.updated[0]
    assert fields["metrics"]["peak"] == pytest.approx(400) and fields["metrics"]["avg_latency_ms"] == pytest.approx(120)
