# 复现说明

本文从源码固定、离线验证、镜像构建、实体板 staging、AxVisor 启动、结果
harvest 到证据校验给出可执行步骤。默认从仓库根目录执行。已归档的早期实体冒烟
分为两个明确层次：RT shared/partitioned 运行绑定
`077ba386c20c29b84749f509b29e8a3f6f76e1e2`，最终 IVC 重启闭环绑定
`598b357f92c848e669c12cca830a4d08d0a50e36`。两者之间仅修改
`competition/ivc/`，精确边界在证据包的 `source-delta.txt`。
当前正式 RT 五配对和双 soak 另行绑定 clean commit
`c82da8464ab69e7da95e9be08293559e67b28fac`；它不与早期单对或历史正式数据拼接。

## 1. 固定源码与工作区

推荐在 WSL2 的 Linux ext4 文件系统中保留一个交付 checkout，再为两次实体运行建立
detached worktree。这样既能从交付 checkout 核验精简证据包，也不会把运行源码 commit
和后续文档/证据提交混在一起。避免在 `/mnt/c` 上让 Windows Git
(`core.autocrlf`) 与 WSL Git 同时解释换行：

```sh
git clone --branch feat/rt-axvisor-partition-virtio-net \
  git@github.com:yueneiqi/tgoskits-rt-ivc.git tgoskits-rt-ivc-delivery
cd tgoskits-rt-ivc-delivery
git config core.autocrlf false

test -z "$(git status --porcelain=v1)"
git cat-file -e 598b357f92c848e669c12cca830a4d08d0a50e36^{commit}
git cat-file -e 077ba386c20c29b84749f509b29e8a3f6f76e1e2^{commit}
git cat-file -e c82da8464ab69e7da95e9be08293559e67b28fac^{commit}

git worktree add --detach ../tgoskits-ivc-source-598b357f9 \
  598b357f92c848e669c12cca830a4d08d0a50e36
git worktree add --detach ../tgoskits-rt-source-077ba386c \
  077ba386c20c29b84749f509b29e8a3f6f76e1e2
git worktree add --detach ../tgoskits-rt-formal-c82da8464 \
  c82da8464ab69e7da95e9be08293559e67b28fac

test "$(git -C ../tgoskits-ivc-source-598b357f9 rev-parse HEAD^{tree})" = \
  33cd7bbf39569ed661c6303ac3b61f5f34d40306
test "$(git -C ../tgoskits-rt-source-077ba386c rev-parse HEAD^{tree})" = \
  f4411a44c7fac2b5b57037005cadf8d3229a0d4f
test "$(git -C ../tgoskits-rt-formal-c82da8464 rev-parse HEAD^{tree})" = \
  424d62d908518601acf8c4e8debea6a0662e9522
```

也可从 `git@github.com:qcl-kernel/tgoskits-seven_bear.git` 的 `dev` 分支取得同一
交付提交。第 4–5 节在 `tgoskits-ivc-source-598b357f9` 执行，第 6 节的早期冒烟在
`tgoskits-rt-source-077ba386c` 执行，第 7 节正式 RT 活动在
`tgoskits-rt-formal-c82da8464` 执行；第 9 节回到 `tgoskits-rt-ivc-delivery`。

当前实体证据的完整 source attestation 在
[`results/current-source-smoke-20260813/provenance.json`](results/current-source-smoke-20260813/provenance.json)：

```text
upstream/dev              56f8bfc8207f38d4b395dae0cf533ecdb079fca8
IVC tested commit         598b357f92c848e669c12cca830a4d08d0a50e36
IVC tested tree           33cd7bbf39569ed661c6303ac3b61f5f34d40306
RT tested commit          077ba386c20c29b84749f509b29e8a3f6f76e1e2
RT tested tree            f4411a44c7fac2b5b57037005cadf8d3229a0d4f
RT formal commit          c82da8464ab69e7da95e9be08293559e67b28fac
RT formal tree            424d62d908518601acf8c4e8debea6a0662e9522
```

验证 source archive：

