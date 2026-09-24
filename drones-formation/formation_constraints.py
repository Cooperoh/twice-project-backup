"""Formation-level turn feasibility estimates for triangular fixed-wing teams."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any


GRAVITY = 9.81
DEFAULT_CRUISE_SPEED = 135.0  # 默认巡航速度，m/s；本次调整前为 120.0。
DEFAULT_MIN_SPEED = 100.0  # 默认速度下限，m/s；本次调整前已为 100.0，保持不变。
DEFAULT_MAX_SPEED = 170.0  # 默认速度上限，m/s；本次调整前已为 170.0，保持不变。
DEFAULT_BANK_ANGLE_DEG = 30.0
DEFAULT_TURN_TIME = 10.0


def calculate_formation_turn(row: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate turn radius constraints for one triangular formation layer.

    ``n`` uses the derivation-document layer index: the 4th visible row is n=3.
    ``spacing`` is the triangular formation base distance in meters; ``d`` is
    accepted as an alias for spreadsheet-style input.
    """

    cruise_speed = _positive_float(row, "cruise_speed", DEFAULT_CRUISE_SPEED)
    min_speed = _positive_float(row, "min_speed", DEFAULT_MIN_SPEED)
    max_speed = _positive_float(row, "max_speed", DEFAULT_MAX_SPEED)
    bank_angle_deg = _positive_float(row, "bank_angle_deg", DEFAULT_BANK_ANGLE_DEG)
    turn_time = _positive_float(row, "turn_time", DEFAULT_TURN_TIME)
    n = _positive_int(row, "n")
    spacing = _positive_float(row, "spacing", None, aliases=("d",))
    tolerance_distance = _non_negative_float(
        row,
        "tolerance_distance",
        cruise_speed * 20.0,
        aliases=("epsilon",),
    )

    bank_angle_rad = math.radians(bank_angle_deg)
    tan_bank = math.tan(bank_angle_rad)
    if tan_bank <= 0.0:
        raise ValueError("bank_angle_deg must produce a positive turn radius")

    default_turn_radius_m = cruise_speed * cruise_speed / (GRAVITY * tan_bank)
    default_turn_rate_deg_s = math.degrees(cruise_speed / default_turn_radius_m)

    heading_change = _optional_float(row, "heading_change_deg")
    if heading_change is None:
        effective_turn_time_s = turn_time
    else:
        effective_turn_time_s = abs(heading_change) / default_turn_rate_deg_s
        if effective_turn_time_s <= 0.0:
            raise ValueError("heading_change_deg must not be zero")

    default_heading_change_deg = default_turn_rate_deg_s * effective_turn_time_s
    p_ratio = max(0.0, (min_speed - tolerance_distance / effective_turn_time_s) / cruise_speed)
    q_ratio = (max_speed + tolerance_distance / effective_turn_time_s) / cruise_speed

    layer_distance = n * spacing
    outer_radius_bound_m = _outer_radius_bound(layer_distance, q_ratio)
    inner_radius_bound_m = _inner_radius_bound(layer_distance, p_ratio)

    actual_turn_radius_m = max(
        default_turn_radius_m,
        outer_radius_bound_m,
        inner_radius_bound_m,
    )
    feasible = math.isfinite(actual_turn_radius_m)
    actual_turn_rate_deg_s = (
        math.degrees(cruise_speed / actual_turn_radius_m) if feasible else 0.0
    )
    actual_heading_change_deg = actual_turn_rate_deg_s * effective_turn_time_s
    max_spacing_at_default_turn_m = min(
        _outer_spacing_bound(default_turn_radius_m, n, q_ratio),
        _inner_spacing_bound(default_turn_radius_m, n, p_ratio),
    )
    max_turn_time_at_default_turn_s = _default_turn_time_limit(
        default_turn_radius_m,
        n,
        spacing,
        cruise_speed,
        min_speed,
        max_speed,
        tolerance_distance,
    )
    max_heading_change_at_default_turn_deg = (
        default_turn_rate_deg_s * max_turn_time_at_default_turn_s
    )
    limiting_side = _limiting_side(
        default_turn_radius_m,
        outer_radius_bound_m,
        inner_radius_bound_m,
    )

    return {
        "n": n,
        "spacing_m": spacing,
        "effective_turn_time_s": effective_turn_time_s,
        "default_turn_radius_m": default_turn_radius_m,
        "default_turn_rate_deg_s": default_turn_rate_deg_s,
        "default_heading_change_deg": default_heading_change_deg,
        "actual_turn_radius_m": actual_turn_radius_m,
        "actual_turn_rate_deg_s": actual_turn_rate_deg_s,
        "actual_heading_change_deg_over_effective_time": actual_heading_change_deg,
        "max_turn_time_at_default_turn_s": max_turn_time_at_default_turn_s,
        "max_heading_change_at_default_turn_deg": max_heading_change_at_default_turn_deg,
        "max_spacing_at_default_turn_m": max_spacing_at_default_turn_m,
        "limiting_side": limiting_side,
        "feasible": feasible,
    }


