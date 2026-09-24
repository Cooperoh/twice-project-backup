import tkinter as tk
from tkinter import messagebox, ttk


class WorkbenchPage(ttk.Frame):
    """Workbench page for algorithm development and verification."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()

    def _build_ui(self):
        px = self.app.ui_px

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        outer = ttk.Frame(self, padding=px(20))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="随机游走测试", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, px(12))
        )

        ttk.Label(outer, text="无人机 ID").grid(
            row=1,
            column=0,
            sticky="e",
            padx=(0, px(8)),
            pady=px(4),
        )
        self._id_var = tk.StringVar(value="1")
        ttk.Entry(outer, textvariable=self._id_var, width=10).grid(
            row=1,
            column=1,
            sticky="w",
            pady=px(4),
        )

        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(px(16), 0))

        ttk.Button(btn_frame, text="启动随机游走", command=self._send_start).pack(side="left")
        ttk.Button(btn_frame, text="全部启动（编队 0）", command=self._send_start_all).pack(
            side="left", padx=(px(8), 0)
        )

        dubins_frame = ttk.LabelFrame(outer, text="Dubins 测试", padding=px(12))
        dubins_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(24), 0))

        ttk.Label(
            dubins_frame,
            text="点击后向所有无人机发送 cmd=\"test_dubins\"。",
        ).grid(row=0, column=0, sticky="w", pady=(0, px(8)))

        ttk.Button(
            dubins_frame,
            text="上传 Dubins Cmd",
            command=lambda: self._send_test_command("test_dubins"),
        ).grid(row=1, column=0, sticky="w")

        vo_frame = ttk.LabelFrame(outer, text="VO 测试", padding=px(12))
        vo_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(px(24), 0))

        ttk.Label(
            vo_frame,
            text="点击后向所有无人机发送 cmd=\"test_vo\"。",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(8)))

        ttk.Button(
            vo_frame,
            text="上传 VO Cmd",
            command=lambda: self._send_test_command("test_vo"),
        ).grid(row=1, column=0, sticky="w")

        mission_frame = ttk.LabelFrame(outer, text="Mission 指令", padding=px(12))
        mission_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(px(24), 0))

        ttk.Label(
            mission_frame,
            text="点击后向所有无人机发送 cmd=\"mission\"。",
        ).grid(row=0, column=0, sticky="w", pady=(0, px(8)))

        ttk.Button(
            mission_frame,
            text="上传 Mission Cmd",
            command=self._send_mission_command,
        ).grid(row=1, column=0, sticky="w")

        obstacle_frame = ttk.LabelFrame(outer, text="Monitor 障碍区", padding=px(12))
        obstacle_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(px(24), 0))

        ttk.Label(
            obstacle_frame,
            text="点击后在 Monitor 地图添加 3 个障碍圆。",
        ).grid(row=0, column=0, sticky="w", pady=(0, px(8)))

        ttk.Button(
            obstacle_frame,
            text="添加障碍圆",
            command=self._add_monitor_obstacles,
        ).grid(row=1, column=0, sticky="w")

    def _parse_id(self):
        try:
            return int(self._id_var.get())
        except ValueError:
            messagebox.showwarning("参数错误", "无人机 ID 须为整数。")
            return None

    def _send_start(self):
        drone_id = self._parse_id()
        if drone_id is None:
            return
        self.app.start_random_walk([drone_id])

    def _send_start_all(self):
        self.app.start_random_walk_for_group(0)

    def _send_mission_command(self):
        self.app.send_mission_command()

    def _send_test_command(self, command):
        self.app.send_workbench_command(command)

    def _add_monitor_obstacles(self):
        self.app.add_workbench_obstacles_to_monitor()
