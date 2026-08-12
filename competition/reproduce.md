# 复现说明

本文从源码固定、离线验证、镜像构建、实体板 staging、AxVisor 启动、结果
harvest 到证据校验给出可执行步骤。默认从仓库根目录执行。当前已归档的实体冒烟
绑定到源码 commit `069c911c1de02cecdc0c1fe891f5d5a288065ef0`。

## 1. 固定源码与工作区

推荐在 WSL2 的 Linux ext4 文件系统中使用独立 clone，避免 `/mnt/c` checkout
同时被 Windows Git (`core.autocrlf`) 和 WSL Git 解释为不同的换行状态：

```sh
git clone git@github.com:yueneiqi/tgoskits-rt-ivc.git
cd tgoskits-rt-ivc
git checkout 069c911c1de02cecdc0c1fe891f5d5a288065ef0
git config core.autocrlf false

test -z "$(git status --porcelain=v1)"
test "$(git rev-parse HEAD^{tree})" = \
  c13efe6409b3a720828c224147bc1e2ca5682ffe
```

当前实体证据的完整 source attestation 在
[`results/current-source-smoke-20260812/provenance.json`](results/current-source-smoke-20260812/provenance.json)：

```text
upstream/dev              fad09ebd3a05f5e7a13ee6bb3cb7e4076cfdb0a1
tested commit             069c911c1de02cecdc0c1fe891f5d5a288065ef0
tested tree               c13efe6409b3a720828c224147bc1e2ca5682ffe
git archive SHA-256       6b65153c727a31edebf3829ef02e34a65090450d98042f1d8d6fbe0256581102
upstream diff SHA-256     1bf1f0e696c95ccd0de6eb73a8f7812138035eebccc35a7c89ee93bf12bcdfb8
```

验证 source archive：

```sh
git archive --format=tar HEAD | sha256sum
git diff --binary upstream/dev...HEAD | sha256sum
```

每次新测量必须记录 `HEAD`、tree、clean/dirty、完整命令、输入/输出哈希、UTC
开始结束时间和板卡身份。不同源码状态的数值不得拼接为一组配对。

## 2. 环境

已验证环境的关键版本：

| 项目 | 版本/要求 |
| --- | --- |
| Rust | 仓库固定 `nightly-2026-07-15` |
| Python | 3.11+；3.10 需 `competition/requirements-host.txt` |
| Zephyr | upstream v4.3.0，commit `3568e1b6d5cdd51a6b964a2a1d6d29200fea2056` |
| Board | Orange Pi 5 Plus / RK3588 / 16 GiB |
| 串口 | CH340，1,500,000 baud，由 board service 独占 |
| Board Linux | SSH、`rsync`、无密码 `sudo sync/reboot`；rootfs 为 ext4 rw |
| 其他 | `dtc`, `fdtget`, `e2fsprogs`, `rsync`, `libclang`, AArch64 toolchain |

Ubuntu/WSL 常用依赖：

```sh
sudo apt-get update
sudo apt-get install -y \
  build-essential clang libclang-14-dev llvm-14-dev \
  device-tree-compiler e2fsprogs rsync git cmake ninja-build \
  python3 python3-pip python3-venv gcc-aarch64-linux-gnu

rustup +nightly-2026-07-15 target add aarch64-unknown-linux-musl
cargo +nightly-2026-07-15 xtask image pull rootfs-aarch64-busybox.img
```

实体板环境变量示例：

```sh
export ORANGEPI_SSH_TARGET=orangepi@192.168.31.33
export ORANGEPI_SSH_IDENTITY="$HOME/.ssh/orangepi_automation"
export ORANGEPI_SERIAL=/dev/serial/by-path/<your-ch340-path>
export ORANGEPI_AXVISOR_HOST_ROOT=PARTUUID=<board-linux-root-partuuid>

# 冷启动/恢复 Linux 时使用；不要提交含凭据的配置。
export TGOS_BOARD_POWER_CONFIG="$HOME/.config/tgos/board-power.toml"
export ORANGEPI_POWER_PYTHON="$HOME/.local/share/tgos-board-power-venv/bin/python"
```

