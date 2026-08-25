#import "../vendor/ilm-zh/lib.typ": *

#show: ilm.with(
  title: [智能化工控混合系统比赛测试报告],
  author: "TGOSKits RT-IVC",
  fonts: (
    "宋体": ((name: "Times New Roman", covers: "latin-in-cjk"), "Noto Serif SC"),
    "黑体": ((name: "Arial", covers: "latin-in-cjk"), "Noto Sans SC"),
    "等宽": ((name: "Cascadia Mono", covers: "latin-in-cjk"), "Noto Sans SC"),
  ),
  date: datetime(year: 2026, month: 8, day: 25),
  date-format: "[year]-[month padding:zero]-[day padding:zero]",
  abstract: [本报告依据 `competition/requirement.md` 汇总启动、实时性、原生 RTOS、客户机通信、可靠性、隔离、AI 推理、控制效果、连续视觉与 SO-100 的测试证据。数值由 `competition/submission/data/evidence-snapshot.json` 基于保留的 JSON 结果归一化生成；除明确标注的 current smoke 外，不把历史 clean commit 的硬件结果描述为当前 HEAD 重跑。],
  chapter-pagebreak: true,
  external-link-circle: false,
)

#set heading(numbering: none)
#show figure.where(kind: table): set text(size: 8pt)
#show figure.where(kind: image): set block(breakable: false)
#include "generated/test-body.typ"
