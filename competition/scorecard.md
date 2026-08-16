# 评分项—实现—证据映射

本表逐项对应 [`requirement.md`](requirement.md) 的 100 分主评分和 10 分
加分项。它是提交前的证据自审，不是裁判分数。分数只表示“当前材料能否稳健支撑
该项”，不把代码存在、单元测试通过和实体板测量混为一谈。

## 证据分层

| 标签 | 含义 |
| --- | --- |
| C-IVC | clean commit `598b357f92c848e669c12cca830a4d08d0a50e36` 的实体 IVC 重启闭环；runner、analyzer、metadata 和退出码绑定同一提交，可从 [`results/current-source-smoke-20260813`](results/current-source-smoke-20260813/) 核验 |
| C-RT | clean commit `077ba386c20c29b84749f509b29e8a3f6f76e1e2` 的实体 RT shared/partitioned 冒烟；之后只改 `competition/ivc/`，精确路径证明见 [`source-delta.txt`](results/current-source-smoke-20260813/source-delta.txt) |
| C-RT-F | clean commit `c82da8464ab69e7da95e9be08293559e67b28fac` 的预注册五配对 + 双 soak 正式实体 RT 活动；23 个 compact 文件、12 份回执和 113 项 raw 归档清单见 [`axvisor-rt-formal-20260816`](results/axvisor-rt-formal-20260816/) |
| F | 历史 clean commit 上预注册的正式多轮实体板活动；本仓库提交精简 summary/preregistration，完整约 844 MiB raw 档案尚需单独发布 |
| H | host/QEMU/单元/契约测试；只能证明相应软件边界，不能替代实体板时延 |
| H-RTOS | Zephyr、RT-Thread、FreeRTOS 原生 QEMU/AArch64 idle/stress 基线；证明等价平台的可复现对照，不是 RK3588 裸机结果 |
| H-IVC-RTOS | RT-Thread、FreeRTOS 在 AxVisor QEMU/AArch64 下的双 Guest normal/ACK-loss 活动；证明 Guest boot、VirtIO/IP 和 IVC/1 端点，不替代 StarryOS/实体板组合证据 |
| H-ISO | 三个 ArceOS guest 的 AxVisor QEMU 动态隔离活动；证明 segment 分离和无默认路由，不替代实体板或动态 spoof 测试 |
| D | 设计或源码静态证据 |

关键边界：C-RT 的早期单对仅验证 device-graph、shared/partitioned 启动、采集、
快照和恢复链；C-RT-F 才承担当前正式性能结论。其 `m2_exit_gate_met=true`，来源为
五配对受控干扰和双侧 30 分钟 soak。RTOS Guest/IVC 与隔离复验也绑定同一提交；
后续仅更新交付材料，校验器逐项证明 34 个预注册运行输入的 Git blob 未变化。

## 任务一：实时 RTOS 化改造（30 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| 实时化目标和关键路径分析 | 4 | [`design.md`](design.md)、[`improvement-plan.md`](improvement-plan.md)；vCPU 放置、timer/GIC 进入退出顺序、直接 IRQ trace、host-noise 模型 | D；C-RT-F | 证据充分 |
| AxVisor 关键机制有实质改造 | 8 | `axvm` dedicated CPU、timer context、GIC/IRQ 路径、host-noise、预分配 trace；device graph 负责设备资源声明/分配/实例化 | D；相关 Rust/配置测试 | 证据充分 |
| ≥2 vCPU 客户机及 CPU/内存/设备/IRQ/启动配置 | 4 | [`starry-orangepi-5-plus-smp2-partitioned.toml`](../scripts/benchmark/axvisor-rt/config/starry-orangepi-5-plus-smp2-partitioned.toml)；`phys_cpu_sets=[0x2,0x4]`、2 vCPU、256 MiB、typed `virtio-blk-mmio` | C-RT-F 两侧双 vCPU 启动、零迁移、lossless trace | 证据充分；使用 StarryOS 替代 Linux |
| 改造前后完整数据并体现 worst-case/抖动改善 | 5 | shared/partitioned 正交配置与比较器 | C-RT-F 五配对：dispatch、emulated IRQ、periodic jitter、direct IRQ max 均 5/5 改善；worst-of-runs 分别改善 99.331%、99.444%、99.548%、43.443%；双 soak | **当前正式证据完整，机器 M2 门通过** |
| idle 与 stress 对比充分 | 4 | RT capture/aggregate 脚本、guest CPU1 stress、受控 host-noise | F host-noise idle 五对 + 双 soak；F guest stress 五对；C-RT shared/partitioned stress 冒烟 | 证据充分，报告中分开解释两种干扰变量 |
| 原生 Zephyr/RTOS 基线合理且可复现 | 5 | [`rt-baseline`](rt-baseline/)；Zephyr v4.3.0、RT-Thread v5.2.2、FreeRTOS Kernel `f1043c49…` | H-RTOS：三种 RTOS 均完成 idle/stress、每组 10,000 样本、固定源码/工具链和 fail-closed 分析 | **赛题允许相同或等价平台；QEMU/AArch64 方法可复现且差异已披露，证据充分** |

