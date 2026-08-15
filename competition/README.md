# AxVisor + StarryOS 混合关键控制演示

本目录是比赛材料入口。当前实现让 AxVisor 在 Orange Pi 5 Plus
(RK3588) 上同时运行双 vCPU StarryOS 与 Zephyr RTOS，通过 device graph
声明的两张 `virtio-net-mmio` 网卡建立隔离 UDP/IPv4 链路。StarryOS 侧执行
神经网络推理，Zephyr 应用控制量、推进热模型并回传状态；ACK、重传、去重、
错误通知、安全回退和客户机重启恢复均有自动化验证。

```text
Orange Pi 5 Plus / AxVisor (4 pCPU)
├─ StarryOS: 2 vCPU, 256 MiB, typed virtio-net + virtio-blk
│  └─ observation → neural/ORT/RKNN inference → CONTROL
├─ Zephyr: 1 vCPU, isolated RAM, typed virtio-net
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
| 当前 RT shared/partitioned 实体冒烟 | 两侧管线通过；本单对 M2 性能门未通过 | [`rt/comparison.json`](results/current-source-smoke-20260813/rt/comparison.json) |
| 正式 RT 五配对 + 双 soak | 历史 clean-commit 活动通过 | [`historical-formal/rt-host-noise`](results/current-source-smoke-20260813/historical-formal/rt-host-noise/) |
| manual/neural 五配对闭环 | 历史活动通过；RMSE/IAE 改善，overshoot 退化 | [`historical-formal/ivc-control`](results/current-source-smoke-20260813/historical-formal/ivc-control/) |
| ACK-loss / ERROR / restart | 历史活动各 3/3；当前 restart 再次通过 | [`historical-formal`](results/current-source-smoke-20260813/historical-formal/) |
| RKNN NPU / ONNX Runtime CPU | 历史活动各 5×1,800 通过 | [`historical-formal/rknpu`](results/current-source-smoke-20260813/historical-formal/rknpu/)、[`ort`](results/current-source-smoke-20260813/historical-formal/ort/) |
| 五分钟视频 | 实体串口与机器 JSON 的 300 秒证据回放版 | [`demo-5min.mp4`](results/current-source-smoke-20260813/demo-5min.mp4) |
| upstream `dev` rebase | 运行源码包含 `56f8bfc8207f…`；IVC source 0 behind / 50 ahead | [`provenance.json`](results/current-source-smoke-20260813/provenance.json) |
| 原生多 RTOS 对照 | Zephyr、RT-Thread、FreeRTOS 均完成 idle/stress 各 10,000 样本的 QEMU/AArch64 基线 | [`rt-baseline`](rt-baseline/)、[`native-rtthread-reference`](results/native-rtthread-reference/)、[`native-freertos-reference`](results/native-freertos-reference/) |
| RT-Thread/FreeRTOS Guest/IVC | QEMU/AArch64 双 Guest normal 与 ACK-loss 共 4/4 通过；每组 100/100，故障组各 20 次重传/去重/恢复 | [`ivc/README.md`](ivc/README.md)、[`competition-rtos-guest-ivc.md`](../book/design/competition-rtos-guest-ivc.md) |
| 三客户机网络隔离 | QEMU 动态通过：同 segment TCP 64 KiB；隔离 segment 发送 100 个探针，接收端 7 秒收到 0 个 | [`axvisor-isolation-reference`](results/axvisor-isolation-reference/) |
| 证据归档工具 | 确定性 tar+gzip、逐文件 manifest、SHA-256、拒绝覆盖并回读验证 | [`evidence`](evidence/) |

当前 100 样本 RT 冒烟有同提交 shared/partitioned 对照，但 periodic 与 dispatch
尾延迟退化，且只有一对、没有受控 host interference，机器判定
`m2_exit_gate_met=false`。正式改善结论严格限定在“受控 host interference、
预注册五配对、相同输入”的历史活动。详见
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
- [`video-storyboard.md`](video-storyboard.md)：五分钟成片的镜头、字幕、
  真实性边界与重新录制方法。
- [`requirement.md`](requirement.md)：比赛原始要求，不作为完成状态声明。
- [`rt-baseline/README.md`](rt-baseline/README.md)：Zephyr、RT-Thread、
  FreeRTOS 的支持层级、统一测量边界和复现入口。
- [`ivc/README.md`](ivc/README.md)：三种 RTOS 的 Guest/IVC 支持矩阵，
  RT-Thread/FreeRTOS 构建、QEMU 活动、严格计数和已知限制。

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
| 多 RTOS 原生基线 | [`rt-baseline`](rt-baseline/)、[`native-zephyr-reference`](results/native-zephyr-reference/)、[`native-rtthread-reference`](results/native-rtthread-reference/)、[`native-freertos-reference`](results/native-freertos-reference/) |
| 三客户机隔离与归档 | [`run-isolation.sh`](../apps/arceos/virtio-net-peer/run-isolation.sh)、[`axvisor-isolation-reference`](results/axvisor-isolation-reference/)、[`package.py`](evidence/package.py) |

## 最快的离线检查

```sh
python3 -m unittest discover -s competition/ivc/tests -p 'test_*.py'
python3 -m unittest discover -s scripts/benchmark/axvisor-rt/tests -p 'test_*.py'
bash scripts/benchmark/axvisor-rt/tests/test_runner.sh
bash scripts/benchmark/axvisor-rt/tests/test_starry_runner.sh
bash competition/rt-baseline/common/tests/run.sh
python3 -m unittest discover -s competition/evidence/tests -p 'test_*.py'

cd competition/results/current-source-smoke-20260813
sha256sum -c checksums.sha256
```

这些命令验证配置、协议、分析器和归档完整性；它们不能替代实体板时延或故障恢复。
