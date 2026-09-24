"""Thread-isolated UDP receive/send workers with append-only disk auditing."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import socket
import threading
from typing import Any

from .audit import AuditStream, default_audit_directory, run_stamp, utc_now_text
from .config import AppSettings, DroneTarget
from .state import StateStore


class UDPUnavailable(RuntimeError):
    """Raised when a command cannot be completed by the local send worker."""


@dataclass(slots=True)
class _SendRequest:
    payload: dict[str, Any]
    data: bytes
    targets: tuple[DroneTarget, ...]
    future: Future[dict[str, Any]]


_STOP = object()


class _ReceiverWorker(threading.Thread):
    def __init__(self, service: "UDPService") -> None:
        super().__init__(name="gcs-udp-receiver", daemon=True)
        self.service = service
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.socket: socket.socket | None = None
        self.start_error: str | None = None

    def run(self) -> None:
        while not self.stop_event.is_set():
            sock: socket.socket | None = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(0.2)
                sock.bind(
                    (
                        self.service.settings.udp.bind_host,
                        self.service.settings.udp.bind_port,
                    )
                )
                self.socket = sock
                self.start_error = None
                self.ready_event.set()
                self.service._notify_health(receiver_ready=True, last_error=None)
                while not self.stop_event.is_set():
                    try:
                        data, addr = sock.recvfrom(
                            self.service.settings.udp.max_packet_size + 1
                        )
                    except socket.timeout:
                        continue
                    except OSError:
                        if self.stop_event.is_set():
                            return
                        raise
                    self.service._handle_datagram_from_thread(data, addr)
            except OSError as exc:
                self.start_error = str(exc)
                self.ready_event.set()
                self.service._notify_health(
                    receiver_ready=False,
                    last_error=f"UDP receive worker failed: {exc}",
                )
                if self.stop_event.wait(self.service.settings.udp.retry_seconds):
                    return
            finally:
                self.socket = None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

    def stop(self) -> None:
        self.stop_event.set()
        sock = self.socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


class _SenderWorker(threading.Thread):
    def __init__(self, service: "UDPService") -> None:
        super().__init__(name="gcs-udp-sender", daemon=True)
        self.service = service
        self.requests: queue.Queue[_SendRequest | object] = queue.Queue(
            maxsize=service.settings.limits.send_queue
        )
        self.ready_event = threading.Event()
        self.socket: socket.socket | None = None
        self.start_error: str | None = None

    def run(self) -> None:
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_connreset = getattr(socket, "SIO_UDP_CONNRESET", None)
            if udp_connreset is not None:
                sock.ioctl(udp_connreset, False)
            sock.bind(("0.0.0.0", 0))
            self.socket = sock
            self.ready_event.set()
            self.service._notify_health(sender_ready=True, last_error=None)
            while True:
                item = self.requests.get()
                if item is _STOP:
                    return
                assert isinstance(item, _SendRequest)
                try:
                    self._send(sock, item)
                finally:
                    # Do not retain the most recently completed command while
                    # the worker blocks waiting for its next request.
                    del item
        except OSError as exc:
            self.start_error = str(exc)
            self.ready_event.set()
            self.service._notify_health(
                sender_ready=False,
                last_error=f"UDP send worker failed: {exc}",
            )
            while True:
                try:
                    pending = self.requests.get_nowait()
                except queue.Empty:
                    break
                if isinstance(pending, _SendRequest) and not pending.future.done():
                    pending.future.set_exception(
                        UDPUnavailable(f"UDP send worker unavailable: {exc}")
                    )
        finally:
            self.socket = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _send(self, sock: socket.socket, request: _SendRequest) -> None:
        targets: list[dict[str, Any]] = []
        for endpoint in request.targets:
            error: str | None = None
            sent = False
            sendto_result: int | None = None
            try:
                sendto_result = sock.sendto(
                    request.data,
                    (endpoint.host, endpoint.port),
                )
                sent = sendto_result == len(request.data)
            except OSError as exc:
                error = str(exc)
            target = {
                "host": endpoint.host,
                "port": endpoint.port,
                "sent": sent,
                "error": error,
            }
            targets.append(target)
            self.service._sent_audit.write(
                {
                    "timestamp": utc_now_text(),
                    "target": {
                        "id": endpoint.id,
                        "host": endpoint.host,
                        "port": endpoint.port,
                    },
                    "bytes": len(request.data),
                    "raw": request.data.decode("utf-8"),
                    "sendto_result": sendto_result,
                    "sent": sent,
                    "error": error,
                }
            )
        if not request.future.done():
            request.future.set_result(
                {"payload": dict(request.payload), "targets": targets}
            )

    def stop(self) -> None:
        try:
            self.requests.put_nowait(_STOP)
        except queue.Full:
            try:
                pending = self.requests.get_nowait()
            except queue.Empty:
                pending = None
            if isinstance(pending, _SendRequest) and not pending.future.done():
                pending.future.set_exception(UDPUnavailable("UDP service is stopping"))
            self.requests.put_nowait(_STOP)


class UDPService:
    """Own independent long-lived UDP receive and send threads."""

    def __init__(
        self,
        settings: AppSettings,
        store: StateStore,
        *,
        audit_dir: str | Path | None = None,
        send_timeout_seconds: float = 1.0,
    ) -> None:
        self.settings = settings
        self.store = store
        self.send_timeout_seconds = send_timeout_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._receiver: _ReceiverWorker | None = None
        self._sender: _SenderWorker | None = None
        self._stopping = False
        stamp = run_stamp()
        directory = Path(audit_dir) if audit_dir is not None else default_audit_directory()
        self._received_audit = AuditStream(
            directory, "received", stamp, self._audit_failed
        )
        self._sent_audit = AuditStream(directory, "sent", stamp, self._audit_failed)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._received_audit.open()
        self._sent_audit.open()
        audit_ready = bool(
            self._received_audit.diagnostics()["healthy"]
            and self._sent_audit.diagnostics()["healthy"]
        )
        await self.store.set_udp_health(
            audit_ready=audit_ready,
            audit_last_error=None if audit_ready else "UDP audit files are unavailable",
        )
        self._receiver = _ReceiverWorker(self)
        self._sender = _SenderWorker(self)
        self._receiver.start()
        self._sender.start()
        await self._wait_until_started(self._receiver.ready_event)
        await self._wait_until_started(self._sender.ready_event)
        if self._receiver.start_error:
            raise RuntimeError(
                "Unable to bind UDP telemetry port "
                f"{self.settings.udp.bind_host}:{self.settings.udp.bind_port}: "
                f"{self._receiver.start_error}"
            )
        if self._sender.start_error:
            raise RuntimeError(f"Unable to start UDP send worker: {self._sender.start_error}")

    async def stop(self) -> None:
        self._stopping = True
        receiver, sender = self._receiver, self._sender
        self._receiver = None
        self._sender = None
        if receiver is not None:
            receiver.stop()
        if sender is not None:
            sender.stop()
        await asyncio.gather(
            *(
                asyncio.to_thread(worker.join, 2.0)
                for worker in (receiver, sender)
                if worker is not None
            )
        )
        self._received_audit.close()
        self._sent_audit.close()
        await self.store.set_udp_health(receiver_ready=False, sender_ready=False)

    async def _wait_until_started(self, event: threading.Event) -> None:
        deadline = asyncio.get_running_loop().time() + 2.0
        while not event.is_set():
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("UDP worker start timed out")
            await asyncio.sleep(0.01)

    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        listed = await self.store.listed_drone_ids()
        requested = payload.get("targets")
        if requested is not None:
            if not isinstance(requested, list) or any(
                isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 24
                for item in requested
            ):
                raise ValueError("targets must contain drone IDs within 1..24")
            # Keep protocol membership and leader ordering unchanged; only the
            # UDP destinations are filtered by the ground-station list.
            drone_ids = list(dict.fromkeys(item for item in requested if item in listed))
        else:
            drone_ids = sorted(listed)
        if not drone_ids:
            raise UDPUnavailable("当前发送范围内没有地面站列表中的无人机，未发送。")
        return await self._queue_json(
            payload, tuple(self.target_for_drone(drone_id) for drone_id in drone_ids)
        )

    async def send_json_to_drone(
        self,
        payload: dict[str, Any],
        drone_id: int,
    ) -> dict[str, Any]:
        target = self.target_for_drone(drone_id)
        if drone_id not in await self.store.listed_drone_ids():
            raise UDPUnavailable(f"无人机 #{drone_id} 不在地面站列表中，未发送。")
        return await self._queue_json(payload, (target,))

    def target_for_drone(self, drone_id: int) -> DroneTarget:
        if (
            isinstance(drone_id, bool)
            or not isinstance(drone_id, int)
            or not 1 <= drone_id <= 24
        ):
            raise ValueError(f"drone ID {drone_id!r} is outside 1..24")
        for target in self.settings.udp.targets:
            if target.id == drone_id:
                return target
        raise UDPUnavailable(f"无人机 #{drone_id} 未配置控制地址，请填写 udp.targets。")

    async def _queue_json(
        self,
        payload: dict[str, Any],
        targets: tuple[DroneTarget, ...],
    ) -> dict[str, Any]:
        sender = self._sender
        if sender is None or sender.socket is None or not sender.is_alive():
            raise UDPUnavailable("UDP send worker is unavailable")
        data = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(data) > self.settings.udp.max_packet_size:
            raise ValueError(
                f"command packet is {len(data)} bytes; limit is "
                f"{self.settings.udp.max_packet_size}"
            )
        future: Future[dict[str, Any]] = Future()
        request = _SendRequest(dict(payload), data, targets, future)
        try:
            sender.requests.put_nowait(request)
        except queue.Full as exc:
            raise UDPUnavailable("UDP send queue is full; command was not queued") from exc
        try:
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)),
                timeout=self.send_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise UDPUnavailable(
                "UDP send worker timed out; local send outcome is unknown and the "
                "command will not be retried automatically"
            ) from exc

    def _handle_datagram_from_thread(
        self,
        data: bytes,
        addr: tuple[str, int],
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": utc_now_text(),
            "remote": {"host": addr[0], "port": addr[1]},
            "bytes": len(data),
        }
        if len(data) > self.settings.udp.max_packet_size:
            record.update(
                parse_status="oversize",
                raw_base64=base64.b64encode(data).decode("ascii"),
            )
            self._received_audit.write(record)
            return
        if self.settings.udp.print_received:
            print(f"[Web UDP recv] from {addr}: {data.decode('utf-8', 'replace')!r}")
        try:
            text = data.decode("utf-8", "strict")
        except UnicodeDecodeError:
            record.update(
                parse_status="invalid_utf8",
                raw_base64=base64.b64encode(data).decode("ascii"),
            )
            self._received_audit.write(record)
            return
        record["raw"] = text
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            record.update(
                parse_status="invalid_json",
            )
            self._received_audit.write(record)
            return
        if not isinstance(message, dict):
            record.update(parse_status="unsupported")
            self._received_audit.write(record)
            return
        accepted = self.store.enqueue_message(message)
        record.update(
            parse_status="accepted" if accepted else "unsupported",
        )
        self._received_audit.write(record)

    def _notify_health(self, **changes: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or self._stopping:
            return

        def schedule() -> None:
            asyncio.create_task(self.store.set_udp_health(**changes))

        loop.call_soon_threadsafe(schedule)

    def _audit_failed(self, message: str) -> None:
        self._notify_health(audit_ready=False, audit_last_error=message)

    def diagnostics(self) -> dict[str, Any]:
        receiver, sender = self._receiver, self._sender
        receiver_port = None
        if receiver is not None and receiver.socket is not None:
            try:
                receiver_port = receiver.socket.getsockname()[1]
            except OSError:
                pass
        return {
            "receiver_thread_alive": bool(receiver and receiver.is_alive()),
            "receiver_port": receiver_port,
            "sender_thread_alive": bool(sender and sender.is_alive()),
            "send_queue": {
                "capacity": self.settings.limits.send_queue,
                "depth": sender.requests.qsize() if sender is not None else 0,
            },
            "audit": {
                "received": self._received_audit.diagnostics(),
                "sent": self._sent_audit.diagnostics(),
            },
        }
