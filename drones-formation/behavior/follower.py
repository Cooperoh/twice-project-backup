"""Follower formation behavior using target-point control frames."""

import asyncio
import math

from utils import (
    calculate_new_coordinates,
    calculate_positions_distance,
    calculate_relative_distance,
    get_offset,
    normalize_targets,
    safe_float,
)

from constants import (
    CHECK_INT,
    FOLLOW_ERR_DEADBAND,
    FOLLOW_SPEED_BASE,
    FOLLOW_SPEED_GAIN,
    FOLLOW_SPEED_MAX,
    FOLLOW_SPEED_MIN,
    LOOKAHEAD_MAX,
    LOOKAHEAD_MIN,
    LOOKAHEAD_SPACING_GAIN,
    LOOKAHEAD_SPEED_TIME,
    TRAIL_DIST,
)


async def follower_task(
    fol,
    bridge,
    slot_index,
    drone_id,
    form_ref,
):
    """跟随领机编队点，并通过空速参数修正前后误差。"""
    last_lead = None
    current_slot = max(1, int(slot_index))

    async def _rx_loop():
        """接收领机广播，并根据 targets 顺序更新本机槽位。"""
        nonlocal last_lead, current_slot
        while True:
            peer_states = await bridge.next_peer()
            my_leader_id = form_ref.get("leader_id")
            if my_leader_id is None:
                continue
            msg = peer_states.get(my_leader_id)
            if not isinstance(msg, dict):
                continue

            targets = normalize_targets(msg.get("targets"))
            if targets and drone_id not in targets:
                continue

            followers = [tid for tid in targets if tid != my_leader_id] if targets else []
            if followers and drone_id in followers:
                current_slot = followers.index(drone_id) + 1

            last_lead = msg

    state = await fol.get_state()
    goto_alt = state.alt
    rx_task = asyncio.create_task(_rx_loop())
    try:
        while True:
            if not last_lead:
                await asyncio.sleep(0.05)
                continue

            # 当前没有检查领机广播的新鲜度；真实飞行中需要加 timestamp/seq 和超时保护，
            # 避免领机失联后从机继续追踪过期的 last_lead 目标。
            form_type = int(last_lead.get("form_type", form_ref.get("type", 1)))
            spacing = float(last_lead.get("spacing", form_ref.get("spacing", TRAIL_DIST)))
            heading = float(last_lead.get("heading", 0.0))
            lead_lat = float(last_lead.get("lat"))
            lead_lon = float(last_lead.get("lon"))
            lead_alt = safe_float(last_lead.get("alt"), goto_alt)
            lead_speed = safe_float(last_lead.get("speed"), FOLLOW_SPEED_BASE)
            lead_speed = max(FOLLOW_SPEED_MIN, min(FOLLOW_SPEED_MAX, lead_speed))

            # 先在领机机体系下计算槽位偏移，再旋转到东北坐标系。
            heading_rad = math.radians(heading)
            offset_north, offset_east = get_offset(current_slot, form_type, spacing)
            tgt_north = offset_north * math.cos(heading_rad) - offset_east * math.sin(heading_rad)
            tgt_east = offset_north * math.sin(heading_rad) + offset_east * math.cos(heading_rad)
            tgt_lat, tgt_lon = calculate_new_coordinates(lead_lat, lead_lon, tgt_north, tgt_east)

            state = await fol.get_state()
            cur_lat, cur_lon = state.lat, state.lon
            # 固定翼不能直接追到队形点，使用前视点保证目标在机体前方。
            delta = spacing * LOOKAHEAD_SPACING_GAIN + lead_speed * LOOKAHEAD_SPEED_TIME
            delta = max(LOOKAHEAD_MIN, min(LOOKAHEAD_MAX, delta))
            fwd_north = tgt_north + delta * math.cos(heading_rad)
            fwd_east = tgt_east + delta * math.sin(heading_rad)
            fwd_lat, fwd_lon = calculate_new_coordinates(lead_lat, lead_lon, fwd_north, fwd_east)

            cur_fwd_dist = calculate_positions_distance(cur_lat, cur_lon, fwd_lat, fwd_lon)
            if cur_fwd_dist < delta * 0.6:
                delta = min(LOOKAHEAD_MAX, delta + max(2.0, spacing * 0.5))
                fwd_north = tgt_north + delta * math.cos(heading_rad)
                fwd_east = tgt_east + delta * math.sin(heading_rad)
                fwd_lat, fwd_lon = calculate_new_coordinates(lead_lat, lead_lon, fwd_north, fwd_east)

            goto_alt = lead_alt

            # 根据沿航向前后误差调节巡航速度：落后则加速，超前则减速。
            err_north, err_east = calculate_relative_distance(cur_lat, cur_lon, tgt_lat, tgt_lon)
            fwd_err = err_north * math.cos(heading_rad) + err_east * math.sin(heading_rad)
            if abs(fwd_err) < FOLLOW_ERR_DEADBAND:
                tgt_spd = lead_speed
            else:
                tgt_spd = lead_speed - FOLLOW_SPEED_GAIN * fwd_err
            tgt_spd = max(FOLLOW_SPEED_MIN, min(FOLLOW_SPEED_MAX, tgt_spd))

            await fol.goto_location(fwd_lat, fwd_lon, goto_alt, tgt_spd)

            await asyncio.sleep(CHECK_INT)
    finally:
        rx_task.cancel()
        try:
            await rx_task
        except (asyncio.CancelledError, Exception):
            pass
