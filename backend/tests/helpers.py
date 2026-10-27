from app.network_model.models import Device, SimState


def make_device(
    id="dev",
    *,
    mode="simulated",
    base_rtt=8.0,
    fault="none",
    params=None,
    probe_target=None,
    ip="192.168.10.50",
) -> Device:
    return Device(
        id=id,
        name=id,
        type="pc",
        ip=ip,
        block="cse",
        monitoring_mode=mode,
        probe_target=probe_target,
        base_rtt_ms=base_rtt if mode == "simulated" else None,
        sim_state=SimState(fault=fault, params=params or {}),
    )
