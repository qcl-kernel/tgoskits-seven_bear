# 测试与证据报告

报告日期：2026-08-12。当前实体板冒烟绑定到源码提交
`069c911c1de02cecdc0c1fe891f5d5a288065ef0`，其上游基线为
`upstream/dev` 的 `fad09ebd3a05f5e7a13ee6bb3cb7e4076cfdb0a1`。运行前 Windows Git
确认 tracked worktree 干净；所有实际输入、输出、Git tree 和板卡身份均记录在
[`current-source-smoke-20260812/provenance.json`](results/current-source-smoke-20260812/provenance.json)。

本报告严格区分四类证据：

| 标签 | 证据范围 | 可以支持的结论 |
| --- | --- | --- |
| C0 | 当前源码提交的 Orange Pi 5 Plus 实体板冒烟 | 当前 device graph、构建、部署、启动、采集、故障恢复和 Linux 回切链可用 |
| F | 历史 clean commit 上预注册的正式实体板多轮活动 | 统计性性能、可靠性和 AI 对照结论；不得改标为当前源码结果 |
| H | host、QEMU、单元、契约和静态测试 | 软件边界与失败路径正确；不得替代实体板时延 |
| D | 设计、配置和源码溯源 | 机制存在及资源契约可审查；不得单独证明运行效果 |

## 1. 结论摘要

| 目标 | 结果 | 证据边界 |
| --- | --- | --- |
| StarryOS + Zephyr 从 typed device graph 启动 | PASS | C0，两次完整冷启动；StarryOS 为 2 vCPU |
| 双客户机 UDP/IPv4 控制闭环 | PASS | C0，当前 restart run 共应用 120 条 CONTROL |
| 实际 Zephyr VM 重启与会话恢复 | PASS | C0，pCPU3 上 `running → reset → running`，新旧 session 分离 |
| RT shared/partitioned 采集链 | PASS | C0，各三项客户机指标 × 100 样本，直接 IRQ trace 无丢失，快照 clean，Linux 恢复 |
| 当前 RT 性能门 M2 | **FAIL** | C0 只有一对且多个尾延迟退化；不能声称当前源码已复现性能改善 |
| RT 正式受控干扰门 | PASS | F，五配对、每指标每 run 10,000 样本、shared/partitioned 双 soak ≥1,800 秒 |
| manual/neural 控制效果 | 混合结果 | F，RMSE 和 IAE 改善，最大超调退化；完整披露 |
| ACK-loss、ERROR、VM restart 故障活动 | PASS | F，各 3/3；C0 另有一次实际 restart |
| 完整历史 raw 可公开下载 | **尚未完成** | 本地约 844 MiB，提交中只有精简索引和当前 C0 raw |

## 2. 当前源码实体板：IVC 重启恢复

板卡为 Orange Pi 5 Plus / RK3588，hardware ID `bf61f4d4a1d994ad`，hostname
`orangepi5plus`。runner 在持有板卡 lease 时通过 Linux 原子暂存当前 StarryOS
kernel、DTB、重启用 rootfs 和 Zephyr image，远端逐项执行 `sha256sum -c`，然后
`sync` 并冷启动 AxVisor。结束后快照文件系统检查为 clean，板卡恢复到
`/dev/mmcblk1p2` ext4 读写 Linux；采集温度为 42.538 °C。

输入哈希：

| 输入 | SHA-256 |
| --- | --- |
| StarryOS kernel | `97fce5daaa9103768736b9a54a690e5f4612a221ac67672c56cebaadaf4c4b05` |
| Orange Pi DTB | `bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981` |
| StarryOS restart rootfs | `1c51f3fc84ee543ded52ab6626ba8fb6f60edefff1367b362a872597d403e1d8` |
| Zephyr guest | `393026c1702d33115b42bdf72528efe49eeb4f0d9e93f3755d6be57354b5791f` |

实际重启由 pCPU3 worker 延时 20,000 ms 触发，`reset_count=1`。旧 session
`286331153` 被退休，新 session `572662306` 被接受。重启前保留 20 个样本，重启后
100/100 指令确认，controller error/timeout/retransmission/recovery 均为 0；Zephyr
合计 accepted/applied 为 120/120。故障探针还确认：safe fallback、session reset、
retired CONTROL rejection、stale STATUS ignore、stale ACK ignore 各发生一次，且产生
1 条 typed ERROR。该结果证明的是重启安全性和闭环恢复，不是无扰动稳态性能。

重启后 100 样本的测量为：

