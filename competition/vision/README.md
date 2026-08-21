# RK3588 视觉 AI 展示与性能证据

## 结论

比赛展示建议增加“智能输送线网球分拣”场景：StarryOS 使用 RK3588 NPU
运行 YOLOv8，识别 `sports ball` 后通过任务二的 UDP/IP 通道通知 RTOS；RTOS
驱动虚拟挡板或 LED/PWM，并回传动作状态。浏览器同时显示带检测框的视频、当前
决策、RTOS 动作和端到端延迟。

该场景复用
[`orangepi-5-plus-uvc-rknn`](../../apps/starry/orangepi-5-plus-uvc-rknn/)
已有的 UVC、RKNN、固定图像验证、MJPEG HTTP 和网球素材。2026-08-18 已在
Orange Pi 5 Plus 上完成阶段 A：AxVisor 同时运行 StarryOS 与 Zephyr，StarryOS
使用真实 RKNN/NPU 后端分析三张固定帧，经 VirtIO Ethernet + UDP/IP 发送独立的
视觉决策，Zephyr 回传实际挡板状态。验收目录为
[`fixed-frame-starry-zephyr-v7`](../results/orangepi-vision-20260818/closed-loop/fixed-frame-starry-zephyr-v7/)；
它是确定性固定帧闭环，不主张 Guest 内实时 UVC 摄像头吞吐。

| 帧 | RKNN 结果 | 请求动作 | RTOS 实际动作 |
| ---: | --- | --- | --- |
| 1 | `sports ball`，置信度 0.7081，bbox `479,706,773,1010` | right | right |
| 2 | `sports ball`，置信度 0.8591，bbox `517,932,730,1151` | left | left |
| 3 | 未检出目标 | hold | hold |

三次动作均应用成功，零 retry/duplicate/protocol error；transport 中位数
11,786 µs，固定帧输入到动作状态回传的端到端中位数 2,008,428 µs。这里的端到端
包含逐帧启动用户态 RKNN 验证进程和证据串联开销，不能写成连续视频 FPS。

## 1. 为什么选择网球分拣

- 评委能直接看到“目标出现 → 检测框 → 网络命令 → 挡板动作 → 状态回传”，
  比温度数值日志更直观。
- 仓库已有三张网球固定图像及逐框期望值，其中 `class 32` 是 COCO
  `sports ball`，可以先建立确定性回归，再接实时摄像头。
- 固定周期分拣可作为 manual 基线；AI 分拣可比较误分率、漏分率、响应延迟、
  有效吞吐和丢帧率，满足赛题“至少两项指标”的要求。
- RTOS 保持最终动作所有权；AI 只发送带置信度、目标类别、帧序号和有效期的
  决策，体现混合关键系统的边界，而不是把 RTOS 降为日志打印器。

## 2. 能力边界与分阶段实现

| 阶段 | 输入和部署 | 闭环动作 | 证据定位 |
| --- | --- | --- | --- |
| A（比赛主线） | AxVisor StarryOS Guest 从 rootfs 读取固定图像/视频帧并执行 RKNN | typed `VISION_DECISION` 经 virtio-net/UDP 发送给 Zephyr，RTOS 回传 `ACTUATOR_STATUS` | 确定性、可重复，先完成 |
| B（现场预演） | 裸 StarryOS 使用现有 UVC + RKNN 应用 | 浏览器显示检测框；可接同一决策逻辑 | 证明真实摄像头和 NPU 管线，不冒充 Guest 闭环 |
| C（增强项） | AxVisor Guest 直接拥有 USB/xHCI 摄像头 | 与 A 相同 | 只有完成 RK3588 xHCI/clock/reset/PHY 所有权审计和实体回归后才主张 |

阶段 A 不应把视觉字段塞入当前热控 `setpoint_milli_c` 或
`actuator_permille`。视觉消息需要独立、版本化的 payload，至少包含：

- `frame_id`、采集/推理时间戳和决策有效期；
- `class_id`、`confidence_q10000`、检测框或区域 ID；
- `action`（保持、分拣、急停）与安全默认值；
- RTOS 回传的实际动作、应用序号、错误码和执行时间戳。

协议扩展属于共享接口和控制行为变更，应先补设计、Rust/C 编解码互操作、重放/
超时/乱序测试，再接设备动作。阶段 C 是硬件所有权高风险项，不作为阶段 A 的
前置条件。

## 3. 可量化验收

固定一段带 ground truth 的正负样本序列，manual 与 AI 使用相同顺序和发送周期，
按 AB/BA/AB/BA/AB 运行五对：

| 类别 | 必报指标 | 通过口径 |
| --- | --- | --- |
| 识别/控制质量 | precision、recall、误分率、漏分率 | AI 至少在误分率或漏分率上优于固定周期基线，同时披露另一项 |
| 实时闭环 | 采集到推理、推理到发送、网络 RTT、RTOS 应用、完整闭环 p50/p95/p99/max | 零 deadline miss 不是由删样得到；最坏值和跨运行 worst-of-runs 必须保留 |
| 吞吐 | capture FPS、inference FPS、有效分拣件/秒、latest-frame 丢弃率 | 记录相机设置和 `infer_every`，不得混用不同输入条件 |
| 资源与稳定性 | CPU、RSS/HWM、NPU core mask、温度/频率、错误计数 | 五次 60 秒配对后，再做至少一次 30 分钟 soak |
| 可靠性 | ACK 丢失、重复决策、过期帧、AI 进程/Guest 重启 | RTOS 进入安全默认动作，恢复后拒绝旧 session/sequence |

manual 基线应是预注册的固定周期/固定位置策略，不能根据测试标签临时调参。若
AI accuracy 改善但闭环 p99 或最大延迟退化，必须像当前热控 overshoot 一样分开
披露，不合并成“整体更优”。

