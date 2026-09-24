"""
后端配置读取器

角色：
    本文件把便于人修改的 ``config.toml`` 转换成便于 Python 代码使用的配置对象。
    程序通常只在启动时读取一次配置，其他模块不需要反复打开 TOML 文件。

主要职责：
    ``ServerSettings``、``UDPSettings``、``MapSettings`` 等数据类分别对应配置文件
    中的不同部分，``AppSettings`` 再把它们组合成一份完整配置。``load_settings()``
    使用 ``tomllib`` 读取文件，并通过辅助函数检查字段类型、数值范围和必填内容。

输入和输出：
    输入是 ``web_app/config.toml`` 或显式指定的其他 TOML 路径；输出是经过验证的
    ``AppSettings``。例如 TOML 中的 ``[udp] bind_port`` 会变成
    ``app_settings.udp.bind_port``。

模块关系和典型数据流：
    ``config.toml -> tomllib -> load_settings() -> AppSettings -> 其他后端模块``。
    ``app.py`` 负责调用本文件，``state.py`` 和 ``udp.py`` 等模块只使用转换后的对象。

阅读重点：
    先看各个 ``Settings`` 数据类了解“有哪些配置”，再看 ``AppSettings`` 如何汇总，
    最后看 ``load_settings()``。以 `_` 开头的函数主要负责检查和转换单个配置值。
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, AddressValueError
import math
from pathlib import Path
from typing import Any, Mapping
import tomllib


class ConfigurationError(ValueError):
    """Raised when ``config.toml`` is missing or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    push_interval_ms: int = 100


@dataclass(frozen=True, slots=True)
class DroneTarget:
    id: int
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class UDPSettings:
    bind_host: str = "0.0.0.0"
    bind_port: int = 56999
    targets: tuple[DroneTarget, ...] = ()
    max_packet_size: int = 65536
    retry_seconds: float = 2.0
    print_received: bool = False


@dataclass(frozen=True, slots=True)
class MapSettings:
    home_lat: float = 38.3094
    home_lon: float = 117.6800
    zoom: int = 14
    tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    attribution: str = "&copy; OpenStreetMap contributors"


@dataclass(frozen=True, slots=True)
class TelemetrySettings:
    normal_seconds: float = 3.0
    weak_seconds: float = 8.0
    poor_seconds: float = 15.0
    disconnected_seconds: float = 20.0


@dataclass(frozen=True, slots=True)
class FormationSettings:
    default_type: int = 1
    default_spacing: float = 2000.0


@dataclass(frozen=True, slots=True)
class LimitSettings:
    track_points_per_drone: int = 10_000
    log_entries: int = 2_000
    websocket_queue: int = 8
    send_queue: int = 64


@dataclass(frozen=True, slots=True)
class ObstacleSettings:
    id: str
    lat: float
    lon: float
    radius_m: float

    def as_dict(self) -> dict[str, str | float]:
        return {
            "id": self.id,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
        }


@dataclass(frozen=True, slots=True)
class AppSettings:
    server: ServerSettings = ServerSettings()
    udp: UDPSettings = UDPSettings()
    map: MapSettings = MapSettings()
    telemetry: TelemetrySettings = TelemetrySettings()
    formation: FormationSettings = FormationSettings()
    limits: LimitSettings = LimitSettings()
    obstacles: tuple[ObstacleSettings, ...] = ()

    def public_config(self) -> dict[str, Any]:
        """Return the non-sensitive configuration needed by the browser."""

        return {
            "home_lat": self.map.home_lat,
            "home_lon": self.map.home_lon,
            "map_zoom": self.map.zoom,
            "tile_url": self.map.tile_url,
            "tile_attribution": self.map.attribution,
            "log_entries": self.limits.log_entries,
            "track_points_per_drone": self.limits.track_points_per_drone,
            "obstacles": [item.as_dict() for item in self.obstacles],
            "telemetry_thresholds": {
                "normal_seconds": self.telemetry.normal_seconds,
                "weak_seconds": self.telemetry.weak_seconds,
                "poor_seconds": self.telemetry.poor_seconds,
                "disconnected_seconds": self.telemetry.disconnected_seconds,
            },
        }


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"配置节 [{name}] 必须是 TOML 表。")
    return value


def _str(section: Mapping[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"配置项 {key} 必须是非空字符串。")
    return value.strip()


def _bool(section: Mapping[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"配置项 {key} 必须是布尔值。")
    return value


def _int(
    section: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"配置项 {key} 必须是整数。")
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"配置项 {key} 不得小于 {minimum}。")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"配置项 {key} 不得大于 {maximum}。")
    return value


def _float(
    section: Mapping[str, Any],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"配置项 {key} 必须是数字。")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigurationError(f"配置项 {key} 必须是有限数字。")
    if minimum is not None and number < minimum:
        raise ConfigurationError(f"配置项 {key} 不得小于 {minimum}。")
    if maximum is not None and number > maximum:
        raise ConfigurationError(f"配置项 {key} 不得大于 {maximum}。")
    return number


