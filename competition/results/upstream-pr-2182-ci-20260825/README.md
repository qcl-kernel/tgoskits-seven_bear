# 上游 PR #2182 CI 成功证据

本目录记录代码专用 PR `rcore-os/tgoskits#2182` 在 HEAD `75d8f3918580471a3451b29ca5d33a015bd5bb81` 上的 GitHub Actions 成功结果。CI 主运行 `32794757246` 于 2026-08-25 完成，35 个任务全部成功，失败和取消任务均为 0。

| 证据项 | 结果 |
| --- | --- |
| Formatting + publish dry-run | SUCCESS |
| Synchronization lint | SUCCESS |
| Workspace Incremental Clippy | SUCCESS |
| Workspace std tests | SUCCESS |
| AxVisor QEMU aarch64 IVC | SUCCESS |
| AxVisor QEMU aarch64 smoke / virtio-blk / timer stress | SUCCESS |
| Orange Pi 5 Plus Linux 与 StarryOS Guest | SUCCESS |
| Orange Pi 5 Plus robot Linux 与 StarryOS Guest | SUCCESS |

完整运行页面见 <https://github.com/rcore-os/tgoskits/actions/runs/32794757246>，机器可读摘要见 `summary.json`。成果分支分别以 `adf9e671dd93f6b8c315aa06d732ede1f6d54d00` 和 `7b5c59af5c199dff4c95166ef4e743cdc6d00b1c` 同步 PR 修复 `cf52846efe04166f17282e5fc10426be6d64e947` 与 `75d8f3918580471a3451b29ca5d33a015bd5bb81`。

## 证据边界

本记录证明代码专用 PR HEAD 通过了列出的持续集成任务，并证明此前失败的 AArch64 IVC 路径已恢复。它不等同于在成果分支文档提交上重新执行正式 RT 五配对与双 soak，也不改变历史性能数据的源提交归属。
