# TGOSKits RT-IVC competition video script

## Scene 1

Title: 单芯片 RK3588 上的智能工控混合系统

Caption: AxVisor + StarryOS + RTOS + IVC/1 + RKNN

Narration: 本系统运行于 Orange Pi 5 Plus，基于 AxVisor 隔离 StarryOS 与 RTOS：前者负责视觉与神经网络，后者负责动作与状态回传。本片只展示可核验证据，并明确区分正式结果、pilot 与未完成的物理闭环。

## Scene 2

Title: 系统架构：算力与确定性分域

Caption: 输入→推理→网络→动作→状态

Narration: 在同一颗 RK3588 上，StarryOS 客户机分配 2 个 vCPU 和 256 MiB，负责 USB 摄像头、图像预处理与 RKNN 推理；Zephyr 分配 1 个 vCPU 和 128 MiB，负责协议与动作状态机。应用数据只通过 IVC/1 over UDP/IPv4 传输，主通道不使用共享内存、HyperCall 或裸 MMIO。

## Scene 3

Title: 实时性：看最差运行，也看逐配对尾延迟

Caption: 5 组 AB/BA；每项每 half 10,000 样本；双约 30 分钟 soak

Narration: 冻结的正式 RT 测试包含 5 组预注册 AB/BA，每项每 half 各采集 10,000 样本。调度延迟、模拟中断、周期抖动与虚拟定时器注入的 worst maximum 分别改善 99.331%、99.444%、99.548% 和 43.443%；但调度延迟 worst p99 为 -1.080%。这些数据均为 observed maximum 而非 WCET，且归属于指定源提交，不是当前 HEAD 重跑。

## Scene 4

Title: 同板原生 Zephyr：给虚拟化结果一个参照

Caption: 4 组 AB/BA、8×10,000 样本、0 miss

Narration: 在同一块 Orange Pi 5 Plus 上，原生 Zephyr 4.3.0 完成 4 组 idle 与 CPU stress 的 AB/BA，共 8 次 10,000 样本运行，全部为 0 timer miss。周期唤醒 p99 中位数为 2,875 ns，timer→task p99 为 1,458 ns；另一次 1,817.822 秒 soak 同样为 0 miss。该结果仅作为同板 RTOS 参照，不是 identical-kernel 虚拟化开销结论。

## Scene 5

Title: IVC/1：能控制、能确认、能报错、能恢复

Caption: UDP/IPv4 上的 32-byte header 与幂等状态机

Narration: IVC/1 的每个 UDP datagram 承载一个 frame，32-byte header 包含 version、type、session、sequence、timestamp、length、error code 与 CRC-32。控制端必须同时收到匹配的 STATUS 与 ACK；64-sequence 窗口使重复包只重放响应，不重复执行动作。ACK-loss、typed ERROR 与 guest restart 各完成 3 次物理 campaign。当前 reset smoke 在真实 VM reset 前后共完成 120 条命令，accepted 与 applied 均为 120。

## Scene 6

Title: AI 控制：误差下降，但超调必须公开

Caption: 统一模型，native Rust / ONNX Runtime / RKNN 三后端

Narration: canonical 神经网络在 native Rust、ONNX Runtime CPU 与 RKNN NPU 三个后端共用权重、golden vectors 与协议载荷。五组 AB/BA 中，相比固定 500 permille 手动基线，neural 的 RMSE 降低 35.926646%，IAE 降低 51.932443%；但最大超调增加 96.315789%。结论表明误差改善与超调退化并存，而不是 AI 全面胜出。

## Scene 7

Title: USB 摄像头到 RTOS：连续视觉链路已闭合

Caption: UVC→RKNN→UDP/IP→Zephyr→状态回传

Narration: USB 摄像头的原生 StarryOS 测试持续 60.1 秒，采集 965 帧并完成 483 次推理，解码与推理错误均为 0。跨 Guest 运行生成 60 条 decision，RTOS 全部 accepted 和 applied 并逐条回传状态。图像采集到动作状态回传的时延中位数为 474.923 ms，p95 为 595.729 ms，观测最大值为 2,437.752 ms。本次动作是虚拟状态，没有物理执行器。

## Scene 8

Title: RK3588 优化与隔离：收益必须可复核

Caption: Q12 预处理稳定受益；all-core 尾延迟有退化

Narration: RK3588 固定输入五配对测试显示，Q12 预处理使 letterbox 平均耗时降低 47.136%，总耗时平均值降低 33.351%，总耗时 p95 降低 28.288%。NPU all-core 的 run 平均值只改善 0.612%，run p95 却退化 2.074%，因此不设为默认。网络隔离测试中，同段 TCP 传输 65,536 bytes，100 个跨 segment UDP 探针的接收数为 0。

## Scene 9

Title: 直观场景与机械臂：展示边界同样重要

Caption: 网球分拣 pilot + SO-100 ID1 有人值守单周期

Narration: 网球分拣将输出映射为 left、right 和 hold，便于同屏展示边界框、sequence、RTOS 状态与延迟。但当前只有 3 个标注正样本，AI 正确 2/3，固定 right 也是 2/3，不能证明总体 AI 优势。SO-100 已通过 USB Control 连接 Orange Pi，并完成 ID1 的 2042→2074→2042 有人值守单周期；它尚未接入 RTOS mediator，也未与摄像头同步。

## Scene 10

Title: 可追溯交付：结果、文档和视频来自同一证据快照

Caption: 21 个证据输入、10 张图表、2 份 PDF、约 5 分钟视频

Narration: 提交材料从单个只读快照汇总 21 个结果 JSON，并保存每个输入的 SHA-256。图表均由快照生成，中文经 agy 与 Gemini 3.7 Flash High 润色，PDF 使用固定提交的 ilm-zh 构建。下一步是重跑当前 HEAD 的正式 RT campaign，扩展分层标注数据，并将 SO-100 接入 RTOS mediator，完成可核验的摄像头同步物理闭环。