```sh
git merge-base --is-ancestor 56f8bfc8207f38d4b395dae0cf533ecdb079fca8 HEAD
git diff --name-only 077ba386c20c29b84749f509b29e8a3f6f76e1e2..\
598b357f92c848e669c12cca830a4d08d0a50e36
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
| RT-Thread | upstream v5.2.2，commit `ddf52e2cdd977f14fc04035c88672ac204aec713` |
| FreeRTOS | `freertos-over-bao` `cb9112f9…`、FreeRTOS-Kernel `f1043c49…`、Bao runtime `c5006808…` |
| 原生 RTOS 工具链 | Arm GNU Toolchain 13.2.Rel1；下载包 SHA-256 `7fe7b8548258f079d6ce9be9144d2a10bd2bf93b551dafbf20fe7f2e44e014b8` |
| Board | Orange Pi 5 Plus / RK3588 / 16 GiB |
| 串口 | CH340，1,500,000 baud，由 board service 独占 |
| Board Linux | SSH、`rsync`、仅 `sync/reboot` 使用无密码 sudo 白名单；rootfs 为 ext4 rw |
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

# Starry freestanding C objects and bindgen headers (Ubuntu package names:
# gcc-aarch64-linux-gnu, binutils-aarch64-linux-gnu, libc6-dev-arm64-cross).
command -v aarch64-linux-gnu-gcc aarch64-linux-gnu-ar
test "$(aarch64-linux-gnu-gcc -dumpmachine)" = aarch64-linux-gnu
test -r /usr/aarch64-linux-gnu/include/stdint.h
bash scripts/benchmark/axvisor-rt/prepare-freestanding-c-toolchain.sh
```

实体板环境变量示例：

```sh
export ORANGEPI_SSH_TARGET=orangepi@192.168.31.33
export ORANGEPI_SSH_IDENTITY="$HOME/.ssh/orangepi_automation"
# 仅供 staging 精确删除旧的 /home/rt{,.host.log}；不要写入仓库或命令行。
read -rsp 'OrangePi sudo password: ' ORANGEPI_SUDO_PASSWORD
export ORANGEPI_SUDO_PASSWORD
printf '\n'
export ORANGEPI_SERIAL=/dev/serial/by-path/<your-ch340-path>
export ORANGEPI_AXVISOR_HOST_ROOT=PARTUUID=<board-linux-root-partuuid>

# 冷启动/恢复 Linux 时使用；不要提交含凭据的配置。
export TGOS_BOARD_POWER_CONFIG="$HOME/.config/tgos/board-power.toml"
export ORANGEPI_POWER_PYTHON="$HOME/.local/share/tgos-board-power-venv/bin/python"
```

正式入口会先捕获并从继承环境删除 `ORANGEPI_SUDO_PASSWORD`，只把它定向传给
staging 子进程；staging 再通过清理 SSH 命令的标准输入交给 `sudo -S`。该值不会写入
argv、日志、manifest 或正式预注册。
板卡 sudoers 仍应仅为 runner 所需的绝对路径 `sync`/`reboot` 配置免密白名单；不要
为了绕过 staging 清理而开放全局免密 sudo。

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

赛题新增路径的快速、fail-closed host 门统一为：

```sh
bash competition/evidence/run-host-validation.sh
```

该入口已接入 CI，依次执行 focused RTOS Guest/IVC、公共 C transport、Zephyr host、
原生 RTOS analyzer/configuration、证据工具测试，并验证 compact evidence 的逐文件
哈希、解压后哈希、活动计数、终止 marker 和 source commit 新鲜度。以下命令保留为
完整底层检查清单：

```sh
python3 -m unittest discover -s competition/ivc/tests -p 'test_*.py'
python3 -m unittest discover \
  -s scripts/benchmark/axvisor-rt/tests -p 'test_*.py'
bash competition/ivc/zephyr/run-host-tests.sh
bash competition/rt-baseline/common/tests/run.sh
python3 -m unittest discover -s competition/rt-baseline/rtthread/tests -p 'test_*.py'
python3 -m unittest discover -s competition/evidence/tests -p 'test_*.py'
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

第 4.1、4.2 节及第 5 节复核冻结的实体 IVC 证据时，先进入对应 clean
source worktree：

```sh
cd ../tgoskits-ivc-source-598b357f9
test "$(git rev-parse HEAD)" = 598b357f92c848e669c12cca830a4d08d0a50e36
test -z "$(git status --porcelain=v1)"
```

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
starryos.bin                         7763df597850f5edb05d4929b980801764d6dacabc39022c7871ff7cacfdf46c
starry-orangepi-5-plus.dtb           bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981
starry-ivc-rootfs-restart.img        1c15956bce9f2bf8adb18e6977e33acb97eb22af0b613cad22914dd79165596d
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

当前证据使用 `7153dfca0787eab0d516b39b1f459a4e02fcf09ca1c831673c5df33864b8261b`。
完整 Zephyr SDK/非 SDK 构建说明见 [`ivc/zephyr/README.md`](ivc/zephyr/README.md)。

### 4.3 原生 RTOS 对照（不属于 IVC 客户机）

以下三条路径直接运行在 QEMU，不经过 AxVisor。它们用于任务一的相同/等价平台
RTOS 对照；不能从这些原生结果推导任何 AxVisor guest/IVC 结论。以下步骤和第
4.4 节应回到包含本次升级的当前交付分支执行。

```sh
# Zephyr v4.3.0
bash competition/rt-baseline/zephyr/prepare.sh
bash competition/rt-baseline/zephyr/run.sh all \
  tmp/competition/rt-baseline/zephyr/reproduction-1

