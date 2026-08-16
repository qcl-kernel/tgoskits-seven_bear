# 智能化工控虚拟化混合系统项目周报

> 统计日期：2026-08-16
>
> 对照基线：`upstream/dev` `56f8bfc8207f38d4b395dae0cf533ecdb079fca8`
>
> 当前交付分支：`feat/rt-axvisor-partition-virtio-net`；正式 RT 复验绑定 clean commit `77704718a1b46fc2fbf51ea6a184aa1071eee0ac`，RT-Thread/FreeRTOS Guest/IVC 与三客户机隔离的 QEMU 复验绑定 clean commit `16a1f3198243a5e1b1bc1810faba6371f7de3215`

## 本周概述

围绕赛题“智能化工控中基于虚拟化的混合系统部署及联动实现”，已完成从
AxVisor 多客户机部署、StarryOS 与 Zephyr RTOS 的 IP 网络互联，到神经网络控制与
RTOS 执行/回传的演示链路，并在 Orange Pi 5 Plus（RK3588）上补充当前源码实体板
冒烟证据、可复现脚本和结果校验材料；同时新增 RT-Thread 与 FreeRTOS 原生
QEMU/AArch64 实时基线，并进一步完成两者的 AxVisor Guest/IVC normal 与 ACK-loss
端点、三客户机动态网络隔离用例和确定性证据归档工具；并完成当前实现的实体板
正式五配对与双侧 30 分钟 soak，使 M2 实时性能门从诊断失败转为正式通过。

一句话总结：本周完成当前实现的实体板五配对与双侧 30 分钟 soak，M2 正式门通过，
同时将 RT-Thread、FreeRTOS 升级为可运行的 AxVisor Guest/IVC 端点并补齐三客户机
动态隔离证据。

当前方案以 StarryOS 替代 Linux 作为通用客户机：StarryOS 使用 2 个 vCPU、256 MiB
内存，Zephyr 使用 1 个 vCPU；两侧通过 AxVisor device graph 创建的 virtio-net-mmio
设备接入同一隔离二层网段。主数据通道为 UDP/IPv4，不使用 vsock、共享内存或
HyperCall 传输应用数据。

## 已完成工作与阶段结果

### 1. 实时化改造与验证（赛题任务一）

- 完成 AxVisor 的 dedicated CPU/vCPU 放置、虚拟 timer、GIC/IRQ 路径、直接 IRQ
  trace、预分配采集与 device graph 资源声明等改造；支持多核 StarryOS 客户机稳定
  启动。
- 在 Orange Pi 5 Plus 上完成 shared 和 partitioned 两种双 vCPU 配置的当前源码实体
  冒烟。vCPU 的物理 CPU 掩码为 `0x2`、`0x4`，两侧均记录为 0 次迁移；采集链、快照、
  host 文件系统同步和 Linux 回切均通过。
- 已完成历史正式的受控 host interference 五配对和 shared/partitioned 双侧 1,800 秒
  soak。该受控场景中，direct IRQ 最大延迟的 worst-of-runs 改善为 87.771%，dispatch
  最大延迟改善为 99.773%；同 VM CPU stress 的结果为混合结果，已单独保留并不外推。
- 从 clean commit `77704718a…` 重新完成当前正式五配对 AB/BA 矩阵和双侧 soak：
  四项 max 均为 5/5 改善；dispatch、emulated IRQ、periodic jitter、direct IRQ 的
  worst-of-runs 分别改善 99.504%、99.465%、99.513%、47.234%，全部 p99 配对通过
  5% 非退化门，机器给出 `m2_exit_gate_met=true`。shared/partitioned soak 分别运行
  1,864.332/1,845.872 秒，采集 229,046/440,413 个 direct IRQ pairs。
- 已将原生 RTOS 对照从 Zephyr v4.3.0 扩展到 RT-Thread v5.2.2 与 FreeRTOS：三者均
  提供固定上游版本、idle/stress 两种 workload、100 次 warm-up、10,000 个 1 ms
  周期样本、负例分析器和不可覆盖证据目录。新增两组结果均为零 timer miss/early wake：
  RT-Thread idle/stress wake p99 为 179,792/190,784 ns，FreeRTOS 为
  209,136/201,888 ns。
- 三种原生基线均运行于等价 QEMU/AArch64 平台，并非同一 RK3588 裸机结果；其
  数据仍只作为原生实时对照。另行实现和验证的 RT-Thread/FreeRTOS AxVisor
  Guest/IVC 路径使用独立 runner 和证据，不由原生结果推导。

说明：2026-08-13 的 100 样本单对冒烟仍以 `m2_exit_gate_met=false` 原样保留，
只作为诊断证据；当前性能结论仅来自 2026-08-16 的预注册五配对和双 soak，不把两批
样本拼接统计，也不将观察最大值表述为 WCET。

### 2. 基于网络的客户机间通信（赛题任务二）

- 建立 StarryOS（`10.0.0.1/24`）与 Zephyr（`10.0.0.2:5500`）之间的隔离
  UDP/IPv4 网络链路；虚拟网络未连接 host NIC、NAT、默认路由或 vsock。
