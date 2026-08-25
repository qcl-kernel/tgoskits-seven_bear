#import "../vendor/ilm-zh/lib.typ": *

#show: ilm.with(
  title: [#text(size: 0.82em)[智能化工控中基于虚拟化的混合系统部署及联动实现]],
  author: "TGOSKits RT-IVC",
  fonts: (
    "宋体": ((name: "Times New Roman", covers: "latin-in-cjk"), "Noto Serif SC"),
    "黑体": ((name: "Arial", covers: "latin-in-cjk"), "Noto Sans SC"),
    "等宽": ((name: "Cascadia Mono", covers: "latin-in-cjk"), "Noto Sans SC"),
  ),
  date: datetime(year: 2026, month: 8, day: 25),
  date-format: "[year]-[month padding:zero]-[day padding:zero]",
  abstract: [本方案在 Orange Pi 5 Plus 的 RK3588 单芯片上运行 AxVisor、至少 2 vCPU 的 StarryOS 客户机与 RTOS 客户机。StarryOS 承担 USB 摄像头采集、神经网络推理与控制决策，RTOS 负责确定性动作执行与状态回传，主数据通道为 IVC/1 over UDP/IPv4。本文同时给出实时化、网络协议、隔离、AI 闭环、物理执行器和可复现证据的设计边界。],
  chapter-pagebreak: true,
  external-link-circle: false,
)

#set heading(numbering: none)
#show figure.where(kind: table): set text(size: 8pt)
#show figure.where(kind: image): set block(breakable: false)
#include "generated/design-body.typ"