# RT-Thread v5.2.2
bash competition/rt-baseline/rtthread/prepare.sh
bash competition/rt-baseline/rtthread/run.sh all \
  tmp/competition/rt-baseline/rtthread/reproduction-1

# FreeRTOS
bash competition/rt-baseline/freertos/prepare.sh
bash competition/rt-baseline/freertos/run.sh all \
  tmp/competition/rt-baseline/freertos/reproduction-1
```

每个 runner 都会构建 idle/cpu-stress、运行 100 次 warm-up + 10,000 次 1 ms
周期、捕获 build/console/config/ELF/binary/command，最后对 pinned clean source
做 attestation 并生成 `summary.json`。输出目录或 summary 已存在时会失败，复测必须
使用新目录。支持层级、方法差异和参考结果见
[`rt-baseline/README.md`](rt-baseline/README.md)。

### 4.4 RT-Thread/FreeRTOS AxVisor Guest/IVC

先准备固定上游源码和 Linux 控制端 rootfs；脚本会拒绝错误 commit、dirty 第三方
源码、已有 Guest 输出和已有证据目录：

```sh
bash competition/ivc/rtthread/prepare.sh
bash competition/ivc/freertos/prepare.sh
bash competition/ivc/linux/build-initramfs.sh

bash competition/ivc/run-rtos-qemu.sh rtthread normal \
  tmp/competition/ivc/results/rtthread-normal-reproduction-1
bash competition/ivc/run-rtos-qemu.sh rtthread ack-loss \
  tmp/competition/ivc/results/rtthread-ack-loss-reproduction-1
bash competition/ivc/run-rtos-qemu.sh freertos normal \
  tmp/competition/ivc/results/freertos-normal-reproduction-1
bash competition/ivc/run-rtos-qemu.sh freertos ack-loss \
  tmp/competition/ivc/results/freertos-ack-loss-reproduction-1
```

每次运行先核对 Guest `SHA256SUMS` 和 ELF entry/`LOAD` 区间，再通过
`cargo xtask axvisor qemu` 启动 VM1 Linux controller 与 VM2 RTOS endpoint。
normal 要求 100/100 ACK、零重传、零协议错误；ACK-loss 固定丢 20 个 ACK，要求
20 次重传、20 次 duplicate suppression、20 次恢复且 `applied` 仍为 100。
输出包含配置、实际命令、原始 `qemu.log`、`summary.json` 和总校验清单。完整资源
契约与限制见 [`ivc/README.md`](ivc/README.md)。

仓库中的 compact 参考日志已在 clean commit
`c82da8464ab69e7da95e9be08293559e67b28fac` 上按上述四条命令刷新；若只复核已保存
结果，运行 `python3 competition/evidence/verify_delivery.py`。

### 4.5 QEMU 三客户机动态隔离

```sh
set -o pipefail
bash apps/arceos/virtio-net-peer/run-isolation.sh 2>&1 | \
  tee tmp/competition/virtio-net-isolation-qemu.log
