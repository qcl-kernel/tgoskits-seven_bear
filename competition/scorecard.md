# 评分项—实现—证据映射

本表逐项对应 [`requirement.md`](requirement.md) 的 100 分主评分和 10 分
加分项。它是提交前的证据自审，不是裁判分数。分数只表示“当前材料能否稳健支撑
该项”，不把代码存在、单元测试通过和实体板测量混为一谈。

## 证据分层

| 标签 | 含义 |
| --- | --- |
| C0 | 当前源码 `069c911c1de02cecdc0c1fe891f5d5a288065ef0` 的实体板冒烟；可直接从 [`results/current-source-smoke-20260812`](results/current-source-smoke-20260812/) 核验 |
| F | 历史 clean commit 上预注册的正式多轮实体板活动；本仓库提交精简 summary/preregistration，完整约 844 MiB raw 档案尚需单独发布 |
| H | host/QEMU/单元/契约测试；只能证明相应软件边界，不能替代实体板时延 |
| D | 设计或源码静态证据 |

关键边界：C0 的 RT 配对只验证当前 device-graph 配置、启动、采集、快照和恢复链。
它的多个尾延迟指标退化，且只有一对、没有受控 host interference，所以不得用来
声称 M2 性能门通过。M2 改善结论来自 F 层五配对受控干扰活动，并保留其原始
source commit，不改写成当前源码结果。

## 任务一：实时 RTOS 化改造（30 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| 实时化目标和关键路径分析 | 4 | [`design.md`](design.md)、[`improvement-plan.md`](improvement-plan.md)；vCPU 放置、timer/GIC 进入退出顺序、直接 IRQ trace、host-noise 模型 | D；F `historical-formal/rt-host-noise` | 证据充分 |
| AxVisor 关键机制有实质改造 | 8 | `axvm` dedicated CPU、timer context、GIC/IRQ 路径、host-noise、预分配 trace；device graph 负责设备资源声明/分配/实例化 | D；相关 Rust/配置测试 | 证据充分 |
| ≥2 vCPU 客户机及 CPU/内存/设备/IRQ/启动配置 | 4 | [`starry-orangepi-5-plus-smp2-partitioned.toml`](../scripts/benchmark/axvisor-rt/config/starry-orangepi-5-plus-smp2-partitioned.toml)；`phys_cpu_sets=[0x2,0x4]`、2 vCPU、256 MiB、typed `virtio-blk-mmio` | C0 两次双 vCPU 启动、零迁移、完整 trace | 证据充分；使用 StarryOS 替代 Linux |
| 改造前后完整数据并体现 worst-case/抖动改善 | 5 | shared/partitioned 正交配置与比较器 | F 五配对：direct IRQ worst-of-runs 改善 87.771%，5/5；dispatch worst-of-runs 改善 99.773%；双 soak | **有历史正式证据，但当前源码未重跑五配对；保守扣 1 分风险** |
| idle 与 stress 对比充分 | 4 | RT capture/aggregate 脚本、guest CPU1 stress、受控 host-noise | F host-noise idle 五对 + 双 soak；F guest stress 五对；C0 stress 一对 | 证据充分，报告中分开解释两种干扰变量 |
| 原生 Zephyr/RTOS 基线合理且可复现 | 5 | [`rt-baseline/zephyr`](rt-baseline/zephyr/)、[`results/native-zephyr-reference`](results/native-zephyr-reference/) | H：Zephyr v4.3.0 idle/stress 10,000 样本 | **平台为 QEMU `qemu_cortex_a53`，不是同一 RK3588；保守扣 2 分风险** |

任务一可辩护证据估计：`27/30`。最有效的补强是从最终提交 commit 重跑受控
host-noise 五对和双 soak，并在同一 Orange Pi 上裸跑 Zephyr 等价基线。

## 任务二：基于网络的客户机间通信（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| Starry/Linux—RTOS IP 网络链路与配置 | 4 | 两个 typed `virtio-net-mmio` 节点接入 AxVisor segment 1；Starry `10.0.0.1/24`，Zephyr `10.0.0.2:5500` | C0 fault-restart；F normal/fault campaigns | 证据充分 |
| 应用协议字段完整且位于 UDP/IP | 5 | [`ivcproto`](../tools/ivcproto/src/lib.rs)：magic/version/type/length/session/sequence/timestamp/error/CRC | H Rust+C 跨实现 golden/negative tests；C0 实际 UDP | 证据充分 |
| CONTROL、STATUS、错误通知可用 | 5 | Starry controller 与 Zephyr endpoint | C0：120 CONTROL 应用、122 STATUS/ACK、1 ERROR；F full campaigns | 证据充分 |
| ACK/超时/重传/乱序重复/重连恢复 | 4 | receive window、exactly-once duplicate suppression、retry、session retirement、safe fallback | F ACK-loss/error/restart 各 3/3；C0 actual VM reset | 证据充分 |
| 自动化测试数据 | 4 | board runner、analyzer、campaign aggregator | F 5×1,800 normal paired；3×fault；C0 machine summary/raw/checksum | 证据充分 |
| 网络隔离与访问控制 | 3 | 无 host NIC/default route/NAT/vsock；segment membership、精确单播、anti-spoof、unknown-unicast drop | H policy tests + D topology | **缺少恶意第三客户机实体/QEMU 动态负例；保守扣 1 分风险** |