| 指标 | 结果 |
| --- | ---: |
| success / throughput | 100% / 9.956 msg/s |
| full-loop p50 / p95 / p99 / max | 2,307 / 8,235 / 34,907 / 67,388 µs |
| RMSE | 20,435.735 m°C |
| IAE | 185,638.1 m°C·s |
| 最大超调 | 0 m°C |

机器结果、原始 CSV、串口和 wrapper 在
[`ivc/`](results/current-source-smoke-20260812/ivc/)。原始 metadata 中的
`dirty=true` 没有被改写：它来自 WSL Git 对 Windows `core.autocrlf` checkout 的
换行差异判断。Windows Git 的运行前 clean 断言、源码 tree/archive 哈希和实际输入
字节哈希作为增量澄清记录在 provenance 中。

## 3. 当前源码实体板：RT shared/partitioned 冒烟

两次运行均从当前源码重建 StarryOS kernel，使用同一 64 MiB capture rootfs、同一
DTB 和同一探针。每次完整经历部署、冷启动、StarryOS 双 vCPU 采集、volatile block
快照、host filesystem sync、关机和 Linux 恢复。每个客户机指标保留 100 样本；
guest/host 直接 IRQ trace 均通过 lossless 校验且 vCPU migration 为 0。

| 指标（ns） | shared p99 / max | partitioned p99 / max | 改善率 p99 / max |
| --- | ---: | ---: | ---: |
| periodic jitter | 215,042 / 238,834 | 330,542 / 412,375 | **-53.710% / -72.662%** |
| dispatch latency | 56,291 / 145,833 | 143,500 / 144,958 | **-154.925% / +0.600%** |
| timerfd IRQ proxy | 8,723,208 / 9,661,667 | 8,561,333 / 9,500,083 | +1.856% / +1.672% |
| virtual timer injection → guest IRQ | 10,913,875 / 421,827,291 | 11,537,458 / 423,535,000 | **-5.714% / -0.405%** |

正值表示 partitioned 更低。该对照的
[`comparison.json`](results/current-source-smoke-20260812/rt/comparison.json)
明确给出 `m2_exit_gate_met=false`：单对、未受控 host interference，且 jitter、
dispatch p99 和直接 IRQ 尾部退化。它只验证当前源码端到端管线，不能替代五配对
正式活动，也不能用“平均更好”掩盖最坏值。

## 4. 历史正式 RT 活动

### 4.1 受控 host interference

精简材料位于
[`historical-formal/rt-host-noise`](results/current-source-smoke-20260812/historical-formal/rt-host-noise/)。
预注册、三次执行前 amendment、soak 预注册和分析契约均被保留。正式 batch 的
measurement commit 为 `0588743ecb807d7363a3dec90c17a159179933b0`，soak 的
measurement commit 为 `2e97430f2171667d4ec16c3a02931653f7ddedf8`。

五个 AB/BA 配对各对 shared 和 partitioned 采集，每个客户机指标每 run 10,000
样本，并完成两侧 ≥1,800 秒 soak。`m2_exit_gate_met=true`。受控干扰模型刻意把
host activity 放入 shared 客户机的 CPU 路径，因此周期和 timerfd proxy 的极大改善
是该 treatment 的效果，不应外推到普通无干扰 workload。

| 正式门指标 | 五对结果 / worst-of-runs |
| --- | ---: |
| direct IRQ p99 | 5/5 改善；worst-of-runs 改善 99.639% |
| direct IRQ max | 5/5 改善；worst-of-runs 改善 87.771% |
| dispatch p99 | 5/5 非退化；worst-of-runs 改善 28.111% |
| dispatch max | 5/5 改善；worst-of-runs 改善 99.773% |

### 4.2 同 VM 客户机 CPU1 stress

[`historical-formal/rt-stress`](results/current-source-smoke-20260812/historical-formal/rt-stress/)
包含五对、十次 lossless capture 和 300,000 个客户机用户态样本，固定 vCPU 放置均
通过。该 workload 与被测任务处于同一 StarryOS VM，不能作为隔离 treatment。
结果也是混合的：dispatch p99 五对均退化，worst-of-runs max 退化 10.443%。因此
报告只主张受控 host-noise 场景的 M2 改善，不主张 partitioning 对所有压力源普遍
降低时延。

## 5. 历史正式 IVC 与 AI 活动

### 5.1 manual/neural AB/BA 五配对

正式 v5 活动绑定 source commit
`f4ced37584964aba56e07ff060ae58374608bc26`，同一实体板完成五个 AB/BA 配对，
10/10 run 均有效。精简 summary/preregistration 位于
[`historical-formal/ivc-control`](results/current-source-smoke-20260812/historical-formal/ivc-control/)。

