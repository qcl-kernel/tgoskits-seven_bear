# AxVisor + StarryOS 混合关键控制演示

本目录是比赛材料入口。当前主线让 AxVisor 在 Orange Pi 5 Plus
(RK3588) 上同时运行双 vCPU StarryOS 与 Zephyr RTOS，通过 device graph
声明的两张 `virtio-net-mmio` 网卡建立隔离 UDP/IPv4 链路；同一实体板还完成了
RT-Thread 与 FreeRTOS 的独立 Guest/IVC smoke。StarryOS 侧执行神经网络推理，
RTOS 应用控制量并回传状态；ACK、重传、去重、错误通知、安全回退和客户机重启
恢复均有自动化验证。

```text
Orange Pi 5 Plus / AxVisor (4 pCPU)
├─ StarryOS: 2 vCPU, 256 MiB, typed virtio-net + virtio-blk
│  └─ observation → neural/ORT/RKNN inference → CONTROL
├─ Zephyr / RT-Thread / FreeRTOS: 1 vCPU, isolated RAM, typed virtio-net
│  └─ CONTROL → actuator/plant → STATUS + ACK / ERROR
└─ AxVisor segment 1: 10.0.0.1/24 ⇄ 10.0.0.2:5500
```

主数据通道只有虚拟以太网与 UDP/IP；没有 host-facing NIC、bridge、NAT、
default route、vsock、共享内存或 HyperCall 应用数据通道。

## 当前交付状态

