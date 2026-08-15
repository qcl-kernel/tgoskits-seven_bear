# 测试与证据报告

报告更新日期：2026-08-15。最终 IVC 实体板运行绑定 clean commit
`598b357f92c848e669c12cca830a4d08d0a50e36`；RT shared/partitioned 实体板运行绑定
`077ba386c20c29b84749f509b29e8a3f6f76e1e2`。两者都包含 `upstream/dev`
`56f8bfc8207f38d4b395dae0cf533ecdb079fca8`，二者之间只改动四个
`competition/ivc/` 路径，没有 RT runtime/config 变化。提交、Git tree、输入产物、
板卡身份和输出哈希统一记录在
[`provenance.json`](results/current-source-smoke-20260813/provenance.json)。

本报告严格区分四类证据：

| 标签 | 证据范围 | 可以支持的结论 |
| --- | --- | --- |
| C-IVC | `598b357f9…` 的 Orange Pi 5 Plus IVC fault-restart 实体冒烟 | 当前 device graph、构建、部署、双 guest 启动、实际 VM reset、会话恢复、快照和 Linux 回切链可用 |
| C-RT | `077ba386c…` 的 Orange Pi 5 Plus RT shared/partitioned 实体冒烟 | 当前 RT device graph、双 vCPU 放置、两侧采集、lossless IRQ trace、快照和 Linux 回切链可用 |
| F | 历史 clean commit 上预注册的正式实体板多轮活动 | 统计性性能、可靠性和 AI 对照结论；不得改标为当前源码结果 |
| H / D | host、QEMU、单元、契约、静态测试和设计溯源 | 软件边界、失败路径和机制存在；不得替代实体板时延 |
| H-IVC-RTOS | clean commit `ec3c363b1…` 的 RT-Thread/FreeRTOS AxVisor QEMU 双 Guest 活动 | Guest boot、VirtIO/IP、IVC/1 normal 与 ACK-loss 端点成立；不是 StarryOS 组合或实体板证据 |

## 1. 结论摘要

| 目标 | 结果 | 证据边界 |
| --- | --- | --- |
| StarryOS + Zephyr 从 typed device graph 启动 | PASS | C-IVC；StarryOS 2 vCPU、Zephyr 1 vCPU |
| 双客户机 UDP/IPv4 控制闭环 | PASS | C-IVC；fault-restart 共 accepted/applied 120/120 |
| 实际 Zephyr VM 重启与会话恢复 | PASS | C-IVC；pCPU3 上 `running → reset → running`，新旧 session 分离 |
| RT shared/partitioned 采集链 | PASS | C-RT；两侧三项 guest 指标各 100 样本、direct IRQ trace 无丢失、快照 clean、Linux 恢复 |
| 当前源码 RT 性能门 M2 | **FAIL** | 同 commit 单对 `m2_exit_gate_met=false`；periodic/dispatch p99 超出非退化门，且一对不足五配对正式矩阵 |
| RT 正式受控干扰门 | PASS | F；五配对、每指标每 run 10,000 样本、shared/partitioned 双 soak ≥1,800 秒 |
| manual/neural 控制效果 | 混合结果 | F；RMSE 和 IAE 改善，最大超调退化，完整披露 |
| ACK-loss、ERROR、VM restart 故障活动 | PASS | F 各 3/3；C-IVC 另有一次当前源码实际 restart |
| Zephyr、RT-Thread、FreeRTOS 原生对照 | PASS | H；三种 QEMU/AArch64 RTOS 均有 idle/stress 各 10,000 样本、固定源码和保留证据 |
| RT-Thread、FreeRTOS Guest/IVC | PASS | H-IVC-RTOS；normal/ACK-loss 共 4/4，每组 100/100，故障组各 20 次重传/去重/恢复 |
| 三客户机跨 segment 动态隔离 | PASS | H；VM3 发送 100 个 UDP 探针，VM1 观察 7 秒收到 0 个，VM3 default route=0 |
| 完整历史 raw 可公开下载 | **尚未完成** | 本地约 844 MiB；仓库提交精简索引和当前 C-IVC/C-RT raw，仍缺不可变公开 URL |

## 2. 当前源码实体板：IVC 重启恢复

板卡为 Orange Pi 5 Plus / RK3588，board service hardware ID
`bf61f4d4a1d994ad`，hostname `orangepi5plus`。正式 wrapper 以
`--require-clean --restore-linux` 运行，metadata 记录 `dirty=false`、tracked/untracked
均为 0、exit status 0。runner 在持有 lease 时原子部署 StarryOS kernel、DTB、重启
rootfs 和 Zephyr image，远端逐项验 SHA-256 后 `sync` 并冷启动 AxVisor。结束时：

