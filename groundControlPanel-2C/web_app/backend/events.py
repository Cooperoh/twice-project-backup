"""
后端 WebSocket 广播站。

角色：
    本文件负责把后端发生的变化主动、实时地推送给所有已连接的浏览器。
    普通 HTTP是浏览器提问后端回答，而 WebSocket 允许后端在数据变化时立即通知浏览器。

主要职责：
    ``WebSocketHub`` 记录当前客户端，为每个客户端建立独立消息队列，并提供订阅、
    取消订阅和广播功能。每条事件还带有递增序号和时间戳，帮助前端按顺序处理更新。

输入和输出：
    输入是 ``state.py`` 发布的事件类型和数据，例如日志、遥测或 UDP 健康状态；
    输出是发给各个 WebSocket 客户端的统一事件信封（envelope）。

模块关系和典型数据流：
    ``state 状态变化 -> hub.publish() -> 客户端队列 -> app.py WebSocket -> 前端``。
    浏览器刚连接时还会先收到一份完整快照，再继续接收这里广播的增量变化。

为什么需要队列：
    每个浏览器速度可能不同。队列设置容量上限，满时丢弃较旧消息，避免一个很慢的
    浏览器阻塞后端，更不能让它拖慢重要的 UDP 数据接收。

阅读重点：
    按 ``subscribe() -> publish() -> unsubscribe()`` 的顺序看，就能理解一条消息
    从进入广播站到送达浏览器的过程。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class WebSocketHub:
    """Publish ordered envelopes without allowing a slow browser to block UDP."""

    def __init__(self, queue_size: int) -> None:
        self._queue_size = queue_size
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._dropped: dict[asyncio.Queue[dict[str, Any]], int] = {}
        self._dropped_total = 0
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], int]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._clients.add(queue)
            self._dropped[queue] = 0
            baseline = self._sequence
        return queue, baseline

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._clients.discard(queue)
            self._dropped.pop(queue, None)

    async def publish(self, event_type: str, payload: Any) -> dict[str, Any]:
        async with self._lock:
            self._sequence += 1
            envelope = {
                "type": event_type,
                "seq": self._sequence,
                "timestamp": utc_now_text(),
                "payload": payload,
            }
            clients = tuple(self._clients)

        for queue in clients:
            if queue.full():
                try:
                    queue.get_nowait()
                    self._dropped[queue] = self._dropped.get(queue, 0) + 1
                    self._dropped_total += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # Another producer may have filled the bounded queue in-between.
                pass
        return envelope

    @staticmethod
    def snapshot_envelope(payload: Any, baseline: int) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "seq": baseline,
            "timestamp": utc_now_text(),
            "payload": payload,
        }

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "clients": len(self._clients),
            "queue_capacity": self._queue_size,
            "dropped_total": self._dropped_total,
            "client_queues": [
                {"depth": queue.qsize(), "dropped": self._dropped.get(queue, 0)}
                for queue in self._clients
            ],
        }