任务二可辩护证据估计：`24/25`。

## 任务三：AI 控制闭环（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| StarryOS 中完成神经网络推理 | 4 | native 4×6×1、同源 ONNX、RKNN NPU、ONNX Runtime CPU 后端 | F RKNN/ORT 各 5×1,800；C0 native controller | 证据充分；不同后端结果分开标注 |
| 模型输出通过任务二协议发送 | 5 | controller `CONTROL` payload | C0/F raw 与 RTOS counters | 证据充分 |
| RTOS 根据输出执行可观察动作 | 5 | Zephyr actuator + deterministic thermal plant | C0 `applied=120`；F 9,000/9,000 | 证据充分 |
| 状态回传形成闭环 | 4 | `STATUS` 作为下一周期观测，`ACK` 确认 side effect | C0/F | 证据充分 |
| 端到端延迟方法与数据 | 3 | Starry 单时钟 round trip：pre-send / transport / full-loop | C0 100 post-reset samples；F full profiles | 证据充分；不做跨客户机时钟相减 |
| 与固定参数手动控制比较至少两项 | 4 | AB/BA 五对 manual/neural | F：RMSE 改善 35.93%，IAE 改善 51.94%；overshoot 退化 96.32% 被保留 | 证据充分且披露负向指标 |

任务三可辩护证据估计：`25/25`。

## 工程完整性与文档（15 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 设计方案完整 | 4 | [`design.md`](design.md) 覆盖 device graph、资源、协议、隔离、故障与测量边界 | 证据充分 |
| 测试文档完整 | 4 | [`test-report.md`](test-report.md)、机器 JSON、validation logs | 证据充分 |
| 源码和配置完整 | 4 | 当前 branch、typed device configs、stager/runner/analyzer；[`provenance.json`](results/current-source-smoke-20260812/provenance.json) | 证据充分 |
| 复现说明可操作 | 3 | [`reproduce.md`](reproduce.md)、source/input/checksum manifests | **精简包可复核；完整 844 MiB raw 档案尚无公开下载地址，保守扣 1 分风险** |

工程完整性可辩护证据估计：`14/15`。

## 创新与扩展性（5 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 实时/网络/控制方案创新 | 2 | device-graph typed virtual NIC/block、直接跨层 IRQ trace、受控 host interference、actual guest restart | 证据充分 |
| 扩展到更多 guest/RTOS/场景 | 2 | code-registered device model、segment/port、profile/backend 分层 | 设计与代码充分 |
| 代码质量与工程规范 | 1 | typed config/errors、fail-closed analyzer、atomic staging、checksum/readback、回归测试 | 证据充分 |

创新与扩展性可辩护证据估计：`5/5`。

## 加分项（最多 10 分）

| 加分项 | 分值 | 当前判断 |
| --- | ---: | --- |
| StarryOS 替代 Linux | 4 | **可主张 4 分**：当前实体 IVC 和 RT 客户机均为 StarryOS |
| StarryOS syscall 完善并合入 `dev` | 4 | **当前不主张**：本工作增强网络/文件系统/实体运行，但没有把新增 syscall 数量和已合入 upstream `dev` 的证据绑定到本提交 |
| 多 RTOS 或多开发板基线 | 2 | **当前不主张**：一个 Zephyr RTOS、一个 Orange Pi 5 Plus；QEMU 不是第二块开发板 |

## 保守汇总与下一步

按上述“证据可辩护”口径，当前主评分约为 `95/100`，可主张 StarryOS
替代 Linux `+4`；这不是官方评分。最值得投入的五项工作按收益排序：

1. 从最终提交 commit 重跑 RT 受控干扰五配对和 shared/partitioned 双 soak，消除历史 commit 与当前代码之间的证据断层。
2. 发布完整 844 MiB raw 证据归档（GitHub Release/LFS/不可变数据集），给出下载 URL、总 SHA-256 和逐文件 manifest。
3. 在同一 RK3588 上裸跑 Zephyr 的 idle/stress/soak 等价基线，记录时钟源、CPU 亲和和原始样本。
4. 增加恶意第三客户机动态隔离用例：跨 segment、MAC spoof、unknown unicast、无默认路由，并保留串口/pcap/计数器证据。
5. 如要争取额外 4 分，单独选择有明确 Linux ABI 依据的 StarryOS syscall 缺口，按项目规范实现、测试并真正合入 upstream `dev`；不要把普通平台修复包装成 syscall 加分。