在板上运行以下命令发现 root selector，不要复制本机示例 PARTUUID：

```sh
findmnt -no SOURCE,FSTYPE,OPTIONS /
blkid
```

预检 board service 与 Linux：

```sh
cargo xtask board ls
ssh -i "$ORANGEPI_SSH_IDENTITY" -o IdentitiesOnly=yes \
  "$ORANGEPI_SSH_TARGET" \
  'hostname; findmnt -no SOURCE,FSTYPE,OPTIONS /; sync'
```

必须先取得 board lease 再 staging/reboot。不要让 SSH、串口终端和
`cargo xtask ... board` 分别抢占同一个 CH340。

## 3. 离线门

```sh
python3 -m unittest discover -s competition/ivc/tests -p 'test_*.py'
python3 -m unittest discover \
  -s scripts/benchmark/axvisor-rt/tests -p 'test_*.py'
bash competition/ivc/zephyr/run-host-tests.sh
bash scripts/benchmark/axvisor-rt/tests/test_runner.sh
bash scripts/benchmark/axvisor-rt/tests/test_starry_runner.sh
```

device-graph 配置门至少覆盖：

```sh
cargo run -p axvmconfig -- \
  check --config-path competition/ivc/config/orangepi-5-plus-starry-smp2-restart.toml
cargo run -p axvmconfig -- \
  check --config-path competition/ivc/config/orangepi-5-plus-zephyr-restart.toml
cargo run -p axvmconfig -- \
  check --config-path scripts/benchmark/axvisor-rt/config/starry-orangepi-5-plus-smp2-shared.toml
cargo run -p axvmconfig -- \
  check --config-path scripts/benchmark/axvisor-rt/config/starry-orangepi-5-plus-smp2-partitioned.toml
```

新格式的要点是 typed `[devices]`：`virtual` 项只给稳定 `id`、注册的
`model` 与 model-owned option。MMIO/IRQ 由 device graph 分配并写入 guest
FDT；基础 DTB 不得重复声明 `virtio_mmio@...`。

## 4. 构建 IVC 客户机

### 4.1 StarryOS

以下单命令构建双 vCPU StarryOS kernel、无 graph-owned virtio 节点的 DTB，
以及 native neural/manual/fault rootfs：

```sh
bash competition/ivc/starry/build.sh 2>&1 | tee tmp/ivc-starry-build.log
```

restart 路线的三个关键输出：

```text
tmp/competition/ivc/starry/starryos.bin
tmp/competition/ivc/starry/starry-orangepi-5-plus.dtb
tmp/competition/ivc/starry/starry-ivc-rootfs-restart.img
```

当前证据对应 SHA-256：

```text
starryos.bin                         97fce5daaa9103768736b9a54a690e5f4612a221ac67672c56cebaadaf4c4b05
starry-orangepi-5-plus.dtb           bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981
starry-ivc-rootfs-restart.img        1c51f3fc84ee543ded52ab6626ba8fb6f60edefff1367b362a872597d403e1d8
```

构建脚本使用 `rustup run nightly-2026-07-15 rust-objcopy`，不会依赖 PATH 中
另一个 nightly 的 `rust-objcopy`。

### 4.2 Zephyr v4.3.0

建立 upstream Zephyr workspace 后构建 restart image：

```sh
west build -p always -b qemu_cortex_a53 \
  -d <repo>/competition/ivc/zephyr/build-board-restart \
  <repo>/competition/ivc/zephyr -- \
  -DEXTRA_CONF_FILE=board-restart.conf

sha256sum \
  <repo>/competition/ivc/zephyr/build-board-restart/zephyr/zephyr.bin
```