- 64 MiB volatile guest block snapshot 的文件系统检查为 clean；
- 出现精确的 `AXVISOR_HOST_FILESYSTEM_SYNCED`；
- Linux 恢复到 `/dev/mmcblk1p2` ext4 读写挂载；
- 板温为 41.615 °C，wrapper 总耗时 243 秒。

输入哈希：

| 输入 | SHA-256 |
| --- | --- |
| StarryOS kernel | `7763df597850f5edb05d4929b980801764d6dacabc39022c7871ff7cacfdf46c` |
| Orange Pi DTB | `bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981` |
| StarryOS restart rootfs | `1c15956bce9f2bf8adb18e6977e33acb97eb22af0b613cad22914dd79165596d` |
| Zephyr guest | `7153dfca0787eab0d516b39b1f459a4e02fcf09ca1c831673c5df33864b8261b` |
| native neural source | `6057046eabd5cb23b38760c1b8ef4369453e7addbabcd71f61b65284732ff5b4` |

实际重启由 pCPU3 worker 延时 20,000 ms 触发，观察延时也是 20,000 ms，
`reset_count=1`。旧 session `286331153` 被退休，新 session `572662306` 被接受。
重启前保留 20 个样本，重启后 100/100 指令确认；controller
error/timeout/retransmission 均为 0，Zephyr accepted/applied 为 120/120。故障探针
还确认 safe fallback、session reset/rejection、retired CONTROL rejection、stale
STATUS ignore、stale ACK ignore 和恢复各发生一次。这证明重启安全与闭环恢复，不是
无扰动稳态性能。

重启后 100 样本测量：

| 指标 | 结果 |
| --- | ---: |
| success / throughput | 100% / 9.721 msg/s |
| full-loop p50 / p95 / p99 / max | 2,340 / 2,551 / 24,692 / 344,033 µs |
| deadline miss | 1 |
| RMSE | 20,435.735 m°C |
| IAE | 185,638.1 m°C·s |
| 最大超调 | 0 m°C |

机器 summary、metadata、原始/压缩 CSV、串口、staging log 和 runner manifest 位于
[`ivc/`](results/current-source-smoke-20260813/ivc/)。

## 3. 当前 RT 实体板：shared/partitioned 冒烟

C-RT 从同一 clean source 重建 StarryOS kernel 和 64 MiB capture rootfs，经过部署、
冷启动、双 vCPU 采集、volatile block 快照、AxVisor host filesystem sync、关机与
Linux 恢复。两侧 vCPU0/1 的物理掩码分别为 `0x2`/`0x4`，迁移次数均为 0；shared
guest/host 直接 IRQ trace 为 880/1,094 条，partitioned 为 888/1,097 条；dropped、
incomplete、failed injection 和 counter frequency mismatch 均为 0。

输入哈希：

| 输入 | SHA-256 |
| --- | --- |
| StarryOS RT kernel | `d163d4c55f740a5040cafd3d3919dd90f9f80f020e23ab1e7c70ccb7b52deb94` |
| Orange Pi DTB | `bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981` |
| capture rootfs | `26a45d4e333dc6039d17d8774ac185a4c3d3b2301dfb23c5803ae89755768626` |
| static RT probe | `8b3f6e7471dc9ecf60d5b64ab5f3c3a4657af8743fde1aa6b1772358c62806da` |

| 指标（ns） | shared p99 / max | partitioned p99 / max | p99 改善 |
| --- | ---: | ---: | ---: |
| periodic jitter | 206,917 / 214,709 | 322,208 / 325,250 | -55.718% |
| dispatch latency | 57,750 / 199,792 | 128,625 / 205,334 | -122.727% |
| timerfd IRQ proxy | 7,780,541 / 8,720,166 | 7,645,209 / 8,583,084 | +1.739% |
| virtual timer injection → guest IRQ | 12,181,166 / 413,733,833 | 11,161,208 / 413,913,500 | +8.373% |

比较器原样保留 `m2_exit_gate_met=false`：正值表示 partitioned 较低，但 periodic 和
dispatch p99 退化，且该 smoke 只有一对、没有 controlled host interference，不能满足
五配对正式矩阵。C-RT 因而支持“两侧移植链路可用”，不支持“当前单对性能改善”。

## 4. 历史正式 RT 活动

### 4.1 受控 host interference

精简材料位于
[`historical-formal/rt-host-noise`](results/current-source-smoke-20260813/historical-formal/rt-host-noise/)。
正式 batch 的 measurement commit 为 `0588743ecb807d7363a3dec90c17a159179933b0`，
soak 的 measurement commit 为 `2e97430f2171667d4ec16c3a02931653f7ddedf8`。

