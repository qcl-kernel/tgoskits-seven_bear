# 五分钟演示视频脚本与证据索引

成片：[`demo-5min.mp4`](results/current-source-smoke-20260813/demo-5min.mp4)。

这是一次**当前源码实体板结果的后验证据回放**：画面使用 2026-08-13 已归档的
Orange Pi 5 Plus 串口标记、机器 JSON、哈希和源码入口制作，不冒充同时发生的现场
录屏。完整原始输入保留在
[`current-source-smoke-20260813`](results/current-source-smoke-20260813/)，观众可以在
视频结束后逐项复核。

## 时间轴

| 时间 | 画面与讲解 | 对应证据 |
| --- | --- | --- |
| 0:00–0:20 | 赛题目标、Orange Pi 5 Plus / RK3588、StarryOS + Zephyr + AxVisor | `provenance.json` |
| 0:20–0:45 | IVC `598b357f9…`、RT `077ba386c…`、`upstream/dev` 基线与 source boundary | `provenance.json`、`source-delta.txt`、`runtime-inputs.sha256` |
| 0:45–1:15 | typed device graph：两个 VM、CPU/内存、两个独立 virtio-net、Starry block | `design.md`、两份 board TOML |
| 1:15–1:40 | 双客户机 IP 拓扑与协议：`10.0.0.1 ↔ 10.0.0.2:5500`，CONTROL/STATUS/ACK/ERROR | `ivcproto`、IVC summary |
| 1:40–2:20 | 实际 Zephyr VM restart：pCPU3 worker、20 s、session 切换、旧流量拒绝、safe fallback | `ivc/console.log.gz`、`ivc/summary.json` |
| 2:20–2:45 | 重启后 100/100、0 error/timeout/retransmission，full-loop percentiles 和 clean snapshot | `ivc/summary.json` |
| 2:45–3:20 | 当前 RT shared/partitioned 两侧各 3×100 样本，冷启动、lossless IRQ trace、Linux restore | `rt/shared`、`rt/partitioned` |
| 3:20–3:50 | 原样展示单对负向结果与 `m2_exit_gate_met=false` | `rt/comparison.json` |
| 3:50–4:20 | 历史正式五配对受控 host-noise 门通过，同时说明它不是当前源码复跑 | `historical-formal/rt-host-noise` |
| 4:20–4:43 | manual/neural 五配对：RMSE、IAE 改善，overshoot 退化 | `historical-formal/ivc-control` |
| 4:43–4:55 | ACK-loss / ERROR / restart 各 3/3，RKNN/ORT 各 9,000/9,000 | `historical-formal/` |
| 4:55–5:00 | 复现入口、总校验清单和剩余缺口 | `reproduce.md`、`checksums.sha256` |

## 必须说清的边界

- 当前源码的 IVC restart 和 RT 两侧管线在实体板通过，但当前 RT 单对 M2 未通过，不作性能改善主张。
- 正式五配对改善属于记录在各自 clean commit 的历史 F 层活动，不能改标成当前提交。
- neural 相对 manual 改善 RMSE 35.93%、IAE 51.94%，但最大超调退化 96.32%。
- 当前原生 Zephyr 基线不是同一 RK3588，隔离也缺恶意第三客户机动态 capture。
- 精简包不包含本地约 844 MiB 的完整历史 raw archive。

## 录制与验收清单

- [x] 时长约五分钟，1280×720，H.264。
- [x] 明示后验回放，不冒充现场串口直播。
- [x] 展示测试 source commit、upstream base、板卡 identity 与关键输入哈希。
- [x] 展示 StarryOS 双 vCPU、Zephyr、IP/UDP 和 typed device graph。
- [x] 展示实际 VM reset、新旧 session、安全回退和 Linux restore。
- [x] 明示当前 RT 同提交单对的退化与 M2 fail，不隐藏负向结果。
- [x] 历史正式数据与当前源码证据使用不同标签。
- [x] AI 改善和超调退化同时出现。
- [x] 视频文件纳入同一 `checksums.sha256`。
- [ ] 发布完整历史 raw archive 的不可变下载 URL 和顶层 SHA-256。
