"""Leader formation behavior using target-point control frames."""

import asyncio
import math
import random

from utils import calculate_new_coordinates, calculate_positions_distance

from constants import CHECK_INT, CRUISE_SPEED, LEG_DIST, REACH_R, TRAIL_DIST


async def leader_patrol_task(lead, bridge, form_ref):
    """领机按航段巡航，同时持续广播位置、航向、速度和编队参数。"""
    state = await lead.get_state(require_heading=True)
    cur_lat, cur_lon = state.lat, state.lon
    goto_alt = state.alt
    heading = float(state.heading)

    while True:
        # 沿当前航向生成下一段巡航目标点。
        rad = math.radians(heading)
        tgt_lat, tgt_lon = calculate_new_coordinates(
            cur_lat,
            cur_lon,
            LEG_DIST * math.cos(rad),
            LEG_DIST * math.sin(rad),
        )
        await lead.goto_location(tgt_lat, tgt_lon, goto_alt, CRUISE_SPEED)

        while True:
            state = await lead.get_state()

            # 广播给从机；GUI 的基础遥测由 telemetry.py 统一推送。
            bridge.send_to_peers(
                {
                    "type": "lead_broadcast",
                    "lat": state.lat,
                    "lon": state.lon,
                    "alt": state.alt,
                    "heading": round(state.heading),
                    "speed": state.speed,
                    "form_type": int(form_ref.get("type", 1)),
                    "spacing": float(form_ref.get("spacing", TRAIL_DIST)),
                    "group": form_ref.get("group", "all"),
                    "leader_id": form_ref.get("leader_id"),
                    "targets": list(form_ref.get("targets", [])),
                }
            )

            if calculate_positions_distance(
                state.lat,
                state.lon,
                tgt_lat,
                tgt_lon,
            ) <= REACH_R * 2:
                break

            # 未到达目标判定点时，重复下发当前目标点，避免飞控丢失上一帧后停止追踪。
            await lead.goto_location(tgt_lat, tgt_lon, goto_alt, CRUISE_SPEED)
            await asyncio.sleep(CHECK_INT)

        # 到达当前航段后随机偏转，继续保持巡航。
        cur_lat, cur_lon = tgt_lat, tgt_lon
        heading = (heading + random.uniform(-90.0, 90.0)) % 360.0
