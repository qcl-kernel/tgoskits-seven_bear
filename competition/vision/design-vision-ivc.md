# 固定帧视觉分拣 IVC 设计

## 状态与风险

本设计面向比赛阶段 A：AxVisor 中的 StarryOS Guest 对固定图像执行 RK3588
RKNN 推理，经隔离的 `virtio-net`/UDP/IPv4 链路把结果交给 RTOS，RTOS 执行可观察的
虚拟挡板动作并回传实际状态。它扩展共享线协议并改变安全回退行为，按
`book/guideline/feature-development.md` 归类为高风险；协议、RTOS 状态机和实板证据可分别
审查，未通过对应门禁时不得把固定图像验证描述为摄像头闭环。

用户是比赛评审、演示操作者和后续接入真实挡板/LED/PWM 的平台开发者。成功标准是：

- 同一实际 RKNN 检测结果产生独立、版本化的 `VISION_DECISION`，不复用热控字段；
- RTOS 对新会话/序列只执行一次动作，并以 `ACTUATOR_STATUS` 回传实际动作；
- 过期、重放、乱序、CRC 错误和控制器静默均 fail closed 到 `HOLD` 或 `EMERGENCY_STOP`；
- Rust/C golden vector 一致，主机故障测试和 Orange Pi 5 Plus 实际 StarryOS + RTOS
  运行均可复核；
- 演示同时给出识别正确率、动作正确率、端到端延迟和 manual 固定动作基线，不把
  accuracy 改善与延迟退化合并为“整体更优”。

非目标包括：本阶段不做 USB/xHCI Guest 直通，不控制真实电机，不把 UDP 变成通用可靠
传输，不声称固定三帧可代表摄像头 FPS 或 30 分钟稳定性，也不修改 StarryOS syscall ABI。

## 现状、先例与方案选择

内部先例是 IVC1 的 32-byte little-endian header、CRC-32、`session_id + sequence` 接收窗口、
ACK/超时/重传和已退役会话拒绝。视觉协议复用这些已经实测的传输语义。RFC 8085 指出
UDP 本身不提供可靠性，并建议在完整性重要时增加应用层 CRC、避免 IP 分片；因此消息仍
限制在现有 1,200-byte payload 上限内，并保留 IVC1 CRC。序列窗口沿用现有 32-bit 有界
实现；若未来允许回绕，应按 RFC 1982 的序列号算术单独设计，当前在耗尽前拒绝继续发送。

参考：

- <https://www.rfc-editor.org/rfc/rfc8085.html>
- <https://www.rfc-editor.org/rfc/rfc1982.html>

评估过的替代方案：

1. 把类别和置信度塞入 `setpoint_milli_c`。改动小但类型不安全、破坏错误边界，拒绝。
2. 发送 JSON。便于调试，但 RTOS 需要动态/文本解析，长度和保留字段难以严格校验，拒绝。
3. 直接发送检测图像或 tensor。超过控制通道职责并增加分片/拥塞风险，拒绝。
4. 使用 TCP。可省去部分可靠性代码，但现有板卡链路、故障注入和证据均基于 UDP；本次
   增量复用已经验证的 stop-and-wait 和接收窗口。
5. 选择固定长度、独立 payload，并继续使用 IVC1 frame。该方案边界最小，Rust/C 可用
   golden vector 锁定，因此采用。

## 线协议

IVC frame version 保持 `1`，因为此次只添加可忽略的新消息类型；每个新 payload 自带
`payload_version = 1`。多字节字段均为 little-endian，保留字段必须为零。

消息类型：

| 值 | 名称 | 方向 |
| ---: | --- | --- |
| 6 | `VISION_DECISION` | StarryOS → RTOS |
| 7 | `ACTUATOR_STATUS` | RTOS → StarryOS |

`VISION_DECISION` 固定 44 bytes：