| 项目 | 状态 | 主证据 |
| --- | --- | --- |
| device-graph 配置入口 | 完成 | typed `[devices]`、initramfs、配置解析回归 |
| 当前源码实体 IVC 重启恢复 | 通过；同一 clean commit 的 runner/analyzer exit 0 | [`current-source-smoke-20260813/ivc`](results/current-source-smoke-20260813/ivc/) |
| 早期 RT shared/partitioned 实体冒烟 | 两侧管线通过；单对诊断不满足 M2 正式矩阵 | [`rt/comparison.json`](results/current-source-smoke-20260813/rt/comparison.json) |
| 当前正式 RT 五配对 + 双 soak | clean commit `c82da8464…` 实体活动通过，`m2_exit_gate_met=true` | [`axvisor-rt-formal-20260816`](results/axvisor-rt-formal-20260816/) |
| 正式与历史 raw 公开归档 | 两个不可变 GitHub Release 已发布并给出总 SHA-256 | [`axvisor-rt-formal-20260816`](https://github.com/yueneiqi/tgoskits-competition-evidence/releases/tag/axvisor-rt-formal-20260816-c82da8464)、[`historical-raw-20260818`](https://github.com/yueneiqi/tgoskits-competition-evidence/releases/tag/historical-raw-20260818) |
| manual/neural 五配对闭环 | 历史活动通过；RMSE/IAE 改善，overshoot 退化 | [`historical-formal/ivc-control`](results/current-source-smoke-20260813/historical-formal/ivc-control/) |
| ACK-loss / ERROR / restart | 历史活动各 3/3；当前 restart 再次通过 | [`historical-formal`](results/current-source-smoke-20260813/historical-formal/) |
| RKNN NPU / ONNX Runtime CPU | 历史活动各 5×1,800 通过 | [`historical-formal/rknpu`](results/current-source-smoke-20260813/historical-formal/rknpu/)、[`ort`](results/current-source-smoke-20260813/historical-formal/ort/) |
| 视觉 AI 增强 | 实体 RK3588 上完成三帧 StarryOS RKNN/NPU → UDP/IP → Zephyr 挡板动作与状态回传；3/3 请求等于实际动作 | [`orangepi-vision-20260818`](results/orangepi-vision-20260818/) |
| 五分钟视频 | 按评分项讲解架构、实时性、客户机通信、AI 闭环与工程证据；关键命令及执行效果在终端展示 | [`demo-terminal-5min.mp4`](results/terminal-demo-20260817/demo-terminal-5min.mp4) |
| upstream `dev` rebase | 运行源码包含 `56f8bfc8207f…`；IVC source 0 behind / 50 ahead | [`provenance.json`](results/current-source-smoke-20260813/provenance.json) |
| 原生多 RTOS 对照 | 三种 RTOS 均有 QEMU/AArch64 idle/stress；另在同一 Orange Pi 5 Plus 原生运行 Zephyr idle/stress/约 30 分钟 soak，均零 miss | [`orangepi-native-zephyr-20260818`](results/orangepi-native-zephyr-20260818/) |
| RT-Thread/FreeRTOS Guest/IVC | QEMU normal/ACK-loss 共 4/4；实体 RK3588 上两种 RTOS 分别与 StarryOS 完成 20/20、PSCI off、快照收割和 Linux 恢复 | [`orangepi-rtos-ivc-20260818`](results/orangepi-rtos-ivc-20260818/) |
| 三客户机网络隔离 | QEMU 动态通过：同 segment TCP 64 KiB；隔离 segment 发送 100 个探针，接收端 7 秒收到 0 个 | [`axvisor-isolation-reference`](results/axvisor-isolation-reference/) |
| 证据归档工具 | 确定性 tar+gzip、逐文件 manifest、SHA-256、拒绝覆盖并回读验证 | [`evidence`](evidence/) |
| 交付一致性门禁 | 32 个 compact 文件、5 份 QEMU gzip、113 项正式归档清单、业务门槛与源码输入统一 fail-closed 校验，并接入 CI | [`verify_delivery.py`](evidence/verify_delivery.py) |

2026-08-13 的 100 样本单对冒烟仍作为诊断记录保留，但不再承担正式性能结论。
2026-08-16 在 clean commit `c82da8464…` 上完成预注册五配对、每项每侧 10,000
样本及 shared/partitioned 双侧 30 分钟 soak，机器判定
`m2_exit_gate_met=true`。正式改善结论严格限定在该受控 host interference 活动；
RT-Thread/FreeRTOS Guest/IVC 与三客户机隔离也在同一 clean commit 上重新运行，后续仅
更新交付文档、证据和校验工具；34 个预注册运行输入经 Git blob 校验均未变化。详见
[`test-report.md`](test-report.md) 和 [`scorecard.md`](scorecard.md)。

## 文档导航

- [`scorecard.md`](scorecard.md)：逐项对应 100+10 分，给出实现、证据、
  可主张范围和最有价值的补强项。
- [`design.md`](design.md)：device graph、资源分配、网络协议、可靠性、
  AI 控制和测量边界。
- [`test-report.md`](test-report.md)：当前源码实体结果与历史正式活动，明确
  区分 smoke、formal、host/QEMU 证据。
- [`reproduce.md`](reproduce.md)：从 source pin、构建、staging、实体运行、
  harvest 到 checksum 的可执行步骤。
- [`video-storyboard.md`](video-storyboard.md)：五分钟成片的评分项映射、镜头、字幕与
  证据边界。
- [`requirement.md`](requirement.md)：比赛原始要求，不作为完成状态声明。
- [`rt-baseline/README.md`](rt-baseline/README.md)：Zephyr、RT-Thread、
  FreeRTOS 的支持层级、统一测量边界和复现入口。
- [`ivc/README.md`](ivc/README.md)：三种 RTOS 的 Guest/IVC 支持矩阵，
  RT-Thread/FreeRTOS 构建、QEMU 活动、严格计数和已知限制。
- [`vision/README.md`](vision/README.md)：智能分拣展示方案、RK3588 同板对比矩阵、
  UVC+RKNN 单次分析与五配对证据门。

## 源码入口

| 边界 | 入口 |
| --- | --- |
| VM device graph 配置/校验 | [`axvmconfig`](../virtualization/axvmconfig/src/lib.rs)、[`device_plan`](../virtualization/axvm/src/vm/prepare/device_plan/mod.rs) |
| 虚拟网卡与隔离交换 | [`virtio_net`](../virtualization/axdevice/src/virtio_net/mod.rs)、[`axvm-net`](../virtualization/axvm-net/src/lib.rs) |
| CPU partition / timer / IRQ | [`axvm`](../virtualization/axvm/src/)、[`RT harness`](../scripts/benchmark/axvisor-rt/) |
| IVC/1 协议与神经控制 | [`ivcproto`](../tools/ivcproto/src/lib.rs) |
| Starry/Zephyr/RT-Thread/FreeRTOS 镜像与配置 | [`ivc`](ivc/)、[`RT configs`](../scripts/benchmark/axvisor-rt/config/) |
| 板端生命周期 | [`board-runner.sh`](ivc/orangepi/board-runner.sh)、[`run-orangepi-5-plus.sh`](ivc/run-orangepi-5-plus.sh) |
| 当前源码原始证据与溯源 | [`current-source-smoke-20260813`](results/current-source-smoke-20260813/) |
| 当前正式 RT 性能证据 | [`axvisor-rt-formal-20260816`](results/axvisor-rt-formal-20260816/) |
| 多 RTOS 原生基线 | [`rt-baseline`](rt-baseline/)、[`orangepi-native-zephyr-20260818`](results/orangepi-native-zephyr-20260818/)、[`native-zephyr-reference`](results/native-zephyr-reference/)、[`native-rtthread-reference`](results/native-rtthread-reference/)、[`native-freertos-reference`](results/native-freertos-reference/) |
| 实体 RT-Thread/FreeRTOS Guest/IVC | [`orangepi-rtos-ivc-20260818`](results/orangepi-rtos-ivc-20260818/) |
| UVC + RKNN 视觉应用与证据工具 | [`orangepi-5-plus-uvc-rknn`](../apps/starry/orangepi-5-plus-uvc-rknn/)、[`vision`](vision/) |
| 三客户机隔离与证据交付 | [`run-isolation.sh`](../apps/arceos/virtio-net-peer/run-isolation.sh)、[`axvisor-isolation-reference`](results/axvisor-isolation-reference/)、[`package.py`](evidence/package.py)、[`verify_delivery.py`](evidence/verify_delivery.py) |

## 最快的离线检查

```sh
bash competition/evidence/run-host-validation.sh
python3 -m unittest discover \
  -s scripts/benchmark/axvisor-rt/tests -p 'test_*.py'
bash scripts/benchmark/axvisor-rt/tests/test_runner.sh
bash scripts/benchmark/axvisor-rt/tests/test_starry_runner.sh
(cd competition/results/current-source-smoke-20260813 && \
  sha256sum -c checksums.sha256)
```

单独复核已提交的正式 RT、RTOS Guest/IVC 与三客户机隔离 compact evidence，可在 Windows、
Linux 或 macOS 的 Python 3 环境运行：

```sh
python3 competition/evidence/verify_delivery.py
```

统一 host runner 验证 RTOS 配置、协议、分析器、C transport、证据语义和源码新鲜度；
它不执行 QEMU 或实体板活动，也不能替代实体板时延、故障恢复或最终 raw 发布。
