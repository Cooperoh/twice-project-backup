#!/usr/bin/env python3

import asyncio

from behavior.telemetry import push_basic_telemetry
from bridge import FGCBridge
from client.autopilot import FlightController
from cmd_process import VALID_FORM_TYPES, cmd_listener
from config import UAV_CFGS, drone_broadcast
from constants import TRAIL_DIST
from utils import normalize_group

GUI_PORT = 56999
INITIAL_TELEMETRY_WAIT_SEC = 5.0

# Communication choices are intentionally kept in the runtime entrypoint.
#
# simulation: multi-aircraft messages use FGCBridge for direct IP/port UDP.
# flight: the data-link business frame, node addressing, and gimbal protocol
#         are not available yet, so field multi-aircraft and gimbal control are
#         not implemented in this runtime.
RUN_MODE = "simulation"
FC_TRANSPORT = "udp"  # "udp" for simulation, or "serial" for bench/flight use.


def _lookup_cfg(uav_id):
    for cfg in UAV_CFGS:
        try:
            cfg_id = int(cfg.get("id", -1))
        except (TypeError, ValueError):
            continue
        if cfg_id == uav_id:
            return cfg
    raise KeyError(f"no UAV config found for id {uav_id}")


def get_cfg(my_index):
    cfg = dict(_lookup_cfg(my_index))
    cfg.setdefault("id", my_index)
    cfg.setdefault("index", my_index)
    cfg["fc_transport"] = FC_TRANSPORT
    group_value = normalize_group(cfg.get("group", 0))
    if group_value is None:
        group_value = 0
    cfg["group"] = group_value
    bind_ip = "0.0.0.0"
    cmd_port = int(cfg.get("cmd_port", 0))
    gui_host = cfg.get("gui_host", "127.0.0.1")
    gui_port = int(cfg.get("gui_port", GUI_PORT))
    return cfg, bind_ip, cmd_port, gui_host, gui_port


def _create_bridge(*, bind_ip, bind_port, gui_host, gui_port, peers, name):
    """Create the currently supported direct-IP simulation bridge.

    When the field data-link frame is defined, RUN_MODE will be checked only
    here to select a DataLinkBridge with the same behavior-facing interface.
    """
    return FGCBridge(
        bind_ip=bind_ip,
        bind_port=bind_port,
        gui_host=gui_host,
        gui_port=gui_port,
        peers=peers,
        name=name,
    )


async def connect_uav(cfg):
    drone = FlightController(cfg)
    await drone.start()
    print(f"flight controller ready: {drone.describe()}")
    return drone


async def _wait_for_initial_telemetry(drone, bridge_name, *, waiting_print=None):
    if waiting_print is None:
        waiting_print = print
    while True:
        try:
            state = await drone.get_state(timeout=INITIAL_TELEMETRY_WAIT_SEC)
        except TimeoutError:
            waiting_print(f"[{bridge_name}] waiting for flight-controller telemetry...")
            continue

        print(
            f"[{bridge_name}] initial telemetry received: "
            f"seq={state.seq} lat={state.lat} lon={state.lon} alt={state.alt}"
        )
        return state


async def _monitor_initial_telemetry(drone, bridge_name, *, waiting_print=None):
    try:
        await _wait_for_initial_telemetry(
            drone,
            bridge_name,
            waiting_print=waiting_print,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[{bridge_name}] flight-controller telemetry monitor stopped: {exc}")


async def _forward_basic_telemetry(drone, bridge, tag, idx, bridge_name):
    try:
        await push_basic_telemetry(drone, bridge, tag=tag, idx=idx)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[{bridge_name}] basic telemetry forwarding stopped: {exc}")


async def _cancel_tasks(tasks):
    tracked = [task for task in tasks if task is not None]
    if not tracked:
        return
    active = [task for task in tracked if not task.done()]
    for task in active:
        task.cancel()
    await asyncio.gather(*tracked, return_exceptions=True)


def _resolve_form_ref(cfg):
    raw_type = cfg.get("formation_types", cfg.get("form_type", 1))
    try:
        form_type = int(raw_type)
    except (TypeError, ValueError):
        form_type = 1
    if form_type not in VALID_FORM_TYPES:
        form_type = 1

    raw_spacing = cfg.get("formation_spacing", cfg.get("spacing", TRAIL_DIST))
    try:
        spacing = float(raw_spacing)
    except (TypeError, ValueError):
        spacing = TRAIL_DIST
    if spacing <= 0:
        spacing = TRAIL_DIST

    return {
        "type": form_type,
        "spacing": spacing,
    }


async def run_drone(uav_id):
    """Bootstrap a single drone instance with group-aware command handling."""
    try:
        cfg, bind_ip, cmd_port, gui_host, gui_port = get_cfg(uav_id)
    except KeyError as exc:
        raise RuntimeError(f"no UAV config found for id {uav_id}") from exc

    role = str(cfg.get("role", "")).strip().lower()
    is_leader = role == "leader" or bool(int(cfg.get("is_leader", 0)))
    drone_id = int(cfg.get("id", uav_id))
    bridge_name = cfg.get("tag", "LEAD" if is_leader else f"DRONE{drone_id}")

    drone = await connect_uav(cfg)
    bridge = None
    background_tasks = []
    behavior_tasks = []
    try:
        bridge = _create_bridge(
            bind_ip=bind_ip,
            bind_port=cmd_port,
            gui_host=gui_host,
            gui_port=gui_port,
            peers=drone_broadcast(drone_id),
            name=bridge_name,
        )

        await bridge.start()
        local_print = print
        bridge.patch_print()

        telemetry_tag = cfg.get("tag", bridge_name)

        background_tasks.append(
            asyncio.create_task(
                _monitor_initial_telemetry(
                    drone,
                    bridge_name,
                    waiting_print=local_print,
                )
            )
        )
        background_tasks.append(
            asyncio.create_task(
                _forward_basic_telemetry(
                    drone,
                    bridge,
                    tag=telemetry_tag,
                    idx=drone_id,
                    bridge_name=bridge_name,
                )
            )
        )

        listener = asyncio.create_task(
            cmd_listener(bridge, behavior_tasks, drone, _resolve_form_ref(cfg), cfg)
        )
        background_tasks.append(listener)

        print(f"[{bridge_name}] ready on {bind_ip}:{cmd_port}, GUI={gui_host}:{gui_port}")
        await listener
    finally:
        await _cancel_tasks(behavior_tasks)
        await _cancel_tasks(background_tasks)
        await drone.stop()
        if bridge is not None:
            bridge.close()
