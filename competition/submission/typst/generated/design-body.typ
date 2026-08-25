= 1. 方案摘要与成功标准
<方案摘要与成功标准>
系统旨在有限的 RK3588 资源约束下，将高算力、低确定性的视觉任务与低延迟、可恢复的控制任务解耦部署于不同客户机，并通过受控的 IP 网络协议实现端到端协同，而非孤立追求单项推理或单项实时指标。成功标准分为四层：第一，AxVisor 稳定启动多核 StarryOS 与 RTOS 客户机，具备明确的 vCPU、物理 CPU、内存、设备及中断路径划分；第二，实时优化在预注册配对与长稳测试中具备可核验的性能收益；第三，基于 CONTROL、STATUS、ACK 与 ERROR 建立可自愈的双向网络闭环；第四，神经网络推理输出驱动可观察动作，并以手动策略为基准客观呈现正向与负向指标。

方案明确界定非目标：observed maximum 不作为 WCET 形式化证明；虚拟 segment 隔离不等同于物理网卡或外部交换机硬件隔离；三张标注图的 pilot 测试不足以断定 AI 策略全面优于固定策略；SO-100 仅提供有人值守的 ID1 单周期验证证据，尚未接入 RTOS mediator，亦未与摄像头构成物理闭环。

= 2. 赛题要求到实现的映射
<赛题要求到实现的映射>
#figure(
  align(center)[#table(
    columns: (25%, 25%, 25%, 25%),
    align: (auto,auto,auto,auto,),
    table.header([赛题要求], [本方案实现], [主要证据], [证据状态],),
    table.hline(),
    [实时关键路径改造], [静态 vCPU 放置、资源分区、定时器与中断路径优化、后台干扰约束], [五组 AB/BA、每项每 half 10,000 样本、双约 30 分钟 soak], [FROZEN FORMAL],
    [多核 Linux/Starry 客户机], [StarryOS VM1 使用 2 vCPU 与 256 MiB，RTOS VM2 使用 1 vCPU 与 128 MiB], [板端启动配置与 compact marker], [PASS],
    [原生 RTOS 基线], [同一 RK3588 上 Zephyr 4 组 AB/BA，共 8 次 10,000 样本运行，另有 1,817.822 秒 soak], [`competition/results/orangepi-native-zephyr-campaign-20260819-v6/summary.json`], [PASS],
    [IP 双向通信], [VirtIO-net 上的 IVC/1 UDP/IPv4，包含 CONTROL、STATUS、ACK、ERROR], [当前源 smoke 与三类故障 campaign], [PASS],
    [可靠性与异常恢复], [单 in-flight、超时重传、64 序号窗口、去重、retired session、安全回退], [ACK-loss、typed ERROR、guest restart 各 3 次], [PASS],
    [网络隔离], [三客户机、两个 segment、无默认跨段转发、anti-spoof 与 unknown-unicast drop], [同段 TCP 65,536 bytes；100 个跨段 UDP 探针接收 0], [PASS],
    [神经网络推理], [native Rust、ONNX Runtime CPU、RKNN NPU 三后端共享 canonical 模型], [5 次 1,800 样本 campaign 与 golden vectors], [PASS],
    [AI 控制闭环], [StarryOS 推理后通过 IVC/1 发送，Zephyr 执行动作并回传状态], [60/60 decision、STATUS、ACK 完整对应], [PASS],
    [实时摄像头], [USB UVC 输入与 RK3588 NPU 推理], [60.1 秒、965 帧、483 次推理、零错误], [PASS],
    [物理执行器], [SO-100 USB Control、ID1 2042→2074→2042 计划轨迹], [有人值守单周期 trace], [LIMITED PASS],
    [物理视觉闭环], [摄像头、RTOS、机械臂同步联动], [尚无同步实拍和统一时钟证据], [BLOCKED],
  )]
  , kind: table
  )

本表用于索引设计实现与支撑证据，不构成对评审最终结论的预设。

= 3. 系统架构
<系统架构>
#figure(image("../../assets/charts/01-system-architecture.png"),
  caption: [
    System architecture
  ]
)

