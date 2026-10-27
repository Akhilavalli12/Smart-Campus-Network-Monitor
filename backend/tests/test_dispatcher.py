import asyncio

from app.config.settings import Settings
from app.probes.base import ProbeResult, ProbeSettings
from app.probes.dispatcher import ProbeDispatcher, build_probe_dispatcher, probe_settings_from
from tests.helpers import make_device


class Recorder:
    def __init__(self, label):
        self.label, self.seen = label, []

    async def probe(self, device, settings, *, upstream=()):
        self.seen.append((device.id, tuple(d.id for d in upstream)))
        return ProbeResult(device_id=device.id, source=self.label, target="t", sent=1, received=1, rtts_ms=(1.0,))


def test_dispatcher_routes_by_monitoring_mode_and_forwards_upstream():
    real, sim = Recorder("real"), Recorder("simulated")
    dispatcher = ProbeDispatcher(real, sim)
    settings = ProbeSettings()
    upstream = [make_device("sw")]
    r1 = asyncio.run(dispatcher.probe(make_device("laptop", mode="real", probe_target="1.1.1.1"), settings))
    r2 = asyncio.run(dispatcher.probe(make_device("pc"), settings, upstream=upstream))
    assert (r1.source, r2.source) == ("real", "simulated")
    assert real.seen == [("laptop", ())] and sim.seen == [("pc", ("sw",))]


def test_probe_settings_come_from_configuration(monkeypatch):
    monkeypatch.setenv("PROBE_COUNT", "7")
    monkeypatch.setenv("PROBE_TIMEOUT_S", "2.5")
    s = probe_settings_from(Settings(_env_file=None))
    assert (s.count, s.timeout_s, s.interval_s) == (7, 2.5, 0.2)


def test_real_dispatcher_serves_both_modes_end_to_end():
    dispatcher = build_probe_dispatcher(Settings(_env_file=None))
    sim = asyncio.run(dispatcher.probe(make_device("pc"), ProbeSettings(count=5)))
    assert sim.source == "simulated" and sim.sent == 5
