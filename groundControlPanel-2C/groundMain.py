import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from groundBridge import UDPBridge
from pageMonitor import MonitorPage
from pageFormation import FormationAssignmentPage
from pageWorkbench import WorkbenchPage

APP_TITLE = "Ground Control Panel"

IP = "10.144.1.100"
CMD_ADDRS = [(IP, 57000 + drone_id) for drone_id in range(1, 25)]
TELEM_ADDR = ("10.144.1.100", 56999) # default is 56999
PRINT_INCOMING_UDP_TEST_DATA = False

# HOME_LAT = 38.0667
# HOME_LON = 118.1575
HOME_LAT = 38.3094
HOME_LON = 117.680

TELEMETRY_GREEN_SECONDS = 3.0
TELEMETRY_YELLOW_SECONDS = 8.0
TELEMETRY_RED_SECONDS = 15.0
TELEMETRY_DISCONNECTED_SECONDS = 20.0

BASE_DPI = 96.0
BASE_WINDOW_SIZE = (1200, 800)
MIN_WINDOW_SIZE = (1100, 740)

WORKBENCH_OBSTACLES = [
    {"id": "obs_0", "lat": 38.31658652, "lon": 117.68000000, "radius_m": 100.00},
    {"id": "obs_1", "lat": 38.32017978, "lon": 117.67542070, "radius_m": 300.00},
    {"id": "obs_2", "lat": 38.32017978, "lon": 117.68457930, "radius_m": 200.00},
]


# # 北京经纬度
# HOME_LAT = 39.9042
# HOME_LON = 116.4074

# netsh int ipv4 show excludedportrange protocol=udp

