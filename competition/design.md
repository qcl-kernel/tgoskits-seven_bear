# 系统与协议设计

## 1. 范围与声明边界

系统在 Orange Pi 5 Plus 上由 AxVisor 同时运行双 vCPU StarryOS 与单 vCPU
Zephyr，完成三项比赛任务：

1. CPU partition、timer/IRQ 路径改造与可重复的实时测量；
2. 基于虚拟以太网和 UDP/IPv4 的双向客户机通信；
3. StarryOS 神经网络推理驱动 Zephyr 控制动作并回传状态的闭环。

本设计证明确定性资源声明、固定 vCPU placement、受控干扰下的观测尾延迟改善、
协议可靠性和完整板卡生命周期。它不把有限采样最大值称为 WCET，不声称隔离了
全部宿主任务/物理中断，也不把当前单对 RT smoke 的退化数值包装成改善。

## 2. 实体架构

```text
Orange Pi 5 Plus / RK3588 / 4 AxVisor pCPU
│
├─ pCPU0 ─ Zephyr VM2 vCPU0 (dedicated)
├─ pCPU1 ─ StarryOS VM1 vCPU0 (dedicated in partitioned profile)
├─ pCPU2 ─ StarryOS VM1 vCPU1 (dedicated in partitioned profile)
└─ pCPU3 ─ AxVisor housekeeping / restart worker / controlled-noise target

StarryOS VM1                              Zephyr VM2
2 vCPU, 256 MiB                          1 vCPU, 128 MiB
virtio-blk disk0                         memory-loaded image
virtio-net net0                          virtio-net net0
52:54:00:00:00:01                        52:54:00:00:00:02
10.0.0.1/24                              10.0.0.2:5500
       │ CONTROL                               │ STATUS + ACK / ERROR
       └────────── AxVisor segment 1 ──────────┘
```

StarryOS 从板卡 Linux ext4 上的 kernel/DTB/rootfs 文件启动，但 guest 只看到
自己的 256 MiB GPA 和 graph 实例化的设备。Zephyr raw image 在构建时嵌入
AxVisor，运行于独立 128 MiB GPA。两者不共享 RAM 或裸 MMIO 应用通道。

## 3. Device graph 配置与生命周期

当前配置入口不再手工写一组易漂移的 MMIO/IRQ 元组，而是声明设备意图：

```toml
[devices]
passthrough = []
disabled = []
virtual = [
  { id = "disk0", model = "virtio-blk-mmio", image_path = "/home/orangepi/axvisor-guest/starry-ivc-rootfs-restart.img" },
  { id = "net0", model = "virtio-net-mmio", mac_suffix = 1, segment_id = 1 },
]
```

设备建立流程：

```text
TOML GuestDevices
  → 校验 stable id / registered model / model-owned options
  → code-registered model 生成 DeviceNodeSpec + resource requirements
  → VM-local MMIO/IRQ/resource pools 统一分配
  → ResolvedDeviceGraph
  → instantiate device + carve stage-2 trap + emit guest FDT node
  → start vCPU
```

框架保留 MMIO base、wired IRQ、host IRQ 与 MSI 等资源字段；配置不能越过 model
自行指定这些框架所有的 option。重复 ID、未知 model、非法 option、资源冲突或
FDT 重复节点均 fail closed。

在当前 IVC Starry VM 中，graph 解析得到：

| 节点 | Guest MMIO | Guest IRQ | 说明 |
| --- | --- | --- | --- |
| `disk0` | `0x0b000000..0x0b000fff` | INTID 32 | 64 MiB volatile ext4 backing；结果可 snapshot |
| machine PL011 | `0x09000000` | INTID 33 | VM-local 输出 console，由 mux 加前缀 |
| `net0` | `0x0b001000..0x0b001fff` | INTID 34 | MAC suffix 1，segment 1 |

Zephyr 只有一个 graph virtual device，因此 `net0` 使用首个 MMIO slot
`0x0b000000` 和 INTID 32。相同 guest 地址/INTID 不冲突，因为 graph、stage-2
address space 和虚拟中断域都是 VM-local。

基础 Starry/Zephyr DTB 不预声明 graph-owned virtio 节点。AxVM 在资源解析后写入
最终 FDT，避免“配置地址、模拟设备地址、DTB 地址”三份真相。

## 4. 资源配置

### 4.1 IVC restart profile

