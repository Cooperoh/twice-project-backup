"""
后端 API 数据格式检查表

角色：
    本文件用 Pydantic 模型规定浏览器请求和后端响应应该包含哪些字段、字段是什么类型，以及某些字段之间必须满足什么条件。

主要职责：
    请求模型检查编队设置、无人机目标和控制命令等输入；响应模型规定命令执行结果的统一结构。
    ``StrictModel`` 还会拒绝没有声明的多余字段，避免拼写错误悄悄通过。

输入和输出：
    输入通常是浏览器发来的 JSON。FastAPI 会先把 JSON 转换成这里定义的模型对象；
    格式正确才交给路由或命令服务，格式错误则直接返回清楚的验证错误。

模块关系和典型数据流：
    ``前端 JSON -> models 验证 -> app.py 路由 -> commands.py 业务处理``。
    ``commands.py`` 也使用这里的响应模型，把处理结果整理成稳定的 API 格式。

容易混淆的地方：
    这里的“模型”是 HTTP 数据格式，不是无人机的实时状态。无人机、轨迹和编队等
    运行中数据由 ``state.py`` 的 ``StateStore`` 保存。

阅读重点：
    先把每个类当作一张表格看字段名称和类型，再看带 ``validator`` 的额外检查；
    Pydantic 的内部工作方式不必深入。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormationSettingsRequest(StrictModel):
    form_type: int = Field(ge=1, le=3)
    spacing: float = Field(gt=0)


class FormationsUpdateRequest(StrictModel):
    revision: int = Field(ge=0)
    members: dict[int, list[int]]
    leaders: dict[int, int | None]

    @field_validator("members")
    @classmethod
    def validate_member_groups(cls, value: dict[int, list[int]]) -> dict[int, list[int]]:
        if set(value) != {0, 1, 2, 3}:
            raise ValueError("members 必须完整包含编队 0、1、2、3。")
        normalized: dict[int, list[int]] = {}
        for group_id, members in value.items():
            if any(isinstance(item, bool) or item < 1 for item in members):
                raise ValueError(f"编队 {group_id} 的无人机 ID 必须是正整数。")
            if len(set(members)) != len(members):
                raise ValueError(f"编队 {group_id} 包含重复无人机 ID。")
            normalized[group_id] = sorted(members)
        return normalized

    @field_validator("leaders")
    @classmethod
    def validate_leader_groups(
        cls,
        value: dict[int, int | None],
    ) -> dict[int, int | None]:
        if set(value) != {0, 1, 2, 3}:
            raise ValueError("leaders 必须完整包含编队 0、1、2、3。")
        if any(
            leader is not None and (isinstance(leader, bool) or leader < 1)
            for leader in value.values()
        ):
            raise ValueError("队长 ID 必须是正整数或 null。")
        return value

    @model_validator(mode="after")
    def validate_unique_members_and_leaders(self) -> "FormationsUpdateRequest":
        seen: dict[int, int] = {}
        for group_id, members in self.members.items():
            for drone_id in members:
                if drone_id in seen:
                    raise ValueError(
                        f"无人机 #{drone_id} 同时出现在编队 {seen[drone_id]} 和 {group_id}。"
                    )
                seen[drone_id] = group_id

            leader = self.leaders[group_id]
            if not members and leader is not None:
                raise ValueError(f"空编队 {group_id} 不得设置队长。")
            if leader is not None and leader not in members:
                raise ValueError(f"编队 {group_id} 的队长不属于该编队。")
        return self


class BasicCommandRequest(StrictModel):
    command: Literal["takeoff", "rtl", "land"]
    group: int = Field(ge=0, le=3)


class FormationCommandRequest(StrictModel):
    group: int = Field(ge=0, le=3)
    form_type: int | None = Field(default=None, ge=1, le=3)
    spacing: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_settings_pair(self) -> "FormationCommandRequest":
        if (self.form_type is None) != (self.spacing is None):
            raise ValueError("form_type 与 spacing 必须同时提供或同时省略。")
        return self


class WorkbenchCommandRequest(StrictModel):
    command: Literal["test_dubins", "test_vo", "mission"]
    targets: list[int] | None = None

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(isinstance(item, bool) or item < 1 for item in value):
            raise ValueError("targets 中的无人机 ID 必须是正整数。")
        normalized = sorted(set(value))
        if not normalized:
            raise ValueError("targets 不得为空数组；全局指令请省略该字段。")
        return normalized


class DispatchTargetResult(StrictModel):
    host: str
    port: int
    sent: bool
    error: str | None = None


class DispatchPacketResult(StrictModel):
    payload: dict[str, Any]
    targets: list[DispatchTargetResult]


class CommandResponse(StrictModel):
    locally_dispatched: bool
    message: str
    dispatches: list[DispatchPacketResult] = Field(default_factory=list)
