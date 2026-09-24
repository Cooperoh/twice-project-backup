# 独立 Web 地面站

新增 **04 Earth** 数字地球实验页：手动启动/关闭，切页保持运行，卫星影像显示飞机及轨迹。
未启动时不加载地球引擎。使用、性能验证和恢复方法见 [EARTH.md](EARTH.md)。

在线地形需在 Earth 右上角 **Token 设置** 中导入自己的 Cesium ion Token（可粘贴或选择文本文件）。
Windows 会将其加密保存在当前用户的 LocalAppData，关闭进程、重启电脑、移动地面站目录后自动读取。
不导入也能使用普通数字地球。Token 不再放入 `.env.local` 或前端构建产物；分发软件时不要附带个人 Token 导入文件。

这个目录包含一套与根目录 Tkinter 程序完全独立的 Web 地面站。它不导入、不修改旧程序；Python 后端继续负责 UDP/JSON 收发与权威状态，浏览器负责 Monitor、Formation 和 Workbench 的显示与交互。

本文档只说明当前版本如何安装、运行、配置和排查。每次具体修改了哪些文件、行为和测试，统一按
日期记录在 [`UPDATE_LOG.md`](UPDATE_LOG.md)，不再把版本流水账混入 README。

## 运行环境

- Python 3.11 或更高版本（当前已在 Python 3.13 验证）
- 首次安装依赖时需要网络
- 正常运行不需要 Node.js；`frontend/dist` 已包含构建后的页面

建议使用虚拟环境，避免影响电脑上的其他 Python 项目。

### Windows PowerShell

```powershell
python -m venv .\web_app\.venv
.\web_app\.venv\Scripts\Activate.ps1
python -m pip install -r .\web_app\requirements.txt
python .\web_app\run.py
```

### macOS / Linux

```bash
python3 -m venv ./web_app/.venv
source ./web_app/.venv/bin/activate
python -m pip install -r ./web_app/requirements.txt
python ./web_app/run.py
```

程序默认启动 `http://127.0.0.1:8765/` 并打开浏览器。可用参数：

```text
python web_app/run.py --no-browser
python web_app/run.py --config path/to/config.toml
python web_app/run.py --test-mode --no-browser
```

`--test-mode` 不绑定真实 UDP 端口，仅用于界面/API 检查，不能控制无人机。

同一份 `web_app` 只允许一个后端实例。再次执行 `run.py` 时，启动器会打印现有 PID 和地址，
并在未指定 `--no-browser` 时直接打开现有页面；不会创建第二组 UDP 线程或审计文件。关闭网页
标签页不影响后端、UDP 通信或审计记录。

关闭浏览器标签页不会自动停止 Python 地面站。需要彻底停止时，在 PowerShell 运行
`powershell -ExecutionPolicy Bypass -File .\web_app\stop_web_app.ps1`。该脚本只关闭本项目的
`run.py` 后端和 Vite 开发服务，不会关闭或误杀共用的 Chrome/Edge/Firefox 进程。

启动器会检查 `frontend/dist/index.html` 引用的本地资源是否完整；本地保留
`frontend/src`、构建配置、`package.json` 或锁文件时，还会拒绝启动比这些输入更旧的
`dist`。出现构建过期提示后，请进入 `web_app/frontend` 运行 `pnpm run build`，
重新启动 Python 进程，并关闭旧标签页或执行浏览器硬刷新。仅部署 `dist`、不附带前端
源码时只检查入口文件及其资源完整性。

## 端口冲突

旧 Tkinter 程序与 Web 版本都需要监听 UDP 56999，因此不能同时运行。若提示 56999 绑定失败，请先关闭旧地面站或占用该端口的其他程序。

出站命令按地面站现有无人机列表发送，不再固定向 24 个端口逐个发送。收到遥测或心跳并加入列表后，
只要无人机仍在列表里，就继续向它发送，即使界面显示“断联”。断联阈值只影响状态显示，不影响发送资格。
从未进入列表的无人机不发送；单纯在配置中填写地址或在编队中填写 ID，不会让它自动进入无人机列表。