```

成功条件为：VM1/VM2 的 64 KiB TCP 长度与 checksum 一致；VM3 无默认路由并
发送 100 个跨 segment 探针；VM1 观察 7 秒收到 0 个；三台 VM 均出现 pass marker，
且未命中 fail/panic regex。参考证据见
[`results/axvisor-isolation-reference`](results/axvisor-isolation-reference/)。

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
  --restore-linux \
  --require-clean
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
delivery_bundle=../tgoskits-rt-ivc-delivery/competition/results/current-source-smoke-20260813

python3 competition/ivc/analyze_board.py \
  "$delivery_bundle/ivc/console.log.gz" \
  --raw-csv "$delivery_bundle/ivc/raw.csv.gz" \
  --pre-reset-raw-csv "$delivery_bundle/ivc/raw-before-reset.csv.gz" \
  --expected-count 100 \
  --expected-pre-reset-count 20 \
  --profile restart \
  --output tmp/reproduction/ivc-reanalyzed.json
```

不要直接用裸 `cargo xtask axvisor board` 替代仓库 runner：裸命令不负责
staging、snapshot harvest、供电恢复和最终 Linux rootfs gate。

## 6. 当前 RT shared/partitioned 实体冒烟

切换到 RT 双侧实跑源码 worktree：

```sh
cd ../tgoskits-rt-source-077ba386c
test "$(git rev-parse HEAD)" = 077ba386c20c29b84749f509b29e8a3f6f76e1e2
test -z "$(git status --porcelain=v1)"
```

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
Starry RT kernel       d163d4c55f740a5040cafd3d3919dd90f9f80f020e23ab1e7c70ccb7b52deb94
guest DTB              bd35510466ffdd314733ef300318373b3524751447a7f7fd7ae9b4283e78e981
capture rootfs         26a45d4e333dc6039d17d8774ac185a4c3d3b2301dfb23c5803ae89755768626
static RT probe        8b3f6e7471dc9ecf60d5b64ab5f3c3a4657af8743fde1aa6b1772358c62806da
guest capture runner   38473826ce2d5b36a4fca809200791a74d898b4c47d05f58735319b40677fd6b
```

本次归档从同一 clean commit 和同一构建输入执行 `shared`、`partitioned` 两侧。
下面的 `result_root` 必须不存在：

```sh
result_root=tmp/reproduction/rt-pair-$(date -u +%Y%m%dT%H%M%SZ)

for profile in shared partitioned; do
  result_dir="$result_root/$profile"
  mkdir -p "$result_dir"

  bash scripts/benchmark/axvisor-rt/stage-starry-board.sh \
    2>&1 | tee "$result_dir/stage.log"

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

复现当前正式活动时先固定已记录的 commit，而不是使用浮动 `HEAD`：

```sh
cd ../tgoskits-rt-formal-c82da8464
test "$(git rev-parse HEAD)" = c82da8464ab69e7da95e9be08293559e67b28fac
test "$(git rev-parse HEAD^{tree})" = 424d62d908518601acf8c4e8debea6a0662e9522
test -z "$(git status --porcelain=v1)"
```

```sh
commit=$(git rev-parse HEAD)
source_ref=$(git symbolic-ref --quiet --short HEAD || printf 'detached-head')
base_rootfs=.tgos-images/rootfs-aarch64-busybox.img/rootfs-aarch64-busybox.img
result_root=/home/$USER/Workspace/starry/results/rt-formal-$(date -u +%Y%m%d)-$commit

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

`prepare` 会重新生成并 smoke-test 仅限本次构建的 freestanding C shim。它把
`lwprintf-rs` 对 `aarch64-linux-musl-gcc/ar` 命令名的硬编码映射到已验证的
`aarch64-linux-gnu-gcc/ar`；该路径不链接 musl libc。真实工具、wrapper、target、
版本、header sysroot、大小和 SHA-256 写入 `build/host-toolchain.json` 并纳入预注册；
后续每个 slot 开始前都会重新核验。

第一次 `run-next` 前确认当前 shell 已设置 `ORANGEPI_SUDO_PASSWORD`（若板卡仍使用
镜像默认密码，也可由 staging 的受限默认值提供）。该值不属于冻结测量输入，不写入
`result_root`；它只授权删除精确的旧结果文件，不能改变 kernel、rootfs、配置或阈值。

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

已归档活动应得到 5 个 comparison、10 个 pair receipt、2 个 soak receipt，shared 与
partitioned soak 分别至少 1,800 秒。当前机器汇总的四项 max 均为 5/5 改善，且
`m2_exit_gate_met=true`；compact 记录位于
[`results/axvisor-rt-formal-20260816`](results/axvisor-rt-formal-20260816/)。

正式入口在每个 half 前重验 commit/tree、关键源码和所有制品哈希，并验证 stage 与
harvest 都是同一 `bf61f4d4a1d994ad/orangepi5plus` 实体板。任一步失败时不会创建
`receipt.json`；修复源码后必须新提交并使用新的 `result_root` 重新预注册，不能编辑
旧收据或降低阈值。设计、替代方案和状态机见
[`book/design/axvisor-rt-formal-campaign.md`](../book/design/axvisor-rt-formal-campaign.md)。

IVC manual/neural 的冻结顺序由 `run-control-campaign.sh formal` 生成：

```sh
cd ../tgoskits-ivc-source-598b357f9
test "$(git rev-parse HEAD)" = 598b357f92c848e669c12cca830a4d08d0a50e36

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

