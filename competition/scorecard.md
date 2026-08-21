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
| F | 历史 clean commit 上预注册的正式多轮实体板活动；完整 raw 已发布到不可变 GitHub Release [`historical-raw-20260818`](https://github.com/yueneiqi/tgoskits-competition-evidence/releases/tag/historical-raw-20260818)，仓库中的精简 summary/preregistration 继续用于快速审阅 |
| H | host/QEMU/单元/契约测试；只能证明相应软件边界，不能替代实体板时延 |
| H-RTOS | Zephyr、RT-Thread、FreeRTOS 原生 QEMU/AArch64 idle/stress 基线；证明等价平台的可复现对照，不是 RK3588 裸机结果 |
| H-IVC-RTOS | RT-Thread、FreeRTOS 在 AxVisor QEMU/AArch64 下的双 Guest normal/ACK-loss 活动；证明 Guest boot、VirtIO/IP 和 IVC/1 端点，不替代 StarryOS/实体板组合证据 |
| H-ISO | 三个 ArceOS guest 的 AxVisor QEMU 动态隔离活动；证明 segment 分离和无默认路由，不替代实体板或动态 spoof 测试 |
| P-NATIVE | 2026-08-18 Orange Pi 5 Plus / RK3588 原生 Zephyr idle、stress 和约 30 分钟 soak；同板补充基线，不经过 AxVisor |
| P-IVC-RTOS | 2026-08-18 Orange Pi 5 Plus 上 StarryOS 分别与 RT-Thread、FreeRTOS 的实体 Guest/IVC smoke；证明两种 RTOS 的同板端点与完整恢复链，不替代正式长时性能活动 |
| P-VISION | 2026-08-18 Orange Pi 5 Plus 上 StarryOS RKNN/NPU 固定帧 → UDP/IP → Zephyr 动作/状态闭环；证明 3 帧确定性视觉闭环，不主张 Guest 实时 UVC/FPS |
| R | 两个公开、非 draft、非 prerelease 的不可变 GitHub Release；正式 RT 与历史 raw 的 archive、manifest、sidecar 及服务端 digest 均公开 |
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
| 原生 Zephyr/RTOS 基线合理且可复现 | 5 | [`rt-baseline`](rt-baseline/)；Zephyr v4.3.0、RT-Thread v5.2.2、FreeRTOS Kernel `f1043c49…`；[`orangepi-native-zephyr-20260818`](results/orangepi-native-zephyr-20260818/) | H-RTOS：三种 RTOS 均完成 QEMU idle/stress、每组 10,000 样本；P-NATIVE：同一 RK3588 的 Zephyr idle/stress/soak 均 10,000 样本、零 miss | **等价平台复现与同板补充对照均已具备；串口证据不是逐样本 CSV 的边界已披露** |

任务一可辩护证据估计：`30/30`。同一 Orange Pi 5 Plus 已增加原生 Zephyr
idle/stress/soak 补充对照；正式虚拟化性能结论仍只由 C-RT-F 承担。

## 任务二：基于网络的客户机间通信（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| Starry/Linux—RTOS IP 网络链路与配置 | 4 | typed `virtio-net-mmio` 节点接入 AxVisor segment 1；controller `10.0.0.1/24`，RTOS `10.0.0.2:5500` | C-IVC Starry/Zephyr；H-IVC-RTOS QEMU；P-IVC-RTOS 实体 Starry/RT-Thread/FreeRTOS | 证据充分；两种新增 RTOS 已在真实 RK3588 与 StarryOS 组合运行 |
| 应用协议字段完整且位于 UDP/IP | 5 | [`ivcproto`](../tools/ivcproto/src/lib.rs)：magic/version/type/length/session/sequence/timestamp/error/CRC | H Rust+C 跨实现 golden/negative tests；C-IVC 与 H-IVC-RTOS 实际 UDP | 证据充分 |
| CONTROL、STATUS、错误通知可用 | 5 | Starry/Linux controller 与共享 RTOS endpoint core | C-IVC：120 CONTROL 应用、122 STATUS/ACK、1 ERROR；H-IVC-RTOS 各 100/100；P-IVC-RTOS 两种 RTOS 各 20/20 | 证据充分 |
| ACK/超时/重传/乱序重复/重连恢复 | 4 | receive window、exactly-once duplicate suppression、retry、session retirement、safe fallback | F ACK-loss/error/restart 各 3/3；C-IVC actual VM reset；H-IVC-RTOS 各 20 次重传/去重/恢复 | 证据充分 |
| 自动化测试数据 | 4 | board/QEMU runner、strict analyzer、campaign aggregator | F 5×1,800 normal paired；3×fault；C-IVC、H-IVC-RTOS 与 P-IVC-RTOS 均有 machine summary/raw/checksum | 证据充分；实体 RTOS smoke 另验证 PSCI off、snapshot fsck 和 Linux rw 恢复 |
| 网络隔离与访问控制 | 3 | 无 host NIC/default route/NAT/vsock；segment membership、精确单播、anti-spoof、unknown-unicast drop；第三 guest 位于 segment 2 | H policy tests + D topology + H-ISO：VM3 发 100 个跨 segment UDP 探针、VM1 观察 7 秒收到 0 个、VM3 default route=0 | 证据充分；动态 spoof/unknown-unicast 仍由最低层 policy tests 覆盖 |

任务二可辩护证据估计：`25/25`。

## 任务三：AI 控制闭环（25 分）

| 细则 | 分值 | 实现入口 | 证据 | 当前判断 |
| --- | ---: | --- | --- | --- |
| StarryOS 中完成神经网络推理 | 4 | native 4×6×1、同源 ONNX、RKNN NPU、ONNX Runtime CPU 后端；YOLOv8 固定帧 | F RKNN/ORT 各 5×1,800；C-IVC native controller；P-VISION 真实 RKNN/NPU | 证据充分；热控与视觉、不同后端结果分开标注 |
| 模型输出通过任务二协议发送 | 5 | controller `CONTROL` 与独立版本化 `VISION_DECISION` payload | C-IVC/F raw 与 RTOS counters；P-VISION 三个独立 frame/decision | 证据充分 |
| RTOS 根据输出执行可观察动作 | 5 | 共享 actuator + deterministic thermal plant；视觉挡板 right/left/hold；Zephyr、RT-Thread、FreeRTOS adapter | C-IVC `applied=120`；F 9,000/9,000；H-IVC-RTOS 各 100；P-IVC-RTOS 各 20；P-VISION 3/3 请求等于实际动作 | 证据充分；视觉场景可直接展示检测到挡板动作 |
| 状态回传形成闭环 | 4 | `STATUS`/`ACTUATOR_STATUS` 回传实际 side effect | C-IVC/F；H-IVC-RTOS 4/4；P-IVC-RTOS 2/2；P-VISION 3/3 | 证据充分 |
| 端到端延迟方法与数据 | 3 | Starry 单时钟 round trip：pre-send / transport / full-loop | C-IVC 100 post-reset samples；F full profiles；P-VISION transport median 11,786 µs、fixed-frame full-loop median 2,008,428 µs | 证据充分；视觉 full-loop 包含逐帧进程启动，不外推连续视频 FPS |
| 与固定参数手动控制比较至少两项 | 4 | AB/BA 五对 manual/neural | F：RMSE 改善 35.93%，IAE 改善 51.94%；overshoot 退化 96.32% 被保留 | 证据充分且披露负向指标 |

任务三可辩护证据估计：`25/25`。

## 工程完整性与文档（15 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 设计方案完整 | 4 | [`design.md`](design.md) 覆盖 device graph、资源、协议、隔离、故障与测量边界 | 证据充分 |
| 测试文档完整 | 4 | [`test-report.md`](test-report.md)、机器 JSON、validation logs | 证据充分 |
| 源码和配置完整 | 4 | 当前 branch、typed device configs、stager/runner/analyzer；[`provenance.json`](results/current-source-smoke-20260813/provenance.json) | 证据充分 |
| 复现说明可操作 | 3 | [`reproduce.md`](reproduce.md)、source/input/checksum manifests、[`axvisor-rt-formal-20260816-c82da8464`](https://github.com/yueneiqi/tgoskits-competition-evidence/releases/tag/axvisor-rt-formal-20260816-c82da8464)、[`historical-raw-20260818`](https://github.com/yueneiqi/tgoskits-competition-evidence/releases/tag/historical-raw-20260818) | **两个完整 raw archive 均已公开；release asset digest 与仓库/sidecar SHA-256 一致** |

工程完整性可辩护证据估计：`15/15`。

## 创新与扩展性（5 分）

| 细则 | 分值 | 证据 | 当前判断 |
| --- | ---: | --- | --- |
| 实时/网络/控制方案创新 | 2 | device-graph typed virtual NIC/block、直接跨层 IRQ trace、受控 host interference、actual guest restart | 证据充分 |
| 扩展到更多 guest/RTOS/场景 | 2 | code-registered device model、segment/port、profile/backend 分层；RT-Thread 与 FreeRTOS 共享 transport/core、独立 OS glue；独立视觉消息 | H-IVC-RTOS 4/4、P-IVC-RTOS 2/2、P-VISION 3/3，设计、代码与实体 smoke 充分 |
| 代码质量与工程规范 | 1 | typed config/errors、fail-closed analyzer、atomic staging、checksum/readback、回归测试；`verify_delivery.py` 将 32 个 compact 文件、5 份 QEMU 日志、113 项 raw 清单、业务门槛和源码输入新鲜度接入 CI | 证据充分 |

创新与扩展性可辩护证据估计：`5/5`。

## 加分项（最多 10 分）

| 加分项 | 分值 | 当前判断 |
| --- | ---: | --- |
| StarryOS 替代 Linux | 4 | **可主张 4 分**：当前实体 IVC 和 RT 客户机均为 StarryOS |
| StarryOS syscall 完善并合入 `dev` | 4 | **合入前仍不主张**：`sync_file_range` errno 优先级修复已提交为 upstream [`rcore-os/tgoskits#2100`](https://github.com/rcore-os/tgoskits/pull/2100)，含 Linux 对照与 pre-fix/post-fix 回归；加分项明确要求合入 `dev`，PR open 不能冒充 merge，且单项修复也不外推为满额数量 |
| 多 RTOS 或多开发板基线 | 2 | **可主张 2 分**：三种原生 RTOS 基线均有固定上游与保留证据；Zephyr 已在 RK3588 原生运行，RT-Thread/FreeRTOS 已在同板完成独立 Guest/IVC；不以 QEMU 冒充第二块开发板 |

## 保守汇总与下一步

按上述“证据可辩护”口径，当前主评分约为 `100/100`，可主张 StarryOS
替代 Linux `+4` 和多 RTOS `+2`，合计加分 `+6`；这不是官方评分。最值得投入的
后续工作按收益排序。原建议 1–5 已完成，第 6 项的实现、回归和上游提交已完成；两轮
CI 的唯一失败均为 RISC-V 全量套件在不同无关用例处非确定性挂起，关联的上游调度修复
为 [`#2101`](https://github.com/rcore-os/tgoskits/pull/2101)。当前账号对 upstream 只有
`READ` 权限，实际 auto-merge 已被 GitHub 以缺少 `MergePullRequest` 权限拒绝；最终合入
仍取决于该修复、上游维护者与必需检查：

| 原优先级 | 完成情况 | 可核验证据 |
| ---: | --- | --- |
| 1 | 完成 | 正式 RT archive 42,722,019 bytes；SHA-256 `68c1efb1ae0338692a84943c7056e104e2abed9e62a89dcdb0e2540ea1f9859e`；公开 Release 见 R |
| 2 | 完成 | 历史 raw archive 87,648,734 bytes（解包约 844 MiB）；SHA-256 `8080f696a3100994a77165743360b14408fc3047eb6f0981f5e41e2b6f46e1f5`；公开 Release 见 R |
| 3 | 完成阶段 A | P-VISION：真实 RK3588、真实 RKNN/NPU、三帧 `right/left/hold` 3/3；明确不主张 Guest 实时 UVC/FPS |
| 4 | 完成 | P-NATIVE：同一 RK3588 上 Zephyr idle/stress/约 30 分钟 soak，三组均 10,000 样本、零 miss |
| 5 | 完成 | P-IVC-RTOS：StarryOS 分别与 RT-Thread、FreeRTOS 在实体 RK3588 完成 20/20，含 PSCI off、快照 fsck 与 Linux rw 恢复 |
| 6 | 完成实现与提交；待上游合入 | [`rcore-os/tgoskits#2100`](https://github.com/rcore-os/tgoskits/pull/2100)：`sync_file_range` errno precedence 已有 Linux 16/16 对照、pre-fix StarryOS QEMU 15/16 红测与 post-fix 16/16；第一轮 RISC-V CI 中本用例也为 16/16，随后无关 suite 挂起；提交 `ffc92277f0` 已 rebase 到 `dev@c76ee0d121`，最终只以 PR 实际 merge 状态主张加分 |