任务一可辩护证据估计：`30/30`。同一 Orange Pi 裸机 RTOS 对照仍可进一步增强
外部有效性，但不再作为“等价平台基线”细则的缺失项。

## 任务二：基于网络的客户机间通信（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| Starry/Linux—RTOS IP 网络链路与配置 | 4 | typed `virtio-net-mmio` 节点接入 AxVisor segment 1；controller `10.0.0.1/24`，RTOS `10.0.0.2:5500` | C-IVC Starry/Zephyr；H-IVC-RTOS Linux/RT-Thread/FreeRTOS | 证据充分；新增 RTOS 路径明确限定 QEMU |
| 应用协议字段完整且位于 UDP/IP | 5 | [`ivcproto`](../tools/ivcproto/src/lib.rs)：magic/version/type/length/session/sequence/timestamp/error/CRC | H Rust+C 跨实现 golden/negative tests；C-IVC 与 H-IVC-RTOS 实际 UDP | 证据充分 |
| CONTROL、STATUS、错误通知可用 | 5 | Starry/Linux controller 与共享 RTOS endpoint core | C-IVC：120 CONTROL 应用、122 STATUS/ACK、1 ERROR；H-IVC-RTOS 两种 RTOS normal 各 100/100 | 证据充分 |
| ACK/超时/重传/乱序重复/重连恢复 | 4 | receive window、exactly-once duplicate suppression、retry、session retirement、safe fallback | F ACK-loss/error/restart 各 3/3；C-IVC actual VM reset；H-IVC-RTOS 各 20 次重传/去重/恢复 | 证据充分 |
| 自动化测试数据 | 4 | board/QEMU runner、strict analyzer、campaign aggregator | F 5×1,800 normal paired；3×fault；C-IVC 与 H-IVC-RTOS machine summary/raw/checksum | 证据充分 |
| 网络隔离与访问控制 | 3 | 无 host NIC/default route/NAT/vsock；segment membership、精确单播、anti-spoof、unknown-unicast drop；第三 guest 位于 segment 2 | H policy tests + D topology + H-ISO：VM3 发 100 个跨 segment UDP 探针、VM1 观察 7 秒收到 0 个、VM3 default route=0 | 证据充分；动态 spoof/unknown-unicast 仍由最低层 policy tests 覆盖 |

任务二可辩护证据估计：`25/25`。

## 任务三：AI 控制闭环（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| StarryOS 中完成神经网络推理 | 4 | native 4×6×1、同源 ONNX、RKNN NPU、ONNX Runtime CPU 后端 | F RKNN/ORT 各 5×1,800；C-IVC native controller | 证据充分；不同后端结果分开标注 |
| 模型输出通过任务二协议发送 | 5 | controller `CONTROL` payload | C-IVC/F raw 与 RTOS counters | 证据充分 |
| RTOS 根据输出执行可观察动作 | 5 | 共享 actuator + deterministic thermal plant；Zephyr、RT-Thread、FreeRTOS adapter | C-IVC `applied=120`；F 9,000/9,000；H-IVC-RTOS 两种 RTOS 各 `applied=100` | 证据充分 |
| 状态回传形成闭环 | 4 | `STATUS` 作为下一周期观测，`ACK` 确认 side effect | C-IVC/F；H-IVC-RTOS 4/4 campaigns | 证据充分 |
| 端到端延迟方法与数据 | 3 | Starry 单时钟 round trip：pre-send / transport / full-loop | C-IVC 100 post-reset samples；F full profiles | 证据充分；不做跨客户机时钟相减 |
| 与固定参数手动控制比较至少两项 | 4 | AB/BA 五对 manual/neural | F：RMSE 改善 35.93%，IAE 改善 51.94%；overshoot 退化 96.32% 被保留 | 证据充分且披露负向指标 |