Orange Pi 5 Plus 提供基于 RK3588 的多核 CPU、板载内存、USB 及 NPU 硬件资源。AxVisor 构成资源划分与故障隔离边界：StarryOS VM1 负责 UVC 采集、图像预处理、RKNN 推理与控制决策端；Zephyr VM2 负责协议端点解析、动作状态机调度与状态回传。应用层数据不依赖共享内存、HyperCall 或裸 MMIO 跨域透传，而是统一经由 VirtIO-net 与 UDP/IPv4 协议栈交互。共享内存机制严格局限于虚拟化设备实现内部，不作为客户机间主数据通道。

系统闭环时序为：输入→推理→网络→动作→状态。CONTROL 指令由 StarryOS 发往 RTOS；RTOS 依次校验 frame、session 与 sequence 合法性，完成动作应用后发送 STATUS 与 ACK。控制端仅在二者严格匹配后推进下一周期观测。该架构将模型推理的不确定性执行时延隔离在控制端，并将动作幂等性、超时控制与安全回退固化于 RTOS 端。

= 4. 客户机、CPU、内存与设备拓扑
<客户机cpu内存与设备拓扑>
#figure(
  align(center)[#table(
    columns: (33.33%, 33.33%, 33.33%),
    align: (auto,auto,auto,),
    table.header([层级], [资源配置], [设计目的],),
    table.hline(),
    [AxVisor], [静态 vCPU 到 pCPU 映射，显式设备树与 IRQ/timer 路径], [降低运行时迁移与共享路径干扰],
    [StarryOS VM1], [2 vCPU、256 MiB、VirtIO-net；视觉场景使用独占 USB/EHCI 与 RKNN 用户态栈], [满足赛题不少于 2 vCPU 的多核客户机要求],
    [Zephyr VM2], [1 vCPU、128 MiB、VirtIO 1.x MMIO 网卡、UDP 5500], [执行 IVC/1 与确定性动作状态机],
    [隔离验证 VM3], [独立 pCPU、独立 MAC/IP、segment 2], [验证跨 segment 默认拒绝],
  )]
  , kind: table
  )

网络主拓扑中，StarryOS 分配 `10.0.0.1/24`，RTOS peer 分配 `10.0.0.2`，网络接口均为 `eth0`，应用监听端口为 UDP `5500`。在实体隔离 campaign 中，VM1、VM2 和 VM3 分别配置为 `10.0.2.15/24`、`10.0.2.16/24` 与 `10.0.2.17/24`；其中 VM1 和 VM2 归属 segment 1，VM3 归属 segment 2。三者的 CPU mask 分别为 `0x2`、`0x4`、`0x8`，精确绑定物理核 pCPU 1、2、3。

设备直通与共享机制遵循最小特权原则：客户机仅映射必需的 MMIO、IRQ 及内存地址段，禁止采用缺省猜测地址或 IRQ 进行模糊容错。板端系统启动、镜像部署及 Linux 恢复流程均在持有 board lease 期间进行，并在重启前执行显式 `sync`。

= 5. 实时化设计
<实时化设计>
实时化目标着眼于压缩长尾时延峰值并抑制跨客户机干扰，而非单纯追求单次测量极小值。shared 配置允许关键路径资源共享，partitioned 配置则通过严格绑定 vCPU 放置并收敛关键资源访问路径实现确定性。预注册指标涵盖调度延迟、模拟中断响应、周期抖动以及虚拟定时器注入至 Guest IRQ；测试均按 AB/BA 交叉顺序执行，规避系统单向时间漂移对优化评估的干扰。

关键实现策略包括：系统初始化期完成静态拓扑一致性校验；运行期禁止 vCPU 动态漂移；将 timer 与 IRQ 处理链路约束在确定性审计路径内；最大限度削减非必要后台任务及全局共享锁竞争；利用 compact marker 精确对齐 host 与 guest 事件时序；针对未适配平台、设备或路由请求均返回显式错误码，杜绝隐式静默回退。

#figure(image("../../assets/charts/02-rt-worst-of-runs.png"),
  caption: [
    RT worst of runs
  ]
)

