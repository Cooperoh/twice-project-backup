import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import cast

import tkintermapview
from tkintermapview.canvas_path import CanvasPath
from tkintermapview.canvas_position_marker import CanvasPositionMarker
from tkintermapview.canvas_polygon import CanvasPolygon
from PIL import Image, ImageDraw, ImageTk

import drone_icon


TELEMETRY_TREE_COLUMNS = (
    ("id", "ID", 58, False),
    ("tag", "标签", 60, True),
    ("speed", "速度", 54, False),
    ("heading", "航向", 54, False),
    ("err", "误差", 54, False),
    ("telemetry", "遥测", 54, False),
    ("flight_control", "飞控", 54, False),
)
TELEMETRY_STATUS_TEXT = {
    "normal": "正常",
    "weak": "较差",
    "poor": "很差",
    "disconnected": "断开",
}
FLIGHT_CONTROL_STATUS_TEXT = {
    "normal": "正常",
    "fault": "故障",
    "dead": "断开",
}
TELEMETRY_STATUS_COLORS = {
    "fault": "#B88700",
    "dead": "#C62828",
    "disconnected": "#888888",
}
TRACK_PATH_WIDTH = 4


class MonitorPage(ttk.Frame):
    """Monitor page with integrated map, telemetry table, and basic commands."""

    GROUP_LABELS = {
        0: "编队0",
        1: "编队1",
        2: "编队2",
        3: "编队3",
    }

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._drone_icon_size = self.app.ui_px(44)
        self._track_path_width = self.app.ui_px(TRACK_PATH_WIDTH)

        self.show_tracks_flag = tk.BooleanVar(value=True)
        self.show_goto_flag = tk.BooleanVar(value=True)
        self._tree_sort_reverse = False
        self._tree_id_label = "ID"
        self._pending_focus_options = ["None"]
        # Key state caches keep type hints for clarity
        self.markers: dict[int, CanvasPositionMarker] = {}
        self.paths: dict[int, CanvasPath] = {}
        self.goto_paths: dict[int, CanvasPath] = {}
        self.goto_markers: dict[int, CanvasPositionMarker] = {}
        self.dubins_paths: dict[int, CanvasPath] = {}
        self.obstacle_circles: dict[str, list[CanvasPolygon]] = {}
        self.goto_icon = self._create_goto_icon()
        self._drone_displayed_headings: dict[int, int] = {}
        self._drone_displayed_positions: dict[int, tuple[float, float]] = {}
        self._drone_displayed_tags: dict[int, str] = {}
        self._track_displayed_signatures: dict[int, tuple[int, tuple[float, float]]] = {}

        self.group_selection = tk.IntVar(value=-1)

        self.form_type_var = tk.StringVar(value="三角")
        self.dist_var = tk.StringVar(value="2000")

        self._build_ui()

    # --------------------------------------------------------------------- UI
    def _build_ui(self):
        px = self.app.ui_px

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=px(8), pady=px(8))
        main.columnconfigure(0, weight=3, uniform="layout")
        main.columnconfigure(1, minsize=px(12))
        main.columnconfigure(2, weight=2, uniform="layout")
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        right = ttk.Frame(main)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3, uniform="right")
        right.rowconfigure(1, minsize=px(6))
        right.rowconfigure(2, weight=2, uniform="right")

        map_frame = ttk.LabelFrame(left, text="OpenStreetMap")
        map_frame.grid(row=0, column=0, sticky="nsew")
        self.map = tkintermapview.TkinterMapView(map_frame, corner_radius=px(8))
        self.map.pack(fill="both", expand=True)

        tool = ttk.Frame(map_frame)
        tool.place(relx=1.0, rely=0.0, anchor="ne")
        self.drone_focus = ttk.Combobox(
            tool,
            state="readonly",
            values=self._pending_focus_options,
            width=8,
        )
        self.drone_focus.pack(side="left", padx=px(2), pady=px(2))
        self.drone_focus.set(self._pending_focus_options[0])
        ttk.Checkbutton(tool, text="期望点", variable=self.show_goto_flag, command=self.toggle_goto).pack(side="left", padx=px(2), pady=px(2))
        ttk.Button(tool, text="清除期望点", command=self.clear_goto).pack(side="left", padx=px(2), pady=px(2))
        ttk.Button(tool, text="显示轨迹", command=self.show_tracks).pack(side="left", padx=px(2), pady=px(2))
        ttk.Button(tool, text="隐藏轨迹", command=self.hide_tracks).pack(side="left", padx=px(2), pady=px(2))
        ttk.Button(tool, text="清空轨迹", command=self.clear_tracks).pack(side="left", padx=px(2), pady=px(2))

        ctrl = ttk.LabelFrame(left, text="交互功能")
        ctrl.grid(row=1, column=0, sticky="ew", pady=(px(6), 0))

        actions_row = ttk.Frame(ctrl)
        actions_row.pack(fill="x", padx=px(6), pady=px(4))
        ttk.Button(actions_row, text="起飞", command=lambda: self._dispatch_basic("takeoff")).pack(side="left", padx=px(4))
        ttk.Button(actions_row, text="返回", command=lambda: self._dispatch_basic("rtl")).pack(side="left", padx=px(4))
        ttk.Button(actions_row, text="降落", command=lambda: self._dispatch_basic("land")).pack(side="left", padx=px(4))
        ttk.Button(actions_row, text="急停", style="Abort.TButton", command=self._dispatch_abort).pack(side="left", padx=(px(20), px(4)))
        ttk.Button(actions_row, text="恢复发令", command=self._dispatch_resume).pack(side="left", padx=px(4))

        formation_row = ttk.Frame(ctrl)
        formation_row.pack(fill="x", padx=px(6), pady=px(4))
        ttk.Label(formation_row, text="编队类型").pack(side="left", padx=(px(12), px(6)))
        ttk.Combobox(
            formation_row,
            state="readonly",
            values=list(self.app.formation_types.keys()),
            textvariable=self.form_type_var,
            width=10,
        ).pack(side="left", padx=px(6))
        ttk.Label(formation_row, text="间距(米)").pack(side="left", padx=(px(10), px(6)))
        ttk.Entry(formation_row, textvariable=self.dist_var, width=8).pack(side="left")
        ttk.Button(
            formation_row,
            text="下发编队",
            command=self._dispatch_formation,
        ).pack(side="left", padx=(px(22), px(4)))

        group_frame = ttk.LabelFrame(ctrl, text="控制目标")
        group_frame.pack(fill="x", padx=px(6), pady=px(4))
        for group_id in range(4):
            ttk.Radiobutton(
                group_frame,
                text=self.GROUP_LABELS[group_id],
                variable=self.group_selection,
                value=group_id,
            ).pack(side="left", padx=px(4))

        log_frame = ttk.LabelFrame(right, text="事件日志")
        log_frame.grid(row=0, column=0, sticky="nsew")

        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill="x", padx=px(6), pady=(px(6), 0))
        ttk.Button(log_toolbar, text="清除日志", command=self.clear_log).pack(side="left")
        ttk.Button(log_toolbar, text="导出日志", command=self.export_log).pack(side="left", padx=(px(6), 0))

        log_container = ttk.Frame(log_frame)
        log_container.pack(fill="both", expand=True, padx=px(6), pady=px(6))
        self.log = tk.Text(log_container, height=1, state="disabled", wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

        table = ttk.LabelFrame(right, text="遥测信息")
        table.grid(row=2, column=0, sticky="nsew")
        tree_container = ttk.Frame(table)
        tree_container.pack(fill="both", expand=True, padx=px(6), pady=px(6))
        columns = tuple(column for column, _title, _width, _stretch in TELEMETRY_TREE_COLUMNS)
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=1)
        tree_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        self._tree_column_base_widths = {}
        for column, title, width, _stretch in TELEMETRY_TREE_COLUMNS:
            scaled_width = px(width)
            self._tree_column_base_widths[column] = scaled_width
            self.tree.column(
                column,
                width=scaled_width,
                minwidth=scaled_width,
                anchor="center",
                stretch=False,
            )
            self.tree.heading(column, text=title)
        self.tree.heading("id", text="ID ASC", command=self.toggle_id_sort)
        self.tree.tag_configure("fault", foreground=TELEMETRY_STATUS_COLORS["fault"])
        self.tree.tag_configure("dead", foreground=TELEMETRY_STATUS_COLORS["dead"])
        self.tree.tag_configure(
            "disconnected",
            foreground=TELEMETRY_STATUS_COLORS["disconnected"],
        )
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Configure>", self._resize_telemetry_columns, add="+")

    def _resize_telemetry_columns(self, event):
        """Keep all telemetry columns proportional to their baseline widths."""
        total_base_width = sum(self._tree_column_base_widths.values())
        available_width = max(total_base_width, event.width - self.app.ui_px(2))
        cumulative_base = 0
        previous_edge = 0

        for column, _title, _width, _stretch in TELEMETRY_TREE_COLUMNS:
            cumulative_base += self._tree_column_base_widths[column]
            edge = round(available_width * cumulative_base / total_base_width)
            column_width = edge - previous_edge
            self.tree.column(column, width=column_width)
            previous_edge = edge

    # ------------------------------------------------------------------ events

    def _dispatch_basic(self, command):
        self.app.handle_basic_command(command)

    def _dispatch_formation(self):
        self.app.handle_formation_command()

    def _dispatch_abort(self):
        self.app.handle_abort_command()

    def _dispatch_resume(self):
        self.app.resume_commands()

    # ----------------------------------------------------------------- logging
    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def export_log(self):
        content = self.log.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("导出日志", "暂无日志可导出。")
            return
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="导出日志",
            defaultextension=".txt",
            filetypes=[("文本文档", "*.txt"), ("所有文件", "*.*")],
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(content + "\n")
        except OSError as exc:
            messagebox.showerror("导出日志", f"写入文件失败：{exc}")
        else:
            messagebox.showinfo("导出日志", f"日志已保存到：\n{file_path}")

    # ------------------------------------------------------------ group access
    def get_selected_group(self):
        value = self.group_selection.get()
        return value if value in self.GROUP_LABELS else None

    # ---------------------------------------------------------- focus options
    def set_focus_options(self, drone_ids):
        new_values = ["None"] + [str(d) for d in sorted(drone_ids)]
        if new_values != self._pending_focus_options:
            self._pending_focus_options = new_values
            current = self.drone_focus.get()
            self.drone_focus.configure(values=new_values)
            # Windows ttk.Combobox 重新 configure 后会按索引恢复选择，
            # 导致显示值漂移；手动按文本恢复。
            self.drone_focus.set(current if current in new_values else new_values[0])
        elif self.drone_focus.get() not in new_values:
            self.drone_focus.set(new_values[0])

    # ------------------------------------------------------------------ tracks
    def rebuild_all_paths(self):
        for pid in list(self.paths.keys()):
            try:
                self.paths[pid].delete()
            except Exception:
                pass
        self.paths.clear()
        self._track_displayed_signatures.clear()

    def show_tracks(self):
        self.show_tracks_flag.set(True)
        self.rebuild_all_paths()
        self.append_log("[轨迹] 显示")

    def hide_tracks(self):
        self.show_tracks_flag.set(False)
        for pid in list(self.paths.keys()):
            try:
                self.paths[pid].delete()
            except Exception:
                pass
            self.paths.pop(pid, None)
            self._track_displayed_signatures.pop(pid, None)
        self.append_log("[轨迹] 隐藏")

    def clear_tracks(self):
        for pid in list(self.paths.keys()):
            try:
                self.paths[pid].delete()
            except Exception:
                pass
        self.paths.clear()
        self._track_displayed_signatures.clear()
        self.app.clear_tracks_history()
        self.append_log("[轨迹] 清空")

    def clear_goto_overlays(self):
        for drone_id in list(set(self.goto_paths.keys()) | set(self.goto_markers.keys())):
            self._clear_goto_overlay(drone_id)

    def toggle_goto(self):
        if self.show_goto_flag.get():
            self.append_log("[Goto] 显示")
        else:
            self.clear_goto_overlays()
            self.append_log("[Goto] 隐藏")

    def clear_goto(self):
        self.app.clear_goto_targets()
        self.append_log("[Goto] 清除")

    def clear_dubins_path(self, drone_id):
        dubins_path = self.dubins_paths.pop(drone_id, None)
        if dubins_path is None:
            return
        try:
            dubins_path.delete()
        except Exception:
            pass

    def set_dubins_path(self, drone_id, points):
        self.clear_dubins_path(drone_id)
        if len(points) < 2:
            return
        try:
            self.dubins_paths[drone_id] = self.map.set_path(
                points,
                color="#2E7D32",
                width=self.app.ui_px(5),
            )
        except Exception:
            self.dubins_paths.pop(drone_id, None)

    # ---------------------------------------------------------- obstacles
    def clear_obstacle_circles(self):
        for obstacle_id in list(self.obstacle_circles.keys()):
            overlays = self.obstacle_circles.pop(obstacle_id, [])
            for overlay in overlays:
                try:
                    overlay.delete()
                except Exception:
                    pass

    def add_obstacle_circles(self, obstacles):
        self.clear_obstacle_circles()
        for obstacle in obstacles:
            try:
                obstacle_id = str(obstacle["id"])
                lat = float(obstacle["lat"])
                lon = float(obstacle["lon"])
                radius_m = float(obstacle["radius_m"])
            except (KeyError, TypeError, ValueError):
                continue
            if radius_m <= 0:
                continue
            overlays = []
            outer_points = self._circle_points(lat, lon, radius_m)
            try:
                overlays.append(
                    self.map.set_polygon(
                        outer_points,
                        outline_color="#D32F2F",
                        fill_color=None,
                        border_width=self.app.ui_px(3),
                        name=obstacle_id,
                        data=obstacle,
                    )
                )
                inner_radius_m = radius_m - 30.0
                if inner_radius_m > 0:
                    inner_points = self._circle_points(lat, lon, inner_radius_m)
                    overlays.append(
                        self.map.set_polygon(
                            inner_points,
                            outline_color="#D32F2F",
                            fill_color="#D32F2F",
                            border_width=self.app.ui_px(1),
                            name=f"{obstacle_id}_inner",
                            data=obstacle,
                        )
                    )
                self.obstacle_circles[obstacle_id] = overlays
            except Exception:
                for overlay in overlays:
                    try:
                        overlay.delete()
                    except Exception:
                        pass
                self.obstacle_circles.pop(obstacle_id, None)

    def _circle_points(self, lat, lon, radius_m, segments=72):
        earth_radius_m = 6371000.0
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        angular_distance = radius_m / earth_radius_m
        points = []

        for index in range(segments):
            bearing = 2.0 * math.pi * index / segments
            point_lat = math.asin(
                math.sin(lat_rad) * math.cos(angular_distance)
                + math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing)
            )
            point_lon = lon_rad + math.atan2(
                math.sin(bearing) * math.sin(angular_distance) * math.cos(lat_rad),
                math.cos(angular_distance) - math.sin(lat_rad) * math.sin(point_lat),
            )
            points.append((math.degrees(point_lat), math.degrees(point_lon)))

        return points

    # ------------------------------------------------------------- tree sorting
    def toggle_id_sort(self):
        self._tree_sort_reverse = not self._tree_sort_reverse
        self._update_id_heading()

    def _update_id_heading(self):
        label = f"{self._tree_id_label} {'DESC' if self._tree_sort_reverse else 'ASC'}"
        self.tree.heading("id", text=label, command=self.toggle_id_sort)

    def _row_status_tag(self, telemetry_status, flight_control_status):
        if telemetry_status == "disconnected":
            return "disconnected"
        if flight_control_status == "dead":
            return "dead"
        if flight_control_status == "fault":
            return "fault"
        return None

    def _create_goto_icon(self):
        size = self.app.ui_px(18)
        near_inset = self.app.ui_px(2)
        far_inset = self.app.ui_px(3)
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse(
            (near_inset, near_inset, size - far_inset, size - far_inset),
            fill="#FFD400",
            outline="#A67C00",
            width=self.app.ui_px(2),
        )
        return ImageTk.PhotoImage(image)

    def _clear_goto_overlay(self, drone_id):
        goto_path = self.goto_paths.pop(drone_id, None)
        if goto_path is not None:
            try:
                goto_path.delete()
            except Exception:
                pass
        goto_marker = self.goto_markers.pop(drone_id, None)
        if goto_marker is not None:
            try:
                goto_marker.delete()
            except Exception:
                pass

    def _sync_goto_overlay(self, drone_id, lat, lon, goto_lat, goto_lon):
        goto_marker = self.goto_markers.get(drone_id)
        if goto_marker is None:
            try:
                self.goto_markers[drone_id] = self.map.set_marker(
                    goto_lat,
                    goto_lon,
                    text=cast(str, None),
                    icon=self.goto_icon,
                    icon_anchor="center",
                )
            except Exception:
                pass
        else:
            try:
                goto_marker.set_position(goto_lat, goto_lon)
            except Exception:
                self._clear_goto_overlay(drone_id)
                try:
                    self.goto_markers[drone_id] = self.map.set_marker(
                        goto_lat,
                        goto_lon,
                        text=cast(str, None),
                        icon=self.goto_icon,
                        icon_anchor="center",
                    )
                except Exception:
                    pass

        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            goto_path = self.goto_paths.pop(drone_id, None)
            if goto_path is not None:
                try:
                    goto_path.delete()
                except Exception:
                    pass
            return

        line_points = [(lat, lon), (goto_lat, goto_lon)]
        goto_path = self.goto_paths.get(drone_id)
        if goto_path is None:
            try:
                self.goto_paths[drone_id] = self.map.set_path(
                    line_points,
                    color="#FFD400",
                    width=self.app.ui_px(4),
                )
            except Exception:
                pass
        else:
            try:
                goto_path.set_position_list(line_points)
            except Exception:
                path_deleted = self.goto_paths.pop(drone_id, None)
                if path_deleted is not None:
                    try:
                        path_deleted.delete()
                    except Exception:
                        pass
                try:
                    self.goto_paths[drone_id] = self.map.set_path(
                        line_points,
                        color="#FFD400",
                        width=self.app.ui_px(4),
                    )
                except Exception:
                    pass

    def _update_marker_icon(self, marker, icon):
        try:
            marker.change_icon(icon)
        except Exception:
            marker.icon = icon
            marker.calculate_text_y_offset()

    # -------------------------------------------------------------- ui refresh
    def refresh(self, state, tracks, show_errors):
        items = sorted(
            state.items(),
            key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else kv[0],
            reverse=self._tree_sort_reverse,
        )
        drone_ids = [int(k) for k, _ in items if str(k).isdigit()]
        self.set_focus_options(drone_ids)
        try:
            focus_value = self.drone_focus.get()
            focus_id = int(focus_value) if focus_value != "None" else None
        except (TypeError, ValueError):
            focus_id = None

        for drone_id, data in items:
            lat = data.get("lat")
            lon = data.get("lon")
            goto_lat = data.get("goto_lat")
            goto_lon = data.get("goto_lon")
            tag = data.get("tag") or f"DRONE{drone_id}"
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                hdg = data.get("heading")
                hdg_val = float(hdg) if isinstance(hdg, (int, float)) else 0.0
                hdg_key = drone_icon.quantize(hdg_val)
                position_key = (float(lat), float(lon))
                marker = self.markers.get(drone_id)
                if marker is None or getattr(marker, "deleted", False):
                    try:
                        self.markers[drone_id] = self.map.set_marker(
                            lat, lon, text=tag,
                            icon=drone_icon.get(hdg_val, self._drone_icon_size),
                            icon_anchor="center",
                        )
                        self._drone_displayed_headings[drone_id] = hdg_key
                        self._drone_displayed_positions[drone_id] = position_key
                        self._drone_displayed_tags[drone_id] = tag
                    except Exception:
                        pass
                else:
                    try:
                        if self._drone_displayed_headings.get(drone_id) != hdg_key:
                            self._update_marker_icon(
                                marker,
                                drone_icon.get(hdg_val, self._drone_icon_size),
                            )
                            self._drone_displayed_headings[drone_id] = hdg_key
                        if self._drone_displayed_positions.get(drone_id) != position_key:
                            marker.set_position(lat, lon)
                            self._drone_displayed_positions[drone_id] = position_key
                        if self._drone_displayed_tags.get(drone_id) != tag:
                            marker.set_text(tag)
                            self._drone_displayed_tags[drone_id] = tag
                    except Exception:
                        try:
                            replacement = self.map.set_marker(
                                lat, lon, text=tag,
                                icon=drone_icon.get(hdg_val, self._drone_icon_size),
                                icon_anchor="center",
                            )
                            try:
                                marker.delete()
                            except Exception:
                                pass
                            self.markers[drone_id] = replacement
                            self._drone_displayed_headings[drone_id] = hdg_key
                            self._drone_displayed_positions[drone_id] = position_key
                            self._drone_displayed_tags[drone_id] = tag
                        except Exception:
                            pass
                if self.show_tracks_flag.get():
                    pts = tracks.get(drone_id, [])
                    if pts:
                        track_signature = (len(pts), pts[-1])
                        path = self.paths.get(drone_id)
                        if path is None or getattr(path, "deleted", False):
                            try:
                                self.paths[drone_id] = self.map.set_path(
                                    pts,
                                    width=self._track_path_width,
                                )
                                self._track_displayed_signatures[drone_id] = track_signature
                            except Exception:
                                pass
                        else:
                            if self._track_displayed_signatures.get(drone_id) != track_signature:
                                try:
                                    path.set_position_list(pts)
                                    self._track_displayed_signatures[drone_id] = track_signature
                                except Exception:
                                    try:
                                        replacement = self.map.set_path(
                                            pts,
                                            width=self._track_path_width,
                                        )
                                        try:
                                            path.delete()
                                        except Exception:
                                            pass
                                        self.paths[drone_id] = replacement
                                        self._track_displayed_signatures[drone_id] = track_signature
                                    except Exception:
                                        pass

            if self.show_goto_flag.get() and isinstance(goto_lat, (int, float)) and isinstance(goto_lon, (int, float)):
                self._sync_goto_overlay(drone_id, lat, lon, goto_lat, goto_lon)
            else:
                self._clear_goto_overlay(drone_id)

        current_iids = set(self.tree.get_children(""))
        desired_order = []
        for drone_id, data in items:
            iid = str(drone_id)
            desired_order.append(iid)
            tag = data.get("tag") or f"DRONE{drone_id}"
            speed = data.get("speed")
            heading = data.get("heading")
            err_s = data.get("err_s")
            err_d = data.get("err_d")
            err = ""
            if show_errors:
                if isinstance(err_s, (int, float)) and isinstance(err_d, (int, float)):
                    err = f"{math.hypot(err_s, err_d):.1f}"
                elif isinstance(err_s, (int, float)):
                    err = f"{abs(err_s):.1f}"
            status_key = data.get("telemetry_status") or "disconnected"
            if status_key not in TELEMETRY_STATUS_TEXT:
                status_key = "disconnected"
            status_text = TELEMETRY_STATUS_TEXT[status_key]
            flight_control_key = data.get("flight_control_status") or "dead"
            if flight_control_key not in FLIGHT_CONTROL_STATUS_TEXT:
                flight_control_key = "dead"
            flight_control_text = FLIGHT_CONTROL_STATUS_TEXT[flight_control_key]
            values = (
                drone_id,
                tag,
                f"{speed:.1f}" if isinstance(speed, (int, float)) else "",
                f"{heading:.0f}" if isinstance(heading, (int, float)) else "",
                err,
                status_text,
                flight_control_text,
            )
            row_status_tag = self._row_status_tag(status_key, flight_control_key)
            tags = (row_status_tag,) if row_status_tag else ()
            if iid in current_iids:
                self.tree.item(iid, values=values, tags=tags)
            else:
                self.tree.insert("", "end", iid=iid, values=values, tags=tags)

            if focus_id is not None:
                try:
                    current_id = int(drone_id)
                except (TypeError, ValueError):
                    current_id = None
                if focus_id == current_id:
                    focus_lat = data.get("lat")
                    focus_lon = data.get("lon")
                    if isinstance(focus_lat, (int, float)) and isinstance(focus_lon, (int, float)):
                        try:
                            self.map.set_position(focus_lat, focus_lon)
                        except Exception:
                            pass

        for iid in current_iids - set(desired_order):
            self.tree.delete(iid)
        for index, iid in enumerate(desired_order):
            try:
                self.tree.move(iid, "", index)
            except Exception:
                pass