当前证据使用 `393026c1702d33115b42bdf72528efe49eeb4f0d9e93f3755d6be57354b5791f`。
完整 Zephyr SDK/非 SDK 构建说明见 [`ivc/zephyr/README.md`](ivc/zephyr/README.md)。

## 5. 当前源码 IVC 实体冒烟

`run-orangepi-5-plus.sh` 对 native profile 会先调用仓库内
`stage-starry-control.sh`。stager 持有 lease，以 `.new` 上传 kernel/DTB/rootfs，
原子 rename，执行 `sync`，并在板端 `sha256sum -c`；因此不会误用上次运行残留
的 guest image。

```sh
result_root=tmp/reproduction/ivc-restart-$(date -u +%Y%m%dT%H%M%SZ)

bash competition/ivc/run-orangepi-5-plus.sh fault-restart \
  --result-dir "$result_root" \
  --timeout 900 \
  --restore-linux
```

runner 只在以下链路全部成立时返回 0：

1. StarryOS 与 Zephyr 从 device graph 创建的设备启动；
2. 20 条旧 session 命令完成；
3. AxVisor 对 Starry VM 做实际 reset，并从 pristine RAM 恢复；
4. 新 session 完成 100 条命令，旧 CONTROL/STATUS/ACK 被拒绝；
5. 客户机结果盘 snapshot 与 host filesystem 显式同步；
6. Linux 冷启动恢复，rootfs 再次为 ext4 rw；
7. raw/console/summary/metadata 与 checksum 写完。

关键成功标记：

```text
AXVISOR_GUEST_RESTART_COMPLETE
IVC-STARRY-DONE exit=0
IVC-RTOS-OUTCOME profile=restart accepted=120 applied=120
AXVISOR_SNAPSHOT_SYNC_OK
AXVISOR_HOST_FILESYSTEM_SYNCED
BOARD_LINUX_RESTORED
ORANGEPI_IVC_RUNS_COMPLETE
```

重新分析已归档 current-source 结果：

```sh
python3 competition/ivc/analyze_board.py \
  competition/results/current-source-smoke-20260812/ivc/console.log.gz \
  --raw-csv competition/results/current-source-smoke-20260812/ivc/raw.csv.gz \
  --pre-reset-raw-csv competition/results/current-source-smoke-20260812/ivc/raw-before-reset.csv.gz \
  --expected-count 100 \
  --expected-pre-reset-count 20 \
  --profile restart \
  --output tmp/reproduction/ivc-reanalyzed.json
```

不要直接用裸 `cargo xtask axvisor board` 替代仓库 runner：裸命令不负责
staging、snapshot harvest、供电恢复和最终 Linux rootfs gate。

## 6. 当前源码 RT shared/partitioned 冒烟

重建内核与 64 MiB capture rootfs：

```sh
bash scripts/benchmark/axvisor-rt/build-starry-kernel.sh

bash scripts/benchmark/axvisor-rt/build-starry-rootfs.sh \
  --mode capture \
  --workload cpu-stress \
  --iterations 100 \
  --output tmp/axvisor-rt/starry-rt-capture-rootfs.img

bash scripts/benchmark/axvisor-rt/stage-starry-board.sh
```

当前输入哈希：

```text
Starry RT kernel       46badacbfbaeda4c396c16925f6cf8d0193cac2bf638534c101369f8d4b21b56
guest DTB              bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981
capture rootfs         8f43624c491fc784331426feb297287bec647bd145f367045b0b55e44b9969f3
static RT probe        8b3f6e7471dc9ecf60d5b64ab5f3c3a4657af8743fde1aa6b1772358c62806da
guest capture runner   38473826ce2d5b36a4fca809200791a74d898b4c47d05f58735319b40677fd6b
```

对每个 profile 执行完整冷启动和恢复。下面的 `result_dir` 必须不存在：

