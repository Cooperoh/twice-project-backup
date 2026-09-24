# 更新记录

## 修改日期：2026.9.8

1. 领机按每次消息的 targets 向本编队成员发送状态；地址目录保留无人机 ID，支持成员变化，空目标不回退为全广播。
2. 地面站遥测收敛到 behavior/telemetry.py 的单一发送调用，删除 leader、follower 和 runtime 的额外遥测发送。
3. 在等待飞控状态之后读取最近已下发目标，避免等待期间更新的 goto 延后一轮；无新状态、等待超时或读取中断时继续携带已有 goto。
4. 保留 formation_set/start 的现有语义及地面站按钮行为，本次仅核对地面站代码。
5. 增加本地 UDP 收包验证，覆盖组内发送、成员切换和 goto 经统一遥测回传；补充等待期间目标更新及读取故障回归测试。

## 修改日期：8.21 号

修改模块：runtime.py、config.py、client/autopilot、client/datalink、client/gimbal、tests

1. 在 runtime.py 中集中定义 RUN_MODE 和 FC_TRANSPORT，默认分别为 simulation 和 udp，运行模式与飞控通道可以独立选择。
2. 从 24 架无人机基础配置中删除重复的 fc_transport 字段，由 runtime.get_cfg() 在启动时统一注入当前飞控通道。
3. 保留原有串口和 UDP 飞控参数，支持仿真 UDP、串口台架测试以及后续实飞配置切换。
4. 将 FGCBridge 的创建集中到 runtime.py 的桥接工厂函数，当前继续使用 IP + port 的仿真直连方式，并为后续 DataLinkBridge 切换保留单一入口。
5. 明确当前尚未提供数据链业务帧、节点寻址和云台协议，因此本次不实现临时 JSON 协议，也不启动数据链或云台接收线程。
6. 新增 client 设备客户端目录，并按 autopilot、datalink、gimbal 三类设备分别管理通信代码。
7. 飞控主实现迁移为 client/autopilot/autopilot_client.py，外部仍通过 FlightController 类使用，不改变 goto_location()、get_state() 等行为接口。
8. 飞控协议文件 frame_common.py、send_frame.py、receive_frame.py、stream_reader.py 移到 client/autopilot 同级目录，删除原有嵌套 protocol 目录。
9. 数据链预留接口迁移为 client/datalink/datalink_client.py，保持未来与 FGCBridge 对齐的 start、next_cmd、next_peer、send_to_peers、send_gui、send_log 和 close 等调用面。
10. 云台预留接口迁移为 client/gimbal/gimbal_client.py，预留启动、停止、读取最新状态和发送控制指令的调用面。
11. 各设备包通过 __init__.py 对外导出主要类和飞控协议函数，运行时可以直接使用 from client.autopilot import FlightController 等简洁导入形式。
12. 删除根目录旧 flight_controller.py、data_link_bridge.py、gimbal_client.py 以及旧 flight_controller/protocol 空目录，避免重复文件名和通信代码散落。
13. 保持 cmd_process.py、behavior/leader.py、behavior/follower.py 的主从判断、编队解算、领机广播、从机过滤和飞控目标点下发逻辑不变。
14. 新增运行时飞控通道注入、配置去重和仿真 Bridge 工厂测试，单元测试由 38 项增加到 41 项并全部通过。
15. 完成 client 包编译检查、公开接口导入冒烟和旧导入路径扫描，均验证通过。

## 修改日期：6.10 号

修改模块：formation_constraints.py、tests/test_formation_constraints.py

1. 新增编队转弯约束计算工具，用于按表格输入计算三角编队在固定翼转弯过程中的可行性。
2. 支持单行计算和批量计算，输入中 spacing 和 d 都可以表示编队距离。
3. 计算结果保持为结构化数据，便于后续程序读取和二次处理。
4. 新增中文格式化输出函数，把计算结果转换成人可读的中文说明。
5. 新增直接运行入口，可通过 python .\formation_constraints.py 快速查看示例计算结果。
6. 新增编队约束计算回归测试，覆盖文档样例、默认容差、批量输入和非法输入等情况。
7. 验证中文输出和结构化 JSON 结果分离，避免把展示文本混入机器可读数据。

## 修改日期：6.8 号

修改模块：config.py、drone-exec/run.py、drone_launcher.py、tests/test_drone_launcher.py

1. 无人机编号统一从 0~23 调整为 1~24，和实际无人机编号、地面站命令端口保持一致。
2. 逐机配置改为显式列出 24 架无人机，包含命令端口、GUI 地址、飞控 UDP 地址和串口参数。
3. 每架无人机保留独立的 id、tag、cmd_port、udp_bind_port、udp_target_port 等部署字段。
4. 编队默认值由 constants.py 合并到逐机配置中，包含默认编队类型、间距、分组和主从角色。
5. 保留单架无人机启动入口 python .\drone-exec\run.py <id>，启动参数按 1~24 的无人机编号传入 runtime.run_drone()。
6. 新增 24 架无人机的 Tkinter 启动器，每个按钮对应一架无人机。
7. 启动器只允许 1~24 号无人机，0 和 25 等非法编号会被拒绝。
8. 每架无人机以独立隐藏子进程启动，避免弹出额外终端窗口。
9. 每个子进程的输出写入 logs/drone_launcher/drone_<id>.log。
10. 支持查看运行状态、停止单架无人机、停止全部无人机和退出时清理进程。
11. 新增启动器辅助函数测试，覆盖合法编号、非法编号、启动命令构造和日志路径。
12. 明确验证 1 和 24 有效，0 和 25 无效。