五个 AB/BA 配对各对 shared 和 partitioned 采集，每个 guest 指标每 run 10,000
样本，并完成两侧 ≥1,800 秒 soak，`m2_exit_gate_met=true`。干扰模型刻意将 host
activity 放入 shared guest 的 CPU 路径，故改善只适用于该 treatment，不能外推到
所有 workload。

| 正式门指标 | 五对结果 / worst-of-runs |
| --- | ---: |
| direct IRQ p99 | 5/5 改善；worst-of-runs 改善 99.639% |
| direct IRQ max | 5/5 改善；worst-of-runs 改善 87.771% |
| dispatch p99 | 5/5 非退化；worst-of-runs 改善 28.111% |
| dispatch max | 5/5 改善；worst-of-runs 改善 99.773% |

### 4.2 同 VM guest CPU1 stress

[`historical-formal/rt-stress`](results/current-source-smoke-20260813/historical-formal/rt-stress/)
包含五对、十次 lossless capture 和 300,000 个 guest 用户态样本。该 workload 与被测
任务位于同一 VM，不能作为隔离 treatment；结果也是混合的：dispatch p99 五对均
退化，worst-of-runs max 退化 10.443%。因此不主张 partitioning 对所有压力源普遍
降低时延。

## 5. 历史正式 IVC 与 AI 活动

### 5.1 manual/neural AB/BA 五配对

正式 v5 活动绑定 `f4ced37584964aba56e07ff060ae58374608bc26`，五个 AB/BA 配对
的 10/10 run 均有效；精简材料位于
[`historical-formal/ivc-control`](results/current-source-smoke-20260813/historical-formal/ivc-control/)。

| 控制指标 | manual | neural | neural 相对变化 |
| --- | ---: | ---: | ---: |
| RMSE (m°C) | 9,258.906 | 5,932.491 | 改善 35.93% |
| IAE (m°C·s) | 1,429,224.7 | 686,993.4 | 改善 51.94% |
| 最大超调 (m°C) | 6,840 | 13,428 | **退化 96.32%** |

full-loop p99 只有 2/5 配对有利于 neural，因此不声称神经策略延迟更低；它以更高
超调换取更低累计控制误差。

### 5.2 可靠性故障活动

| 活动 | source commit | 正式结果 | 被验证机制 |
| --- | --- | ---: | --- |
| ACK loss | `bac4ad16b4adf673942e6c31897872c2c5c116dc` | 3/3 | timeout、重传、重复抑制、exactly-once apply |
| typed ERROR | `29be4fc4c8668b8e94cd253fb4484bbeba1d8481` | 3/3 | 错误通知与失败闭合 |
| actual VM restart | `6adf49e09ce91b53d2573cb8d34c60dc6a9ec47c` | 3/3 | 新 session、旧流量拒绝、safe fallback、恢复 |

### 5.3 神经推理后端

| 后端 | source commit | 样本 | 结果 |
| --- | --- | ---: | --- |
| RKNN / RK3588 NPU | `c3f01dc34b83695eddf8da83cf4ed71622f64f7c` | 5 × 1,800 | 9,000/9,000；仅每 run 首周期 miss；device p99 ≈1.67 ms |
| ONNX Runtime / CPU | `0110647de52f5e2ad6b550cb594780d7506ffecf` | 5 × 1,800 | 9,000/9,000；仅每 run 首周期 miss；ORT wall p99 约 174–176 µs |

两种后端的 full-loop p99 约 12–13.5 ms。它们证明 StarryOS 内推理部署和网络闭环，
不把不同执行设备的墙钟值当作公平加速比。

## 6. QEMU 原生多 RTOS 与三客户机隔离

### 6.1 原生 RTOS idle/stress

三种 RTOS 都直接运行于等价 QEMU/AArch64 平台，不经过 AxVisor。每个 workload
使用 1 ms 周期、100 次 warm-up 和 10,000 个保留样本。下表为单次参考 capture，
单位为 ns：

