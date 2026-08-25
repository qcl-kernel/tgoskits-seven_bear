# 比赛材料复现说明

本说明涵盖证据校验、图表重建、文档与 PDF 生成、视频生成，以及可选的 QEMU 和 Orange Pi 5 Plus 板端验证。硬件步骤不会随文档构建自动触发；执行板测前必须取得 board lease，并确认电源、串口、Linux rootfs 和恢复路径。

# 1. 固定源码与分支

目标分支为 `chore/seven-bear-results-materials`，基于 upstream PR #2182 通过 CI 时对应的 `upstream/dev` 提交 `f70cf8d0eadc43caf176e7873244e8fae8154d9c`。证据快照与文档重建输入 HEAD 为 `0118ed5bbda46fefca64a39424a270e20232dff8`。首先确认分支与基线：

```sh
git status --short
git rev-parse HEAD
git rev-parse upstream/dev
git rev-list --left-right --count upstream/dev...HEAD
```

正式 RT 证据另行绑定 `c82da8464ab69e7da95e9be08293559e67b28fac`。重建输入 HEAD 并非该提交的板端重跑，文档重建不得改变此边界。

# 2. 环境与工具

推荐在 Windows 11 + WSL2 Ubuntu 环境中复现材料。所需依赖包括 Python 3.10+、Matplotlib、Pillow、Typst 0.15.1、Poppler 22.02、FFmpeg 7.1、Pandoc，以及 Windows/WSL 环境可用的 Noto Sans CJK 或 Source Han Sans 字体。中文润色采用 `/home/seven_wsl/.local/bin/agy` 1.1.19，模型固定为 `gemini-3.7-flash-high`，effort=high。PDF 模板固定采用 `ilm-zh` 提交 `7a6080e891631d45ab2c2b40531ea8a3f211270f`。

如需重建 Rust 代码或硬件镜像，还需配置仓库指定的 Rust 2024 nightly、AArch64 交叉工具链、device-tree-compiler、e2fsprogs、rsync、CMake、Ninja 及相应 RTOS SDK。完整板端依赖与环境变量配置以 `competition/reproduce.md` 为准。

# 3. 离线证据与材料校验

在仓库根目录下执行：

```sh
python3 competition/submission/tools/extract_evidence.py
python3 competition/submission/tools/generate_charts.py
python3 -m unittest discover -s competition/submission/tests -p 'test_*.py'
python3 competition/submission/tools/verify_submission.py
```

证据提取脚本将重新读取 21 个保留结果 JSON，并校验关键 gate、主张边界与 SHA-256。若任一源结果被修改、路径缺失或字段发生偏移，重建流程必须报错终止。图表严格仅读取 `competition/submission/data/evidence-snapshot.json` 与 `competition/submission/copy/chart-labels.json`。

# 4. 中文润色复现

对四类中文文案与图表标签分别执行结构化润色：

```sh
python3 competition/submission/tools/polish_with_agy.py --source competition/submission/copy/source/chart-labels.json --output competition/submission/copy/chart-labels.json --purpose 比赛图表标签 --batch-size 100
python3 competition/submission/tools/polish_with_agy.py --source competition/submission/copy/source/design-sections.json --output competition/submission/copy/design-sections.json --purpose 比赛设计文档 --batch-size 100
python3 competition/submission/tools/polish_with_agy.py --source competition/submission/copy/source/test-sections.json --output competition/submission/copy/test-sections.json --purpose 比赛测试报告 --batch-size 100
python3 competition/submission/tools/polish_with_agy.py --source competition/submission/copy/source/reproduction-sections.json --output competition/submission/copy/reproduction-sections.json --purpose 比赛复现说明 --batch-size 100
python3 competition/submission/tools/polish_with_agy.py --source competition/submission/copy/source/video-scenes.json --output competition/submission/copy/video-scenes.json --purpose 比赛视频旁白与字幕 --batch-size 100
```