在冻结正式 campaign 中，partitioned 相对 shared 的 worst-of-runs maximum 改善幅度分别为：调度延迟 99.331%、模拟中断响应 99.444%、周期抖动 99.548%、虚拟定时器注入至 Guest IRQ 43.443%。上述 maximum 均为实测样本观测最大值，不构成 WCET 的形式化上界。同时，调度延迟的 worst p99 出现 -1.080% 的微幅波动，表明评估需综合考量多维统计，五个配对测试中的 p99 指标亦完整公开。

#figure(image("../../assets/charts/03-rt-p99-pairs.png"),
  caption: [
    RT p99 pairs
  ]
)

= 6. 实时证据的版本边界
<实时证据的版本边界>
正式 RT 数据源自提交 `c82da8464ab69e7da95e9be08293559e67b28fac`：包含 5 个预注册配对，每项每 half 采集 10,000 样本；shared soak 运行时长为 1,864.677 秒，partitioned soak 为 1,845.735 秒。当前材料 HEAD 尚未重跑该板端 campaign。Git blob 审计对比 34 个预注册源码输入，其中 33 个一致，唯一变化为 `competition/ivc/orangepi/restore-linux.sh`。该文件仅用于运行结束后的 Linux 恢复编排，未装入被测运行时镜像。

由于正式证据提交不是当前 HEAD 的祖先，完整 delivery verifier 按设计返回 exit code 2，拒绝将历史测量数据转换为当前 HEAD 的性能声明。准确的证据边界为：冻结数据仅对对应源提交有效；当前分支虽可核验大部分源码输入一致，但不能据此声称已完成当前 HEAD 板测。

= 7. 同一 RK3588 的原生 Zephyr 基线
<同一-rk3588-的原生-zephyr-基线>
原生系统基准测试在 Orange Pi 5 Plus 硬件平台上展开，配置包括 RK3588、Zephyr 4.3.0、`roc_rk3588_pc` 目标板配置、Cortex-A55 CPU0 与 24 MHz AArch64 architected counter。测试基准周期设为 1,000 µs，每次经 100 个 warmup 周期后连续采集 10,000 个样本。测试包含 idle 与 CPU stress 构成的 4 组 AB/BA 配对（共 8 次运行），在两种负载模式下均录得 0 timer miss 与 0 early wake。独立 soak 测试采集 10,000 样本，持续运行 1,817.822 秒，同样保持 0 miss。

#figure(image("../../assets/charts/07-native-zephyr.png"),
  caption: [
    Native Zephyr
  ]
)

原生 Zephyr 实测显示：周期唤醒 p99 中位数在 idle 与 stress 条件下均为 2,875 ns，timer→task p99 中位数均为 1,458 ns；在 stress 压力下，周期唤醒 max 中位数由 3,875 ns 升至 4,229 ns，timer→task max 中位数由 2,625 ns 升至 2,916 ns。该基准用于揭示裸机 RTOS 在 CPU 负载扰动下的时延响应特性，而非 identical-kernel 的严格虚拟化开销对比，不可将全部数值差异直接归因于 AxVisor。

= 8. IVC/1 应用层协议
<ivc1-应用层协议>
每个 UDP datagram 严格承载一个 IVC frame，最大 payload 为 1,200 bytes。协议采用固定 32-byte little-endian header，结构定义如下：

#figure(
  align(center)[#table(
    columns: (23.08%, 30.77%, 23.08%, 23.08%),
    align: (auto,right,auto,auto,),
    table.header([Offset], [Size], [Field], [约束],),
    table.hline(),
    [0], [4], [magic], [ASCII `IVC1`],
    [4], [1], [version], [1],
    [5], [1], [type], [CONTROL=1, STATUS=2, ERROR=3, ACK=4, TELEMETRY=5],
    [6], [2], [flags], [ACK-required / retransmission；未知 bit 拒绝],
    [8], [4], [session], [非零],
    [12], [4], [sequence], [非零],
    [16], [8], [sender timestamp], [发送端 monotonic µs；不与另一 guest 时钟直接相减],
    [24], [2], [payload length], [datagram 长度必须精确匹配],
    [26], [2], [error code], [仅 ERROR 为非零],
    [28], [4], [checksum], [checksum 字段清零后的 CRC-32/IEEE],
  )]
  , kind: table
  )

