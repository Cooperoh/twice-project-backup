#!/usr/bin/env python3

import asyncio

from behavior import follower_task, leader_patrol_task
from constants import TRAIL_DIST
from utils import normalize_group, normalize_targets

VALID_FORM_TYPES = {1, 2, 3}
TASK_RESET_TIMEOUT_SEC = 2.0

# 已删除或下线的命令仍然需要被 cmd_process 接收并回复地面站；
# 这里只保留“收到但不执行”的原因，不再保留对应飞行动作入口。
REMOVED_COMMANDS = {

    "takeoff":                          "起飞功能已删除，已收到但不执行",
    "rtl":                              "返航功能已删除，已收到但不执行",
    "land":                             "降落功能已删除，已收到但不执行",
    "target_location_starlink_sim":     "目标处置功能已删除，已收到但不执行",
    "target_location_starlink_sender":  "目标处置发送端功能已删除，已收到但不执行",
    "test_dubins":                      "Dubins 测试功能已删除，已收到但不执行",
    "test_vo":                          "VO 测试功能已删除，已收到但不执行",
    "mission":                          "mission 功能暂不支持，已收到但不执行",
}


def _format_targets(targets):
    ordered = normalize_targets(targets)
    if not ordered:
        return "全部"
    return ", ".join(str(v) for v in ordered)


class DroneContext:
    def __init__(self, drone_id, tag, default_group, current_group, is_leader, role):
        """保存单机身份信息和运行时编组状态。"""
        self.drone_id = drone_id
        self.tag = tag
        self.default_group = default_group
        self.current_group = current_group
        self.is_leader = is_leader
        self.role = role

    @classmethod
    def from_cfg(cls, cfg):
        """从 UAV 配置字典构造 DroneContext。"""
        tag = str(cfg.get("tag", "DRONE"))
        drone_id = int(cfg.get("id", cfg.get("index", 0)))
        group_value = normalize_group(cfg.get("group", 0))
        if group_value is None:
            group_value = 0
        role = str(cfg.get("role", "")).strip().lower()
        is_leader_cfg = bool(int(cfg.get("is_leader", 1 if role == "leader" else 0)))
        is_leader = is_leader_cfg or role == "leader"
        return cls(
            drone_id=drone_id,
            tag=tag,
            default_group=group_value,
            current_group=group_value,
            is_leader=is_leader,
            role=role,
        )

    def adopt_group(self, group):
        """更新当前编组；非法 group 会被忽略。"""
        value = normalize_group(group)
        if value is not None:
            self.current_group = value


