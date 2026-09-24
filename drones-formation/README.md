# drones-formation

`drones-formation` 是多无人机编队控制程序。每架无人机运行一个独立实例，接收地面站命令，根据编组和目标列表确定领机或从机角色，并通过目标点控制帧驱动飞控。

## 通信流程

- 领机读取本机飞控状态，向飞控发送目标点，同时仅向当前 `targets` 中除自身外的编队成员发送位置、航向、速度和编队参数；空成员列表不发送。
- 从机接收领机广播，按 `leader_id` 和 `targets` 判断消息是否属于本机，解算编队位置后向飞控发送 `goto_location()`。
- 地面站遥测统一由 `behavior/telemetry.py` 发送，每轮最多一包（周期由 `CHECK_INT` 控制，目前为 0.5 秒）。领机、从机和启动入口不额外发送遥测。
- 新飞控状态只转发一次；没有新状态时发送心跳。两种包都携带最近已发送的 goto 经纬度、高度和速度，飞控状态等待超时或读取中断也不阻断目标点回传。goto 来自本机发送缓存，不代表飞控确认；尚未下发目标时不携带 goto 字段。
- 当前仿真多机通信使用 `FGCBridge`，直接通过 IP 和端口发送 UDP JSON 消息。
- 实飞数据链业务帧、节点寻址和云台协议尚未确定，目前只保留接口，不启动对应通信线程。

## 客户端目录

```text
client/
├─ autopilot/
│  ├─ autopilot_client.py
│  ├─ frame_common.py
│  ├─ receive_frame.py
│  ├─ send_frame.py
│  └─ stream_reader.py
├─ datalink/
│  └─ datalink_client.py
└─ gimbal/
   └─ gimbal_client.py
```

- `autopilot`：飞控串口/UDP收发、控制帧封装、遥测帧解析和最新状态缓存。
- `datalink`：预留实飞数据链 Bridge 接口，等待实际业务帧协议。
- `gimbal`：预留云台状态接收和控制接口，等待实际云台协议。

## 运行配置

在 `runtime.py` 中选择运行方式：

```python
RUN_MODE = "simulation"
FC_TRANSPORT = "udp"  # 也可以设置为 "serial"
```

`RUN_MODE` 和 `FC_TRANSPORT` 相互独立。逐机编号、命令端口、飞控串口参数和飞控 UDP 参数保存在 `config.py`。

## 启动

启动单架无人机实例，编号范围为 `1~24`：

```powershell
python .\drone-exec\run.py 1
```

也可以启动图形化多机启动器：

```powershell
python .\drone_launcher.py
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖编队成员定向发送、成员切换，以及目标点从飞控发送缓存经统一遥测到达本地 UDP 接收端的链路。

详细修改记录见 `UPDATE_LOG.md`。
