

# groundMain 无人机回传消息格式


`groundMain.py` 通过 `UDPBridge` 接收无人机回传信息，监听地址为：

```text
0.0.0.0:56999
```

回传数据需要是 UTF-8 编码的 JSON。`groundMain.py` 主要处理 `telemetry`、`telemetry_batch`、`log`、`trajectory` 四类消息。




## 单条遥测 telemetry

```json
{
  "type": "telemetry",
  "id": 1,
  "lat": 38.3094,
  "lon": 117.68,
  "speed": 12.3,
  "heading": 87,
  "err_s": 0.5,
  "err_d": -1.2,
  "tag": "DRONE1",
  "goto_lat": 38.3101,
  "goto_lon": 117.6812
}
```

字段说明：

| string        | 是否必须   | 说明 |
| ---           | ---       | --- |
| `type`        | 是        | 固定为 `"telemetry"` |
| `id`          | 是        | 无人机 ID，可以是整数，也可以是纯数字字符串 |
| `lat`         | 否        | 当前纬度，地图轨迹依赖该字段 |
| `lon`         | 否        | 当前经度，地图轨迹依赖该字段 |
| `speed`       | 否        | 当前速度，显示在遥测表格中 |
| `heading`     | 否        | 当前航向角，显示在表格中，并用于地图无人机图标朝向 |
| `err_s`       | 否        | 编队纵向误差 |
| `err_d`       | 否        | 编队横向误差 |
| `tag`         | 否        | 无人机显示名称；未提供时界面使用 `DRONE{id}` |
| `goto_lat`    | 否        | 期望点纬度，需要和 `goto_lon` 成对出现 |
| `goto_lon`    | 否        | 期望点经度，需要和 `goto_lat` 成对出现 |

注意：

- `id` 缺失或无法转换为整数时，该条消息会被忽略。
- `lat`、`lon`、`speed`、`heading` 建议直接发送 JSON 数字，不要发送字符串。
- `goto_lat` 和 `goto_lon` 只要任意一个字段出现在消息中，程序就会尝试同时读取两者；如果其中一个为空或无法转成数字，会清除该无人机的期望点显示。
- `lat` 和 `lon` 同时为数字时，程序会更新无人机位置并追加轨迹点。




## 批量遥测 telemetry_batch

批量包由 `groundBridge.py` 拆包，`list` 中的每个对象会被当作单独消息送给 `groundMain.py` 处理。

```json
{
  "type": "telemetry_batch",
  "list": [
    {
      "type": "telemetry",
      "id": 1,
      "lat": 38.3094,
      "lon": 117.68,
      "speed": 12.3,
      "heading": 87,
      "tag": "DRONE1"
    },
    {
      "type": "telemetry",
      "id": 2,
      "lat": 38.3098,
      "lon": 117.681,
      "speed": 11.8,
      "heading": 91,
      "err_s": 0.2,
      "err_d": -0.6,
      "tag": "DRONE2"
    }
  ]
}
```




## 日志 log

用于把无人机端或控制端日志显示到 Monitor 页面的事件日志窗口。

```json
{
  "type": "log",
  "text": "无人机1已起飞"
}
```

字段说明：

| string    | 是否必须   | 说明 |
| ---       | ---       | --- |
| `type`    | 是        | 固定为 `"log"` |
| `text`    | 是        | 要显示的日志文本 |




## 轨迹 trajectory

用于在地图上显示指定无人机的规划轨迹，例如 Dubins 路径。

```json
{
  "type": "trajectory",
  "id": 1,
  "points": [
    { "lat": 38.3094, "lon": 117.68 },
    { "lat": 38.31, "lon": 117.681 }
  ]
}
```

字段说明：

| string    | 是否必须   | 说明 |
| ---       | ---       | --- |
| `type`    | 是        | 固定为 `"trajectory"` |
| `id`      | 是        | 无人机 ID，可以是整数，也可以是纯数字字符串 |
| `points`  | 是        | 路径点列表，每个点包含 `lat` 和 `lon` |

`points` 中无法转换为数字的点会被跳过。有效点少于 2 个时，地图不会显示轨迹线。






# groundMain 地面站下发指令格式


地面站通过 `UDPBridge.send()` 下发控制指令。所有指令同样是 UTF-8 编码的 JSON，通过 UDP 发送。

当前 `groundMain.py` 中配置的发送目标为：

```text
10.144.1.100:57001
10.144.1.100:57002
10.144.1.100:57003
10.144.1.100:57004
10.144.1.100:57005
10.144.1.100:57006
10.144.1.100:57007
10.144.1.100:57008
10.144.1.100:57009
10.144.1.100:57010
10.144.1.100:57011
10.144.1.100:57012
10.144.1.100:57013
10.144.1.100:57014
10.144.1.100:57015
10.144.1.100:57016
10.144.1.100:57017
10.144.1.100:57018
10.144.1.100:57019
10.144.1.100:57020
10.144.1.100:57021
10.144.1.100:57022
10.144.1.100:57023
10.144.1.100:57024
```