class CommandProcessor:
    """单机命令处理器：负责接收地面站命令、过滤作用域并回复处理结果。"""

    def __init__(self, *, bridge, drone, cfg, tasks, form_ref):
        self.bridge = bridge
        self.drone = drone
        self.tasks = tasks
        self.form_ref = form_ref
        self.cfg = cfg
        self.ctx = DroneContext.from_cfg(cfg)

        # 编队状态由 cmd_process 维护，leader/follower 行为只读取该引用。
        self.form_ref.setdefault("type", 1)
        self.form_ref.setdefault("spacing", TRAIL_DIST)
        self.form_ref.setdefault("group", self.ctx.current_group)
        group_in_ref = normalize_group(self.form_ref.get("group", self.ctx.current_group))
        if group_in_ref is None:
            group_in_ref = self.ctx.current_group
        self.form_ref["group"] = group_in_ref
        self.form_ref["targets"] = []
        self.form_ref["leader_id"] = None

        self._pending_group = self.form_ref["group"]
        self._pending_group_label = str(self._pending_group)
        self._pending_targets = list(self.form_ref.get("targets", []))
        self.log_prefix = f"[{self.ctx.tag}]"
        self._last_abort_time = 0.0

    async def run(self):
        """主循环：持续读取地面站命令并分发处理。"""
        while True:
            msg = await self.bridge.next_cmd()
            if not isinstance(msg, dict):
                continue
            try:
                await self._dispatch(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.bridge.send_log(
                    f"{self.log_prefix} 命令处理异常：{type(exc).__name__}: {exc}"
                )

    async def _dispatch(self, msg):
        """按 cmd 字段路由命令；所有已知路径都通过 send_log 回复地面站。"""
        cmd = str(msg.get("cmd", "")).strip().lower()
        if not cmd:
            return

        if cmd == "config_update":
            await self._handle_config_update(msg)
            return

        if cmd in REMOVED_COMMANDS:
            self._handle_removed_command(cmd)
            return

        if not self._select_scope(cmd, msg):
            return
        self._apply_scope()

        if cmd == "abort":
            await self._handle_abort()
        elif cmd == "formation_set":
            self._handle_formation_set(msg)
        elif cmd == "formation_start":
            await self._handle_formation_start(msg)
        else:
            self.bridge.send_log(f"{self.log_prefix} 未知指令：{cmd}，已收到但不支持")

    async def _handle_config_update(self, msg):
        """处理运行时配置更新：编组、主从角色、编队类型和间距。"""
        target = msg.get("id")
        if target is not None:
            try:
                target_id = int(target)
            except (TypeError, ValueError):
                self.bridge.send_log(f"{self.log_prefix} config_update 目标 id 非法，已忽略")
                return
            if target_id != self.ctx.drone_id:
                self.bridge.send_log(
                    f"{self.log_prefix} 忽略 config_update：目标 id {target_id} 不是本机"
                )
                return

        updates = {}
        group_changed = False

        if "group" in msg:
            group = normalize_group(msg.get("group"))
            if group is not None and group != self.ctx.current_group:
                self.cfg["group"] = group
                self.ctx.current_group = group
                self.ctx.default_group = group
                self.form_ref["group"] = group
                updates["group"] = group
                group_changed = True

        if "is_leader" in msg:
            try:
                is_leader = bool(int(msg.get("is_leader")))
            except (TypeError, ValueError):
                is_leader = bool(msg.get("is_leader"))
            self.cfg["is_leader"] = int(is_leader)
            self.ctx.is_leader = is_leader
            updates["is_leader"] = 1 if is_leader else 0

        raw_form_type = msg.get("formation_types", msg.get("form_type"))
        if raw_form_type is not None:
            try:
                form_type = int(raw_form_type)
            except (TypeError, ValueError):
                form_type = None
            if form_type in VALID_FORM_TYPES:
                self.form_ref["type"] = form_type
                updates["formation_type"] = form_type

        raw_spacing = msg.get("formation_spacing", msg.get("spacing"))
        if raw_spacing is not None:
            try:
                spacing = float(raw_spacing)
            except (TypeError, ValueError):
                spacing = None
            if spacing and spacing > 0:
                self.form_ref["spacing"] = spacing
                updates["formation_spacing"] = spacing

        if group_changed and self.tasks:
            if await self._reset_tasks():
                self.form_ref["targets"] = []
                self.form_ref["leader_id"] = None
                updates["tasks_cancelled"] = True
            else:
                updates["tasks_cancel_timeout"] = True

        if updates:
            self.bridge.send_log(f"{self.log_prefix} 配置更新：{updates}")
        else:
            self.bridge.send_log(f"{self.log_prefix} config_update 已收到，但没有有效变更")

    def _select_scope(self, cmd, msg):
        """
        判断本机是否应该响应该命令。
        支持按 targets 精确指定无人机，或按 group 过滤编组；不匹配时也会回复地面站。
        """
        group = normalize_group(msg.get("group"))
        targets = normalize_targets(msg.get("targets"))

        if group is None:
            self._pending_group = self.ctx.current_group
            self._pending_group_label = "全部"
        else:
            self._pending_group = group
            self._pending_group_label = str(group)
        self._pending_targets = targets

        if targets:
            if self.ctx.drone_id not in targets:
                self._log_skip(cmd, targets=targets)
                return False
            return True

        if group is None:
            return True

        allowed_groups = {self.ctx.current_group, self.ctx.default_group}
        if group not in allowed_groups:
            self._log_skip(cmd, group=group)
            return False

        return True

    def _apply_scope(self):
        """将待处理命令的 targets/group 写入编队状态。"""
        if self._pending_targets:
            # 地面站会按无人机 id 升序发送 targets，因此 targets[0] 是组内最小 id。
            self.form_ref["targets"] = list(self._pending_targets)
            self.form_ref["leader_id"] = self._pending_targets[0]
        else:
            self.form_ref["targets"] = []
            self.form_ref["leader_id"] = None
        self.form_ref["group"] = self._pending_group
        self.ctx.adopt_group(self._pending_group)

    def _compute_follower_slot(self, members, leader_id):
        """根据 targets 顺序计算本机跟随槽位；leader 之后从 1 开始。"""
        try:
            idx = members.index(self.ctx.drone_id)
            return max(1, idx)
        except ValueError:
            return max(1, len(members))

    async def _handle_abort(self):
        """急停：取消当前异步任务；1 秒内重复急停只回复不重复处理。"""
        now = asyncio.get_event_loop().time()
        if now - self._last_abort_time < 1.0:
            self.bridge.send_log(f"{self.log_prefix} 重复急停已收到，忽略重复处理")
            return
        self._last_abort_time = now
        had_tasks = bool(self.tasks)
        reset_ok = await self._reset_tasks()
        if had_tasks and reset_ok:
            self.bridge.send_log(f"{self.log_prefix} 急停：已终止当前任务")
        elif had_tasks:
            self.bridge.send_log(f"{self.log_prefix} 急停：已请求终止当前任务，但仍有任务未退出")
        else:
            self.bridge.send_log(f"{self.log_prefix} 急停：当前没有运行中的任务")

    def _handle_removed_command(self, cmd):
        """已删除功能的命令只负责回复，不再触发飞行动作。"""
        self.bridge.send_log(f"{self.log_prefix} {cmd}: {REMOVED_COMMANDS[cmd]}")

    def _handle_formation_set(self, msg):
        """更新编队类型和间距，不启动飞行任务。"""
        try:
            self._update_formation_config(msg)
        except ValueError as exc:
            text = str(exc) or "编队参数错误"
            self.bridge.send_log(f"{self.log_prefix} formation_set 失败：{text}")
            return

        self.bridge.send_log(
            f"{self.log_prefix} 编队配置已更新：组={self._pending_group_label} "
            f"类型={self.form_ref['type']} 间距={self.form_ref['spacing']}m"
        )

    async def _handle_formation_start(self, msg):
        """更新编队参数并启动 leader/follower 控制帧编队任务。"""
        try:
            self._update_formation_config(msg)
        except ValueError as exc:
            text = str(exc) or "编队参数错误"
            self.bridge.send_log(f"{self.log_prefix} formation_start 失败：{text}")
            return

        if not await self._reset_tasks():
            self.bridge.send_log(
                f"{self.log_prefix} formation_start 失败：旧编队任务取消超时，未启动新任务"
            )
            return
        started, reason = self._start_formation_task()
        targets_display = _format_targets(self.form_ref.get("targets", []))
        self.bridge.send_log(
            f"{self.log_prefix} formation_start: {reason}；组={self._pending_group_label} "
            f"类型={self.form_ref['type']} 间距={self.form_ref['spacing']}m 目标={targets_display}"
        )
        if not started:
            return

    async def _reset_tasks(self):
        """取消并等待当前所有行为任务退出，然后清空任务列表。"""
        tasks = list(self.tasks)
        if not tasks:
            return True
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=TASK_RESET_TIMEOUT_SEC)
        for task in done:
            try:
                self.tasks.remove(task)
            except ValueError:
                pass
        if pending:
            self.bridge.send_log(
                f"{self.log_prefix} 等待旧编队任务退出超时：{len(pending)} 个任务仍未结束"
            )
            return False
        return True

    def _track_behavior_task(self, coro):
        task = asyncio.create_task(coro)
        task.add_done_callback(self._on_behavior_task_done)
        self.tasks.append(task)

    def _on_behavior_task_done(self, task):
        try:
            self.tasks.remove(task)
        except ValueError:
            pass
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            self.bridge.send_log(f"{self.log_prefix} 编队任务已退出")
            return
        self.bridge.send_log(
            f"{self.log_prefix} 编队任务异常退出：{type(exc).__name__}: {exc}"
        )

    def _start_formation_task(self):
        """根据 targets[0] 决定本机作为 leader 还是 follower 启动编队任务。"""
        members = normalize_targets(self.form_ref.get("targets", []))
        if not members:
            return False, "无法启动编队：targets 为空"
        # 这里依赖地面站已排序的 targets，最小 id 的无人机自动成为 leader。
        leader_id = members[0]
        self.form_ref["leader_id"] = leader_id

        if self.ctx.drone_id == leader_id:
            coro = leader_patrol_task(self.drone, self.bridge, self.form_ref)
            role = "leader"
        else:
            slot_index = self._compute_follower_slot(members, leader_id)
            coro = follower_task(
                self.drone,
                self.bridge,
                slot_index,
                self.ctx.drone_id,
                self.form_ref,
            )
            role = f"follower slot {slot_index}"
        self._track_behavior_task(coro)
        return True, f"已启动目标点帧编队任务，角色={role}"

    def _update_formation_config(self, msg):
        """从命令中解析编队类型和间距，非法参数抛出 ValueError。"""
        raw_type = msg.get("form_type", self.form_ref.get("type", 1))
        raw_spacing = msg.get("spacing", self.form_ref.get("spacing", TRAIL_DIST))
        try:
            form_type = int(raw_type)
            spacing = float(raw_spacing)
        except (TypeError, ValueError):
            raise ValueError("编队参数格式错误")
        if form_type not in VALID_FORM_TYPES or spacing <= 0:
            raise ValueError("编队参数取值非法")
        self.form_ref["type"] = form_type
        self.form_ref["spacing"] = spacing

    def _log_skip(self, cmd, *, targets=None, group=None):
        """回复本机跳过某条命令的原因。"""
        if targets:
            target_str = _format_targets(targets)
            self.bridge.send_log(f"{self.log_prefix} 忽略 {cmd}：本机不在目标列表 {target_str}")
        else:
            group_label = "*" if group is None else group
            self.bridge.send_log(
                f"{self.log_prefix} 忽略 {cmd}：当前组 {self.ctx.current_group} "
                f"不匹配指令组 {group_label}"
            )


async def cmd_listener(bridge, tasks, drone, form_ref, cfg):
    processor = CommandProcessor(
        bridge=bridge,
        drone=drone,
        cfg=cfg,
        tasks=tasks,
        form_ref=form_ref,
    )
    await processor.run()