| 资源 | StarryOS VM1 | Zephyr VM2 |
| --- | --- | --- |
| vCPU | 2 | 1 |
| affinity | `0x2`, `0x4` → pCPU1/2 | `0x1` → pCPU0 |
| dedicated | true | true |
| memory | `0x80000000..0x8fffffff`，256 MiB | `0x40000000..0x47ffffff`，128 MiB |
| kernel | fs: `/home/orangepi/axvisor-guest/starryos.bin` | embedded `zephyr.bin` |
| entry | `0x80200000` | `0x4000100c` |
| DTB | `0x80000000` | `0x47e00000` |
| block | typed `virtio-blk-mmio` | none |
| network | typed `virtio-net-mmio`, segment 1 | typed `virtio-net-mmio`, segment 1, fixed 12-byte header |

AxVisor restart worker 固定在 pCPU3，等待 20,000 ms，在 StarryOS 完成 20 条旧
session 命令后执行 VM1 running → reset → running。reset 过程停止 vCPU、恢复
pristine guest RAM，重新准备 VM/device state，再启动 vCPU；不能沿用 reset 前
的可变 guest RAM 或 console selection。

### 4.2 RT shared / partitioned

两侧的 kernel、DTB、rootfs、vCPU 数、内存、block device、测量参数和 guest
CPU1 stress 完全相同，只切换 `dedicated_cpus`：

| Profile | `phys_cpu_sets` | `dedicated_cpus` | 含义 |
| --- | --- | --- | --- |
| shared | `[0x2, 0x4]` | false | vCPU 仍固定以保护 RK3588 virtual timer PPI，但不保留 pCPU；host task 可竞争 |
| partitioned | `[0x2, 0x4]` | true | planner 为 VM 独占 pCPU1/2，其他 registered vCPU task 被排除 |

“shared”并不等于允许迁移到任意核；它是 reservation off 的对照。这样只改变
host/guest 竞争隔离变量，不引入 timer PPI 因迁移丢失的额外故障。

CPU planner 在任何 vCPU 激活前解析所有 VM：专用 mask 必须非零、在线、互不
重叠；shared mask 会减去所有 dedicated mask；减完为空是错误。初始 placement
使用最大匹配而不是注册顺序相关的贪心选择，运行前再次检查 online mask。

## 5. 实时路径与测量

### 5.1 关键改造

- vCPU affinity 与 dedicated reservation 分离，允许正交 policy-off/on 配置；
- AArch64 guest timer state 在 VM exit 保存并关闭，在下一次 entry 恢复，避免
  宿主任务运行时产生未归属 PPI27 风暴；
- GIC acknowledge、hardware LR 转移、timer disable/restore 保持明确顺序；
- guest/host 直接 IRQ trace 使用预分配固定环，测量热路径不分配、不打印；
- trace 同时记录 vCPU run/wait、pCPU running/idle、affinity mask 和 migration；
- 有界 host-noise 记录 requested/observed pCPU、覆盖时间和 stop reason；
- guest 完成后先 snapshot block backing，再同步 AxVisor host filesystem，最后
  才允许冷启动恢复 Linux。

### 5.2 指标语义

| 指标 | 权威边界 |
| --- | --- |
| `periodic_jitter` | StarryOS 内 absolute `clock_nanosleep` 到实际 wake 的 lateness |
| `dispatch_latency` | 同 guest CPU 的 eventfd signal 到高优先级 reader 运行 |
| `emulated_irq_response` | timerfd expiration 到 userspace read；是 proxy，不是 direct IRQ |
| `virtual_timer_injection_to_guest_irq` | AxVisor 注入到 StarryOS timer IRQ handler entry，共用 24 MHz guest virtual counter domain |

每项在 warm-up 后采样；串口只在测量完成后输出。analyzer 要求完整序号、频率一致、
零 dropped/incomplete/failed injection，并从 raw 重算 nearest-rank percentile。

当前 C-RT 的同 commit 100-sample shared/partitioned 冒烟证明 pipeline 完整，但
单对的 periodic/dispatch 尾延迟退化，且没有 controlled host interference，M2 未通过。
正式改善只来自历史五配对 controlled host interference
活动：该活动的 shared 干扰在 pCPU1、
partitioned 干扰在 pCPU3，五对 direct IRQ p99 全部通过，worst-of-runs 改善
87.771%，并有 shared/partitioned 双侧至少 1,800 秒 soak。两个证据层不得互换。

### 5.3 多 RTOS 支持边界

赛题允许在相同或等价平台运行原生 RTOS 对照。当前提供三条可复现路径：

| RTOS | 原生 QEMU 基线 | AxVisor guest boot | IVC/1 端点 |
| --- | --- | --- | --- |
| Zephyr v4.3.0 | 已验证 | 已验证 | 已验证 |
| RT-Thread v5.2.2 | 已验证 | QEMU/AArch64 已验证 | normal 与 ACK-loss 已验证 |
| FreeRTOS Kernel `f1043c49…` | 已验证 | QEMU/AArch64 已验证 | normal 与 ACK-loss 已验证 |