## 4. Orange Pi 5 Plus 对比矩阵

优先完成以下正交实验；每次只改变表中的一个因素：

| 优先级 | 对比 | 固定因素 | 目的 |
| --- | --- | --- | --- |
| P0 | RKNN NPU core `0` vs `all` | StarryOS 裸机、同模型/相机/FPS/阈值/频率策略 | 判断多核 NPU 是否改善推理 p95 和吞吐 |
| P0 | Linux 裸机 vs StarryOS 裸机 | 同板、同 `.rknn`、相同 UVC 参数和 core mask | 量化 OS/驱动边界开销 |
| P0 | idle vs CPU/network stress | 同一 StarryOS 镜像和 NPU 配置 | 验证视觉管线的最坏延迟与丢帧 |
| P1 | StarryOS 裸机 vs AxVisor StarryOS Guest 固定帧 | 同模型、图像序列和推理参数 | 分离虚拟化成本；不混入 USB 直通差异 |
| P1 | 60 秒五配对 vs 30 分钟 soak | 最优但预先冻结的配置 | 检查温升、降频、内存增长和错误累积 |
| P1 | RK3588 原生 Zephyr idle/stress/soak vs Guest | 同周期、时钟源、CPU 亲和和负载定义 | 补强当前只有 QEMU/AArch64 的原生 RTOS 基线 |

每个运行都保存：完整 console、模型 SHA-256、板卡/源码身份、相机参数、CPU
affinity/governor、NPU core mask、温度/频率、原始逐帧样本、summary 和 checksum。
Rockchip Model Zoo 的数据只用于量级 sanity check；模型、量化、前后处理或相机
链路不同，不能直接写成 StarryOS 的性能对比。

性能优化按 profile 结果决策：

1. `rknn_perf_run_ms` 占比高时，再比较 `0`/`1`/`2`/`all`、模型量化和 NPU
   调度；
2. `letterbox`、decode 或 postprocess 占比高时，优先 RGA/零拷贝、缓冲复用和
   CPU affinity；
3. capture FPS 足够而 inference FPS 不足时保留 latest-frame 策略，报告丢帧率，
   不堆积过期控制命令；
4. soak 中温度升高同时 p95/max 变差时，固定 governor/散热条件后重测，不能只
   选择冷启动最好值。

## 5. 已加入的证据工具

新增的单次分析器会拒绝缺失/重复完成标记、固定图像验证失败、验证与 benchmark
参数漂移、推理错误、短运行、profile 样本数不一致、FPS/吞吐自相矛盾和缺失内存
指标；输出同时记录 console 与传入 `.rknn` 的 SHA-256：

```bash
python3 competition/vision/analyze_uvc_rknn.py run.log \
  --model-artifact \
    apps/starry/orangepi-5-plus-uvc-rknn/rknn-yolov8-image/model/yolov8.rknn \
  --expected-duration-sec 60 \
  --output run.summary.json
```

五对结果使用比较器；它拒绝重复日志、模型哈希变化、组内配置漂移和未声明的
实验变量，并报告每项的配对改善方向、中位数、worst 和有利配对数：

```bash
python3 competition/vision/compare_uvc_rknn.py \
  --baseline core0/run-1.json --candidate all/run-1.json \
  --baseline core0/run-2.json --candidate all/run-2.json \
  --baseline core0/run-3.json --candidate all/run-3.json \
  --baseline core0/run-4.json --candidate all/run-4.json \
  --baseline core0/run-5.json --candidate all/run-5.json \
  --baseline-label starry-core0 --candidate-label starry-all \
  --vary core_mask --output comparison.json
```

板端配置保持其他参数完全一致：

```bash
cargo xtask starry app board -t orangepi-5-plus-uvc-rknn \
  --board-config configs/board-orangepi-5-plus-bench-core0.toml \
  -b OrangePi-5-Plus

cargo xtask starry app board -t orangepi-5-plus-uvc-rknn \
  --board-config configs/board-orangepi-5-plus-bench.toml \
  -b OrangePi-5-Plus
```

主机契约测试：

```bash
python3 -m unittest discover -s competition/vision/tests -p 'test_*.py'
```

分析器通过只代表证据结构通过，不代表 candidate 的性能必然改善；比较结论仍由
输出数据决定。

## 6. 当前不应主张的内容

- 可以主张 AxVisor/StarryOS/Zephyr 的三帧固定图像视觉闭环；不能把它描述为
  Guest 内实时 UVC 摄像头闭环，也不能用三帧结果外推持续识别准确率。
- 没有提交真实 `UVC_RKNN_BENCH_RESULT` 及原始日志前，不能主张现场摄像头 FPS、
  连续视频延迟或资源数据；上述固定帧端到端数据只适用于 v7 的执行方式。
- `--model-artifact` 记录的是 host 侧 staging 输入；正式活动还需保留 rootfs manifest
  或板端模型哈希，单靠该字段不能证明运行时文件身份。
- 不把官方 Model Zoo FPS 当成本仓库端到端 camera-to-actuator 数据。
- 不为现场效果跳过固定图像验证、错误计数、长稳测试或失败运行留档。

外部依据：Orange Pi 官方列出该板使用 RK3588、带最高 6 TOPS NPU；Rockchip
官方 RKNN Model Zoo 提供 RK3588 YOLOv8 转换与 Linux demo；`rknn_api.h`
明确给出 RK3588 的 NPU core mask 选择能力。链接分别为
[Orange Pi 5 Plus](https://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-5-plus.html)、
[RKNN Model Zoo YOLOv8](https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8/README.md)
和
[RKNN API](https://github.com/rockchip-linux/rknpu2/blob/master/runtime/RK3588/Linux/librknn_api/include/rknn_api.h)。
