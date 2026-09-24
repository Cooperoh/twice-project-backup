#!/usr/bin/env python3
"""Tkinter launcher for starting drone runtime instances as hidden processes."""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

REPO_ROOT = Path(__file__).resolve().parent
RUN_SCRIPT = Path("drone-exec") / "run.py"
DRONE_IDS = tuple(range(1, 25))
STOP_TIMEOUT_SEC = 2.0
POLL_INTERVAL_MS = 500


def is_valid_drone_id(drone_id: int) -> bool:
    return drone_id in DRONE_IDS


def build_run_command(drone_id: int, python_executable: str | None = None) -> list[str]:
    if not is_valid_drone_id(drone_id):
        raise ValueError(f"invalid drone id: {drone_id}")
    return [python_executable or sys.executable, str(RUN_SCRIPT), str(drone_id)]


def hidden_creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def start_drone_process(drone_id: int) -> subprocess.Popen:
    command = build_run_command(drone_id)
    return subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=hidden_creationflags(),
    )


def terminate_process(process: subprocess.Popen, timeout: float = STOP_TIMEOUT_SEC) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


class DroneLauncher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Drone Launcher")
        self.geometry("980x680")
        self.minsize(860, 480)

        self.processes: dict[int, subprocess.Popen] = {}
        self.status_vars: dict[int, tk.StringVar] = {}
        self.start_buttons: dict[int, ttk.Button] = {}
        self.stop_buttons: dict[int, ttk.Button] = {}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(POLL_INTERVAL_MS, self._poll_processes)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        for col in range(4):
            outer.columnconfigure(col, weight=1, uniform="drone")

        title = ttk.Label(outer, text="Drone Runtime Launcher", font=("", 14, "bold"))
        title.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        for index, drone_id in enumerate(DRONE_IDS):
            row = index // 4 + 1
            col = index % 4
            self._create_drone_card(outer, drone_id, row, col)

    def _create_drone_card(self, parent: tk.Misc, drone_id: int, row: int, col: int) -> None:
        frame = ttk.LabelFrame(parent, text=f"Drone {drone_id}", padding=8)
        frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        status = tk.StringVar(value="Idle")
        self.status_vars[drone_id] = status
        ttk.Label(frame, textvariable=status).grid(row=0, column=0, columnspan=2, sticky="w")

        start_button = ttk.Button(
            frame,
            text="Start",
            command=lambda did=drone_id: self._start_drone(did),
        )
        start_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        self.start_buttons[drone_id] = start_button

        stop_button = ttk.Button(
            frame,
            text="Stop",
            command=lambda did=drone_id: self._stop_drone(did),
            state="disabled",
        )
        stop_button.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(8, 0))
        self.stop_buttons[drone_id] = stop_button

    def _start_drone(self, drone_id: int) -> None:
        process = self.processes.get(drone_id)
        if process is not None and process.poll() is None:
            self._set_status(drone_id, "Running")
            return

        try:
            process = start_drone_process(drone_id)
        except Exception as exc:
            self._set_status(drone_id, f"Failed: {exc}")
            return

        self.processes[drone_id] = process
        self._set_running(drone_id, process.pid)

    def _stop_drone(self, drone_id: int) -> None:
        process = self.processes.get(drone_id)
        if process is None or process.poll() is not None:
            self._set_stopped(drone_id, "Exited")
            return

        self._set_status(drone_id, "Stopping...")
        self.start_buttons[drone_id].configure(state="disabled")
        self.stop_buttons[drone_id].configure(state="disabled")
        process.terminate()
        self.after(int(STOP_TIMEOUT_SEC * 1000), lambda did=drone_id: self._finish_stop(did))

    def _finish_stop(self, drone_id: int) -> None:
        process = self.processes.get(drone_id)
        if process is None:
            self._set_stopped(drone_id, "Stopped")
            return
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        self._set_stopped(drone_id, "Stopped")

    def _poll_processes(self) -> None:
        for drone_id, process in list(self.processes.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            self._set_stopped(drone_id, f"Exited ({return_code})")
        self.after(POLL_INTERVAL_MS, self._poll_processes)

    def _set_running(self, drone_id: int, pid: int | None) -> None:
        suffix = f" pid={pid}" if pid else ""
        self._set_status(drone_id, f"Running{suffix}")
        self.start_buttons[drone_id].configure(state="disabled")
        self.stop_buttons[drone_id].configure(state="normal")

    def _set_stopped(self, drone_id: int, text: str) -> None:
        self.processes.pop(drone_id, None)
        self._set_status(drone_id, text)
        self.start_buttons[drone_id].configure(state="normal")
        self.stop_buttons[drone_id].configure(state="disabled")

    def _set_status(self, drone_id: int, text: str) -> None:
        self.status_vars[drone_id].set(text)

    def _on_close(self) -> None:
        running = [did for did, proc in self.processes.items() if proc.poll() is None]
        if running:
            count = len(running)
            if not messagebox.askyesno(
                "Close launcher",
                f"Stop {count} running drone process(es) and exit?",
                parent=self,
            ):
                return
            for drone_id in running:
                process = self.processes.get(drone_id)
                if process is not None:
                    terminate_process(process)
        self.destroy()


def main() -> None:
    app = DroneLauncher()
    app.mainloop()


if __name__ == "__main__":
    main()
