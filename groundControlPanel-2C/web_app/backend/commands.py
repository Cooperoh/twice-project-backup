"""
后端命令审核与处理，位于浏览器 API 与 UDP 通信之间。

角色：
    本文件负责判断一个格式正确的控制请求在当前状态下能不能执行，以及应该转换成哪些协议消息；
    它是业务规则层，不负责接收 HTTP，也不直接操作网络 socket。

主要职责：
    ``CommandService`` 检查目标无人机、命令阻塞状态和编队规则，组织起飞、降落、返航、编队与工作台命令，然后调用 UDP 服务发送。
    必要时还会更新状态或写入日志。

输入和输出：
    输入是已经由 ``models.py`` 检查过的请求对象，以及 ``StateStore`` 中的当前状态；
    输出是交给 ``udp.py`` 的协议消息和返回给 API 的 ``CommandResponse``。

模块区别：
    ``models.py`` 检查“数据格式对不对”；
    ``commands``  本文件检查“业务上能不能这样做”；
    ``udp.py``    负责“把最终消息发出去”。
    三者分开后，每一层的责任更清楚。

模块关系和典型数据流：
    ``前端 -> app.py -> models 验证 -> CommandService -> UDPService -> 无人机``。
    如果命令被禁止、参数冲突或发送不可用，本文件会产生适合 API 返回的明确错误。

阅读重点：
    先看 ``CommandService`` 的公开处理方法，跟踪一条简单命令如何检查并发送；
    之后再阅读编队发布、紧急停止、串行化装饰器和失败结果汇总等复杂流程。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import wraps
from typing import Any, Protocol

from .models import (
    BasicCommandRequest,
    CommandResponse,
    FormationCommandRequest,
    WorkbenchCommandRequest,
)
from .state import StateStore
from .udp import UDPUnavailable


class CommandBlockedError(RuntimeError):
    pass


class CommandValidationError(ValueError):
    pass


class JSONSender(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def send_json_to_drone(
        self,
        payload: dict[str, Any],
        drone_id: int,
    ) -> dict[str, Any]: ...


def serialized(method: Any) -> Any:
    """Run one complete control operation behind the emergency command gate."""

    @wraps(method)
    async def wrapper(self: "CommandService", *args: Any, **kwargs: Any) -> Any:
        async with self._dispatch_lock:
            return await method(self, *args, **kwargs)

    return wrapper


class CommandService:
    """Build protocol-compatible payloads and dispatch each packet once."""

    def __init__(self, store: StateStore, sender: JSONSender) -> None:
        self.store = store
        self.sender = sender
        # Checking the emergency latch and completing the corresponding local
        # UDP dispatch must be one serialized operation. Otherwise an abort can
        # overtake a command that already passed its initial latch check.
        self._dispatch_lock = asyncio.Lock()
        self._emergency_generation = 0
        self._completed_abort_generation = 0
        self._abort_completion = asyncio.Event()
        self._abort_completion.set()

    async def ensure_not_blocked(self) -> None:
        abort_pending = self._completed_abort_generation < self._emergency_generation
        if abort_pending or await self.store.is_command_blocked():
            raise CommandBlockedError("当前处于急停状态，普通指令已阻止。")

    @staticmethod
    def _leader_first_targets(
        members: list[int],
        leader: int | None,
    ) -> list[int]:
        targets = sorted(set(members))
        if leader in targets:
            targets = [leader] + [item for item in targets if item != leader]
        return targets

    async def _resolve_targets(self, group_id: int) -> list[int]:
        members, leader = await self.store.formation_members(group_id)
        targets = self._leader_first_targets(members, leader)
        if not targets:
            raise CommandValidationError(f"编队 {group_id} 暂无无人机。")
        return targets

    @staticmethod
    def _response(message: str, dispatches: list[dict[str, Any]]) -> CommandResponse:
        target_results = [target for packet in dispatches for target in packet["targets"]]
        locally_dispatched = bool(target_results) and all(
            bool(target["sent"]) for target in target_results
        )
        return CommandResponse(
            locally_dispatched=locally_dispatched,
            message=message,
            dispatches=dispatches, # pyright: ignore[reportArgumentType]
        )

    @staticmethod
    def _raise_for_dispatch_failure(
        stage: str,
        dispatch: Mapping[str, Any],
    ) -> None:
        targets = dispatch.get("targets")
        if not isinstance(targets, list) or not targets:
            raise UDPUnavailable(f"{stage}下发失败：未配置发送目标。")
        failures = [
            target
            for target in targets
            if isinstance(target, Mapping) and not bool(target.get("sent"))
        ]
        if not failures:
            return
        details = "；".join(
            f"{target.get('host', '?')}:{target.get('port', '?')}"
            f"（{target.get('error') or '本地发送失败'}）"
            for target in failures
        )
        raise UDPUnavailable(f"{stage}下发失败：{details}。")

    @staticmethod
    def _raise_for_config_failures(responses: list[CommandResponse]) -> None:
        failures = [
            target
            for response in responses
            for packet in response.dispatches
            for target in packet.targets
            if not target.sent
        ]
        if not failures:
            return
        details = "；".join(
            f"{target.host}:{target.port}（{target.error or '本地发送失败'}）"
            for target in failures
        )
        raise UDPUnavailable(f"编队成员配置下发失败：{details}。")

    @serialized
    async def send_basic(self, request: BasicCommandRequest) -> CommandResponse:
        await self.ensure_not_blocked()
        targets = await self._resolve_targets(request.group)
        payload = {
            "cmd": request.command,
            "targets": targets,
            "group": request.group,
        }
        dispatch = await self.sender.send_json(payload)
        await self.store.append_log(
            f"[指令] 本机已尝试发送 {request.command} -> 编队 {request.group}，成员 {targets}。"
        )
        return self._response(
            "本机已尝试向列表内目标发送指令；该结果不代表无人机已收到或执行。",
            [dispatch],
        )

    @serialized
    async def send_formation(self, request: FormationCommandRequest) -> CommandResponse:
        await self.ensure_not_blocked()
        targets = await self._resolve_targets(request.group)
        if request.form_type is not None and request.spacing is not None:
            form_type = request.form_type
            spacing = request.spacing
            await self.store.update_formation_settings(form_type, spacing)
        else:
            form_type, spacing = await self.store.formation_settings()

        common = {
            "group": request.group,
            "targets": targets,
            "form_type": int(form_type),
            "spacing": float(spacing),
        }
        # 机载端 formation_start 会先应用完整编队参数，再取消旧任务并启动新任务，
        # 无需先发相同参数的 formation_set。保留全部 common 字段，避免依赖旧配置。
        # 不自动重发 start，因为重复接收会再次重启机载编队任务。
        start_dispatch = await self.sender.send_json({"cmd": "formation_start", **common})
        await self.store.mark_formation_active(request.group)
        await self.store.append_log(
            "[编队] 本机已尝试发送 formation_start（含完整编队参数） "
            f"-> 编队 {request.group}，类型 {form_type}，间距 {spacing:.1f} 米，成员 {targets}。"
        )
        return self._response(
            "本机已尝试向列表内目标发送含完整参数的编队启动指令；该结果不代表无人机已收到或执行。",
            [start_dispatch],
        )

    @serialized
    async def send_workbench(self, request: WorkbenchCommandRequest) -> CommandResponse:
        await self.ensure_not_blocked()
        payload: dict[str, Any] = {"cmd": request.command}
        if request.targets is not None:
            payload["targets"] = list(request.targets)
        dispatch = await self.sender.send_json(payload)
        target_text = f"，目标 {request.targets}" if request.targets is not None else "，全局指令"
        await self.store.append_log(
            f"[Workbench] 本机已尝试发送 {request.command}{target_text}。"
        )
        return self._response(
            "本机已尝试向列表内目标发送 Workbench 指令；该结果不代表无人机已收到或执行。",
            [dispatch],
        )

    async def abort(self) -> CommandResponse:
        self._emergency_generation += 1
        generation = self._emergency_generation
        completion = asyncio.Event()
        self._abort_completion = completion
        # Emergency state is committed before network I/O and remains active
        # even when the local UDP send channel is unavailable.
        try:
            await self.store.set_emergency(True)
            # Set the latch before waiting for the FIFO dispatch gate. Commands
            # already queued ahead of abort will then fail their latch check rather
            # than sending before the emergency packet.
            async with self._dispatch_lock:
                # Reassert after older queued operations have drained: an in-flight
                # formation may have marked itself active, or an older queued
                # resume may have temporarily cleared the latch while abort waited.
                await self.store.set_emergency(True)
                await self.store.append_log("[急停] 已进入全局指令阻止状态，正在尝试向列表内目标发送 abort。")
                dispatch = await self.sender.send_json({"cmd": "abort"})
                return self._response(
                    "已进入急停状态，并在本机尝试向列表内目标发送 abort；该结果不代表无人机已收到或执行。",
                    [dispatch],
                )
        finally:
            self._completed_abort_generation = max(
                self._completed_abort_generation,
                generation,
            )
            completion.set()

    async def resume(self) -> CommandResponse:
        generation = self._emergency_generation
        completion = self._abort_completion
        await completion.wait()
        async with self._dispatch_lock:
            if (
                generation != self._emergency_generation
                or self._completed_abort_generation < generation
            ):
                raise CommandBlockedError("恢复请求早于最新急停，已忽略；请重新执行恢复。")
            await self.store.set_emergency(False)
            # An abort may register while set_emergency() yields. Recheck before
            # releasing the dispatch gate so a later ordinary command cannot
            # observe a stale resume between the two operations.
            if generation != self._emergency_generation:
                await self.store.set_emergency(True)
                raise CommandBlockedError("恢复请求已被新的急停取代；请重新执行恢复。")
            await self.store.append_log("[急停] 指令阻止已解除；未发送任何 UDP 指令。")
            return CommandResponse(
                locally_dispatched=False,
                message="本地指令阻止已解除；恢复操作不会发送 UDP。",
                dispatches=[],
            )

    @serialized
    async def config_update_for_drone(
        self,
        drone_id: int,
        group_id: int,
        leader: bool,
    ) -> CommandResponse:
        await self.ensure_not_blocked()
        return await self._config_update_for_drone(drone_id, group_id, leader)

    async def _config_update_for_drone(
        self,
        drone_id: int,
        group_id: int,
        leader: bool,
    ) -> CommandResponse:
        form_type, spacing = await self.store.formation_settings()
        payload = {
            "cmd": "config_update",
            "id": drone_id,
            "group": group_id,
            "is_leader": 1 if leader else 0,
            "form_type": form_type,
            "spacing": spacing,
        }
        dispatch = await self.sender.send_json_to_drone(payload, drone_id)
        return self._response(
            f"本机已尝试向无人机 #{drone_id} 的独立控制地址发送编队配置。",
            [dispatch],
        )

    @serialized
    async def config_updates_for_discovery(
        self,
        drone_id: int,
        _group_id: int,
        _leader: bool,
        displaced_leader_id: int | None,
    ) -> None:
        """Configure only the newcomer and a leader it actually displaced.

        Resolve both aircraft against the current authoritative formations while
        holding the formation transaction. This avoids sending stale group flags
        if a formation publication was already queued when telemetry discovered
        the newcomer.
        """

        await self.ensure_not_blocked()
        affected_ids = [drone_id]
        if displaced_leader_id is not None and displaced_leader_id != drone_id:
            affected_ids.append(displaced_leader_id)

        async with self.store.formation_transaction():
            members, leaders = await self.store.all_formations()
            assignments = {
                member_id: group_id
                for group_id in range(4)
                for member_id in members[group_id]
            }
            for affected_id in affected_ids:
                group_id = assignments.get(affected_id)
                if group_id is None:
                    continue
                await self._config_update_for_drone(
                    affected_id,
                    group_id,
                    leaders[group_id] == affected_id,
                )

    @serialized
    async def broadcast_current_configs(
        self,
        group_ids: set[int] | None = None,
    ) -> list[CommandResponse]:
        """Snapshot and target authoritative formations as one transaction."""

        await self.ensure_not_blocked()
        selected = set(range(4)) if group_ids is None else set(group_ids)
        async with self.store.formation_transaction():
            members, leaders = await self.store.all_formations()
            filtered_members = {
                group_id: members[group_id] if group_id in selected else []
                for group_id in range(4)
            }
            filtered_leaders = {
                group_id: leaders[group_id] if group_id in selected else None
                for group_id in range(4)
            }
            return await self._broadcast_all_configs_unlocked(
                filtered_members,
                filtered_leaders,
            )

    @serialized
    async def update_formation_settings(
        self,
        form_type: int,
        spacing: float,
    ) -> dict[str, Any]:
        await self.ensure_not_blocked()
        return await self.store.update_formation_settings(form_type, spacing)

    @serialized
    async def publish_formations(
        self,
        revision: int,
        members: Mapping[int, list[int]],
        leaders: Mapping[int, int | None],
    ) -> dict[str, Any]:
        """Send a validated proposal, then commit it as authoritative state.

        Groups that were active before publication are restarted after their
        proposed member configs have been sent, provided the proposed group is
        still nonempty. If the local UDP channel is unavailable, no formation
        revision or membership is changed. The gate also prevents another
        ordinary command from interleaving with the configuration packets.
        """

        await self.ensure_not_blocked()
        async with self.store.formation_transaction():
            previously_active = await self.store.active_formations()
            normalized_members, normalized_leaders = await self.store.validate_formations(
                revision,
                members,
                leaders,
            )
            config_responses = await self._broadcast_all_configs_unlocked(
                normalized_members,
                normalized_leaders,
            )
            self._raise_for_config_failures(config_responses)
            form_type, spacing = await self.store.formation_settings()
            restarted_groups: list[int] = []
            for group_id in sorted(previously_active):
                targets = self._leader_first_targets(
                    normalized_members[group_id],
                    normalized_leaders[group_id],
                )
                if not targets:
                    continue
                common = {
                    "group": group_id,
                    "targets": targets,
                    "form_type": int(form_type),
                    "spacing": float(spacing),
                }
                # 发布调整仍先逐机发送 config_update，更新分组和角色。
                # 对原已启动且仍非空的编队，仅用一条携带完整参数的 start 重建任务；
                # start 自身会更新编队配置，因此不再额外发送 formation_set。
                start_dispatch = await self.sender.send_json(
                    {"cmd": "formation_start", **common}
                )
                self._raise_for_dispatch_failure(
                    f"编队 {group_id} formation_start",
                    start_dispatch,
                )
                restarted_groups.append(group_id)
            payload = await self.store.update_formations(
                revision,
                normalized_members,
                normalized_leaders,
            )
        restarted_text = (
            f"，并重新启动编队 {restarted_groups}"
            if restarted_groups
            else ""
        )
        await self.store.append_log(
            "[编队] 已发布最新成员分布，并按无人机 ID 向独立控制地址发送配置更新"
            f"{restarted_text}。"
        )
        return payload

    async def _broadcast_all_configs_unlocked(
        self,
        members: Mapping[int, list[int]],
        leaders: Mapping[int, int | None],
    ) -> list[CommandResponse]:
        responses: list[CommandResponse] = []
        for group_id in range(4):
            leader = leaders[group_id]
            for drone_id in sorted(set(members[group_id])):
                responses.append(
                    await self._config_update_for_drone(
                        drone_id,
                        group_id,
                        drone_id == leader,
                    )
                )
        return responses
