"""Telemetry streaming helpers."""

import asyncio

from constants import CHECK_INT


async def push_basic_telemetry(drone, bridge, tag, idx):
    """Single GUI telemetry producer: fresh flight state plus latest sent target."""
    last_sent_received_at = None
    reader_error_reported = False
    loop = asyncio.get_running_loop()
    while True:
        cycle_started = loop.time()
        fields = {"id": idx, "tag": tag}
        try:
            state = await drone.get_state(timeout=CHECK_INT)
            reader_error_reported = False
        except TimeoutError:
            state = None
        except RuntimeError as exc:
            state = None
            if not reader_error_reported:
                bridge.send_log(f"[{tag}] 飞控状态读取异常，继续回传心跳和最近目标点：{exc}")
                reader_error_reported = True

        if state is not None and state.received_at != last_sent_received_at:
            last_sent_received_at = state.received_at
            fields.update(
                lat=state.lat,
                lon=state.lon,
                alt=state.alt,
                speed=state.speed,
                heading=round(state.heading),
                phase=state.phase,
            )

        # get_state may wait while a behavior sends a new goto. Sample afterwards,
        # including on timeout/error or unchanged flight state, so it is not lost.
        fields.update(_last_target_fields(drone))
        bridge.send_telemetry(**fields)
        await asyncio.sleep(max(0.0, CHECK_INT - (loop.time() - cycle_started)))


def _last_target_fields(drone):
    getter = getattr(drone, "get_last_target", None)
    if not callable(getter):
        return {}

    target = getter()
    if target is None:
        return {}

    try:
        return {
            "goto_lat": float(target.lat),
            "goto_lon": float(target.lon),
            "goto_alt": float(target.alt),
            "goto_speed": float(target.speed),
        }
    except (AttributeError, TypeError, ValueError):
        return {}