- 实现 IVC/1 应用层协议，包含 magic、版本、消息类型、负载长度、session、序号、
  时间戳、错误码和 CRC 字段；支持 CONTROL、STATUS、ACK 和 ERROR 消息。
- 实现 ACK、超时重传、重复/乱序抑制、session 退休、旧流量拒绝、安全回退和客户机
  重启后的恢复逻辑，并配套 Rust/C 跨实现、负例和分析器测试。
- 当前源码在实体板完成一次实际 Zephyr VM 重启恢复：重启前 20 个、重启后 100 个
  指令均完成，RTOS 共 accepted/applied `120/120`；安全回退、旧 CONTROL 拒绝和陈旧
  STATUS/ACK 忽略均被验证，运行器退出码为 0。
- 历史正式实体板活动已完成 ACK-loss、ERROR、实际 VM restart 三类故障场景各 3/3 次，
  为通信可靠性结论提供多轮证据。
- 新增共享 VirtIO 1.x MMIO raw Ethernet driver 与 RTOS IVC server，分别接入
  RT-Thread lwIP 和 FreeRTOS-Plus-TCP；固定上游、ELF entry/LOAD、RAM、MMIO、MAC、
  segment 与 12-byte header 均由脚本或契约测试校验。
- RT-Thread/FreeRTOS 各完成 normal 与每 5 次丢 1 个 ACK 两组 AxVisor QEMU 双
  Guest 活动，共 4/4 通过。每组 accepted/applied 与 controller ACK 均为 100/100；
  两个故障组各得到 20 次丢 ACK、20 次 duplicate suppression、20 次重传恢复，
  且 protocol error 为 0。
- RT-Thread 首次实跑发现 MMU 下直接访问 Guest MMIO GPA 的 translation fault；按
  先失败回归、后修复流程改为 `rt_ioremap` Device mapping，重建 normal/ACK-loss
  镜像后两组均通过。
- 新增三客户机 QEMU 动态隔离用例：VM1/VM2 位于 segment 1 并完成 64 KiB TCP
  交换；VM3 位于 segment 2、无默认路由，向目标子网发送 100 个 UDP 探针。VM1 在
  7 秒观察窗内收到 0 个跨 segment 探针，三台客户机均到达成功 marker。MAC spoof
  与 unknown-unicast 丢弃继续由 `axvm-net` 最低层 policy tests 验证。

### 3. AI 模型与控制闭环（赛题任务三）

- 在 StarryOS 侧部署确定性 4×6×1 热控制神经网络；固定权重可从单一来源导出 ONNX，
  并生成 RKNN FP16 与 ONNX Runtime 格式，配有 manifest、golden vectors 和重建校验。
- 已形成完整闭环：状态观测 → StarryOS 推理 → UDP CONTROL → Zephyr 热模型/执行器 →
  STATUS/ACK 回传。Zephyr 的可观察动作包括控制量应用、热模型状态更新和日志记录。
- 同一 canonical neural policy、IVC/1 codec、receive window 与确定性热模型已在
  Linux controller + RT-Thread/FreeRTOS 的四组 QEMU 活动复用，证明新增 RTOS 端点
  不需要修改控制 payload 或可靠性语义；该证据不替代 StarryOS 实体组合。
- 历史正式 manual/neural AB/BA 五配对（10 个有效 half）显示，neural 相对手动固定
  参数的 RMSE 改善 35.93%、IAE 改善 51.94%；同时最大超调退化 96.32%，且 full-loop
  p99 未呈现稳定优势。报告已完整保留正、负两类指标。
- 已完成 RK3588 NPU（RKNN）和 ONNX Runtime CPU 两条后端的历史实体闭环活动，均为
  5×1,800 个控制周期、9,000/9,000 成功。后端数据分开统计，不把 NPU 与 CPU 的初始化
  或推理时间混为同一性能序列。

### 4. 工程化、复现与交付材料

- 完成 typed device graph 配置、StarryOS/Zephyr 镜像构建、板端原子部署、串口采集、
  raw 分析、checksum、文件系统检查和 Linux 自动恢复脚本。
- 当前实体证据包绑定两个 clean commit：RT shared/partitioned 为 `077ba386…`，IVC
  重启闭环为 `598b357f…`；两者均包含上述 `upstream/dev` 基线，且两次运行之间仅修改
  `competition/ivc/` 路径，不影响 RT runtime/config 的证据边界。
- 已整理设计、测试、复现、评分映射和五分钟演示说明；当前证据包包含输入/输出哈希、
  原始数据、机器 summary 和校验清单。五分钟视频已生成，内容为实体串口日志和机器
  JSON 的证据回放。
- 新增确定性证据归档工具：固定 tar/gzip 元数据、生成逐文件 SHA-256 manifest、
  拒绝覆盖/链接/特殊文件，并在发布前逐成员回读校验。它解决本地 844 MiB raw 的
  可验证打包问题，但公开上传 URL 仍需要外部发布步骤。