def calculate_formation_turn_table(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Calculate turn constraints for every row in a parameter table."""

    return [calculate_formation_turn(row) for row in rows]


def format_formation_turn_chinese(result: Mapping[str, Any]) -> str:
    """Return a human-readable Chinese summary for one calculation result."""

    lines = [
        f"第 {result['n']} 层，编队距离 {result['spacing_m']:.2f} m：",
        "",
        "1. 主机默认值",
        f"   - 默认转弯半径：{result['default_turn_radius_m']:.2f} m",
        f"   - 默认转向角速度：{result['default_turn_rate_deg_s']:.3f} deg/s",
        f"   - 按当前有效时间默认会转向：{result['default_heading_change_deg']:.2f} deg",
        "",
        "2. 当前参数下实际需要值",
        f"   - 有效转弯时间：{result['effective_turn_time_s']:.2f} s",
        f"   - 实际主机转弯半径：{result['actual_turn_radius_m']:.2f} m",
        f"   - 实际转向角速度：{result['actual_turn_rate_deg_s']:.3f} deg/s",
        "   - 在有效时间内实际可转向："
        f"{result['actual_heading_change_deg_over_effective_time']:.2f} deg",
        "",
        "3. 如果仍按主机默认转弯半径飞",
        "   - 当前编队距离下最多可持续转弯："
        f"{_format_float(result['max_turn_time_at_default_turn_s'], '.2f')} s",
        "   - 当前编队距离下最多可转向："
        f"{_format_float(result['max_heading_change_at_default_turn_deg'], '.2f')} deg",
        "   - 当前有效时间下最大允许编队距离："
        f"{_format_float(result['max_spacing_at_default_turn_m'], '.2f')} m",
        "",
        "4. 判定",
        f"   - 主导约束：{_limiting_side_label(str(result['limiting_side']))}",
        f"   - 公式是否可行：{'是' if result['feasible'] else '否'}",
    ]
    return "\n".join(lines)


def format_formation_turn_table_chinese(results: Iterable[Mapping[str, Any]]) -> str:
    """Return a human-readable Chinese summary for a result table."""

    return "\n\n".join(format_formation_turn_chinese(result) for result in results)


def _outer_radius_bound(layer_distance: float, q_ratio: float) -> float:
    term = 4.0 * q_ratio * q_ratio - 3.0
    denominator = 2.0 * (q_ratio * q_ratio - 1.0)
    if term < 0.0 or denominator <= 0.0:
        return math.inf
    return layer_distance * (1.0 + math.sqrt(term)) / denominator


def _inner_radius_bound(layer_distance: float, p_ratio: float) -> float:
    term = 4.0 * p_ratio * p_ratio - 3.0
    if term <= 0.0:
        return 0.0
    denominator = 2.0 * (1.0 - p_ratio * p_ratio)
    if denominator == 0.0:
        return math.inf
    return layer_distance * (1.0 + math.sqrt(term)) / denominator


def _outer_spacing_bound(default_radius: float, n: int, q_ratio: float) -> float:
    term = 4.0 * q_ratio * q_ratio - 3.0
    if term < 0.0:
        return float("nan")
    return default_radius / (2.0 * n) * (math.sqrt(term) - 1.0)


def _inner_spacing_bound(default_radius: float, n: int, p_ratio: float) -> float:
    term = 4.0 * p_ratio * p_ratio - 3.0
    if term <= 0.0:
        return math.inf
    return default_radius / (2.0 * n) * (1.0 - math.sqrt(term))


def _default_turn_time_limit(
    default_radius: float,
    n: int,
    spacing: float,
    cruise_speed: float,
    min_speed: float,
    max_speed: float,
    tolerance_distance: float,
) -> float:
    layer_distance = n * spacing
    radius_ratio = layer_distance / default_radius
    alpha_out = math.sqrt(1.0 + radius_ratio + radius_ratio * radius_ratio)
    alpha_in = math.sqrt(1.0 - radius_ratio + radius_ratio * radius_ratio)
    min_ratio = min_speed / cruise_speed
    max_ratio = max_speed / cruise_speed
    mismatch = max(0.0, alpha_out - max_ratio, min_ratio - alpha_in)
    if mismatch == 0.0:
        return math.inf
    return tolerance_distance / (cruise_speed * mismatch)


def _limiting_side(default_radius: float, outer_radius: float, inner_radius: float) -> str:
    actual_radius = max(default_radius, outer_radius, inner_radius)
    if math.isinf(actual_radius):
        if math.isinf(outer_radius):
            return "outer"
        if math.isinf(inner_radius):
            return "inner"
        return "none"
    if actual_radius == outer_radius and outer_radius > default_radius:
        return "outer"
    if actual_radius == inner_radius and inner_radius > default_radius:
        return "inner"
    if actual_radius == default_radius:
        return "aircraft"
    return "none"


def _limiting_side_label(limiting_side: str) -> str:
    labels = {
        "outer": "外侧僚机最大速度约束",
        "inner": "内侧僚机最小速度约束",
        "aircraft": "主机默认转弯半径约束",
        "none": "无主导约束",
    }
    return labels.get(limiting_side, limiting_side)


def _format_float(value: Any, format_spec: str) -> str:
    if isinstance(value, float) and math.isinf(value):
        return "无限"
    if isinstance(value, float) and math.isnan(value):
        return "不可计算"
    return format(float(value), format_spec)


def _positive_int(row: Mapping[str, Any], key: str) -> int:
    if key not in row:
        raise ValueError(f"{key} is required")
    try:
        value = int(row[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _positive_float(
    row: Mapping[str, Any],
    key: str,
    default: float | None,
    *,
    aliases: tuple[str, ...] = (),
) -> float:
    value = _lookup(row, key, default, aliases)
    parsed = _finite_float(value, key)
    if parsed <= 0.0:
        raise ValueError(f"{key} must be positive")
    return parsed


def _non_negative_float(
    row: Mapping[str, Any],
    key: str,
    default: float,
    *,
    aliases: tuple[str, ...] = (),
) -> float:
    value = _lookup(row, key, default, aliases)
    parsed = _finite_float(value, key)
    if parsed < 0.0:
        raise ValueError(f"{key} must be non-negative")
    return parsed


def _optional_float(row: Mapping[str, Any], key: str) -> float | None:
    if key not in row or row[key] is None or row[key] == "":
        return None
    return _finite_float(row[key], key)


def _lookup(
    row: Mapping[str, Any],
    key: str,
    default: float | None,
    aliases: tuple[str, ...],
) -> Any:
    if key in row and row[key] not in (None, ""):
        return row[key]
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    if default is None:
        alias_text = f" or one of {aliases}" if aliases else ""
        raise ValueError(f"{key}{alias_text} is required")
    return default


def _finite_float(value: Any, key: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be a finite number")
    return parsed


if __name__ == "__main__":
    sample_rows = [
        {
            "cruise_speed": 135,  # m/s；本次调整前的示例值为 120。
            "min_speed": 100,  # m/s；本次调整前的示例值为 90。
            "max_speed": 170,  # m/s；本次调整前的示例值为 160。
            "bank_angle_deg": 30,
            "tolerance_distance": 2000,
            "turn_time": 120,
            "heading_change_deg": 90,
            "n": 2,
            "d": 1500,
        }
    ]
    results = calculate_formation_turn_table(sample_rows)

    # print("JSON 结果：")
    # print(
    #     json.dumps(
    #         results,
    #         ensure_ascii=False,
    #         indent=2,
    #     )
    # )
    # print()


    print(format_formation_turn_table_chinese(results))