消息语义定义：CONTROL 载荷包含 operation、mode、actuator permille、setpoint 与 sample ID；STATUS 载荷包含运行状态、当前 mode、actuator、temperature、setpoint、applied sequence 与 fault；ACK 载荷包含 acknowledged sequence、next expected 与 receive-window mask；ERROR 载荷包含 offending type、sequence 与 typed error code。协议解析端显式校验并拒绝未知协议版本、长度不符、校验和错误、非预期消息类型及非法 session 状态迁移。

= 9. 可靠性、恢复与安全状态
<可靠性恢复与安全状态>
控制端采用严格单 in-flight command 机制，要求必须收到相互匹配的 STATUS 与 ACK 响应。超时未收到应答时触发相同 session/sequence 的重传；RTOS 接收端依托 64-sequence 滑动窗口区分 fresh、duplicate 与 outside-window 报文。针对 fresh 指令严格执行单次生效；针对 duplicate 重复帧仅重发缓存的 STATUS/ACK 响应，避免重复触发 actuator side effect 或 plant step 计算。新建立的 session 强制从 sequence 1 起步，并维护 8 项 retired-session ring 丢弃滞后的旧会话流量。若超过 500,000 µs 未收到有效控制帧，RTOS 自动触发 actuator=0 的 safe fallback 安全回退状态。

在当前源码 smoke 测试中，系统在真实 VM reset 前后分别执行 20+100 条命令，录得 accepted=120、applied=120，成功率为 100.0%，并观测到 AxVisor 触发的完整 guest reset 生命周期。冻结的故障 campaign 针对 ACK-loss、typed ERROR 与 guest restart 分别执行 3 次注入测试，均顺利通过预注册 gate 并于测试结束后恢复板端 Linux。恢复用例同时验证历史残留的 stale CONTROL、STATUS 与 ACK 报文不会对新 session 产生污染。

= 10. 网络隔离与访问控制
<网络隔离与访问控制>
网络隔离策略由 segment membership、源 MAC/IP 一致性与已知目标转发规则共同决定。VM1 与 VM2 位于 segment 1，可进行同段 TCP 通信；VM3 位于 segment 2，默认不能跨段访问 VM1。系统对未知单播不进行默认泛洪，源地址与分配身份不一致时直接丢弃。

#figure(image("../../assets/charts/08-isolation.png"),
  caption: [
    Isolation
  ]
)

在实体板 campaign 中，同段 TCP 成功传输 65,536 bytes；VM3 发送 100 个跨 segment UDP 探针，VM1 接收 0。底层主动 L2 探针测试覆盖 32 个 known cross-segment、32 个 unknown-unicast 与 32 个 spoofed-source；策略计数器记录 unknown-unicast drop 64、spoof source drop 32。该结果仅证明当前虚拟 segment 隔离策略，不外推为物理 NIC、交换机 VLAN 或外部防火墙的隔离结论。

= 11. AI 模型、后端与控制策略
<ai-模型后端与控制策略>
规范控制模型为 `thermal-4x6x1-v1`：包含 4 个输入、6 个 ReLU hidden、1 个 clamped 输出。输入为 setpoint error、相对 ambient setpoint、temperature rate 与 previous actuator，输出量化为 0..=1000 actuator permille。native Rust、ONNX Runtime CPU 与 RKNN NPU 共享权重、golden vectors、ONNX 来源和 IVC payload，确保三个后端遵循同一模型语义。

RKNN campaign 共执行 5 次、总计 9,000 样本，设备 p99 中位数为 1,670 µs、full-loop p99 中位数为 13,502 µs、成功率 100.0%。ONNX Runtime CPU 同样执行 5 次、总计 9,000 样本，wall p99 中位数为 174.709 µs、full-loop p99 中位数为 12,251 µs。测试结果支持统一模型与协议在三种运行时中部署，但不支持得出不同硬件具备绝对性能优势的结论。

