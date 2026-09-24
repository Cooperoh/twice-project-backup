
# dronesBridge.py (typed-queue version)
#!/usr/bin/env python3
import socket, json, threading, asyncio, builtins, queue

from utils import normalize_targets

class FGCBridge:
    def __init__(
        self,
        bind_ip="0.0.0.0",
        bind_port=0,
        gui_host="127.0.0.1",
        gui_port=56999,
        peers=None,
        name="drone",
    ):
        """初始化 UDP socket、各类消息队列和线程锁。"""
        self.gui_addr = (gui_host, gui_port)
        self.bind_ip, self.bind_port = bind_ip, bind_port
        self.name = name

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.bind_ip, self.bind_port))
        self.sock.setblocking(True)

        self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tx_sock.bind(("0.0.0.0", 0))

        self._q_cmd = queue.Queue()
        self._q_misc = queue.Queue()

        # leader broadcast：每个主机只保留最新一条，按 leader_id 分槽
        self._peer_lock = threading.Lock()
        self._peer_states = {}               # {leader_id: msg_dict}
        self._peer_update_q = queue.Queue(maxsize=1)

        # drone broadcast：每架无人机只保留最新状态
        self._broadcast_lock = threading.Lock()
        self._broadcast_states = {}          # {drone_id: msg_dict}
        self._broadcast_update_q = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._rx_th = None

        self._orig_print = builtins.print
        self._print_patched = False

        # 保存其他无人机的 ID -> 地址；每次只向消息 targets 内的成员发送。
        # 从机仍检查 leader_id/targets，防止切换期间消费旧编队消息。
        self.peers = dict(peers or {})

    # --- rx thread ---
    def _rx_loop(self):
        """后台接收线程：持续读取 UDP 包，按消息类型分发到对应队列。"""
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65536)
            except ConnectionResetError:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self._orig_print(f"[{self.name}] UDP command receive stopped: {exc}")
                break
            try:
                msg = json.loads(data.decode("utf-8","ignore"))
                if isinstance(msg, dict):
                    msg["_from"] = f"{addr[0]}:{addr[1]}"
                    if "cmd" in msg:
                        self._q_cmd.put(msg)
                    elif msg.get("type") == "lead_broadcast":
                        leader_id = msg.get("leader_id")
                        if leader_id is not None:
                            with self._peer_lock:
                                self._peer_states[leader_id] = msg
                            try:
                                self._peer_update_q.put_nowait(True)
                            except queue.Full:
                                pass
                    elif msg.get("type") == "drone_broadcast":
                        drone_id = msg.get("id")
                        if drone_id is not None:
                            with self._broadcast_lock:
                                self._broadcast_states[drone_id] = msg
                            try:
                                self._broadcast_update_q.put_nowait(True)
                            except queue.Full:
                                pass
                    else:
                        self._q_misc.put(msg)
            except Exception:
                continue

    async def start(self):
        """启动后台接收线程（已在运行则跳过）。"""
        if self._rx_th and self._rx_th.is_alive():
            return
        self._stop.clear()
        self._rx_th = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_th.start()

    async def _await_queue(self, q):
        """将阻塞的 queue.get 包装为 async，避免阻塞事件循环。"""
        while not self._stop.is_set():
            try:
                return await asyncio.to_thread(q.get, True, 0.1)
            except queue.Empty:
                continue
        raise asyncio.CancelledError

    async def next_cmd(self):
        """阻塞等待并返回下一条地面站指令消息。"""
        return await self._await_queue(self._q_cmd)

    async def next_peer(self):
        """阻塞等待主机广播更新，返回所有主机的最新状态快照 {leader_id: msg}。"""
        await self._await_queue(self._peer_update_q)
        with self._peer_lock:
            return dict(self._peer_states)

    async def next_misc(self):
        """阻塞等待并返回下一条杂类消息（非指令、非广播）。"""
        return await self._await_queue(self._q_misc)

    async def next_broadcast(self):
        """阻塞等待任意无人机状态更新，返回全体无人机最新状态快照 {drone_id: msg}。"""
        await self._await_queue(self._broadcast_update_q)
        with self._broadcast_lock:
            return dict(self._broadcast_states)

    # --- ---- ------ ---

    def get_peer_states(self):
        """非阻塞，直接读取当前所有已知无人机状态。"""
        with self._broadcast_lock:
            return dict(self._broadcast_states)

    def get_peer_state(self, drone_id):
        """非阻塞，读取指定无人机的最新状态，未收到过则返回 None。"""
        with self._broadcast_lock:
            return self._broadcast_states.get(drone_id)

    # --- send helpers ---
    def _sendto(self, addr, payload):
        """向指定地址发送 JSON 数据包，发送失败静默忽略。"""
        try:
            self.tx_sock.sendto(json.dumps(payload, ensure_ascii=False).encode("utf-8"), addr)
        except Exception:
            pass

    def send_gui(self, payload):
        """向地面站 GUI 发送任意消息。"""
        self._sendto(self.gui_addr, payload)

    def send_telemetry(self, **fields):
        """向 GUI 发送遥测数据。"""
        self.send_gui({"type":"telemetry", **fields})

    def send_log(self, text):
        """向 GUI 发送日志文本。"""
        self.send_gui({"type":"log", "text": str(text)})

    def send_to_peers(self, payload):
        """按本次消息的 targets 发送；空目标不发送，不回退为全广播。"""
        for drone_id in normalize_targets(payload.get("targets")):
            addr = self.peers.get(drone_id)
            if addr is not None:
                self._sendto(addr, payload)

    def patch_print(self):
        """劫持内置 print，使其在打印到终端的同时也转发到 GUI 日志。"""
        if self._print_patched: return
        def _patched_print(*args, **kwargs):
            try:
                self.send_log(" ".join(str(a) for a in args))
            except Exception:
                pass
            return self._orig_print(*args, **kwargs)
        builtins.print = _patched_print
        self._print_patched = True

    def unpatch_print(self):
        if self._print_patched:
            builtins.print = self._orig_print
            self._print_patched = False

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass
        try:
            self.tx_sock.close()
        except Exception:
            pass
