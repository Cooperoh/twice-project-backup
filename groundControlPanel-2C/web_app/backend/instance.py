"""Cross-platform process-lifetime lock for one Web ground station instance."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, BinaryIO


class InstanceLock:
    """Hold an OS lock until the launcher process exits, even after a crash."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: BinaryIO | None = None

    def acquire(self, metadata: dict[str, Any]) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        stream = self.path.open("r+b", buffering=0)
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b" \n")
        stream.seek(0)
        try:
            _lock_first_byte(stream)
        except OSError:
            stream.close()
            return False

        encoded = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        stream.seek(1)
        stream.write(encoded)
        stream.truncate()
        self._file = stream
        return True

    def read_metadata(self) -> dict[str, Any] | None:
        try:
            # Windows byte-range locks are mandatory: start reading after the
            # locked sentinel byte instead of trying to read and slice it.
            with self.path.open("rb") as stream:
                stream.seek(1)
                raw = stream.read()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def release(self) -> None:
        stream, self._file = self._file, None
        if stream is None:
            return
        try:
            stream.seek(0)
            _unlock_first_byte(stream)
        finally:
            stream.close()

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


if os.name == "nt":
    import msvcrt

    def _lock_first_byte(stream: BinaryIO) -> None:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_first_byte(stream: BinaryIO) -> None:
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_first_byte(stream: BinaryIO) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_first_byte(stream: BinaryIO) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
