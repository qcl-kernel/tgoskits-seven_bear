# seven_bear 成果材料

本目录是 `seven_bear` 团队的比赛成果统一入口。最终成果以 AxVisor 虚拟化技术为核心，包括原型系统、完整源代码、详细技术文档、测试报告和演示视频。

## 交付文件

| 文件 | 内容 |
| --- | --- |
| `tgoskits-competition-design-zh.pdf` | 详细技术文档，说明系统架构、虚拟化与 IVC 方案、RK3588 板端实现、视觉闭环及 SO-100 执行器验证。 |
| `tgoskits-competition-test-report-zh.pdf` | 测试报告，汇总实时性、隔离性、视觉性能、原生 RTOS 基线及物理执行器证据。 |
| `tgoskits-ivc-competition-demo.mp4` | 五分钟成果演示视频。 |
| `SHA256SUMS` | 上述三项交付文件的 SHA-256 完整性校验值。 |

## 上游 PR CI 交付验证

上游 PR `rcore-os/tgoskits#2182` 在代码提交 `75d8f3918580471a3451b29ca5d33a015bd5bb81` 上完成 CI 运行 `32794757246`，主流水线 35 个任务全部成功。通过项包括 Formatting、Synchronization lint、Workspace Clippy/std tests、AArch64 IVC，以及 Orange Pi 5 Plus 的 Linux、StarryOS 与 robot 板卡任务。成果分支以 patch-equivalent 方式同步了 RT 工具修复和已分配 SPI 归属修复；机器可读快照见 `competition/results/upstream-pr-2182-ci-20260825/summary.json`。该结果属于集成验证，不替代正式 RT 五配对与双 soak 的当前 HEAD 板端重跑。

## 原型系统与源代码

源代码保留在仓库原有工程结构中，避免在成果目录内复制并形成多个实现版本：

- AxVisor 原型系统：[os/axvisor](../os/axvisor/)
- 虚拟机与设备模型：[virtualization/axvm](../virtualization/axvm/)、[virtualization/axdevice](../virtualization/axdevice/)
- IVC 与 Orange Pi 5 Plus 板端流程：[competition/ivc](../competition/ivc/)
- 连续视觉闭环与分析工具：[competition/vision](../competition/vision/)
- RK3588 UVC/RKNN 应用：[apps/starry/orangepi-5-plus-uvc-rknn](../apps/starry/orangepi-5-plus-uvc-rknn/)
- 原始测试证据：[competition/results](../competition/results/)
- Upstream PR CI 成功证据：[competition/results/upstream-pr-2182-ci-20260825](../competition/results/upstream-pr-2182-ci-20260825/)

完整的成果生成与复现说明见 [reproduction-guide.md](../competition/submission/reproduction-guide.md)，正式交付包校验入口见 [competition/submission/README.md](../competition/submission/README.md)。

## 完整性校验

在本目录执行：

```bash
sha256sum -c SHA256SUMS
```
