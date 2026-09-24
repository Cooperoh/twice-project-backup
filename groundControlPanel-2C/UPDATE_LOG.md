# 更新记录

## 修改日期：2026.9.8

修改模块：web_app/backend/commands.py、web_app/tests

1. “下发编队”改为只发送一条包含 group、targets、form_type、spacing 的 formation_start，不再先发送相同参数的 formation_set。
2. “发布编队调整”保留逐机 config_update，对原已启动且调整后仍非空的编队，仅发送 formation_start 重建任务。
3. 添加注释说明机载 start 已包含配置更新，以及不自动重发 start 的原因；同步更新日志和接口返回描述。
4. 更新命令数量、完整参数、急停并发、发布失败不提交及本地 UDP 实际收包测试。

## 修改日期：7.10 号

修改模块：web_app/frontend

1. 网页版 Monitor、Formation、Workbench 和顶栏统一放大字号，提高操作信息可读性。
2. 地图无人机标记由 42px 放大到 56px，并同步放大航向箭头、标签和提示偏移。
3. 保持无人机轨迹与期望点连线现有粗细，不改变地图轨迹语义。
4. Monitor 宽屏布局增加视口高度约束，Event Log 内容改为面板内部滚动，不再拉长页面或推走 Flight Control。
5. 长日志可在内容列内换行，并保留新增日志自动滚动到底部的行为。
6. 补充不同页面、不同视口、日志高度稳定性和地图标记尺寸的浏览器测试。

## 修改日期：6.24 号

修改模块：drone_icon.py、pageMonitor.py

1. 无人机图标航向量化从 5 度调整为 2 度，提升地图图标转向细腻度。
2. Monitor 页缓存无人机已显示的位置和标签，位置或标签未变化时不再重复调用地图 marker 更新。
3. Monitor 页缓存轨迹更新签名，轨迹没有新增点时不再重复刷新 path。
4. 蓝色无人机轨迹线显式设置为 width=4，与黄色期望点连线粗细保持一致。
5. 保持现有 150ms 界面刷新周期，不加入位置插值、预测或额外动画刷新。

## 修改日期：6.8 号

修改模块：groundMain.py、pageFormation.py、pageMonitor.py

1. 地面站命令端口和无人机 ID 使用范围统一调整为 1~24，与无人机端编号保持一致。
2. CMD_ADDRS 按无人机 ID 1~24 生成，分别对应 57001 到 57024。
3. 新增编队分配状态，记录编队 0、编队 1、编队 2、编队 3 的成员和各编队队长。
4. 下发命令时按 leader-first 顺序组织目标列表，确保队长排在 targets 首位。
5. 新注册的无人机会自动加入编队 0，并立即下发当前分组和队长配置。
6. 新增编队分配页，支持编队 0、编队 1、编队 2、编队 3 的可视化成员管理。
7. 支持点击和拖拽移动无人机；编队 0 可快速分配到编队 1/2，编队 1/2/3 可回到编队 0。
8. 自动维护每个编队的队长，默认使用当前编队中编号最小的无人机。
9. 新增“发布编队调整”按钮，将成员和队长配置同步回主程序并下发给无人机端。
10. Monitor 页新增编队类型选择，支持“三角”“横向一线”“纵向一线”。
11. Monitor 页新增编队间距输入，单位为米。
12. “下发编队”按钮使用当前选中的编队类型、间距和目标编队成员。
13. 地图目标点和轨迹更新改为优先原地更新，减少刷新时的闪烁。
14. formation_set 和 formation_start 连续下发，并都携带 group、targets、form_type、spacing。
15. config_update 同步携带当前编队类型和间距，避免无人机端继续使用旧配置。
16. 日志中显示下发的编队类型、间距和成员，便于确认地面站已经发送了正确参数。

## 修改日期：6.3 号

修改模块：groundMain.py、pageMonitor.py

1. 新增“遥测”状态，用于判断无人机程序到地面站的链路是否正常。
2. 新增“飞控”状态，用于判断完整飞控数据是否持续更新。
3. 空 telemetry 现在只刷新遥测链路时间，不刷新飞控时间。
4. 空 telemetry 不会覆盖旧的 lat 和 lon。
5. 空 telemetry 不会新增轨迹点。
6. 遥测和飞控状态阈值使用 groundMain.py 开头的全局变量配置。
7. 地图图标会停在最后一次完整飞控数据的位置，不会被空 telemetry 移动。
8. Monitor 页遥测表新增“飞控”列。
9. 遥测表使用整行颜色提示状态：故障为黄色，死机为红色，遥测断开为灰色。

## 修改日期：5.26 号

修改模块：README.md、groundBridge.py

1. 新增地面站 UDP 回传消息格式说明，记录 telemetry、telemetry_batch、log、trajectory 等消息。
2. 新增地面站命令格式说明，记录 formation_set、formation_start、config_update、abort 等命令 payload。
3. 文档只描述地面站实际发送和接收的 JSON，不假设无人机端未验证的内部响应逻辑。
4. 保留便于纯文本阅读的表格写法，方便直接打开 Markdown 查看字段。
5. 支持接收 telemetry_batch，把 list 中每条 telemetry 拆成单独消息交给 groundMain.py 处理。
6. 保持 UDP 监听端口 56999 的多无人机遥测接入方式。

## 修改日期：5.25 号

修改模块：groundMain.py、pageMonitor.py、已删除 Starlink 文件

1. 移除 Starlink 相关页面和发送端功能入口，保留地面站核心监控、编队和工作台功能。
2. 地图刷新时优先复用已有无人机 marker，只更新位置、文本和图标。
3. 轨迹线优先使用 set_position_list() 原地更新，避免频繁删除和重建 path。
4. 目标点 marker 和目标连线也采用原地更新优先的方式，减少 Monitor 页刷新闪烁。
5. 删除 pageStarlink.py、starlink_sender.py、starlink_sender_gui.py 等 Starlink 相关文件。