```sh
result_root=tmp/reproduction/rt-pair-$(date -u +%Y%m%dT%H%M%SZ)

for profile in shared partitioned; do
  result_dir="$result_root/$profile"
  mkdir -p "$result_dir"

  env \
    ORANGEPI_AXVISOR_BUILD_CONFIG="scripts/benchmark/axvisor-rt/config/axvisor-orangepi-5-plus-starry-$profile.toml" \
    ORANGEPI_AXVISOR_BOARD_CONFIG="scripts/benchmark/axvisor-rt/config/board-orangepi-5-plus-starry-$profile.toml" \
    ORANGEPI_AXVISOR_SHUTDOWN_MARKER_REQUIRED=1 \
    ORANGEPI_RESTORE_LINUX=1 \
    ORANGEPI_RUN_TIMEOUT_SECONDS=900 \
    bash competition/ivc/orangepi/board-runner.sh \
    2>&1 | tee "$result_dir/console.log"

  env \
    ORANGEPI_RT_RESULT_IMAGE=/home/rt \
    ORANGEPI_RT_RAW_LOG="$result_dir/raw.log" \
    ORANGEPI_RT_SUMMARY_JSON="$result_dir/summary.json" \
    ORANGEPI_RT_GUEST_IRQ_LOG="$result_dir/guest-irq.log.gz" \
    ORANGEPI_RT_HOST_TRACE_LOG="$result_dir/host.log" \
    ORANGEPI_RT_PROFILE="$profile" \
    ORANGEPI_RT_EXPECTED_WORKLOAD=cpu-stress \
    ORANGEPI_RT_EXPECTED_ITERATIONS=100 \
    ORANGEPI_RT_SOAK=0 \
    bash scripts/benchmark/axvisor-rt/harvest-starry-board.sh \
    2>&1 | tee "$result_dir/harvest.log"
done

python3 scripts/benchmark/axvisor-rt/compare_starry_board.py \
  "$result_root/shared/summary.json" \
  "$result_root/partitioned/summary.json" \
  --output "$result_root/comparison.json"
```

比较器的 `improvement_percent` 正数表示 partitioned 更低。它故意把单对结果的
`m2_exit_gate_met` 置为 false；正式 M2 至少需要五个预注册正交配对和两侧 soak。

## 7. 正式活动规则

正式活动与 smoke 的差别不是目录名，而是以下 fail-closed 条件：

- 在第一轮前固定完整 40 位 commit、AB/BA 顺序、阈值、profile 和输入哈希；
- clean worktree，且同一 campaign 内不得换 commit/镜像/config；
- 每个 half 全新板卡会话、完整 snapshot、fsck、Linux restore；
- RT 五对使用 controlled host interference，shared 固定 pCPU1、partitioned
  固定 pCPU3，并验证观测 affinity 与覆盖区间；
- RT shared/partitioned 各做至少 1,800 秒 soak；
- IVC manual/neural 使用 AB/BA/AB/BA/AB 五对；fault profile 各 3 次；
- 任何失败尝试保留原始状态，不用离线 replay 改写为成功 run。

RT 正式入口先在 clean worktree 中构建并冻结全部输入。`base_rootfs` 使用已由
`cargo xtask image pull rootfs-aarch64-busybox.img` 获取的受管镜像；`result_root`
必须是尚不存在的新目录：

```sh
commit=$(git rev-parse HEAD)
source_ref=$(git symbolic-ref --quiet --short HEAD || printf 'detached-head')
base_rootfs=.tgos-images/rootfs-aarch64-busybox.img/rootfs-aarch64-busybox.img
result_root=/home/$USER/Workspace/starry/results/rt-formal-20260812-$commit

bash scripts/benchmark/axvisor-rt/run-formal-campaign.sh prepare \
  --result-dir "$result_root" \
  --expected-commit "$commit" \
  --source-ref "$source_ref" \
  --base-rootfs "$base_rootfs" \
  --hardware-id bf61f4d4a1d994ad \
  --hostname orangepi5plus \
  --service-id orangepi-5-plus-1 \
  --board OrangePi-5-Plus
```

