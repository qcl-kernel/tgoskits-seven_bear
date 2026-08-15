# RTOS Guest/IVC 复现说明

本目录除实体板上的 StarryOS + Zephyr 主路径外，还提供 RT-Thread v5.2.2
和 FreeRTOS 的 QEMU/AArch64 AxVisor Guest/IVC 路径。两种 RTOS 都作为 VM2，
通过 AxVisor typed `virtio-net-mmio` 接入 segment 1，并与 VM1 Linux 控制端完成
同一套 IVC/1 UDP 控制闭环。

## 支持边界

| RTOS | 固定上游 | AxVisor guest boot | IVC/1 normal | IVC/1 ACK-loss |
| --- | --- | --- | --- | --- |
| Zephyr v4.3.0 | `3568e1b6…` | 已验证（QEMU/实体板） | 已验证 | 已验证 |
| RT-Thread v5.2.2 | `ddf52e2c…` | 已验证（QEMU/AArch64） | 100/100 | 20 次丢 ACK、20 次去重恢复 |
| FreeRTOS Kernel | `f1043c49…` | 已验证（QEMU/AArch64） | 100/100 | 20 次丢 ACK、20 次去重恢复 |

RT-Thread/FreeRTOS 的结论限定为 QEMU/AArch64：尚未在 RK3588 实体板验证，也不把
原生 RTOS 实时基线当作 Guest/IVC 证据。当前 QEMU 活动使用 Linux 控制端；它证明
RTOS Guest 的 VirtIO/IP/IVC 端点兼容性，不替代 StarryOS + RTOS 的实体组合验证。

## 固定资源契约

| 资源 | Linux VM1 | RTOS VM2 |
| --- | --- | --- |
| vCPU / pCPU | 2 / pCPU1、pCPU2 | 1 / pCPU0 |
| RAM | `0x80000000`，256 MiB | RT-Thread `0x40000000`，FreeRTOS `0x50000000`，均为 128 MiB |
| IPv4 | `10.0.0.1/24` | `10.0.0.2/24` |
| MAC | `52:54:00:00:00:01` | `52:54:00:00:00:02` |
| VirtIO MMIO | device graph 自动分配 | `0x0b000000` / `0x1000`，INTID 32 |
| 协议 | IVC/1 controller | UDP 5500 endpoint，固定 12-byte VirtIO net header |

RT-Thread 在 `main()` 前已开启 MMU，因此使用 `rt_ioremap` 将上述设备 GPA 映射为
Device memory；FreeRTOS/Bao 当前 QEMU 平台保持所需的恒等映射。两种适配器共享
仓库内的 VirtIO 1.x MMIO raw Ethernet 驱动、IVC/1 codec、receive window、热模型
和 RTOS server，仅保留各自网络栈、时钟与任务 glue。

## 从干净环境复现

以下命令在 Linux/WSL 中执行。准备脚本校验固定 commit 和 clean worktree；构建和
证据目录存在时会拒绝覆盖，复测应使用新的输出目录。

```sh
bash competition/ivc/rtthread/prepare.sh
bash competition/ivc/freertos/prepare.sh
bash competition/ivc/linux/build-initramfs.sh

bash competition/ivc/run-rtos-qemu.sh rtthread normal \
  tmp/competition/ivc/results/rtthread-normal-1
bash competition/ivc/run-rtos-qemu.sh rtthread ack-loss \
  tmp/competition/ivc/results/rtthread-ack-loss-1
bash competition/ivc/run-rtos-qemu.sh freertos normal \
  tmp/competition/ivc/results/freertos-normal-1
bash competition/ivc/run-rtos-qemu.sh freertos ack-loss \
  tmp/competition/ivc/results/freertos-ack-loss-1
```

runner 会按需构建 Guest，验证 ELF entry 和所有非空 `LOAD` 区间均位于声明 RAM，
再通过 `cargo xtask axvisor qemu` 启动双 Guest。成功目录包含 Guest 来源/哈希、实际
AxVisor/QEMU 配置、命令、原始串口日志、机器 `summary.json` 与 `SHA256SUMS`。

normal 的严格后置条件是两侧均完成 100 个命令，RTOS `applied=100`、
`duplicates=0`、`protocol_errors=0`，控制端 `acknowledged=100` 且无重传。ACK-loss
固定丢弃序号 5、10、…、100 的 ACK，要求 `applied=100`、`duplicates=20`、
`acks_dropped=20`，控制端 `retransmissions=20`、`recoveries=20`、最终仍为 100%。
故障注入或活动结束后的控制端静默会触发 actuator=0 的安全回退日志，这是预期
安全行为，不代表命令被重复应用。

## 低层回归

```sh
bash competition/ivc/common/run-host-tests.sh
bash competition/ivc/zephyr/run-host-tests.sh
python3 -m unittest \
  competition.ivc.tests.test_analyze_qemu \
  competition.ivc.tests.test_qemu_config \
  competition.ivc.tests.test_rtos_guest_contract \
  competition.ivc.tests.test_validate_guest_elf
```

已知限制是 RX 使用 RTOS polling task 而非 Guest IRQ 唤醒；这适合当前 100 ms 控制
周期，但不能作为中断时延结果。FreeRTOS 还继承 Bao linker 的 RWX `LOAD` warning，
RT-Thread 构建会输出少量上游声明/未使用函数 warning；这些 warning 均不被隐去，
也不影响本次严格的 Guest/IVC 运行后置条件。
