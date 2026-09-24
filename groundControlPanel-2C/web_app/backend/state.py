"""
后端中央数据仓库，也是运行状态的权威来源。

角色：
    ``StateStore`` 保存地面站当前真正认可的最新状态；实际飞行轨迹和 Event Log
    历史只存在于当前浏览器标签页的固定容量结构中，不由本仓库持久保留。

主要职责：
    本文件保存最多 24 机的最新遥测、轨迹序号/清空 epoch、规划航线、编队成员与
    队长、编队参数、活跃编队、命令阻塞标志和 UDP 健康状态，并计算遥测与飞控连接状态。

输入和输出：
    输入主要来自 ``udp.py`` 收到的数据，以及 ``commands.py`` 或 API 发起的状态修改。
    输出包括供 HTTP 使用的当前状态 ``snapshot``，以及通过 ``events.py`` 发布给前端
    的有界实时批次；snapshot 不包含实际轨迹或日志历史。

模块关系和典型数据流：
    ``无人机 -> udp.py -> StateStore 保存 -> hub.publish() -> 浏览器更新``。
    浏览器读取状态时则是 ``API -> snapshot()/其他查询方法 -> JSON 响应``。

并发保护：
    UDP、API 和后台任务可能同时访问数据，因此本文件使用 ``asyncio.Lock`` 等锁，
    防止修改互相穿插而产生不一致；锁可以先理解成“同一时刻只让一个任务改仓库”。

阅读重点：
    先看 ``StateStore.__init__()`` 了解固定容量入口和最新状态，再看 ``snapshot()``
    了解刷新时返回什么；之后按照文件中的功能分区标题，分别阅读遥测、编队和 UDP。
"""

# pyright: reportArgumentType=false
# pyright: reportOperatorIssue=false

# single row ignore use: # pyright: ignore[reportArgumentType]

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import math
import threading
import time
from typing import Any

from .config import AppSettings
from .events import WebSocketHub, utc_now_text


Point = tuple[float, float]
TrackUpdate = dict[str, Any]
NewDroneHandler = Callable[[int, int, bool, int | None], Awaitable[None]]

# Partial heartbeat packets must not erase the last flight-controller sample.
# Core fields are retained explicitly; a small bounded extension area keeps the
# protocol forward-compatible without allowing changing field names to grow a
# per-drone state dictionary forever.
TELEMETRY_CORE_FIELDS = frozenset(
    {
        "id",
        "tag",
        "lat",
        "lon",
        "alt",
        "speed",
        "heading",
        "heading_valid",
        "phase",
        "err_s",
        "err_d",
        "goto_lat",
        "goto_lon",
        "goto_alt",
        "goto_speed",
        "last_telemetry_at",
        "last_flight_control_at",
    }
)
MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE = 16


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    message: Mapping[str, Any]
    received_mono: float
    received_wall: str


class RevisionConflict(RuntimeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"编队版本冲突：提交版本 {expected}，当前版本 {actual}。")
        self.expected = expected
        self.actual = actual


def normalize_drone_id(value: Any) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def finite_json_value(value: Any) -> bool:
    """Reject non-finite numbers without imposing a telemetry field whitelist."""

    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(finite_json_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite_json_value(item) for item in value)
    return True


def valid_position(lat_value: Any, lon_value: Any) -> bool:
    """Return whether a telemetry pair is usable as a geographic position.

    The flight-controller simulator emits an initial ``0, 0`` frame before its
    navigation solution is ready.  Treating that placeholder as a real fix
    creates a track from the Gulf of Guinea to the first valid sample and can
    move every map layer far outside the configured home view.
    """

    if not finite_number(lat_value) or not finite_number(lon_value):
        return False
    lat = float(lat_value)
    lon = float(lon_value)
    return (
        -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
        and not (lat == 0.0 and lon == 0.0)
    )


