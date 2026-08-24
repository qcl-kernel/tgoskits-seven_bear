# TGOSKits RT-IVC competition video script

## Scene 1

Title: 单芯片 RK3588 上的智能工控混合系统

Caption: AxVisor + StarryOS + RTOS + IVC/1 + RKNN

Narration: 本演示呈现一套运行在 Orange Pi 5 Plus 上的智能工控混合关键系统。由 AxVisor 隔离 StarryOS 与 RTOS：前者负责视觉与神经网络，后者负责动作控制与状态回传。本片仅展示可核验证据，并严格区分正式测试结果、pilot 试验与未完成的物理闭环。

## Scene 2

Title: 系统架构：算力与确定性分域

Caption: 输入→推理→网络→动作→状态

Narration: 在同一颗 RK3588 上，StarryOS 客户机分配 2 个 vCPU 和 256 MiB，负责 USB 摄像头采集、图像预处理与 RKNN 推理；Zephyr 分配 1 个 vCPU 和 128 MiB，负责协议解析与动作状态机。应用数据仅通过 IVC/1 over UDP/IPv4 传输，主通道不使用共享内存、HyperCall 或裸 MMIO。

## Scene 3

Title: 实时性：看最差运行，也看逐配对尾延迟

Caption: 5 组 AB/BA；每项每 half 10,000 样本；双约 30 分钟 soak

Narration: 冻结的正式 RT 测试包含 5 组预注册 AB/BA 实验，每项每 half 各采集 10,000 样本。调度延迟、模拟中断、周期抖动与虚拟定时器注入的 worst maximum 分别改善 99.331%、99.444%、99.548% 和 43.443%。但调度延迟的 worst p99 为 -1.080%。上述指标均为 observed maximum，而非 WCET；且数据源自指定基准提交，并非当前 HEAD 重跑结果。

## Scene 4

Title: 同板原生 Zephyr：给虚拟化结果一个参照

Caption: 4 组 AB/BA、8×10,000 样本、0 miss

Narration: 在同一块 Orange Pi 5 Plus 上，原生 Zephyr 4.3.0 完成了 4 组 idle 与 CPU stress 的 AB/BA 测试，共 8 次 10,000 样本运行，全部保持 0 timer miss。周期唤醒 p99 中位数为 2,875 ns，timer→task p99 为 1,458 ns。另一次 1,817.822 秒 soak 测试同样记录为 0 miss。该结果作为同板 RTOS 参照，并非 identical-kernel 虚拟化开销结论。

## Scene 5

Title: IVC/1：能控制、能确认、能报错、能恢复

Caption: UDP/IPv4 上的 32-byte header 与幂等状态机

Narration: IVC/1 协议的每个 UDP datagram 承载一个 frame，其 32-byte header 包含 version、type、session、sequence、timestamp、length、error code 与 CRC-32。控制端必须同时收到匹配的 STATUS 与 ACK 响应；64-sequence 窗口机制确保重复数据包仅重放应答，不重复执行动作。针对 ACK-loss、typed ERROR 和 guest restart 场景各完成 3 次物理 campaign。当前 reset smoke 测试在真实 VM reset 前后完成 120 条命令，accepted 与 applied 数量均为 120。

## Scene 6

Title: AI 控制：误差下降，但超调必须公开

Caption: 统一模型，native Rust / ONNX Runtime / RKNN 三后端

Narration: canonical 神经网络在 native Rust、ONNX Runtime CPU 和 RKNN NPU 三个推理后端间共享权重、golden vectors 与协议载荷。在五组 AB/BA 测试中，相较于固定 500 permille 的手动基线，neural 控制的 RMSE 降低 35.926646%，IAE 降低 51.932443%；但最大超调增加 96.315789%。实验结论表明跟踪误差改善与超调退化并存，而非 AI 全面胜出。

## Scene 7

Title: 现场 USB 摄像头：真实输入

Caption: Orange Pi 5 Plus /dev/video0；UVC MJPEG；600 帧现场采集

Narration: 本段画面由 Orange Pi 5 Plus 的 /dev/video0 通过 uvcvideo 驱动直接采集，共计 600 帧，非 validation 目录中的样本图片，亦非仓库中的推理结果截图。该画面仅用于证明当前物理摄像头输入链路真实可用。历史连续链路测试持续 60.1 秒，采集 965 帧并完成 483 次推理，跨 Guest 的 60 条 decision 均被 RTOS 确认为 accepted 和 applied；但本段实拍与该测试不在同一时间线，不能作为 RKNN、RTOS 或机械臂动作的同步证据。

## Scene 8

Title: RK3588 优化与隔离：收益必须可复核

Caption: Q12 预处理稳定受益；all-core 尾延迟有退化

Narration: RK3588 固定输入五配对测试显示，Q12 预处理使 letterbox 平均耗时降低 47.136%，总耗时平均值降低 33.351%，总耗时 p95 降低 28.288%。NPU all-core 模式下的 run 平均值仅改善 0.612%，run p95 却退化 2.074%，故未设为默认配置。网络隔离测试中，同网段 TCP 传输 65,536 bytes，100 个跨 segment UDP 探针的接收数均为 0。

## Scene 9

Title: 实机采集与物理执行：明确边界

Caption: 现场摄像头实拍 + SO-100 ID1 单周期；两项尚未同步

Narration: 画面左侧为 Orange Pi 现场采集的物理摄像头画面，右侧为 SO-100 的有人值守测试记录。机械臂通过 USB Control 接入 Orange Pi，完成 ID1 的 2042→2074→2042 单周期动作，观测最大位置为 2073，测试结束正常卸载扭矩且无故障。两项证据均来自实体硬件，但未在同一 sequence 下同步；机械臂目前尚未接入 RTOS mediator，因此不声明基于摄像头驱动的物理闭环。

## Scene 10

Title: 一芯多域：迈向确定性执行

Caption: USB 感知、RKNN 推理、IVC/1、RTOS 状态机、SO-100

Narration: 基于单颗 RK3588 芯片，AxVisor 将感知计算与实时控制解耦至不同客户机：由 StarryOS 负责 USB 图像采集与 RKNN 推理，RTOS 维护通信协议与动作状态。现有实测证据已覆盖实时调度、网络隔离、IVC 恢复、板端视觉与 SO-100 单关节执行；当前的验证边界为摄像头与机械臂尚未按同一 sequence 同步。下一步将由 RTOS mediator 串联决策输出、动作回执与急停记录，构建全链路可审计的物理闭环。