任务三可辩护证据估计：`25/25`。

## 工程完整性与文档（15 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 设计方案完整 | 4 | [`design.md`](design.md) 覆盖 device graph、资源、协议、隔离、故障与测量边界 | 证据充分 |
| 测试文档完整 | 4 | [`test-report.md`](test-report.md)、机器 JSON、validation logs | 证据充分 |
| 源码和配置完整 | 4 | 当前 branch、typed device configs、stager/runner/analyzer；[`provenance.json`](results/current-source-smoke-20260813/provenance.json) | 证据充分 |
| 复现说明可操作 | 3 | [`reproduce.md`](reproduce.md)、source/input/checksum manifests | **精简包可复核；当前正式 RT 42,722,019-byte archive 和历史约 844 MiB raw 尚无公开下载地址，保守扣 1 分风险** |

工程完整性可辩护证据估计：`14/15`。

## 创新与扩展性（5 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 实时/网络/控制方案创新 | 2 | device-graph typed virtual NIC/block、直接跨层 IRQ trace、受控 host interference、actual guest restart | 证据充分 |
| 扩展到更多 guest/RTOS/场景 | 2 | code-registered device model、segment/port、profile/backend 分层；RT-Thread 与 FreeRTOS 共享 transport/core、独立 OS glue | H-IVC-RTOS 4/4 严格 QEMU 活动，设计与代码充分 |
| 代码质量与工程规范 | 1 | typed config/errors、fail-closed analyzer、atomic staging、checksum/readback、回归测试；`verify_delivery.py` 将 32 个 compact 文件、5 份 QEMU 日志、113 项 raw 清单、业务门槛和源码输入新鲜度接入 CI | 证据充分 |

创新与扩展性可辩护证据估计：`5/5`。

## 加分项（最多 10 分）

| 加分项 | 分值 | 当前判断 |
| --- | ---: | --- |
| StarryOS 替代 Linux | 4 | **可主张 4 分**：当前实体 IVC 和 RT 客户机均为 StarryOS |
| StarryOS syscall 完善并合入 `dev` | 4 | **当前不主张**：本工作增强网络/文件系统/实体运行，但没有把新增 syscall 数量和已合入 upstream `dev` 的证据绑定到本提交 |
| 多 RTOS 或多开发板基线 | 2 | **可主张 2 分**：三种原生 RTOS 基线均有固定上游与保留证据，RT-Thread/FreeRTOS 还完成独立 Guest/IVC QEMU 活动；不以 QEMU 冒充第二块开发板 |

## 保守汇总与下一步

按上述“证据可辩护”口径，当前主评分约为 `99/100`，可主张 StarryOS
替代 Linux `+4` 和多 RTOS `+2`，合计加分 `+6`；这不是官方评分。最值得投入的
后续工作按收益排序：

新增正式活动消除了任务一与当前实现之间的性能证据断层；剩余 1 分风险只保留在
完整 raw 归档尚无公开不可变下载地址。

1. 将已生成的 42,722,019-byte 当前正式 RT archive 发布到 GitHub Release/LFS/不可变数据集；总 SHA-256 为 `68c1efb1ae0338692a84943c7056e104e2abed9e62a89dcdb0e2540ea1f9859e`，113 项逐文件 manifest 已提交。
2. 如需统一公开全部历史活动，再发布约 844 MiB 历史 raw 归档并给出不可变 URL。
3. 在同一 RK3588 上裸跑至少一种 RTOS 的 idle/stress/soak，记录时钟源、CPU 亲和和原始样本，作为比等价 QEMU 更强的补充对照。
4. 将已通过的 RT-Thread/FreeRTOS Guest/IVC 路径移植到 Orange Pi 5 Plus，并至少运行一组 StarryOS controller 组合；当前只主张 QEMU/AArch64 endpoint 支持。
5. 如要争取额外 4 分，单独选择有明确 Linux ABI 依据的 StarryOS syscall 缺口，按项目规范实现、测试并真正合入 upstream `dev`；不要把普通平台修复包装成 syscall 加分。