| RTOS | Workload | wake p99 / max | dispatch p99 / max | 负载验证 | 完成记录 |
| --- | --- | ---: | ---: | --- | --- |
| Zephyr v4.3.0 | idle | 186,256 / 841,264 | 40,288 / 162,896 | idle 988‰ | measured coalescing 0 |
| Zephyr v4.3.0 | stress | 669,408 / 6,236,608 | 134,912 / 1,141,536 | stress 985‰ | measured coalescing 68，全部保留在样本中 |
| RT-Thread v5.2.2 | idle | 179,792 / 441,824 | 43,696 / 143,984 | idle 1,000‰ | timer miss 0，early wake 0 |
| RT-Thread v5.2.2 | stress | 190,784 / 4,848,912 | 45,408 / 199,312 | stress 1,000‰ | timer miss 0，early wake 0 |
| FreeRTOS `f1043c49…` | idle | 209,136 / 4,370,096 | 62,480 / 642,816 | idle 983‰ | timer miss 0，early wake 0 |
| FreeRTOS `f1043c49…` | stress | 201,888 / 3,483,376 | 58,144 / 475,872 | stress 984‰ | timer miss 0，early wake 0 |

RT-Thread/FreeRTOS 原生结果来自 2026-08-14 的 clean upstream source attestation；
summary、原始 console/build gzip、hash 和复现命令分别位于
[`native-rtthread-reference`](results/native-rtthread-reference/) 与
[`native-freertos-reference`](results/native-freertos-reference/)。这些数据支持
“多原生 RTOS 等价平台对照”，本身不支持 AxVisor Guest/IVC 结论；后者由下一节
完全独立的运行路径和证据支持。

### 6.2 RT-Thread/FreeRTOS Guest/IVC

2026-08-15 在 clean commit `ec3c363b1a61956069365a06c262091ce847b335` 上用
QEMU 6.2.0 TCG/Cortex-A72 运行 AxVisor，VM1 为双 vCPU Linux controller，VM2
分别替换为单 vCPU RT-Thread 或 FreeRTOS endpoint。四次
runner 均先验证固定上游、Guest SHA-256、ELF entry/非空 `LOAD` 区间和显式 rootfs，
再由严格 analyzer 核对 RTOS 身份、profile 与计数。

| Endpoint / profile | accepted / applied | duplicate / drop | ACK / retransmit / recovery | protocol error |
| --- | ---: | ---: | ---: | ---: |
| RT-Thread normal | 100 / 100 | 0 / 0 | 100 / 0 / 0 | 0 |
| RT-Thread ACK-loss | 100 / 100 | 20 / 20 | 100 / 20 / 20 | 0 |
| FreeRTOS normal | 100 / 100 | 0 / 0 | 100 / 0 / 0 | 0 |
| FreeRTOS ACK-loss | 100 / 100 | 20 / 20 | 100 / 20 / 20 | 0 |

ACK-loss 固定丢弃序号 5、10、…、100 的确认，20 个重复 CONTROL 均返回状态与 ACK
但不再次应用。RT-Thread 首次运行暴露 MMU 开启后直接访问 `0x0b000000` 的 translation
fault；先加入失败回归，再用 `rt_ioremap` 建立 Device mapping，重建后的两种 profile
均通过。紧凑机器记录、压缩完整日志、输入/summary 哈希和 clean-commit 边界位于
[`rtos-guest-ivc-qemu-20260815`](results/rtos-guest-ivc-qemu-20260815/)。完整 raw 保留
在记录所列的 `tmp/competition/final-evidence-ec3c363b1/` 目录，可由 [`reproduce.md`](reproduce.md)
第 4.4 节重新生成。

该证据不声称 RT-Thread/FreeRTOS 已在 RK3588 运行，也未实际替换实体路径中的
StarryOS controller。轮询 RX、QEMU host scheduling、RT-Thread 上游编译 warning 和
FreeRTOS/Bao RWX `LOAD` linker warning 均保留为已知边界。

### 6.3 三客户机动态隔离

QEMU 使用 4 个 Cortex-A72：AxVisor 位于 pCPU0，三个单 vCPU ArceOS guest 分别固定
到 pCPU1/2/3。VM1 `10.0.2.15` 与 VM2 `10.0.2.16` 位于 segment 1，完成
65,536-byte TCP 交换并核对 checksum `0x7f8000`；VM3 `10.0.2.17` 位于 segment 2，
验证 default route 数量为 0 后向 `10.0.2.255:5002` 发送 100 个 UDP 探针，guest
NIC TX 计数增加 100。VM1 预先绑定 UDP 端口并在 TCP 完成后观察 7,000 ms，收到
跨 segment 探针数为 0。三台 guest 均到达 terminal pass marker。

完整 60,342-byte QEMU/build log 的 gzip 与机器 summary 位于
[`axvisor-isolation-reference`](results/axvisor-isolation-reference/)。该 capture 绑定
clean commit `ec3c363b1a61956069365a06c262091ce847b335`，不是实体板证据；动态覆盖
segment separation 与无默认路由，MAC spoof/unknown-unicast 仍由
`axvm-net` 最低层 policy tests 覆盖。