def telemetry_status(last_seen: float | None, now: float, settings: AppSettings) -> str:
    if not finite_number(last_seen):
        return "disconnected"
    elapsed = max(0.0, now - float(last_seen)) 
    if elapsed <= settings.telemetry.normal_seconds:
        return "normal"
    if elapsed <= settings.telemetry.weak_seconds:
        return "weak"
    if elapsed <= settings.telemetry.disconnected_seconds:
        return "poor"
    return "disconnected"


def flight_control_status(
    last_seen: float | None,
    now: float,
    settings: AppSettings,
) -> str:
    if not finite_number(last_seen):
        return "dead"
    elapsed = max(0.0, now - float(last_seen)) 
    if elapsed <= settings.telemetry.normal_seconds:
        return "normal"
    if elapsed <= settings.telemetry.weak_seconds:
        return "fault"
    return "dead"


class StateStore:
    """Single source of truth shared by UDP, REST and WebSocket adapters."""

    def __init__(self, settings: AppSettings, hub: WebSocketHub) -> None:
        self.settings = settings
        self.hub = hub
        self._lock = asyncio.Lock()
        self._formation_transaction_lock = asyncio.Lock()
        # Orders snapshots against incremental WebSocket publication.
        self._snapshot_event_lock = asyncio.Lock()
        # Orders batched track publication against clear_tracks().
        self._track_event_lock = asyncio.Lock()
        self._drones: dict[int, dict[str, Any]] = {}
        self._track_sequences: dict[int, int] = {}
        self._track_epoch = 0
        self._trajectories: dict[int, list[Point]] = {}
        # The UDP receiver thread writes these bounded ingress structures.
        # Telemetry is latest-only by ID; UI log history lives only in browsers.
        self._ingress_lock = threading.Lock()
        self._latest_telemetry: dict[int, ReceivedMessage] = {}
        self._pending_logs: deque[ReceivedMessage] = deque(
            maxlen=settings.limits.log_entries
        )
        self._telemetry_replaced_total = 0
        self._log_dropped_total = 0
        self._ingress_high_watermark = 0
        self._receive_last_batch_size = 0
        self._receive_last_batch_duration_ms = 0.0

        self._members: dict[int, list[int]] = {group_id: [] for group_id in range(4)}
        self._leaders: dict[int, int | None] = {group_id: None for group_id in range(4)}
        self._formation_revision = 0
        self._form_type = settings.formation.default_type
        self._spacing = settings.formation.default_spacing
        self._active_formations: set[int] = set()
        self._command_blocked = False

        self._udp_health: dict[str, Any] = {
            "receiver_ready": False,
            "sender_ready": False,
            "audit_ready": False,
            "audit_last_error": None,
            "last_error": None,
            "bind_host": settings.udp.bind_host,
            "bind_port": settings.udp.bind_port,
        }
        self._new_drone_handler: NewDroneHandler | None = None
        self._discovery_tasks: set[asyncio.Task[None]] = set()
        self._receive_task: asyncio.Task[None] | None = None
        self._status_task: asyncio.Task[None] | None = None
        self._last_statuses: dict[int, tuple[str, str]] = {}
        self._stopping = False

    def set_new_drone_handler(self, handler: NewDroneHandler) -> None:
        self._new_drone_handler = handler

    @asynccontextmanager
    async def formation_transaction(self):
        """Block first-discovery revision changes during a formation publish."""

        async with self._formation_transaction_lock:
            yield

    @asynccontextmanager
    async def _formation_state_guard(self):
        # Always acquire in formation -> state order; CommandService uses the
        # same order while validating, broadcasting and committing a proposal.
        async with self._formation_transaction_lock:
            async with self._lock:
                yield

    async def start(self) -> None:
        self._stopping = False
        if self._receive_task is None or self._receive_task.done():
            self._receive_task = asyncio.create_task(
                self._receive_loop(),
                name="ground-control-receive-batch-loop",
            )
        if self._status_task is None or self._status_task.done():
            self._status_task = asyncio.create_task(
                self._status_loop(),
                name="ground-control-status-loop",
            )

    async def stop(self) -> None:
        self._stopping = True
        tasks = [self._receive_task, self._status_task, *self._discovery_tasks]
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        for task in tasks:
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._receive_task = None
        self._status_task = None
        self._discovery_tasks.clear()
        with self._ingress_lock:
            self._latest_telemetry.clear()
            self._pending_logs.clear()

    # --------------------------------------------------------------- incoming
    async def listed_drone_ids(self) -> set[int]:
        """Return the ground-station list, including disconnected aircraft."""

        async with self._lock:
            return set(self._drones)

    def enqueue_message(self, message: Any) -> bool:
        """Accept one packet into fixed-size thread-safe ingress state."""

        if not isinstance(message, Mapping):
            return False
        message_type = message.get("type")
        normalized = dict(message)
        if message_type == "telemetry":
            drone_id = normalize_drone_id(message.get("id"))
            if drone_id is None or drone_id > 24:
                return False
            normalized["id"] = drone_id
        elif message_type == "log":
            if not isinstance(message.get("text"), str) or not message["text"]:
                return False
        else:
            return False

        received = ReceivedMessage(
            message=normalized,
            received_mono=time.monotonic(),
            received_wall=utc_now_text(),
        )
        with self._ingress_lock:
            if message_type == "telemetry":
                drone_id = int(normalized["id"])
                if drone_id in self._latest_telemetry:
                    self._telemetry_replaced_total += 1
                self._latest_telemetry[drone_id] = received
            else:
                if len(self._pending_logs) == self._pending_logs.maxlen:
                    self._log_dropped_total += 1
                self._pending_logs.append(received)
            self._ingress_high_watermark = max(
                self._ingress_high_watermark,
                len(self._latest_telemetry) + len(self._pending_logs),
            )
        return True

    async def handle_message(self, message: Any) -> bool:
        """Compatibility helper for direct callers; UDP uses ``enqueue_message``."""

        recognized = self.enqueue_message(message)
        if recognized:
            previous_tasks = set(self._discovery_tasks)
            await self.process_receive_queue_once()
            created_tasks = self._discovery_tasks.difference(previous_tasks)
            if created_tasks:
                await asyncio.gather(*created_tasks)
        return recognized

    async def process_receive_queue_once(self) -> bool:
        """Atomically swap bounded ingress state and publish at most one live batch."""

        started = time.perf_counter()
        with self._ingress_lock:
            latest_telemetry = self._latest_telemetry
            pending_logs = list(self._pending_logs)
            self._latest_telemetry = {}
            self._pending_logs.clear()
        self._receive_last_batch_size = len(latest_telemetry) + len(pending_logs)
        try:
            if not latest_telemetry and not pending_logs:
                return False

            logs: list[dict[str, str]] = []
            for received in pending_logs:
                logs.append(
                    {
                        "timestamp": received.received_wall,
                        "text": str(received.message["text"])[:4096],
                    }
                )

            await self._apply_receive_batch(latest_telemetry, logs)
            return True
        finally:
            self._receive_last_batch_duration_ms = round(
                (time.perf_counter() - started) * 1000.0,
                3,
            )

    async def _apply_receive_batch(
        self,
        latest_telemetry: Mapping[int, ReceivedMessage],
        logs: list[dict[str, str]],
    ) -> None:
        discoveries: list[tuple[int, int, bool, int | None]] = []
        formation_payload: dict[str, Any] | None = None
        track_updates: dict[int, TrackUpdate] = {}

        async with self._snapshot_event_lock:
            async with self._track_event_lock:
                async with self._formation_state_guard():
                    for drone_id, received in latest_telemetry.items():
                        discovery = self._apply_telemetry_locked(
                            drone_id,
                            received,
                            track_updates,
                        )
                        if discovery is not None:
                            discoveries.append(discovery)
                            formation_payload = self._formations_snapshot_locked()

                    payload: dict[str, Any] = {
                        "drones": self._telemetry_payload_locked(
                            time.monotonic(),
                            set(latest_telemetry),
                        )["drones"],
                        "track_updates": {
                            str(drone_id): update
                            for drone_id, update in sorted(track_updates.items())
                        },
                        "logs": logs,
                    }
                    if formation_payload is not None:
                        payload["formations"] = formation_payload

                await self.hub.publish("realtime_batch", payload)

        if self._new_drone_handler is None:
            return
        for discovery in discoveries:
            task = asyncio.create_task(
                self._notify_new_drone(discovery),
                name=f"ground-control-discovery-{discovery[0]}",
            )
            self._discovery_tasks.add(task)
            task.add_done_callback(self._discovery_tasks.discard)

    async def _notify_new_drone(
        self,
        discovery: tuple[int, int, bool, int | None],
    ) -> None:
        if self._new_drone_handler is None:
            return
        drone_id, group_id, is_new_leader, displaced_leader_id = discovery
        try:
            await self._new_drone_handler(
                drone_id,
                group_id,
                is_new_leader,
                displaced_leader_id,
            )
        except Exception as exc:  # UDP failures must never kill ingestion.
            await self.append_log(
                f"[编队] 无人机 #{drone_id} 配置定向发送失败：{exc}"
            )

    def _apply_telemetry_locked(
        self,
        drone_id: int,
        received: ReceivedMessage,
        track_updates: dict[int, TrackUpdate],
    ) -> tuple[int, int, bool, int | None] | None:
        message = received.message
        received_at = received.received_mono
        received_wall = received.received_wall
        lat_value = message.get("lat")
        lon_value = message.get("lon")
        has_flight_data = valid_position(lat_value, lon_value)
        is_new_drone = False
        is_new_leader = False
        displaced_leader_id: int | None = None

        previous = self._drones.get(drone_id)
        if previous is None:
            previous_leader = self._leaders[0]
            is_new_drone = True
            self._members[0] = sorted(set(self._members[0] + [drone_id]))
            self._leaders[0] = min(self._members[0])
            is_new_leader = self._leaders[0] == drone_id
            if is_new_leader and previous_leader is not None:
                displaced_leader_id = previous_leader
            self._formation_revision += 1

        # Telemetry is a partial-update protocol: drone-side empty heartbeat
        # packets normally contain only id/tag (and sometimes Goto fields).
        # Keep the last known values, then apply fields present in this packet.
        # A bounded dynamic-field tail below prevents arbitrary field-name growth.
        state: dict[str, Any] = dict(previous) if previous is not None else {}
        state["id"] = drone_id

        for key, value in message.items():
            if (
                key in {"type", "id", "lat", "lon", "goto_lat", "goto_lon"}
                or key.startswith("_")
            ):
                continue
            if finite_json_value(value):
                if key not in TELEMETRY_CORE_FIELDS:
                    # Refresh insertion order so overflow removes the least
                    # recently received extension field.
                    state.pop(key, None)
                state[key] = value

        state["_last_telemetry_mono"] = received_at
        state["last_telemetry_at"] = received_wall

        if has_flight_data:
            lat = float(lat_value)
            lon = float(lon_value)
            state["lat"] = lat
            state["lon"] = lon
            state["_last_flight_control_mono"] = received_at
            state["last_flight_control_at"] = received_wall

            previous_lat = previous.get("lat") if previous is not None else None
            previous_lon = previous.get("lon") if previous is not None else None
            if (
                not finite_number(previous_lat)
                or not finite_number(previous_lon)
                or abs(float(previous_lat) - lat) > 1e-6
                or abs(float(previous_lon) - lon) > 1e-6
            ):
                point_count = self._track_sequences.get(drone_id, 0) + 1
                self._track_sequences[drone_id] = point_count
                track_updates[drone_id] = {
                    "epoch": self._track_epoch,
                    "seq": point_count,
                    "point": {"lat": lat, "lon": lon},
                }

        goto_lat_present = "goto_lat" in message
        goto_lon_present = "goto_lon" in message
        if goto_lat_present or goto_lon_present:
            try:
                goto_lat = float(message.get("goto_lat"))
                goto_lon = float(message.get("goto_lon"))
                if not math.isfinite(goto_lat) or not math.isfinite(goto_lon):
                    raise ValueError
            except (TypeError, ValueError):
                state.pop("goto_lat", None)
                state.pop("goto_lon", None)
            else:
                state["goto_lat"] = goto_lat
                state["goto_lon"] = goto_lon

        dynamic_fields = [
            key
            for key in state
            if not key.startswith("_") and key not in TELEMETRY_CORE_FIELDS
        ]
        for key in dynamic_fields[:-MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE]:
            state.pop(key, None)

        self._drones[drone_id] = state

        if is_new_drone:
            return drone_id, 0, is_new_leader, displaced_leader_id
        return None

    # --------------------------------------------------------------- snapshots
    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._snapshot_locked()

    async def subscribe_snapshot(
        self,
    ) -> tuple[asyncio.Queue[dict[str, Any]], int, dict[str, Any]]:
        """Create a WebSocket subscription and its initial consistent snapshot."""

        async with self._snapshot_event_lock:
            queue, baseline = await self.hub.subscribe()
            async with self._lock:
                snapshot = self._snapshot_locked()
        return queue, baseline, snapshot

    def _snapshot_locked(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "drones": self._drones_snapshot_locked(now),
            # Actual tracks and UI logs are browser-session state. Empty keys
            # keep older clients source-compatible without retaining history.
            "tracks": {},
            "track_meta": {},
            "trajectories": {
                str(drone_id): self._points_to_json(points)
                for drone_id, points in sorted(self._trajectories.items())
            },
            "logs": [],
            "formations": self._formations_snapshot_locked(),
            "formation_settings": {
                "form_type": self._form_type,
                "spacing": self._spacing,
            },
            "active_formations": sorted(self._active_formations),
            "command_blocked": self._command_blocked,
            "udp": dict(self._udp_health),
            "config": self.settings.public_config(),
        }

    def _drones_snapshot_locked(self, now: float) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for drone_id, state in sorted(self._drones.items()):
            item = {key: value for key, value in state.items() if not key.startswith("_")}
            telemetry_seen = state.get("_last_telemetry_mono")
            flight_seen = state.get("_last_flight_control_mono")
            item["telemetry_status"] = telemetry_status(
                telemetry_seen,
                now,
                self.settings,
            )
            item["flight_control_status"] = flight_control_status(
                flight_seen,
                now,
                self.settings,
            )
            item["telemetry_age_seconds"] = (
                round(max(0.0, now - telemetry_seen), 3)
                if finite_number(telemetry_seen)
                else None
            )
            item["flight_control_age_seconds"] = (
                round(max(0.0, now - flight_seen), 3)
                if finite_number(flight_seen)
                else None
            )
            result[str(drone_id)] = item
        return result

    def _formations_snapshot_locked(self) -> dict[str, Any]:
        return {
            "revision": self._formation_revision,
            "members": {
                str(group_id): list(self._members[group_id]) for group_id in range(4)
            },
            "leaders": {
                str(group_id): self._leaders[group_id] for group_id in range(4)
            },
        }

    async def telemetry_payload(
        self,
        drone_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            return self._telemetry_payload_locked(time.monotonic(), drone_ids)

    def _telemetry_payload_locked(
        self,
        now: float,
        drone_ids: set[int] | None,
    ) -> dict[str, Any]:
        all_drones = self._drones_snapshot_locked(now)
        if drone_ids is None:
            drones = all_drones
        else:
            drones = {
                str(drone_id): all_drones[str(drone_id)]
                for drone_id in sorted(drone_ids)
                if str(drone_id) in all_drones
            }
        return {"drones": drones}

    @staticmethod
    def _points_to_json(points: list[Point]) -> list[dict[str, float]]:
        return [{"lat": lat, "lon": lon} for lat, lon in points]

    # -------------------------------------------------------------- formations
    async def formation_settings(self) -> tuple[int, float]:
        async with self._lock:
            return self._form_type, self._spacing

    async def update_formation_settings(
        self,
        form_type: int,
        spacing: float,
    ) -> dict[str, Any]:
        payload = {"form_type": int(form_type), "spacing": float(spacing)}
        async with self._lock:
            self._form_type = payload["form_type"]
            self._spacing = payload["spacing"]
        await self.hub.publish("formation_settings", payload)
        return payload

    def _validate_formations_locked(
        self,
        revision: int,
        members: Mapping[int, list[int]],
        leaders: Mapping[int, int | None],
    ) -> tuple[dict[int, list[int]], dict[int, int | None]]:
        if revision != self._formation_revision:
            raise RevisionConflict(revision, self._formation_revision)

        normalized_members = {
            group_id: sorted(set(members[group_id])) for group_id in range(4)
        }
        seen: set[int] = set()
        normalized_leaders: dict[int, int | None] = {}
        for group_id in range(4):
            group_members = normalized_members[group_id]
            duplicates = seen.intersection(group_members)
            if duplicates:
                duplicate = min(duplicates)
                raise ValueError(f"无人机 #{duplicate} 不能同时属于多个编队。")
            seen.update(group_members)

            requested_leader = leaders[group_id]
            if requested_leader is not None and requested_leader not in group_members:
                raise ValueError(f"编队 {group_id} 的队长不属于该编队。")
            # The protocol uses targets[0] as leader; use the deterministic minimum ID.
            normalized_leaders[group_id] = min(group_members) if group_members else None
        return normalized_members, normalized_leaders

    async def validate_formations(
        self,
        revision: int,
        members: Mapping[int, list[int]],
        leaders: Mapping[int, int | None],
    ) -> tuple[dict[int, list[int]], dict[int, int | None]]:
        """Validate and normalize a proposal without changing authoritative state."""

        async with self._lock:
            normalized_members, normalized_leaders = self._validate_formations_locked(
                revision,
                members,
                leaders,
            )
            return (
                {group_id: list(values) for group_id, values in normalized_members.items()},
                dict(normalized_leaders),
            )

    async def update_formations(
        self,
        revision: int,
        members: Mapping[int, list[int]],
        leaders: Mapping[int, int | None],
    ) -> dict[str, Any]:
        active_payload: dict[str, Any] | None = None
        async with self._lock:
            normalized_members, normalized_leaders = self._validate_formations_locked(
                revision,
                members,
                leaders,
            )

            self._members = normalized_members
            self._leaders = normalized_leaders
            previous_active = set(self._active_formations)
            self._active_formations.intersection_update(
                group_id
                for group_id, group_members in normalized_members.items()
                if group_members
            )
            if self._active_formations != previous_active:
                active_payload = {
                    "command_blocked": self._command_blocked,
                    "active_formations": sorted(self._active_formations),
                }
            self._formation_revision += 1
            payload = self._formations_snapshot_locked()
        await self.hub.publish("formations", payload)
        if active_payload is not None:
            await self.hub.publish("emergency", active_payload)
        return payload

    async def formation_members(self, group_id: int) -> tuple[list[int], int | None]:
        async with self._lock:
            return list(self._members[group_id]), self._leaders[group_id]

    async def all_formations(self) -> tuple[dict[int, list[int]], dict[int, int | None]]:
        async with self._lock:
            return (
                {group_id: list(values) for group_id, values in self._members.items()},
                dict(self._leaders),
            )

    async def active_formations(self) -> set[int]:
        async with self._lock:
            return set(self._active_formations)

    async def mark_formation_active(self, group_id: int) -> None:
        async with self._lock:
            self._active_formations.add(group_id)
            payload = {
                "command_blocked": self._command_blocked,
                "active_formations": sorted(self._active_formations),
            }
        await self.hub.publish("emergency", payload)

    async def is_command_blocked(self) -> bool:
        async with self._lock:
            return self._command_blocked

    async def set_emergency(self, blocked: bool) -> dict[str, Any]:
        async with self._lock:
            self._command_blocked = blocked
            if blocked:
                self._active_formations.clear()
                for state in self._drones.values():
                    state.pop("goto_lat", None)
                    state.pop("goto_lon", None)
            payload = {
                "command_blocked": self._command_blocked,
                "active_formations": sorted(self._active_formations),
            }
        await self.hub.publish("emergency", payload)
        if blocked:
            await self.hub.publish("goto_targets_cleared", {})
        return payload

    # ------------------------------------------------------------------ clear
    async def clear_tracks(self) -> None:
        async with self._snapshot_event_lock:
            async with self._track_event_lock:
                async with self._lock:
                    self._track_epoch += 1
                    self._track_sequences.clear()
                    payload = {"epoch": self._track_epoch}
                await self.hub.publish("tracks_cleared", payload)

    async def clear_goto_targets(self) -> None:
        async with self._lock:
            for state in self._drones.values():
                state.pop("goto_lat", None)
                state.pop("goto_lon", None)
        await self.hub.publish("goto_targets_cleared", {})

    async def append_log(self, text: str) -> dict[str, str]:
        entry = {"timestamp": utc_now_text(), "text": str(text)[:4096]}
        async with self._snapshot_event_lock:
            await self.hub.publish("log", {"entry": entry})
        return entry

    async def clear_logs(self) -> None:
        async with self._snapshot_event_lock:
            await self.hub.publish("logs_cleared", {})

    async def export_logs_text(self) -> str:
        return ""

    # --------------------------------------------------------------- UDP state
    async def set_udp_health(self, **changes: Any) -> dict[str, Any]:
        async with self._lock:
            changed = any(self._udp_health.get(key) != value for key, value in changes.items())
            self._udp_health.update(changes)
            payload = dict(self._udp_health)
        if changed:
            await self.hub.publish("udp_health", payload)
        return payload

    async def udp_health(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self._udp_health)

    def receive_queue_diagnostics(self) -> dict[str, int | float]:
        with self._ingress_lock:
            telemetry_depth = len(self._latest_telemetry)
            log_depth = len(self._pending_logs)
        return {
            "capacity": 24 + self.settings.limits.log_entries,
            "depth": telemetry_depth + log_depth,
            "telemetry_depth": telemetry_depth,
            "log_depth": log_depth,
            "high_watermark": self._ingress_high_watermark,
            "telemetry_replaced_total": self._telemetry_replaced_total,
            "log_dropped_total": self._log_dropped_total,
            "dropped_total": self._log_dropped_total,
            "last_batch_size": self._receive_last_batch_size,
            "last_batch_duration_ms": self._receive_last_batch_duration_ms,
        }

    # -------------------------------------------------------------- batch loop
    async def _receive_loop(self) -> None:
        interval = self.settings.server.push_interval_ms / 1000.0
        next_tick = asyncio.get_running_loop().time() + interval
        try:
            while True:
                await asyncio.sleep(
                    max(0.0, next_tick - asyncio.get_running_loop().time())
                )
                await self.process_receive_queue_once()
                next_tick += interval
                now = asyncio.get_running_loop().time()
                if next_tick <= now:
                    next_tick = now + interval
        except asyncio.CancelledError:
            raise

    async def _status_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                async with self._lock:
                    now = time.monotonic()
                    current = {
                        drone_id: (
                            telemetry_status(
                                state.get("_last_telemetry_mono"), now, self.settings
                            ),
                            flight_control_status(
                                state.get("_last_flight_control_mono"), now, self.settings
                            ),
                        )
                        for drone_id, state in self._drones.items()
                    }
                if current != self._last_statuses:
                    self._last_statuses = current
                    await self.hub.publish("telemetry", await self.telemetry_payload())
        except asyncio.CancelledError:
            raise