class GroundControlApp(tk.Tk):
    """Main window: manages shared state, networking, and pages."""

    formation_types = {
        "三角": 1,
        "横向一线": 2,
        "纵向一线": 3,
    }

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)

        tk_scaling = float(self.tk.call("tk", "scaling"))
        detected_dpi = tk_scaling * 72.0
        detected_scale = detected_dpi / BASE_DPI
        if abs(detected_scale - 1.0) < 0.05:
            detected_scale = 1.0
        self.ui_scale = min(2.0, max(1.0, detected_scale))
        self.geometry(
            f"{self.ui_px(BASE_WINDOW_SIZE[0])}x{self.ui_px(BASE_WINDOW_SIZE[1])}"
        )
        self.minsize(
            self.ui_px(MIN_WINDOW_SIZE[0]),
            self.ui_px(MIN_WINDOW_SIZE[1]),
        )

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("Treeview", rowheight=self.ui_px(20))
        self.style.configure("Abort.TButton", foreground="white", background="#CC2222", font=("", 9, "bold"))
        self.style.map("Abort.TButton", background=[("active", "#FF4444"), ("disabled", "#999999")])

        self.state_lock = threading.Lock()
        self.drone_state = {}
        self.tracks = {}
        self.known_drones = set()
        self.command_blocked = False

        self.group_assignments = {0: [], 1: [], 2: [], 3: []}
        self.group_leaders = {0: None, 1: None, 2: None, 3: None}
        self.active_formations = set()

        self._msg_q = queue.Queue()
        self.bridge = UDPBridge(
            bind_addr=TELEM_ADDR,
            send_addrs=CMD_ADDRS,
            out_queue=self._msg_q,
            print_received=PRINT_INCOMING_UDP_TEST_DATA,
        )
        self.bridge.start()

        self.home_lat = HOME_LAT
        self.home_lon = HOME_LON

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.monitor_page = MonitorPage(self.nb, self)
        self.assignment_page = FormationAssignmentPage(self.nb, self)
        self.workbench_page = WorkbenchPage(self.nb, self)

        self.nb.add(self.monitor_page, text="Monitor")
        self.nb.add(self.assignment_page, text="Formation")
        self.nb.add(self.workbench_page, text="Workbench")

        self.monitor_page.map.set_position(self.home_lat, self.home_lon)
        self.monitor_page.map.set_zoom(14)

        self.after(50, self._poll_messages)
        self.after(100, self._refresh_pages)

    def ui_px(self, value):
        """Scale a baseline 96-DPI pixel value for the current display."""
        return int(round(value * self.ui_scale))

    # --------------------------------------------------------------- ui helpers
    def _append_log(self, text):
        self.monitor_page.append_log(text)

    def _update_dubins_path(self, drone_id, points):
        self.monitor_page.set_dubins_path(drone_id, points)

    # ---------------------------------------------------------------- network
    def _poll_messages(self):
        for _ in range(200):
            try:
                msg = self._msg_q.get_nowait()
            except queue.Empty:
                break
            self._handle_message(msg)
        self.after(50, self._poll_messages)

    def _handle_message(self, msg):
        if isinstance(msg, dict):
            mtype = msg.get("type")
            if mtype == "log":
                text = msg.get("text", "")
                if text:
                    self._append_log(text)
                return
            if mtype == "trajectory":
                drone_id = msg.get("id")
                if isinstance(drone_id, str) and drone_id.isdigit():
                    drone_id = int(drone_id)
                if not isinstance(drone_id, int):
                    return
                points = []
                for point in msg.get("points", []):
                    if not isinstance(point, dict):
                        continue
                    lat = point.get("lat")
                    lon = point.get("lon")
                    try:
                        points.append((float(lat), float(lon))) # type: ignore
                    except (TypeError, ValueError):
                        continue
                self._update_dubins_path(drone_id, points)
                return
            if mtype == "telemetry":
                drone_id = msg.get("id")
                if drone_id is None:
                    return
                if isinstance(drone_id, str) and drone_id.isdigit():
                    drone_id = int(drone_id)
                if not isinstance(drone_id, int):
                    return
                self._register_drone(drone_id)
                msg_lat = msg.get("lat")
                msg_lon = msg.get("lon")
                flight_control_telemetry = isinstance(msg_lat, (int, float)) and isinstance(msg_lon, (int, float))
                received_at = time.monotonic()
                with self.state_lock:
                    state = self.drone_state.setdefault(drone_id, {})
                    for key in ("lat", "lon", "speed", "heading", "err_s", "err_d", "tag"):
                        value = msg.get(key)
                        if value is not None:
                            state[key] = value
                    state["last_telemetry_at"] = received_at
                    if flight_control_telemetry:
                        state["last_flight_control_at"] = received_at
                    goto_lat_present = "goto_lat" in msg
                    goto_lon_present = "goto_lon" in msg
                    if goto_lat_present or goto_lon_present:
                        goto_lat = msg.get("goto_lat")
                        goto_lon = msg.get("goto_lon")
                        try:
                            if goto_lat is None or goto_lon is None:
                                raise ValueError
                            state["goto_lat"] = float(goto_lat)
                            state["goto_lon"] = float(goto_lon)
                        except (TypeError, ValueError):
                            state.pop("goto_lat", None)
                            state.pop("goto_lon", None)
                    lat = state.get("lat")
                    lon = state.get("lon")
                    if flight_control_telemetry and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                        track = self.tracks.setdefault(drone_id, [])
                        if not track or (
                            abs(track[-1][0] - lat) > 1e-6
                            or abs(track[-1][1] - lon) > 1e-6
                        ):
                            track.append((lat, lon))
                return
        if isinstance(msg, str):
            self._append_log(msg)

    # ----------------------------------------------------------------- refresh
    def _refresh_pages(self):
        now = time.monotonic()
        with self.state_lock:
            state_snapshot = {}
            for drone_id, state in self.drone_state.items():
                snapshot = dict(state)
                snapshot["telemetry_status"] = self._get_telemetry_status(
                    snapshot.get("last_telemetry_at"),
                    now,
                )
                snapshot["flight_control_status"] = self._get_flight_control_status(
                    snapshot.get("last_flight_control_at"),
                    now,
                )
                state_snapshot[drone_id] = snapshot
            tracks_snapshot = {k: list(v) for k, v in self.tracks.items()}
        show_errors = bool(self.active_formations)
        self.monitor_page.refresh(state_snapshot, tracks_snapshot, show_errors)
        self.after(150, self._refresh_pages)

    def _get_telemetry_status(self, last_seen_at, now):
        if not isinstance(last_seen_at, (int, float)):
            return "disconnected"

        elapsed = now - last_seen_at
        if elapsed <= TELEMETRY_GREEN_SECONDS:
            return "normal"
        if elapsed <= TELEMETRY_YELLOW_SECONDS:
            return "weak"
        if elapsed <= TELEMETRY_RED_SECONDS:
            return "poor"
        if elapsed <= TELEMETRY_DISCONNECTED_SECONDS:
            return "poor"
        return "disconnected"

    def _get_flight_control_status(self, last_seen_at, now):
        if not isinstance(last_seen_at, (int, float)):
            return "dead"

        elapsed = now - last_seen_at
        if elapsed <= TELEMETRY_GREEN_SECONDS:
            return "normal"
        if elapsed <= TELEMETRY_YELLOW_SECONDS:
            return "fault"
        return "dead"

    # -------------------------------------------------------------- drone data
    def _register_drone(self, drone_id):
        if drone_id not in self.known_drones:
            self.known_drones.add(drone_id)
            if drone_id not in self.group_assignments[0]:
                self.group_assignments[0].append(drone_id)
                self.group_assignments[0] = sorted(set(self.group_assignments[0]))
            if self.group_leaders[0] is None:
                self.group_leaders[0] = drone_id
            self.assignment_page.update_drone_roster([drone_id])
            leader_flag = self.group_leaders[0] == drone_id
            self._send_config_update(drone_id, 0, leader_flag)

    def clear_tracks_history(self):
        with self.state_lock:
            self.tracks = {key: [] for key in self.tracks.keys()}

    def clear_goto_targets(self):
        with self.state_lock:
            for state in self.drone_state.values():
                state.pop("goto_lat", None)
                state.pop("goto_lon", None)
        self.monitor_page.clear_goto_overlays()

    def get_home_location(self):
        return self.home_lat, self.home_lon

    # --------------------------------------------------------- command helpers

    def _resolve_command_targets(self):
        group_id = self.monitor_page.get_selected_group()
        if group_id is None:
            self._append_log("[提示] 请先选择目标编队。")
            return None

        members = self.group_assignments.get(group_id, [])
        if not members:
            self._append_log(f"[提示] {MonitorPage.GROUP_LABELS[group_id]} 暂无无人机。")
            return None

        targets = sorted(set(members))
        leader_id = self.group_leaders.get(group_id)
        if leader_id in targets:
            targets = [leader_id] + [drone_id for drone_id in targets if drone_id != leader_id]
        return group_id, targets

    def handle_basic_command(self, command):
        resolved = self._resolve_command_targets()
        if not resolved:
            return
        group_id, targets = resolved
        payload = {"cmd": command, "targets": targets, "group": group_id}
        self._send_command(payload)

    def start_random_walk(self, targets, description=None):
        normalized_targets = []
        for drone_id in targets:
            try:
                normalized_targets.append(int(drone_id))
            except (TypeError, ValueError):
                continue

        normalized_targets = sorted(set(normalized_targets))
        if not normalized_targets:
            self._append_log("[Workbench] 没有可执行随机游走的无人机。")
            return

        if not self._send_command({"cmd": "test_dubins", "targets": normalized_targets}):
            return

        if description:
            self._append_log(f"[Workbench] 随机游走已启动 -> {description}")
        elif len(normalized_targets) == 1:
            self._append_log(f"[Workbench] 随机游走已启动 -> 无人机 #{normalized_targets[0]}")
        else:
            members = ", ".join(f"#{drone_id}" for drone_id in normalized_targets)
            self._append_log(f"[Workbench] 随机游走已启动 -> 无人机 {members}")

    def start_random_walk_for_group(self, group_id):
        members = sorted(set(self.group_assignments.get(group_id, [])))
        if not members:
            self._append_log(f"[Workbench] 编队{group_id} 当前没有可执行随机游走的无人机。")
            return
        self.start_random_walk(members, description=f"编队{group_id} 全部无人机 {members}")

    def handle_formation_command(self):
        resolved = self._resolve_command_targets()
        if not resolved:
            return
        group_id, targets = resolved
        try:
            form_type_name = self.monitor_page.form_type_var.get()
            form_type = int(self.formation_types[form_type_name])
            spacing = float(self.monitor_page.dist_var.get())
        except Exception:
            messagebox.showwarning("参数错误", "请正确选择编队类型并输入数字距离。")
            return
        config_payload = {
            "cmd": "formation_set",
            "group": group_id,
            "targets": targets,
            "form_type": form_type,
            "spacing": spacing,
        }
        start_payload = {
            "cmd": "formation_start",
            "group": group_id,
            "targets": targets,
            "form_type": form_type,
            "spacing": spacing,
        }
        self._send_command(config_payload)
        self._send_command(start_payload)
        self.active_formations.add(group_id)
        self._append_log(
            f"[编队] 已向 {MonitorPage.GROUP_LABELS[group_id]} 下发：类型 {form_type}，间距 {spacing:.1f} 米，成员 {targets}"
        )

    def handle_abort_command(self):
        self.command_blocked = True
        self.active_formations.clear()
        payload = {"cmd": "abort"}
        try:
            self.bridge.send(payload)
        except Exception as exc:
            messagebox.showerror("网络错误", f"急停发送失败：{exc}")
        self.clear_goto_targets()
        self._append_log("[急停] 已向所有无人机发送中止指令，后续指令已阻止。")

    def resume_commands(self):
        self.command_blocked = False
        self._append_log("[急停] 指令阻止已解除，可继续发令。")

    def _send_command(self, payload):
        if self.command_blocked and payload.get("cmd") != "abort":
            self._append_log("[急停] 指令被阻止（当前处于急停状态）。")
            return False
        try:
            self.bridge.send(payload)
        except Exception as exc:
            messagebox.showerror("网络错误", f"发送失败：{exc}")
            return False
        return True

    def _send_config_update(self, drone_id, group_id, leader):
        payload = {
            "cmd": "config_update",
            "id": drone_id,
            "group": group_id,
            "is_leader": 1 if leader else 0,
        }
        try:
            form_type_name = self.monitor_page.form_type_var.get()
            payload["form_type"] = int(self.formation_types[form_type_name])
            payload["spacing"] = float(self.monitor_page.dist_var.get())
        except Exception:
            pass
        return self._send_command(payload)

    def send_mission_command(self):
        if not self._send_command({"cmd": "mission"}):
            return
        self._append_log("[Workbench] 已向所有无人机发送 mission 指令。")

    def send_workbench_command(self, command):
        if not self._send_command({"cmd": command}):
            return
        self._append_log(f"[Workbench] 已向所有无人机发送 {command} 指令。")

    def add_workbench_obstacles_to_monitor(self):
        self.monitor_page.add_obstacle_circles(WORKBENCH_OBSTACLES)
        self._append_log("[Workbench] 已在 Monitor 地图添加 3 个障碍圆。")

    def on_assignments_uploaded(self, members, leaders):
        for group_id in range(4):
            group_members = list(sorted(set(members.get(group_id, []))))
            self.group_assignments[group_id] = group_members
            leader_id = leaders.get(group_id)
            if leader_id in group_members:
                self.group_leaders[group_id] = leader_id
            else:
                self.group_leaders[group_id] = group_members[0] if group_members else None

        self._append_log("[编队] 最新成员分布：")
        for group_id in range(4):
            members_line = ", ".join(str(m) for m in self.group_assignments[group_id]) or "无"
            leader_id = self.group_leaders[group_id]
            leader_line = f"队长 #{leader_id}" if leader_id is not None else "队长未设定"
            self._append_log(
                f"  - {MonitorPage.GROUP_LABELS[group_id]}: {members_line} ({leader_line})"
            )

        self.assignment_page.load_assignments(self.group_assignments, self.group_leaders)

        for group_id, members_list in self.group_assignments.items():
            leader_id = self.group_leaders[group_id]
            for drone_id in members_list:
                self._send_config_update(drone_id, group_id, drone_id == leader_id)

    def on_close(self):
        try:
            self.bridge.stop()
        except Exception:
            pass
        self.destroy()


def main():
    app = GroundControlApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