编队命令只发给该编队中也在无人机列表里的成员；Workbench 指定 `targets` 时同样取这些 ID 与列表的交集；
未指定目标的全局命令（包括 `abort` 急停）发给列表中的全部无人机。协议里的编队成员和队长顺序保持原值，
只筛选网络目的地址，不自动重排编队。单机 `config_update` 也按列表判断，断联后仍然发送。
发送范围内没有列表中的无人机时明确报错，不会回退到全部端口；急停仍会先锁住本地普通指令。
接口返回的“本机已尝试发送”仅表示本机 UDP 调用结果，不代表无人机已经收到或执行。

## 配置

所有运行参数位于 `web_app/config.toml`：

- `[server]`：本机 Web 地址、端口、自动打开浏览器和 100ms 接收批处理周期
- `[udp]`：遥测监听地址和 `targets` 中逐机配置的 ID、IP、控制监听端口
- `[map]`：Home 坐标、缩放级别、在线瓦片地址与署名
- `[telemetry]`：遥测和飞控状态阈值
- `[formation]`：默认编队类型与间距
- `[limits]`：每机浏览器轨迹点数、界面日志数、每客户端 WebSocket 批次数和发送请求队列上限
- `[[obstacles]]`：Workbench 预设障碍圆

HTTP 默认只监听 `127.0.0.1`，没有局域网多用户或公网控制功能。

`[udp] targets` 每行对应一架无人机，例如：

```toml
[udp]
bind_host = "0.0.0.0"
bind_port = 56999
targets = [
  { id = 1, host = "10.144.1.100", port = 57001 },
  { id = 2, host = "10.144.1.100", port = 57002 },
]
```

主配置已经列出 ID 1～24，各自暂用 `10.144.1.100` 和原来的 `57001～57024` 对应端口。
有真实 IP 后只修改该 ID 所在行的 `host`，控制端口变化时再改 `port`。目的端口是无人机接收控制指令的端口，
不从遥测数据报的来源端口推断。不同 IP 可以使用相同控制端口；同一 IP 上的仿真无人机应分别使用不同端口。
ID 决定对应关系，与行顺序无关；可以只配置需要使用的 ID，不要求连续。重复 ID、重复 IP/端口组合或无效地址会在启动时报错。
收到未配置地址的无人机遥测时仍可显示，但向它发送会提示补充 `udp.targets`，不会自动猜测地址。
旧的 `target_host` / `target_ports` 配置需要改成上述格式，否则启动会提示迁移。
配置只在启动时读取，修改后重启 Python 后端生效，无需重新构建前端。

UDP 接收和发送分别运行在独立线程，各自长期持有一个 socket，不占用 FastAPI/WebSocket
事件循环。无人机上行只接受 ID 1～24 的 `telemetry` JSON 对象和不要求 ID 的
`{"type":"log","text":"..."}`；`telemetry_batch`、`trajectory` 和未知上行类型不会被兼容展开。
接收线程把遥测写入“按 ID 覆盖”的最新值表（最多 24 项），把待显示日志写入最多 2000 项的
有界缓冲。后端每 100ms 原子取走当前内容，同一批每机只应用最后一条遥测，并最多发布一个
`realtime_batch`。批次包含 `drones`、`track_updates` 和 `logs`。

`telemetry` 是部分更新协议：只有新飞控帧才携带 `lat/lon/alt/speed/heading/phase`，中间心跳通常
只有 `id/tag`。后端会保留上一份核心飞行字段，只覆盖当前包明确携带的字段，因此心跳不会再让
速度、航向或图标姿态归零。为兼容未来协议，每机还允许保留最近 16 个扩展字段；更老的扩展字段
会被淘汰，所以字段名不断变化也不会造成状态无限增长。