三种基线都使用单核 AArch64、1 ms 周期、100 次 warm-up，以及 idle/stress 各
10,000 个样本；公共统计和 miss accounting 复用同一实现，但各自保留真实 timer、
优先级和 RTOS 调度记账语义。原生基线直接运行在 QEMU、不经过 AxVisor，因此只用于
任务一的原生/等价 RTOS 对照和多 RTOS 加分，不能替代 Orange Pi 实体时延，也不被
用作客户机网络互通证据。完整基线设计见
[`competition-multi-rtos-baselines.md`](../book/design/competition-multi-rtos-baselines.md)。

另有独立的 AxVisor 双 Guest QEMU 路径：Linux 控制端使用 2 vCPU，RT-Thread 或
FreeRTOS 端点使用 1 vCPU，通过 segment 1 的 VirtIO 1.x MMIO 网卡执行相同 IVC/1
协议。两种端点均完成 100-command normal 与每 5 次丢 1 个 ACK 的确定性活动；后者
严格得到 20 次重传、20 次去重、20 次恢复且只应用 100 次。该结果证明 Guest boot、
IP/virtio-net 和 IVC 端点兼容性，但仍是 QEMU/AArch64，不是 RK3588 实体板证据。
设计与复现入口见 [`competition-rtos-guest-ivc.md`](../book/design/competition-rtos-guest-ivc.md)
和 [`ivc/README.md`](ivc/README.md)。

## 6. 网络隔离

`virtio-net-mmio` model 根据 `mac_suffix` 生成固定 MAC，并把 port 注册到
`segment_id`。switch 的边界规则：

- port ID 和同 segment MAC 必须唯一；MAC 必须是非零单播；
- ingress source MAC 必须等于该 port 的配置 MAC，防止 spoof；
- known unicast 只送到同 segment 的唯一目的 port；
- unknown/reflected unicast 丢弃，不 flood；
- broadcast/multicast 只送到同 segment 的其他 port；
- topology、buffer 与 delivery 失败被计数并局部隔离。

本 profile 没有 host-facing NIC、bridge、NAT、default route、vsock、共享内存或
HyperCall 应用通道，因此不需要 host firewall rule。将来增加外部 NIC 必须单独
设计 route/firewall/threat model，不能沿用当前“无出口 segment”的结论。

QEMU 动态负例另启三个 ArceOS guest：VM1/VM2 在 segment 1 完成 64 KiB TCP
交换；VM3 在 segment 2、无默认路由，并向 `10.0.2.255:5002` 发送 100 个 UDP
探针。VM1 先绑定非阻塞 UDP 监听，再在 TCP 完成后观察 7 秒，必须收到 0 个跨
segment 探针；同时 VM3 的 guest NIC 发送计数必须至少增加 100。该用例证明动态
segment 分离和无默认路由，anti-spoof 与 unknown-unicast 丢弃仍由更低层的
`axvm-net` policy tests 验证，不能描述成动态 spoof capture。

## 7. IVC/1 协议

每个 UDP datagram 恰好承载一个 IVC frame；最大 payload 1,200 bytes。固定
32-byte little-endian header：

| Offset | Size | Field | 约束 |
| --- | ---: | --- | --- |
| 0 | 4 | magic | ASCII `IVC1` |
| 4 | 1 | version | 1 |
| 5 | 1 | type | CONTROL=1, STATUS=2, ERROR=3, ACK=4, TELEMETRY=5 |
| 6 | 2 | flags | ACK-required / retransmission；未知 bit 拒绝 |
| 8 | 4 | session | 非零 |
| 12 | 4 | sequence | 非零 |
| 16 | 8 | sender timestamp | 发送端 monotonic µs；不与另一 guest 时钟直接相减 |
| 24 | 2 | payload length | datagram 长度必须精确匹配 |
| 26 | 2 | error code | 仅 ERROR 为非零 |
| 28 | 4 | checksum | header checksum 字段清零后的 CRC-32/IEEE |

CONTROL 携带 operation、mode、actuator permille、setpoint 和 sample ID；STATUS
携带状态、当前 mode、actuator、temperature、setpoint、applied sequence 与 fault；
ACK 携带 acknowledged sequence、next expected 与 receive-window mask；ERROR
携带 offending type/sequence 和 typed error code。

### 7.1 可靠性

- controller 一次只保留一个 in-flight command，必须同时收到匹配 STATUS 与 ACK；
- timeout 后 retransmit 同一 session/sequence；
- endpoint 的 64-sequence window 对 fresh command 只应用一次；duplicate 只重发
  STATUS/ACK，不重复 actuator side effect 或 plant step；