def load_settings(path: str | Path | None = None) -> AppSettings:
    """Load and validate ``web_app/config.toml`` (or an explicitly supplied file)."""

    config_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else Path(__file__).resolve().parents[1] / "config.toml"
    )
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"找不到配置文件：{config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"配置文件格式错误：{config_path}: {exc}") from exc

    server_raw = _section(data, "server")
    udp_raw = _section(data, "udp")
    map_raw = _section(data, "map")
    telemetry_raw = _section(data, "telemetry")
    formation_raw = _section(data, "formation")
    limits_raw = _section(data, "limits")

    if "target_host" in udp_raw or "target_ports" in udp_raw:
        raise ConfigurationError(
            "请将 udp.target_host / target_ports 改为 udp.targets，"
            "逐机配置 { id = 1, host = \"实际 IP\", port = 57001 }。"
        )
    raw_targets = udp_raw.get("targets", [])
    if not isinstance(raw_targets, list):
        raise ConfigurationError("配置项 udp.targets 必须是 TOML 表数组。")
    targets: list[DroneTarget] = []
    target_ids: set[int] = set()
    addresses: set[tuple[str, int]] = set()
    for item in raw_targets:
        if not isinstance(item, Mapping) or not {"id", "host", "port"} <= item.keys():
            raise ConfigurationError("每个 udp.targets 项必须包含 id、host、port。")
        drone_id = _int(item, "id", 0, minimum=1, maximum=24)
        host = _str(item, "host", "")
        try:
            address = IPv4Address(host)
        except AddressValueError as exc:
            raise ConfigurationError(f"无人机 #{drone_id} 的 host 必须是 IPv4 地址。") from exc
        if address.is_unspecified or address.is_multicast or host == "255.255.255.255":
            raise ConfigurationError(f"无人机 #{drone_id} 的 host 必须是单机 IPv4 地址。")
        port = _int(item, "port", 0, minimum=1, maximum=65535)
        if drone_id in target_ids:
            raise ConfigurationError(f"udp.targets 中的无人机 ID 重复：{drone_id}。")
        if (host, port) in addresses:
            raise ConfigurationError(f"udp.targets 中的目标地址重复：{host}:{port}。")
        target_ids.add(drone_id)
        addresses.add((host, port))
        targets.append(DroneTarget(drone_id, host, port))

    server = ServerSettings(
        host=_str(server_raw, "host", "127.0.0.1"),
        port=_int(server_raw, "port", 8765, minimum=1, maximum=65535),
        open_browser=_bool(server_raw, "open_browser", True),
        push_interval_ms=_int(server_raw, "push_interval_ms", 100, minimum=10),
    )
    udp = UDPSettings(
        bind_host=_str(udp_raw, "bind_host", "0.0.0.0"),
        bind_port=_int(udp_raw, "bind_port", 56999, minimum=1, maximum=65535),
        targets=tuple(targets),
        max_packet_size=_int(udp_raw, "max_packet_size", 65536, minimum=512),
        retry_seconds=_float(udp_raw, "retry_seconds", 2.0, minimum=0.1),
        print_received=_bool(udp_raw, "print_received", False),
    )
    map_settings = MapSettings(
        home_lat=_float(map_raw, "home_lat", 38.3094, minimum=-90, maximum=90),
        home_lon=_float(map_raw, "home_lon", 117.6800, minimum=-180, maximum=180),
        zoom=_int(map_raw, "zoom", 14, minimum=0, maximum=24),
        tile_url=_str(
            map_raw,
            "tile_url",
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        ),
        attribution=_str(map_raw, "attribution", "&copy; OpenStreetMap contributors"),
    )
    telemetry = TelemetrySettings(
        normal_seconds=_float(telemetry_raw, "normal_seconds", 3.0, minimum=0),
        weak_seconds=_float(telemetry_raw, "weak_seconds", 8.0, minimum=0),
        poor_seconds=_float(telemetry_raw, "poor_seconds", 15.0, minimum=0),
        disconnected_seconds=_float(
            telemetry_raw,
            "disconnected_seconds",
            20.0,
            minimum=0,
        ),
    )
    if not (
        telemetry.normal_seconds
        <= telemetry.weak_seconds
        <= telemetry.poor_seconds
        <= telemetry.disconnected_seconds
    ):
        raise ConfigurationError(
            "遥测阈值必须满足 normal <= weak <= poor <= disconnected。"
        )
    formation = FormationSettings(
        default_type=_int(formation_raw, "default_type", 1, minimum=1, maximum=3),
        default_spacing=_float(
            formation_raw,
            "default_spacing",
            2000.0,
            minimum=0.000001,
        ),
    )
    limits = LimitSettings(
        track_points_per_drone=_int(
            limits_raw,
            "track_points_per_drone",
            10_000,
            minimum=1,
        ),
        log_entries=_int(limits_raw, "log_entries", 2_000, minimum=1),
        websocket_queue=_int(limits_raw, "websocket_queue", 8, minimum=1),
        send_queue=_int(limits_raw, "send_queue", 64, minimum=1),
    )

    obstacles_raw = data.get("obstacles", [])
    if not isinstance(obstacles_raw, list):
        raise ConfigurationError("[[obstacles]] 必须是 TOML 表数组。")
    obstacles: list[ObstacleSettings] = []
    obstacle_ids: set[str] = set()
    for index, item in enumerate(obstacles_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"obstacles[{index}] 必须是 TOML 表。")
        obstacle_id = _str(item, "id", f"obs_{index}")
        if obstacle_id in obstacle_ids:
            raise ConfigurationError(f"障碍物 id 重复：{obstacle_id}")
        obstacle_ids.add(obstacle_id)
        obstacles.append(
            ObstacleSettings(
                id=obstacle_id,
                lat=_float(item, "lat", map_settings.home_lat, minimum=-90, maximum=90),
                lon=_float(item, "lon", map_settings.home_lon, minimum=-180, maximum=180),
                radius_m=_float(item, "radius_m", 1.0, minimum=0.000001),
            )
        )

    return AppSettings(
        server=server,
        udp=udp,
        map=map_settings,
        telemetry=telemetry,
        formation=formation,
        limits=limits,
        obstacles=tuple(obstacles),
    )