从任意交付 checkout 先验证新增 compact QEMU evidence：

```sh
python3 competition/evidence/verify_delivery.py
```

成功标志为 `COMPETITION_DELIVERY_EVIDENCE_PASS`，同时给出 QEMU/formal source
commit、3 个证据集、32 个受检文件、5 份 QEMU 日志与 113 项 archive manifest。
若 checksum 漏列/不符、gzip 解压身份不符、业务计数或成功 marker 不成立、QEMU
证据 commit 不一致、正式 M2/soak/回执契约不成立，或者 34 个预注册源码输入发生
变化，命令以 2 退出。文档、证据、验证工具和 CI 变更允许晚于运行 commit。

从仓库根目录验证当前 compact bundle：

```sh
cd ../tgoskits-rt-ivc-delivery
bundle=competition/results/current-source-smoke-20260813

(cd "$bundle" && sha256sum -c checksums.sha256)
(cd "$bundle/ivc" && sha256sum -c runner-checksums.sha256)
python3 "$bundle/validation/verify-evidence.py" .
sh "$bundle/validation/verify-source-index.sh" . \
  598b357f92c848e669c12cca830a4d08d0a50e36 \
  "$bundle/source-files.git-ls-tree.txt"

(cd competition/results/axvisor-rt-formal-20260816 && \
  sha256sum -c SHA256SUMS)
```

当前正式 RT raw archive 已确定性生成。取得 archive 后与仓库 sidecar 一起校验：

```sh
formal_archive=axvisor-rt-formal-20260816-c82da8464.tar.gz
cp competition/results/axvisor-rt-formal-20260816/archive.sha256 .
sha256sum -c archive.sha256
test "$(stat -c %s "$formal_archive")" -gt 40000000
```

其预期总 SHA-256 为
`68c1efb1ae0338692a84943c7056e104e2abed9e62a89dcdb0e2540ea1f9859e`；
`archive.manifest.json` 还应逐项核验 archive 内 113 个文件。

将完整本地 raw 目录制成不可覆盖、可逐文件核验的确定性归档：

```sh
python3 competition/evidence/package.py \
  competition/results/orangepi-5-plus \
  tmp/publish/tgoskits-competition-full-evidence.tar.gz

cd tmp/publish
sha256sum -c tgoskits-competition-full-evidence.tar.gz.sha256
```

命令同时生成外置 manifest 和 SHA-256 sidecar，并把同一 manifest 嵌入 tar。
脚本会拒绝链接、特殊文件、重复输出，并回读验证每个 archive member。仍需把三个
文件上传到同一不可变 release/dataset；本地打包不能代替公开 URL 或服务端 checksum。

五分钟成片：

```text
competition/results/terminal-demo-20260817/demo-terminal-5min.mp4
```

成片按评审顺序讲解总体架构、实时性改造与正式结果、基于 IP 的客户机通信、AI
闭环控制和工程证据。归档 UART 以 4× 回放并常驻标识，主机侧分析器和 fail-closed
verifier 在录制时实际执行。镜头、评分项映射、证据边界和重新生成说明见
[`video-storyboard.md`](video-storyboard.md)。历史静态回放仍留在
`current-source-smoke-20260813` 冻结包中，不修改原归档校验和。

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

原生 RTOS QEMU case 则以 analyzer exit 0、唯一且完整的机器 marker、固定样本数、
idle/stress 实测 CPU 记账、零 early wake、pinned clean-source attestation 和全部
artifact hash 为成功条件；它独立于实体板生命周期门，也不得标成 RK3588 结果。