每次调用发送时，地面站会把同一个 JSON 包依次发到上面所有地址。




## 基础控制指令

Monitor 页面的“起飞 / 返回 / 降落”按钮会发送以下格式：

```json
{
  "cmd": "takeoff",
  "targets": [1, 2],
  "group": 1
}
```

`cmd` 可能取值：

| `cmd`         | 来源               | 说明 |
| ---           | ---               | --- |
| `"takeoff"`   | monitor起飞按钮    | 起飞 |
| `"rtl"`       | monitor返回按钮    | Return To Launch / 返航 |
| `"land"`      | monitor降落按钮    | 降落 |

字段说明：

| string        | 是否必须           | 说明 |
| ---           | ---               | --- |
| `cmd`         | 是                | 指令名称 |
| `targets`     | 是                | 目标无人机 ID 列表，来自当前选中的编队 |
| `group`       | 是                | 当前选中的编队 ID |

发送这些基础指令前，界面必须先选中目标编队；如果编队内没有无人机，则不会发送。




## 急停 abort

Monitor 页面的“急停”按钮会发送：

```json
{
  "cmd": "abort"
}
```

急停指令没有 `targets` 和 `group`，表示发给所有无人机。发送急停后，地面站会进入“指令阻止”状态，后续非 `abort` 指令会被拦截；点击“恢复发令”只解除地面站本地阻止状态，不会向无人机发送 UDP 指令。




## 编队指令

Monitor 页面的“下发编队”按钮会连续发送两条指令：先 `formation_set`，再 `formation_start`。

注意：这里仅记录地面站当前实际发送的 UDP JSON。无人机侧收到后如何区分“设置”和“启动”、是否需要两条都发、是否允许只发其中一条，需要以无人机端命令处理代码为准；当前文档不假设无人机侧的具体响应逻辑。

```json
{
  "cmd": "formation_set",
  "group": 1,
  "targets": [1, 2, 3],
  "form_type": 1,
  "spacing": 10.0
}
```

```json
{
  "cmd": "formation_start",
  "group": 1,
  "targets": [1, 2, 3],
  "form_type": 1,
  "spacing": 10.0
}
```

字段说明：

| string        | 是否必须   | 说明 |
| ---           | ---       | --- |
| `cmd`         | 是        | 地面站当前会连续发送 `"formation_set"` 和 `"formation_start"` |
| `group`       | 是        | 当前选中的编队 ID |
| `targets`     | 是        | 当前编队中的无人机 ID 列表 |
| `form_type`   | 是        | 编队类型编号 |
| `spacing`     | 是        | 编队间距，单位米 |

当前编队类型映射：

| 界面选项       | `form_type` |
| ---           | --- |
| 三角队形       | `1` |
| 横向一线       | `2` |
| 纵向一线       | `3` |




## 编队成员配置 config_update

当地面站首次发现某架无人机，或者在 Formation 页面点击“发布编队调整”后，会向无人机发送配置更新：

```json
{
  "cmd": "config_update",
  "id": 1,
  "group": 1,
  "is_leader": 1
}
```

字段说明：

| string        | 是否必须   | 说明 |
| ---           | ---       | --- |
| `cmd`         | 是        | 固定为 `"config_update"` |
| `id`          | 是        | 要更新配置的无人机 ID |
| `group`       | 是        | 分配到的编队 ID |
| `is_leader`   | 是        | 是否为队长，`1` 表示队长，`0` 表示普通成员 |

注意：Formation 页面中显示的卡片文本是 `#{drone_id}`，实际下发的 `id` 也使用同一个无人机编号。




## Workbench 测试指令

Workbench 页会发送几类测试指令。

指定无人机或编队 0 全部无人机启动随机游走时，发送：

```json
{
  "cmd": "test_dubins",
  "targets": [1]
}
```

或：

```json
{
  "cmd": "test_dubins",
  "targets": [1, 2, 3]
}
```

Workbench 中“上传 Dubins Cmd”按钮会发送不带目标的测试指令：

```json
{
  "cmd": "test_dubins"
}
```

Workbench 中“上传 VO Cmd”按钮会发送：

```json
{
  "cmd": "test_vo"
}
```

Workbench 中“上传 Mission Cmd”按钮会发送：

```json
{
  "cmd": "mission"
}
```

这些不带 `targets` 的 Workbench 指令只说明地面站没有指定目标无人机；无人机侧如何响应需要查看无人机端命令处理代码。




## 本地界面操作但不下发 UDP 的功能

以下操作只影响地面站界面状态，不会向无人机发送 UDP 指令：

- Monitor 页“恢复发令”：解除地面站本地急停阻止状态。
- Monitor 页“清除期望点”：清除地面站本地 `goto_lat` / `goto_lon` 显示。
- Monitor 页“显示轨迹 / 隐藏轨迹 / 清空轨迹”：只影响地图轨迹显示。
- Workbench 页“添加障碍圆”：只在 Monitor 地图上显示本地障碍圆。