## 7. 源码、设备图与产物溯源

端口后的运行入口均使用当前 typed device graph：设备资源由配置声明并经
parse/validate/allocate/instantiate 阶段进入 VM，OS/guest 不再依赖旧的隐式全局设备
表。AArch64 路径同时覆盖双 vCPU VBAR 保存恢复、stage-2 VTCR、虚拟 timer deadline
claim、PSCI `CPU_ON` 异步生命周期以及无抢占 guest console mux。

证据包提供四层绑定：

1. `provenance.json` 绑定 commit/tree、upstream、板卡、输入产物和运行结论；
2. `source-delta.txt` 证明 C-RT 到 C-IVC 之间没有 RT/runtime/config 变化；
3. `runtime-inputs.sha256` 使用实体运行 Linux clean checkout 的 LF 字节哈希；
4. `source-files.git-ls-tree.txt` 映射相关 Git blob，总 manifest 覆盖交付文件。

`commands/` 是带 clean/source 断言的可复用 wrapper；跨机器步骤见
[`reproduce.md`](reproduce.md)。

## 8. 已执行验证

已执行的实体、QEMU 和 host 验证包括；每项结论继续受前述证据层级约束：

- 冻结历史证据对应的 IVC 完整 test discovery：194/194；analyzer 单元测试：77/77；
- Zephyr v4.3.0 guest：190-step `-Wall -Wextra -Werror` cross build 与 host tests；
- `arm_vcpu`：13/13；`axvm` host-test：273 项及 device-graph boundary/contract tests；
- `axvm` 八个 feature matrix、`arm_vcpu`、`axbuild` targeted clippy；
- AArch64 QEMU `axtest` 80/80 与 dedicated-smp2 1/1 marker、RT Python
  tests/shell runners、rustfmt；
- 当前 raw 的重新分析、JSON/gzip、Markdown 链接、五分钟媒体与 bundle checksum；
- RTOS 公共 C 统计/miss accounting、Python analyzer 负例、RT-Thread 配置测试；
- RT-Thread 与 FreeRTOS idle/stress 原生 QEMU 端到端构建、运行和 analyzer 验证；
- RT-Thread 与 FreeRTOS AxVisor Guest/IVC normal、ACK-loss 共 4/4，含共享 C host
  tests、ELF/config 负例、严格身份/计数分析和证据 checksum；
- 三 guest AxVisor/ArceOS QEMU 动态隔离运行，64 KiB 同 segment TCP 与 100 个跨
  segment 探针后零接收；
- 确定性 evidence packager 的相同字节、拒绝覆盖、输出边界和重复 manifest 负例。

本次升级在 clean commit `ec3c363b1…` 上执行的 RTOS Guest/IVC focused Python suite 为 36/36，公共
fake-MMIO/transport host tests、Zephyr host logic tests 和原生 RTOS 公共逻辑测试 7/7
均通过。Windows 环境的全量 IVC discovery 未列为本次通过项：部分既有 campaign
shell 脚本使用 CRLF、部分板端 fixture 的 raw SHA 与快照记录不一致，且 RKNN reference
tests 缺少 NumPy 依赖；这些问题不属于本次 RTOS Guest/IVC 改动范围，也未通过放宽测试规避。

实体冒烟对应的最终命令输出保存在
[`validation/`](results/current-source-smoke-20260813/validation/)；新增 QEMU 运行的
console/build 日志和机器 summary 分别保存在第 6 节链接的参考证据目录。

## 9. 测量限制与待补强项

- 当前 C-RT 同 commit 单对 M2 为 **FAIL**；若要闭合当前源码的正式性能主张，仍应
  重跑预注册五配对和双 soak，不能把历史 F 层结果改标成当前提交。
- 完整历史 raw archive 仍只在本地 `results/orangepi-5-plus/`；应发布不可变下载和
  总 SHA-256，仓库中的精简 summary 不能重算全部历史统计。
- 三种原生 RTOS 基线和新增 RT-Thread/FreeRTOS Guest/IVC 都是等价 QEMU 平台，
  不是同一 RK3588，无法消除硬件、时钟源和 QEMU/host scheduling 差异；新增端点
  也尚未与实体 StarryOS controller 组合验证。
- 三客户机隔离是 QEMU 动态 capture，不是实体板；动态 spoof/unknown-unicast 流量
  尚未加入该端到端 case，但对应最低层 policy tests 已存在。
- 五分钟视频是已归档实体串口与机器 JSON 的后验回放，不伪装成现场同步拍摄。
- 所有 maximum 都是观察样本最大值，不是 WCET 证明或硬实时上界。