- 不在 window 内的乱序/过远 sequence 返回 typed error；
- 新 session 只能从 sequence 1 开始；八项 retired-session ring 拒绝延迟旧流量；
- 超过 500,000 µs 没有有效控制即进入 actuator=0 safe fallback；
- malformed version/length/checksum/type/session 分别映射到 ERROR，随后仍可继续正常控制。

restart 测试额外验证旧 session CONTROL、stale STATUS 与 stale ACK 均不能污染
新 session。C-IVC 实体结果正好各拒绝一次，并在新 session 完成 100/100。

## 8. AI 控制闭环

canonical 模型为 `thermal-4x6x1-v1`：4 输入、6 ReLU hidden、1 clamped 输出。
输入为 setpoint error、相对 ambient setpoint、temperature rate 和 previous
actuator。输出量化为 `0..=1000` actuator permille。

```text
STATUS / initial observation
      → native Rust / ONNX Runtime CPU / RKNN NPU inference
      → CONTROL over UDP/IP
      → Zephyr actuator + deterministic thermal plant
      → STATUS + ACK
      └──────────────────────── next observation
```

三后端共用 canonical weights、golden vectors、ONNX 来源与同一 IVC payload：

| Backend | 用途 | 证据边界 |
| --- | --- | --- |
| native Rust | dependency-free/current restart smoke | C-IVC source `neural.rs` hash绑定 |
| RKNN NPU | RK3588 hardware inference | 历史 clean commit 5×1,800，API 2.3.2 / driver 0.9.8 |
| ONNX Runtime CPU | 标准 CPU runtime 对照 | 历史 clean commit 5×1,800，ORT 1.25.0 CPUExecutionProvider |

手动基线固定 500 permille。五对 AB/BA 正式活动中 neural 相比 manual 的 RMSE
改善 35.93%、IAE 改善 51.94%，但 maximum overshoot 从 6,840 mC 增至
13,428 mC（退化 96.32%）。报告必须同时给出这项负向结果。

`full_loop` 从 observation/policy 前开始，在匹配 STATUS+ACK decode 后结束；
`pre_send` 隔离 policy 与编码前工作；`transport` 覆盖余下编码及 UDP/virtio/
RTOS action/response。三者均用 StarryOS 同一个 monotonic clock 做 round trip，
不相减 Starry/Zephyr 的独立时钟 epoch。

## 9. 板端安全生命周期

stager 与 runner 的状态机：

```text
Linux + board lease
  → upload *.new
  → atomic rename + sync + remote sha256sum -c
  → Linux sync/reboot
  → U-Boot loads AxVisor
  → guests run and emit compact markers
  → guest block snapshot + fsck identity
  → AXVISOR_HOST_FILESYSTEM_SYNCED
  → smart-plug cold cycle if needed
  → U-Boot boots TF-card Linux
  → hostname + findmnt ext4,rw gate
  → harvest/analyze/checksum
```

runner 未见 host filesystem sync 时拒绝断电；restore 未确认 Linux rootfs 为 rw
时运行失败。上传路径限制在 `/home/orangepi`，文件名使用安全 basename，board
lease 覆盖 staging 和串口操作。仓库不保存 SSH/smart-plug 凭据。

## 10. 剩余保证边界

- 早期 C-RT 只有一对 100-sample cpu-stress 且 M2 未通过，仍作为诊断保留；正式
  C-RT-F 已完成五配对+双 soak 并通过 M2，二者不得拼接；
- 正式 RT 与历史 formal raw 已发布到两个不可变 GitHub Release，archive、manifest、
  sidecar 与服务端 digest 均可复核；
- 三种 native RTOS 仍有等价 QEMU/AArch64 baseline；另有同一 RK3588 上原生 Zephyr
  idle/stress/soak 补充证据，但串口结果不是逐样本 CSV；
- RT-Thread/FreeRTOS 已与 StarryOS 在 RK3588 完成各 20/20 Guest/IVC smoke，但它们
  不是原生裸机基线，也不替代 clean-commit 长时正式活动；
- 固定三帧视觉分拣已形成真实 RKNN/NPU 跨 Guest 闭环，不外推 Guest 实时 UVC/FPS；
- 三客户机动态隔离已覆盖跨 segment 与无默认路由，MAC spoof/unknown-unicast
  仍只有最低层 policy tests，未做实体板动态恶意流量 capture；
- observed maximum 不是数学/静态证明的 WCET；
- pCPU partition 不等于全部宿主任务、cache/memory bus 和物理 IRQ 的硬隔离；
- 串口共享会造成日志粘连，所以成功以短 marker、snapshot raw 和 checksum 的冗余
  证据判定，不能只看一段终端文本。