每次只跑下一个冻结 slot，适合在首次 pair 通过后检查再继续，也适合中断恢复：

```sh
bash scripts/benchmark/axvisor-rt/run-formal-campaign.sh status \
  --result-dir "$result_root"

bash scripts/benchmark/axvisor-rt/run-formal-campaign.sh run-next \
  --result-dir "$result_root"

bash scripts/benchmark/axvisor-rt/run-formal-campaign.sh run-all \
  --result-dir "$result_root"
```

`run-all` 完成十二个 slot 后自动聚合。若需要单独重验派生结果：

```sh
bash scripts/benchmark/axvisor-rt/run-formal-campaign.sh aggregate \
  --result-dir "$result_root"

jq -e '.assessment.m2_exit_gate_met == true' \
  "$result_root/campaign-summary.json"
(cd "$result_root" && sha256sum -c checksums.sha256)
```

正式入口在每个 half 前重验 commit/tree、关键源码和所有制品哈希，并验证 stage 与
harvest 都是同一 `bf61f4d4a1d994ad/orangepi5plus` 实体板。任一步失败时不会创建
`receipt.json`；修复源码后必须新提交并使用新的 `result_root` 重新预注册，不能编辑
旧收据或降低阈值。设计、替代方案和状态机见
[`book/design/axvisor-rt-formal-campaign.md`](../book/design/axvisor-rt-formal-campaign.md)。

IVC manual/neural 的冻结顺序由 `run-control-campaign.sh formal` 生成：

```sh
bash competition/ivc/run-control-campaign.sh formal \
  --result-dir <new-result-root> \
  --expected-commit "$(git rev-parse HEAD)" \
  --timeout 900
```

## 8. AI 模型与后端

确定性模型链：

```sh
bash competition/ivc/model/rebuild-check.sh
bash competition/ivc/model/rebuild-rknn-check.sh
bash competition/ivc/model/rebuild-ort-check.sh
```

这些脚本分别验证 canonical weights/golden vectors → ONNX、ONNX → RK3588
FP16 RKNN、ONNX → ORT format。RKNN Toolkit2、ONNX Runtime、模型、required
operators 和数值容差由 [`ivc/model/README.md`](ivc/model/README.md) 与
`model-manifest.json` 固定。不要把 native Rust、RKNN NPU 与 ORT CPU 的
初始化/推理时间混成一个统计系列。

## 9. 证据包与视频

验证当前 compact bundle：

```sh
cd competition/results/current-source-smoke-20260812
sha256sum -c checksums.sha256
python3 -m json.tool provenance.json >/dev/null
python3 -m json.tool ivc/summary.json >/dev/null
python3 -m json.tool rt/comparison.json >/dev/null
```

五分钟成片：

```text
competition/results/current-source-smoke-20260812/demo-5min.mp4
```

它是实际串口日志和机器 summary 的后制证据回放，不伪装成同步拍摄的板卡视频。
镜头和重新生成说明见 [`video-storyboard.md`](video-storyboard.md)。

## 10. 复现成功判定

一次实体运行只有同时满足以下条件才算成功：

- runner exit 0，未命中 panic/exception/timeout/fail regex；
- guest 完成 marker、期望样本数、协议计数与 workload 生命周期通过 analyzer；
- snapshot hash、raw hash、guest IRQ hash、host trace hash一致；
- ext4 snapshot 为 clean，且 AxVisor host filesystem 已同步；
- 板卡最终回到预期 Linux hostname，根文件系统为 ext4 rw；
- metadata、summary、raw、console 和 checksum 全部落盘。

QEMU/host tests、离线 replay、串口中看到一行成功 marker 都不能单独替代上述实体
生命周期门。
