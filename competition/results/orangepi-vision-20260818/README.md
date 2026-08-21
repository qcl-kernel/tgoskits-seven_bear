# Orange Pi 5 Plus 视觉闭环证据（2026-08-18）

比赛主线采用
[`closed-loop/fixed-frame-starry-zephyr-v7`](closed-loop/fixed-frame-starry-zephyr-v7/)：
真实 RK3588、AxVisor、StarryOS RKNN/NPU 固定帧推理、VirtIO Ethernet + UDP/IP、
Zephyr 动作应用与状态回传。机器摘要的 `acceptance.passed`、
`real_rknn_backend` 和 `requested_equals_actual` 均为 `true`，三帧动作依次为
`right / left / hold`，3/3 应用成功。

`fixed-frame-starry-zephyr-v1` 至 `v6` 是 bring-up 过程中保留的失败或不完整运行，
不得与 v7 合并计数。`fixed-pairs` 和 `starry-fixed-smoke` 是固定图像验证与早期
诊断材料，不替代 v7 的跨 Guest 闭环证据。

当前证据明确设置 `camera_throughput_claimed=false`：它证明确定性固定帧闭环，
不证明 AxVisor Guest 内实时 UVC 摄像头、连续视频 FPS 或长时识别准确率。