| 偏移 | 类型 | 字段 |
| ---: | --- | --- |
| 0 | u8 | payload version |
| 1 | u8 | requested action: hold/left/right/emergency-stop |
| 2 | u8 | safe action，只允许 hold 或 emergency-stop |
| 3 | u8 | flags；bit 0 表示 detection present |
| 4 | u32 | frame id，非零且会话内严格递增 |
| 8 | u64 | capture timestamp (Starry monotonic us) |
| 16 | u64 | inference-finished timestamp (Starry monotonic us) |
| 24 | u32 | TTL us，范围 1..=5,000,000 |
| 28 | u16 | class id；无检测为 `0xffff` |
| 30 | u16 | confidence q10000，范围 0..=10000 |
| 32 | u16 | calibrated region id |
| 34 | u16 | reserved = 0 |
| 36..43 | 4×u16 | bounding box left/top/right/bottom |

`ACTUATOR_STATUS` 固定 32 bytes：payload version、状态、requested/actual action、frame id、
applied sequence、decision age at send、RTOS local apply latency、RTOS execution timestamp、
fault code和零保留字段。发送端和 RTOS monotonic clock 不共享 epoch；因此跨 VM age 仅由
Starry header timestamp 减 inference timestamp 得到，RTOS 只报告本地 receive-to-apply
耗时，不相减两个时钟。

新增错误码 `INVALID_VISION_DECISION` 和 `VISION_DECISION_EXPIRED`。ERROR 仍使用现有
offending type/sequence payload，ACK 仍由同一接收窗口生成。

## 决策和执行语义

固定样本使用最高置信度的 COCO class 32 (`sports ball`)。标定边界 `x = 625`：目标中心
小于边界为 `SORT_LEFT`，大于等于边界为 `SORT_RIGHT`，没有合格目标为 `HOLD`。该边界在
活动前冻结，不根据 ground truth 临时调参；`EMERGENCY_STOP` 只由显式安全策略产生。

RTOS 按以下顺序处理：frame/CRC → payload 版本与范围 → session/sequence 窗口 → frame id
重放检查 → sender timestamp/TTL → 动作应用。只有 `NEW` 或 `NEW_SESSION` 能产生 side
effect；重复包只重发 status/ACK。任何校验失败不执行挡板并返回 ERROR。控制器静默超过
500 ms 后，RTOS 进入最近有效决策声明的安全动作；新会话必须从 sequence 1 开始，恢复后
仍拒绝旧 session 和旧 frame id。

## 实现边界与验证

- `tools/ivcproto`：Rust payload、输入记录解析、UDP controller 和结果/延迟摘要；
- `competition/ivc/zephyr` 与 `competition/ivc/common`：C 编解码、执行状态机和 RTOS
  response；RT-Thread/FreeRTOS 复用 common server；
- `orangepi-5-plus-uvc-rknn`：从实际检测结果输出机器可读 decision record；
- rootfs/staging：把相同 YOLOv8 `.rknn`、三张固定图像、runner 和 controller 放入
  StarryOS Guest，manifest 绑定模型和二进制哈希；
- NPU 资源所有权：Axvisor host 完成并验证 power/clock/reset 后，Guest DTB 以
  `tgos,host-prepared-resources` 显式声明 Guest 只拥有 NPU core MMIO 和 DMA；Starry RKNPU
  glue 仅在该属性存在时跳过 `clk_npu` 编程。属性缺失时保留实体板原有的 800 MHz
  clock 设置与 readback，不能把缺少 clock provider 静默解释为 handoff；
- dashboard：只消费已验证的 decision/status 事件，显示 frame、bbox、requested/actual
  action、ACK、错误和分段延迟，不参与控制。

验证顺序是测试先行：Rust payload/边界、C golden vector、Rust→C 和 C→Rust 互操作、
重放/乱序/过期/未来时间/静默回退、ACK-loss 不重复动作、进程/Guest 重启拒绝旧会话，最后
才运行 QEMU 和 Orange Pi。实板活动保留完整 console、源提交/dirty 边界、模型哈希、
镜像哈希、逐帧记录、summary 和 checksums。30 分钟 soak 与真实 UVC 仍作为独立增强活动，
不能由固定帧 smoke 替代。