## 修改日期：6.1 号

修改模块：cmd_process.py、behavior/leader.py、behavior/follower.py、runtime.py、flight_controller.py、behavior/telemetry.py、tests

1. 加固命令处理循环，避免行为任务取消时卡死导致后续命令无法继续处理。
2. 新增旧编队任务取消超时控制，超时后通过日志说明未启动新任务。
3. formation_set 和 formation_start 都会解析并保存 form_type、spacing、group 和 targets。
4. 编队启动时按 leader-first 的目标顺序确定队长和从机槽位。
5. 已删除的命令继续由无人机侧接收，并通过 bridge.send_log() 回复“收到但不执行”的原因。
6. 领机广播编队参考信息时携带当前编队类型、间距、队长目标点和状态。
7. 领机任务继续负责生成目标点控制帧，作为从机跟随的参考来源。
8. 从机根据领机广播中的 form_type 和 spacing 计算自己的编队偏移。
9. 从机前视点计算加入间距和速度因素，避免固定翼追踪目标落到机体后方。
10. 运行时初始化时解析配置中的编队类型和编队间距，形成统一的 form_ref。
11. 地面站桥接、飞控遥测监控、基础 telemetry 转发和命令监听并行启动。
12. 本地等待飞控遥测的提示只打印到本地终端，不作为地面站日志回传。
13. 新增最近一次目标点缓存，goto_location() 下发控制帧时同步记录目标纬度、经度、高度和速度。
14. 新增 heading_valid 判断，区分是否已经具备可用于编队计算的航向。
15. 支持按配置控制控制帧发送日志的打印频率，避免日志刷屏。
16. telemetry 中加入 goto_lat、goto_lon、goto_alt、goto_speed，用于地面站显示预期目标点。
17. 当飞控数据超时或没有新帧时，发送只包含 id、tag 和目标点字段的空心跳 telemetry。
18. 补充编队命令、运行时、飞控控制器、telemetry、leader 行为等测试，覆盖目标点回传、空心跳和编队参数传递。

## 修改日期：5.29 号

修改模块：runtime.py、behavior/telemetry.py、cmd_process.py、tests

1. 启动流程调整为地面站通信和飞控通信并行进行，不再等待首帧飞控数据后才启动命令监听。
2. 启动后先向地面站发送一次空 telemetry 注册，让地面站能先看到无人机程序链路。
3. 飞控首帧数据的等待作为后台监控任务运行，不阻塞地面站命令通道。
4. 使用飞控状态中的 received_at 判断 telemetry 是否为新数据。
5. 没有新飞控数据时继续发送空 telemetry，表示无人机程序到地面站的链路仍然存在。
6. 下线的 takeoff、rtl、land、test_dubins、test_vo、mission 等命令不再执行飞行动作。
7. 下线命令由无人机端立即返回日志，地面站不再伪造这些回执。
8. 整理 pytest 入口和测试目录，让协议、运行时、桥接和命令处理测试纳入默认测试集合。

## 修改日期：5.28 号

修改模块：protocol、flight_controller.py、config.py、tests/test_protocol.py

1. 新增外部飞控二进制协议包，集中处理发送帧、接收帧、校验和、字段缩放和连续字节流解析。
2. send_frame.py 负责打包 msg_id=1 控制帧。
3. receive_frame.py 负责解析 msg_id=2 telemetry 帧。
4. stream_reader.py 支持串口和字节流重同步，并只保留最新解析帧供运行时读取。
5. 用内部 FlightController 适配器替换原 MAVSDK/PX4 控制路径。
6. 支持 UDP 和串口两种飞控连接方式。
7. goto_location() 直接打包并发送外部飞控控制帧。
8. get_state() 返回最新 telemetry 状态，并根据位置变化或初始航向估算 heading。
9. 配置拆分为基础配置、串口配置和 UDP 配置，再合并为最终 UAV_CFGS。
10. 每架无人机显式保留自己的 GUI 地址、命令端口、串口参数、UDP 监听端口和 UDP 目标端口。
11. 将协议测试纳入 tests，覆盖帧打包、接收帧解析、连续流解析和校验逻辑。

## 修改日期：5.27 号

修改模块：behavior、cmd_process.py、已删除功能文件和目录

1. 编队逻辑拆分为领机和从机职责，避免把所有行为压在单个模块中。
2. 恢复三种编队形态：三角队形、横向一线、纵向一线。
3. 编队偏移计算集中在工具函数中，便于后续扩展更多队形。
4. 保留命令接收和日志回复能力，删除已经下线的飞行动作入口。
5. abort、config_update、formation_set、formation_start 保持可用。
6. 回复逻辑保持简单，只通过日志通道返回结果，不额外引入独立状态接口。
7. 删除 YOLO 目标检测、路径规划、offboard、起飞、降落、返航、打击、VO 跟踪、Dubins 跟踪等不再使用的功能入口。
8. 清理相关陈旧导入、测试脚本和功能说明，避免地面站继续触发已删除功能。