- 新增标准库实现的一键交付门禁并接入 CI：逐项校验 32 个 compact evidence 文件、
  5 份 QEMU gzip、四组 RTOS 计数、完整隔离 marker、正式 M2/soak 契约、12 份回执、
  110 项 archive manifest 和 34 个预注册源码输入；独立 CI 仅按交付路径触发，
  交付 verifier 配套 23 个确定性正负例，连同归档工具共 27 项 evidence tests。
- 修复 fork CI 容器路由：非 `rcore-os` 仓库统一消费 upstream 公开 base/LVZ 镜像，
  路由回归、YAML 解析和两类 manifest 可用性检查均通过；远端 lock-lint、format、
  sync-lint、clippy 已实际越过容器初始化并通过。
- 修复 `rsext4` 三个 JBD2 unmount 错误注入 fixture 与新缓存活动块约束不一致的问题；
  Linux 完整 host-test 通过。该改动仅位于 `#[cfg(test)]`，交付门以精确旧/新 Git blob
  对锁定这一转换，未对文件路径做宽泛豁免。
- 补齐 RT-Thread/FreeRTOS Guest 构建、AxVisor VM/QEMU 配置、Linux controller
  rootfs、严格 analyzer、host fake-MMIO/transport 测试、复现文档和紧凑验证记录；
  四组 raw 日志仍保留在 ignored `tmp/` 目录，机器哈希摘要进入 competition results。

## 对赛题要求的阶段性覆盖

| 赛题方向 | 当前状态 | 本周可交付证据 |
| --- | --- | --- |
| 实时 RTOS 化改造 | 当前正式 M2 门通过 | RT 配置、采集/比较脚本、当前实体五配对、12 份回执与双 soak 数据 |
| IP 网络通信 | 已完成 | virtio-net device graph、UDP/IPv4 地址/端口配置、IVC/1 协议与故障恢复数据 |
| AI 控制闭环 | 已完成 | StarryOS 推理、Zephyr 执行/回传、manual/neural 对照和端到端测量 |
| 多 RTOS 基线与 Guest 扩展（加分） | 可主张 | 三种固定源码的原生 QEMU idle/stress 基线；RT-Thread/FreeRTOS 另有 AxVisor Guest/IVC normal + ACK-loss 4/4 |
| 网络动态隔离 | 已完成 QEMU 负例 | 三 guest、双 segment、无默认路由、100 个探针、7 秒零接收证据 |
| 工程完整性 | 基本完成 | 设计、测试、复现、溯源、checksum、确定性归档、板端自动化和视频材料 |
| StarryOS 替代 Linux（加分） | 可主张 | 当前 RT 与 IVC 实体客户机均使用 StarryOS |

按现有评分映射的证据自评，主评分材料约可支撑 `99/100`，并可主张 StarryOS 替代
Linux 的 `+4` 与多 RTOS 的 `+2`，合计加分 `+6`；该数字为内部证据自审，不代表
官方评审结果。

## 当前风险与下周计划

1. 将已生成的约 41 MiB 当前正式 RT archive 发布到不可变地址；总 SHA-256 为
   `60fedba15032a7d5a036355102859571a6bfec628d61676fffaa3d312d398ba9`，110 项 manifest 已提交。
2. 在同一 Orange Pi 5 Plus 上完成至少一种 RTOS 的 idle、stress 和 soak 裸机基线，
   进一步消除现有 QEMU 等价基线带来的平台与时钟源差异。
3. 发布完整历史 raw 归档的不可变下载地址、总 SHA-256 和逐文件 manifest；当前仓库
   已提交精简证据，但约 844 MiB 的完整原始归档尚未公开。
4. 将 RT-Thread/FreeRTOS Guest/IVC 从 QEMU/AArch64 移植到 Orange Pi 5 Plus，
   至少补一组 StarryOS controller 实体组合和中断驱动 RX；当前不跨级声称板端支持。
5. 复核报告、复现步骤和五分钟演示内容与最终冻结数据的一致性，并按赛题安排准备后续
   PR 提交。

## 证据入口

- 赛题要求：[requirement.md](requirement.md)
- 评分映射与缺口：[scorecard.md](scorecard.md)
- 设计说明：[design.md](design.md)
- 测试与数据报告：[test-report.md](test-report.md)
- 复现说明：[reproduce.md](reproduce.md)
- 当前源码实体证据：[current-source-smoke-20260813](results/current-source-smoke-20260813/)
- 当前正式 RT 性能证据：[axvisor-rt-formal-20260816](results/axvisor-rt-formal-20260816/)
- 原生多 RTOS 基线：[rt-baseline](rt-baseline/)
- RT-Thread/FreeRTOS Guest/IVC：[ivc/README.md](ivc/README.md)、[QEMU 验证记录](results/rtos-guest-ivc-qemu-20260815/)
- 三客户机隔离证据：[axvisor-isolation-reference](results/axvisor-isolation-reference/)
- 证据归档工具：[evidence](evidence/)