| 控制指标 | manual | neural | neural 相对变化 |
| --- | ---: | ---: | ---: |
| RMSE (m°C) | 9,258.906 | 5,932.491 | 改善 35.93% |
| IAE (m°C·s) | 1,429,224.7 | 686,993.4 | 改善 51.94% |
| 最大超调 (m°C) | 6,840 | 13,428 | **退化 96.32%** |

full-loop p99 只有 2/5 配对有利于 neural，所以不声称神经策略更低延迟。它的
价值是以更高超调换取更低累计控制误差，取舍由结果显式呈现。

### 5.2 可靠性故障活动

| 活动 | source commit | 正式结果 | 被验证的机制 |
| --- | --- | ---: | --- |
| ACK loss | `bac4ad16b4adf673942e6c31897872c2c5c116dc` | 3/3 | timeout、重传、重复抑制、exactly-once apply |
| typed ERROR | `29be4fc4c8668b8e94cd253fb4484bbeba1d8481` | 3/3 | 错误通知和失败闭合 |
| actual VM restart | `6adf49e09ce91b53d2573cb8d34c60dc6a9ec47c` | 3/3 | 新 session、旧流量拒绝、safe fallback、恢复 |

三类活动都通过 raw gzip、manifest、lifecycle 和 Linux restore gate；精简材料分别在
`historical-formal/ivc-ack-loss`、`ivc-error` 和 `ivc-restart`。

### 5.3 神经推理后端

| 后端 | source commit | 样本 | 结果 |
| --- | --- | ---: | --- |
| RKNN / RK3588 NPU | `c3f01dc34b83695eddf8da83cf4ed71622f64f7c` | 5 × 1,800 | 9,000/9,000；仅每 run 首周期 miss，共 5 次；首周期后 0 miss/error/timeout；device p99 ≈1.67 ms |
| ONNX Runtime / CPU | `0110647de52f5e2ad6b550cb594780d7506ffecf` | 5 × 1,800 | 9,000/9,000；同样仅 5 次首周期 miss；ORT wall p99 约 174–176 µs |

两种后端的 full-loop p99 约为 12–13.5 ms。后端结果用于证明 StarryOS 内推理部署和
网络闭环，不把不同执行设备的墙钟值直接当作公平加速比。

## 6. 源码与产物溯源

精简包提供三层绑定：

1. `provenance.json` 绑定 commit、tree、`git archive`、相对 upstream diff、板卡身份和运行结论；
2. `runtime-inputs.sha256` 绑定配置、stager、runner、analyzer、guest 程序、模型和探针的实际字节；
3. `source-files.git-ls-tree.txt` 把相关路径映射到 Git blob ID，当前 raw/console/summary 再由总 manifest 覆盖。

`commands/` 中的两个 wrapper 是运行时原始命令记录，包含绝对工作区路径，因此用于
审计而不是跨机器直接复制。可移植命令见 [`reproduce.md`](reproduce.md)。历史目录中
原始 `checksums.sha256` 是完整 844 MiB archive 的索引；精简包自己的
`checksums.sha256` 才是本目录可直接执行的完整性入口。

## 7. 已执行验证

与当前实体运行对应的回归已通过：IVC test discovery 183/183、Starry staging contract
20/20、AxVisor AArch64 `axtest` 79/79、相关 `axbuild` 107/107、RT shell runner，以及
targeted clippy 和 rustfmt。最终文档/证据提交另保留 JSON、gzip、Markdown 链接、
checksum 和 `git diff --check` 的验证日志于
[`validation/`](results/current-source-smoke-20260812/validation/)。

完整 `axbuild` sweep 曾遇到一个与本工作无关、已存在的 Starry grouped-QEMU failure
并在后续矩阵中超时；本报告没有把那次 sweep 写成全绿，也没有降低测试断言。

## 8. 测量限制与待补强项

- 当前 C0 RT 只有一对，且 M2 fail；最终提交应重跑正式五对与双 soak，闭合源码版本差。
- 完整历史 raw archive 仍只在本地 `results/orangepi-5-plus/`，提交的精简 summary 无法重算所有历史统计；应发布不可变下载和总 SHA-256。
- 原生 Zephyr 基线目前是等价 QEMU 平台，不是同一 RK3588；不能消除硬件与时钟源差异。
- 隔离由 device graph、switch policy 和 H 层负例支持，但没有恶意第三客户机的实体/QEMU 动态 capture。
- 当前视频是对已归档实体串口和机器结果的五分钟后验回放，不是伪装成现场实时采集的录像。
- 所有 maximum 都是观察样本最大值，不是 WCET 证明或硬实时上界。