= 12. 可量化控制效果
<可量化控制效果>
对比基准采用固定 500 permille 输出的手动控制策略。在板端进行的五组 AB/BA 交叉对比（每种配置各执行 5×1,800 样本采样）中，neural 策略相较 manual 策略使 RMSE 降低 35.926646%，IAE 降低 51.932443%；但系统最大超调量增加 96.315789%，由 6,840 mC 上升至 13,428 mC。

#figure(image("../../assets/charts/04-control-effect.png"),
  caption: [
    Control effect
  ]
)

该实验数据表明，当前 AI 控制策略有效压缩了累计跟踪误差与均方误差，但并未在全部控制指标上全面优于固定策略。工程迭代方向并非回避超调现象，而是在维持协议标准与后端一致性的架构下，引入超调惩罚项、执行器饱和保护及可解释的模式切换阈值，并依托新一轮预注册 AB/BA 实验进行复核。

= 13. USB 摄像头与连续视觉闭环
<usb-摄像头与连续视觉闭环>
原生 StarryOS 下 UVC→RKNN 测试持续运行 60.1 秒，采集 965 帧、完成 483 次推理，capture 速率为 16.06 fps、inference 速率为 8.04 fps，decode error 与 inference error 均为 0，推理 p95 为 75.1 ms。在跨 Guest 连续运行中，StarryOS 通过 UVC 与 RKNN 产生 60 条 decision，经 UDP/IPv4 发送至 Zephyr；RTOS 回传 60 条状态，accepted=60、applied=60、retry=0。

#figure(image("../../assets/charts/05-vision-loop-latency.png"),
  caption: [
    Vision latency
  ]
)

端到端从图像采集到动作状态回传，中位数为 474,923 µs、p95 为 595,729 µs、观测最大值为 2,437,752 µs；推理结束到发送的中位数为 64,894 µs，网络与 RTOS 往返中位数为 238,375 µs。动作分布为 left=1、hold=59。60/60 结果仅证明该次有界运行内的决策与状态对应，不证明更长时间稳定性、识别准确率或硬实时上界。该次运行未接入物理执行器，动作仅为 RTOS 可观察的虚拟状态。

= 14. RK3588 视觉性能优化与取舍
<rk3588-视觉性能优化与取舍>
预处理优化经由两组独立的五配对固定输入测试验证。Q12 letterbox 使平均耗时降低 47.136%，总耗时平均值降低 33.351%，总耗时 p95 降低 28.288%，三项在 5/5 配对中均表现有利。NPU all-core 策略使 run 平均值改善 0.612%，但 run p95 退化 2.074%（5/5 配对均不利），总耗时 p95 亦退化 0.364%。

#figure(image("../../assets/charts/06-vision-optimization.png"),
  caption: [
    Vision optimization
  ]
)

因此，默认路径优先采用配对证据更稳定的 Q12 预处理；all-core 不应仅凭微弱的均值收益设为默认配置。建议在热状态、频率与并发负载受控后重新预注册测试，再按模型尺寸与 tail-latency SLO 选择 core 策略。

= 15. 直观 AI 场景与标注 pilot
<直观-ai-场景与标注-pilot>
在网球分拣演示场景中，模型推理输出被映射为 left、right 与 hold 控制动作。可视化界面实时叠加目标边界框、检测置信度、控制决策、sequence 序号、RTOS 运行状态以及闭环往返时延，适于在 5 分钟视频演示中清晰阐释完整数据流。当前标注 pilot 验证集包含 3 个典型正样本：清晰近景、黑箱背景干扰与绿植复杂背景。

#figure(image("../../assets/charts/10-labeled-pilot.png"),
  caption: [
    Labeled pilot
  ]
)

实测 AI 动作决策准确率为 66.667%，与固定输出 right 的对比基准（66.667%）持平；其中 AI 策略的 wrong direction 发生率为 0.0%，但记录有 1 次 missed action。由于当前样本量极小，不能据此得出 AI 策略具备全面优势的结论。后续扩展应构建并冻结更大规模的分层测试集，全面覆盖无目标、多目标、遮挡、逆光、运动模糊及相邻易混类别，在统一基准下综合评估准确率、反向动作率、漏动作率以及端到端尾部时延。