润色工具遵循结构化 JSON 规范，严格保护数字、百分比、单位、URL、提交哈希、反引号内容与 Markdown 结构；输出记录写入 `competition/submission/agy-polish-manifest.json`。模型输出仍须通过证据快照与人工事实核对，不得以语言模型替代实际测量。

# 5. 文档与 PDF

由组装脚本基于润色后的 JSON 生成 Markdown，经 Pandoc 转换为 Typst 正文，最后套用本地 vendored 的 `ilm-zh` 模板：

```sh
python3 competition/submission/tools/assemble_documents.py
powershell -File competition/submission/tools/build-pdfs.ps1
```

构建产物为 `competition/submission/output/pdf/tgoskits-competition-design-zh.pdf` 与 `competition/submission/output/pdf/tgoskits-competition-test-report-zh.pdf`。构建脚本同步运行 `pdfinfo`、`pdftotext` 与 `pdftoppm`，生成的逐页 PNG 将存入临时 QA 目录，不纳入提交。人工视觉检查须覆盖封面、目录、各类表格、每张图表、长代码块和末页，若发现裁切、重叠、乱码或孤行须修正后重新构建。

# 6. 视频与字幕

视频分镜脚本、画面标题与旁白取自 `competition/submission/copy/video-scenes.json`。执行构建：

```sh
python3 competition/submission/tools/build_video.py
```

脚本生成 1920×1080 分辨率的 H.264/AAC 成片、独立 `zh-CN.srt` 字幕、视频脚本及媒体清单。成片目标时长约 5 分钟，画面引用归一化图表、保留的终端证据与明确标注的静态照片，不把历史终端录像描述为同步物理实拍。生成后使用 `ffprobe` 检查时长、分辨率、帧率、编码与音轨，并在每个 scene 中点抽帧进行画面质量核查。

# 7. 可选 QEMU 验证

在缺少物理板卡时，可运行仓库提供的 host validation 与 QEMU IVC 测试：

```sh
bash competition/evidence/run-host-validation.sh
bash competition/ivc/linux/build-initramfs.sh
bash competition/ivc/run-rtos-qemu.sh rtthread normal
bash competition/ivc/run-rtos-qemu.sh rtthread ack-loss
bash competition/ivc/run-rtos-qemu.sh freertos normal
bash competition/ivc/run-rtos-qemu.sh freertos ack-loss
bash competition/isolation/run-qemu-three-guest.sh
```

具体执行参数、固定的源码版本与成功判定 marker 以 `competition/reproduce.md` 为准。QEMU 运行结果用于协议与拓扑回归验证，不替代 RK3588 板端性能实测数据。

# 8. 可选 Orange Pi 5 Plus 板测

首先检查 board service 与 Linux 系统状态：

```sh
cargo xtask board ls
cargo xtask board connect OrangePi-5-Plus
```

获取并持有 lease 后，按 `competition/reproduce.md` 的 runner 执行当前 IVC smoke、正式 RT、原生 Zephyr、实体隔离、UVC/NPU 或连续视觉活动。请勿直接使用原生 `cargo xtask axvisor board` 替代仓库 runner，因为 runner 负责 staging、hash、`sync`、compact marker 匹配、结果收集、Linux 恢复与最终 gate 判定。执行 SO-100 动作测试还要求 12 V 急停处于可触达位置、机械臂可靠固定、工作区清空且操作人员全程在场。

# 9. 复现成功判定

离线材料复现成功判定标准：证据快照断言全部通过；10 张图表的 SVG/PNG 文件成对存在；全部中文输出在润色清单中存在匹配哈希；两份 PDF 可正常解析且无缺字、逐页视觉检查通过；视频时长约 5 分钟、分辨率 1920×1080、H.264/AAC 编码、字幕可用且 scene 抽帧无裁切；最终 `SHA256SUMS` 与所有交付文件一致。

硬件复现成功仅按对应 campaign 预注册的 gate 判定。若当前 HEAD 未实际完成正式 RT 重跑，必须继续保留 FROZEN FORMAL 标签；若未实现摄像头、RTOS 与 SO-100 的同步运行，必须继续保留 camera-synchronized physical loop=not-tested。
