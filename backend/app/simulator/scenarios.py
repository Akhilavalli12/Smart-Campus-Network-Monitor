"""Named demo scenarios: ready-made sets of faults for the Simulation page."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    expect: str
    faults: tuple[tuple[str, str, dict], ...]  # (device id, fault, parameters)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("device-failure", "Single PC fails", "CSE PC 1 stops answering.",
             "After 3 failed cycles: CSE PC 1 turns OFFLINE and one critical alert opens.",
             (("cse-pc-1", "offline", {}),)),
    Scenario("switch-failure", "CSE switch fails (upstream failure)", "The CSE block switch goes down, cutting off everything behind it.",
             "CSE Switch turns OFFLINE; its 5 devices turn grey UNREACHABLE; ONE critical alert names the switch as the root cause.",
             (("cse-switch", "offline", {}),)),
    Scenario("core-failure", "Core L3 switch fails", "The core switch dies: every block loses its gateway.",
             "Core turns OFFLINE and 14 devices become UNREACHABLE; still only one critical alert.",
             (("core-switch", "offline", {}),)),
    Scenario("latency-spike", "Latency spike", "The Library access point answers slowly (about 220 ms).",
             "Library Access Point turns DEGRADED (amber) and a high-latency alert opens.",
             (("library-ap", "high_latency", {"rtt_ms": 220.0}),)),
    Scenario("packet-loss", "Packet loss", "35 % of the packets to CSE PC 2 are lost.",
             "CSE PC 2 turns DEGRADED and a high-packet-loss alert opens.",
             (("cse-pc-2", "packet_loss", {"loss_pct": 35.0}),)),
    Scenario("congestion", "Network congestion", "The Admin block uplink is driven to 96 % utilization.",
             "The Admin uplink turns red on the topology, a high-utilization alert opens, latency and loss rise.",
             (("admin-switch", "congestion", {"utilization_pct": 96.0}),)),
)


def get_scenario(scenario_id: str) -> Scenario | None:
    return next((s for s in SCENARIOS if s.id == scenario_id), None)