= 16. SO-100 物理执行器集成
<so-100-物理执行器集成>
SO-100 通过 USB Control 连接 Orange Pi，由 12 V 独立电源供电。测试流程严格要求机械臂已固定、工作区清空、人员在场且断电开关触手可及；流程先以只读方式确认位置与故障，再执行小步长运动，最后断开扭矩。现有授权测试仅执行 ID1 的单周期计划轨迹 2042→2074→2042，位置容差设为 8。

#figure(image("../../assets/charts/09-so100-id1.png"),
  caption: [
    SO-100 ID1
  ]
)

观测最大外行程位置为 2073，回程监测终点与断扭矩位置为 2045，postflight 稳定位置为 2047，状态故障为 0，结束时为 torque disabled 状态。证据等级为 supervised-single-cycle-physical-actuator。当前未测试 full-arm motion、armed-motion estop、RTOS mediator 与 camera-synchronized physical loop，因此不能将该 trace 与连续视觉运行合并为物理闭环证据。

= 17. 可追溯性与复现设计
<可追溯性与复现设计>
`competition/submission/data/evidence-snapshot.json` 为交付材料生成专用的只读归一化快照，完整记录 21 个保留证据输入的相对路径与 SHA-256，并对关键 gate 与声明边界执行断言。所有图表严格仅读取该快照及经 `agy` 润色的标签，不从任何独立手写数值生成。中文正文、图表标签、视频字幕与旁白由 `agy` CLI 调用 `gemini-3.7-flash-high`（配置 effort=high）完成润色，并在 `competition/submission/agy-polish-manifest.json` 中完整记录输入输出哈希、conversation ID 与 usage。

#figure(
  align(center)[#table(
    columns: (50%, 50%),
    align: (auto,auto,),
    table.header([Upstream CI 字段], [记录],),
    table.hline(),
    [PR], [`rcore-os/tgoskits#2182`],
    [HEAD], [`75d8f3918580471a3451b29ca5d33a015bd5bb81`],
    [CI 运行], [`32794757246`；主流水线 35/35 成功],
    [关键通过项], [AArch64 IVC、Workspace Clippy/std tests、Orange Pi 5 Plus Linux、StarryOS 与 robot 板卡任务],
    [机器摘要], [`competition/results/upstream-pr-2182-ci-20260825/summary.json`],
  )]
  , kind: table
  )

该结果用于证明代码集成路径成立，不替代当前成果分支的正式 RT 板端性能重跑。

PDF 基于 Typst 及固定提交 `7a6080e891631d45ab2c2b40531ea8a3f211270f` 的 `ilm-zh` 模板构建。最终交付材料包含生成命令、工具版本、PDF 逐页视觉检查记录、视频抽帧核验结果与 SHA-256 清单。复现流程建议先进行离线证据校验，再选择 QEMU、板端 smoke 或需要 board lease 的物理 campaign；文档与材料生成流程不能替代硬件重跑。

= 18. 结论与后续优先级
<结论与后续优先级>
当前交付形成了一条可核验的单芯片混合系统链路：AxVisor 划分 StarryOS 与 RTOS 的资源和故障域，IVC/1 在 UDP/IPv4 上提供控制、状态、确认、错误与异常恢复，神经网络输出可通过同一协议驱动 RTOS 可观察动作。RK3588 上还具备 UVC、NPU、原生 Zephyr、虚拟 segment 隔离与 SO-100 单关节证据。

后续核心演进工作包含三项：第一，在当前 HEAD 上重新执行正式 RT 五配对与双 soak，建立当前 HEAD 的独立性能证据；第二，扩展分层标注场景并预注册 AI 与固定策略对比，解决 3 样本 pilot 的统计不足；第三，将 SO-100 接入 RTOS mediator，以统一 sequence、状态回传和急停记录完成摄像头同步的有人值守物理闭环。
