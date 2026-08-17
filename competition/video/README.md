# Judge-facing five-minute demo production

The primary competition demo is
[`demo-terminal-5min.mp4`](../results/terminal-demo-20260817/demo-terminal-5min.mp4).
Its narrative follows the judging rubric: system architecture, real-time changes
and formal results, inter-guest networking and restart recovery, AI closed-loop
control, and reproducible engineering evidence. Short chapter cards orient the
viewer; the substantive claims are demonstrated through terminal commands,
configuration, retained board logs, analyzer output, and machine summaries.

The terminal uses the Hack font for conventional, readable code rendering. The
physical-board UART segment is retained evidence and carries a persistent
`ORANGE PI UART · 2026-08-13 · 4×` label. Host-side analyzers and the archived
bundle's fail-closed verifier execute during recording. These labels preserve
the evidence boundary without turning production details into presentation
content.

## Production inputs

- [`terminal-timeline.json`](terminal-timeline.json): exact 300-second visual
  timeline and per-segment speed.
- [`terminal-narration.json`](terminal-narration.json): matching Chinese
  narration segments.
- [`terminal-demo.ass`](terminal-demo.ass): chapter cards and evidence labels.
- [`tapes/`](tapes/): ten deterministic VHS terminal recordings.
- [`show-evidence.py`](show-evidence.py): renders repository configuration,
  retained evidence, machine summaries, and analyzer results.
- [`render-terminal-demo.ps1`](render-terminal-demo.ps1): records, normalizes,
  narrates, composes, and writes delivery metadata.

Raw VHS captures remain at `competition/video/build/raw/` at 1× speed and are
ignored by Git. Only the retained UART replay is accelerated to 4× in the final
timeline.

## Reproduce

Prerequisites are Windows PowerShell, WSL Ubuntu, Docker, FFmpeg/FFprobe,
Python, `edge-tts`, and a Chinese font. The VHS image is pinned by digest.

```powershell
wsl -d Ubuntu -- docker pull ghcr.io/charmbracelet/vhs@sha256:9d5fc3dc0c160b0fb1d2212baff07e6bdf3fa9438c504a3237484567302fcf93
python -m pip install --user edge-tts
competition/video/render-terminal-demo.ps1
```

After the raw captures and narration exist, a composition-only rerender can
reuse them:

```powershell
competition/video/render-terminal-demo.ps1 -ReuseCaptures -ReuseNarration
```

The result directory also contains FFprobe metadata, the MP4 SHA-256, a
production/evidence input hash manifest, and the source worktree state.

## Historical version

[`render-demo.ps1`](render-demo.ps1), [`demo-5min.ass`](demo-5min.ass), and
[`narration.json`](narration.json) reproduce the earlier slide-oriented replay
in `current-source-smoke-20260813`. That frozen evidence bundle remains
unchanged and is not the primary judging video.
