# RK3588 RS-422 双向测试

根据 `MCS_RK3588-V1.0-Ubuntu-用户手册-20260204.pdf`：

- 普通 J1 RS-422 口：`/dev/ttyS0`
- J1 调试口：`/dev/ttyFIQ0`
- 手册测试程序使用波特率：`115200`

本测试使用 `115200 8N1`、无软件流控、无硬件流控。两端每秒发送一条带序号、时间戳和 CRC32 的 ASCII 数据帧，同时监听和校验对端数据。

## Windows 端

依赖：`pyserial`。当前电脑已安装。

```powershell
python .\pc_rs422_test.py --port COM5 --duration 15
```

## RK3588 Ubuntu 端

程序只使用 Python 3 标准库，不需要安装 `pyserial`：

```bash
python3 ~/board_rs422_test.py --port /dev/ttyS0 --duration 15
```

## 判定

- `RX-OK`：收到对端且 CRC 正确。
- `RX-SELF`：收到本机发出的帧，只说明存在回环，不算双端通信成功。
- `RX-BAD`：收到数据但格式或 CRC 错误，常见于波特率、极性或信号质量问题。
- `RESULT PASS`：至少收到一条对端有效帧。
- `RESULT FAIL`：没有收到对端有效帧。

RS-422 四线全双工接线应交叉连接：板卡 `TX+/-` 接转接器 `RX+/-`，板卡 `RX+/-` 接转接器 `TX+/-`，并按设备要求连接参考地。不同厂家的 `A/B`、`+/-` 命名可能相反，应以各自说明书为准。

## 2026-07-31 实测记录

- Windows：`COM5` 发送 8 帧，接收 0 帧。
- RK3588：`/dev/ttyS0` 发送 8 帧，接收 0 帧。
- Windows 程序的软件回环自检通过，正确识别 6 条本机回环帧。
- Ubuntu 程序的伪终端自检通过，正确接收并校验 4 条对端帧。

程序与数据校验逻辑正常，但当前实际 RS-422 物理链路没有数据到达任意一侧。优先检查是否使用四线全双工 RS-422 转接器、TX/RX 两对差分线是否交叉连接，以及每一对的 `+/-` 极性。

## P2 转接板端口映射

转接板没有标记 `J1` 时，通常使用 P2 的 `RS422_1` 至 `RS422_9`：

| 转接板通道 | Ubuntu 设备 |
| --- | --- |
| RS422_1 | `/dev/ttyACM4` |
| RS422_2 | `/dev/ttyACM5` |
| RS422_3 | `/dev/ttyACM6` |
| RS422_4 | `/dev/ttyACM7` |
| RS422_5 | `/dev/ttyACM0` |
| RS422_6 | `/dev/ttyACM1` |
| RS422_7 | `/dev/ttyACM2` |
| RS422_8 | `/dev/ttyACM3` |
| RS422_9 | `/dev/ttyS3` |

只监听、不向该通道发送数据：

```bash
python3 ~/board_rs422_test.py --port /dev/ttyACM4 --duration 15 --listen-only
```

### P2 被动扫描结果

2026-07-31 使用 PC `COM5` 连续发送 210 帧，板卡依次监听 P2 九路：

- `/dev/ttyACM0` 至 `/dev/ttyACM7`：每路 `rx_bytes=0`
- `/dev/ttyS3`：`rx_bytes=0`
- PC `COM5`：`rx_bytes=0`

因此没有发现乱码或 CRC 错误，而是没有任何原始串口字节到达。下一步应先对 USB-RS422 转接器做本地硬件回环，再检查转接板通道标记和四线交叉接法。

USB-RS422 转接器硬件回环：断开板卡，短接转接器 `TX+` 到 `RX+`、`TX-` 到 `RX-`，然后运行：

```powershell
python .\pc_rs422_test.py --port COM5 --duration 10 --loopback
```