后端只保留每机最新状态、轨迹 `epoch/seq`、编队状态、蓝色参考航线和通信健康状态，不保存
实际飞行轨迹或 Event Log 历史。`/api/bootstrap` 的 `tracks`、`track_meta` 和 `logs` 因而始终为空。
浏览器收到 WebSocket 消息后立即更新遥测表、标记、日志和本批轨迹，不再使用 200ms Monitor
刷新定时器。实际轨迹位于 Vue 深层响应式系统之外：每机一个固定 10000 点 TypedArray 环形缓冲，
由 WebGL2 增量绘制；Goto、障碍物、无人机标记和蓝色编队参考轨迹仍是独立 Leaflet 图层。
轨迹序号或 WebSocket 批次有缺口时，新点会开始新线段，禁止跨缺口连接；较新的 epoch 会清空
旧实际轨迹。页内切换和 WebSocket 重连保留轨迹，浏览器硬刷新从空轨迹、空日志开始。

Event Log 在每个浏览器标签页严格保留最近 2000 条，并通过虚拟列表只渲染可见行。“导出 TXT”
只导出该标签页当前可见历史。每个 WebSocket 客户端最多积压 8 个批次；慢客户端队列满时淘汰
最旧批次并计数，不会反压 UDP。页面发令、急停、编队和 Workbench HTTP 请求不经过接收缓冲；
发送线程使用最多 64 项的瞬时队列，请求完成后释放。发送超时表示“本地发送结果未知”，飞行
指令不会自动重发。

## 永久收发审计

每次正常启动都会在 `web_app/audit` 创建新的
`received-<UTC启动时间>.jsonl` 和 `sent-<UTC启动时间>.jsonl`，已有文件不会被覆盖或自动删除。
`run.py` 启动时也会把完整目录打印为 `[GCS] audit directory: ...`。

格式采用 UTF-8 JSONL（一行一个独立 JSON 对象），无需数据库且跨 Windows、Linux、macOS；进程
意外结束时，前面的完整行仍可直接读取。接收文件逐数据报记录 UTC 毫秒时间戳、来源、字节数、
解析状态和未经重排的 `raw` UTF-8 文本；非法 UTF-8 或超长数据使用 `raw_base64` 保留原始字节。
发送文件按每个实际目标地址记录无人机 ID、IP、端口、交给 `sendto()` 的 `raw` 文本、字节数、返回值和错误；
例如列表中只有 3 架无人机时，一条全局命令产生 3 行发送记录，包括其中显示断联的无人机。未进入列表的无人机不会产生实际发送记录。

UDP 线程只把日志行非阻塞地放入有界队列，两个后台审计线程最多每 0.5 秒或每 256 行合并写盘，
不会让收包、发令和急停等待磁盘。正常 Ctrl+C 或 `stop_web_app.ps1` 会先排空队列并关闭文件；
直接强制杀进程时，最多可能丢失尚未刷新的一小段尾部记录。审计写入失败或队列极端过载不会让
通信线程退出，但会使 `/api/health` 降级并显示丢弃数。

`/api/health` 的 `receive_buffer`（以及兼容旧监控的 `receive_queue` 别名）提供遥测/日志深度、
最高水位、遥测覆盖数、日志淘汰数和批处理耗时；`udp_workers` 提供收发线程、发送队列和两份审计
文件状态；`websocket` 提供客户端队列深度与丢批数。

## 前端开发

只有修改 Vue 前端时才需要 Node.js 与 pnpm：

```text
cd web_app/frontend
pnpm install
pnpm run test
pnpm run build
pnpm exec playwright install chromium firefox webkit
pnpm run test:e2e
```

开发服务器默认运行在 `127.0.0.1:5173`，并把 `/api` 和 WebSocket 代理到 Python 后端的 8765 端口。`pnpm run build` 会更新 `web_app/frontend/dist`。更新生产构建后必须重启正在运行的 Python 进程，并关闭或硬刷新此前打开的页面。

## 测试

```text
python -m pytest -q web_app/tests
```

测试使用假发送器、测试模式或回环临时端口，不会向真实的 57001～57024 下发飞行指令。`pnpm run test:e2e` 会自动启动 8766 端口的安全测试服务，并只向 `127.0.0.1:57901～57924` 发送测试包。隔离测试会从 Web 目录之外启动应用，并确认后端不会导入根目录 Tkinter 模块；兄弟程序文件的内容和变化不再影响 Web 测试。
