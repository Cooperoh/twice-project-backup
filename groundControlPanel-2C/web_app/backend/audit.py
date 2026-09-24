"""Low-overhead append-only JSONL audit streams for raw UDP traffic."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, TextIO


AuditFailureHandler = Callable[[str], None]
_STOP = object()


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def default_audit_directory() -> Path:
    """Keep operator-visible audit files beside this standalone Web app."""

    return Path(__file__).resolve().parents[1] / "audit"


class AuditStream:
    """One process-run JSONL file written by a small background worker.

    UDP workers only enqueue a small record.  The audit worker serializes and
    combines records into larger writes, then flushes twice per second, keeping I/O and
    latency out of the real-time receive/send paths.  The bounded queue prevents
    an unhealthy disk from growing memory without limit.
    """

    def __init__(
        self,
        directory: Path,
        direction: str,
        run_stamp: str,
        on_failure: AuditFailureHandler,
        *,
        queue_capacity: int = 8192,
        batch_size: int = 256,
        flush_interval_seconds: float = 0.5,
    ) -> None:
        self.path = directory / f"{direction}-{run_stamp}.jsonl"
        self.direction = direction
        self._on_failure = on_failure
        self._queue: queue.Queue[dict[str, Any] | object] = queue.Queue(
            maxsize=queue_capacity
        )
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_seconds
        self._file: TextIO | None = None
        self._worker: threading.Thread | None = None
        self._healthy = False
        self._last_error: str | None = None
        self._records = 0
        self._written = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open(
                "a",
                encoding="utf-8",
                newline="\n",
                buffering=256 * 1024,
            )
        except OSError as exc:
            self._fail(exc)
            return
        self._healthy = True
        self._last_error = None
        self._worker = threading.Thread(
            target=self._run,
            name=f"gcs-audit-{self.direction}",
            daemon=True,
        )
        self._worker.start()

    def write(self, record: dict[str, Any]) -> bool:
        if not self._healthy or self._worker is None:
            return False
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                first_drop = self._dropped == 1
            if first_drop:
                self._fail(RuntimeError("audit queue is full; records are being dropped"))
            return False
        with self._lock:
            self._records += 1
        return True

    def close(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            # Shutdown is allowed to wait: every record already accepted by the
            # audit queue is written before the sentinel is processed.
            if worker.is_alive():
                try:
                    self._queue.put(_STOP, timeout=1.0)
                except queue.Full:
                    self._fail(RuntimeError("audit queue did not drain during shutdown"))
            worker.join(timeout=3.0)
            if worker.is_alive():
                self._fail(RuntimeError("audit writer did not stop within 3 seconds"))
                return
        stream, self._file = self._file, None
        if stream is None:
            return
        try:
            stream.flush()
            stream.close()
        except OSError as exc:
            self._fail(exc)

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            records = self._records
            written = self._written
            dropped = self._dropped
        worker = self._worker
        return {
            "path": str(self.path),
            "healthy": self._healthy,
            "last_error": self._last_error,
            "records": records,
            "written": written,
            "dropped": dropped,
            "queue_depth": self._queue.qsize(),
            "writer_alive": bool(worker and worker.is_alive()),
        }

    def _run(self) -> None:
        stream = self._file
        if stream is None:
            return
        last_flush = time.monotonic()
        try:
            while True:
                try:
                    item = self._queue.get(timeout=self._flush_interval_seconds)
                except queue.Empty:
                    stream.flush()
                    last_flush = time.monotonic()
                    continue
                if item is _STOP:
                    break

                records = [item]
                stopping = False
                while len(records) < self._batch_size:
                    try:
                        item = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is _STOP:
                        stopping = True
                        break
                    records.append(item)

                lines = [
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                    for record in records
                ]
                stream.writelines(lines)
                with self._lock:
                    self._written += len(records)
                now = time.monotonic()
                if stopping or now - last_flush >= self._flush_interval_seconds:
                    stream.flush()
                    last_flush = now
                if stopping:
                    break
            stream.flush()
        except (OSError, ValueError, TypeError) as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        self._healthy = False
        self._last_error = str(exc)
        self._on_failure(f"{self.direction} audit write failed: {exc}")


def run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
