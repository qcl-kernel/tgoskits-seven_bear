# Demo video production

[`demo-5min.ass`](demo-5min.ass) is the timed on-screen evidence layer and
[`narration.json`](narration.json) is the matching Chinese narration source.
[`render-demo.ps1`](render-demo.ps1) renders a 300-second 1280×720 H.264/AAC
evidence replay and writes it to
`../results/current-source-smoke-20260813/demo-5min.mp4`.

The renderer requires FFmpeg, FFprobe, Python, `edge-tts`, network access for
speech synthesis, and a Chinese font. The delivered MP4 is included in the
evidence bundle checksum manifest, so reproducing it is optional when only
verifying the submission.

Run from PowerShell:

```powershell
python -m pip install --user edge-tts
competition/video/render-demo.ps1
```

This is deliberately labelled as a post-run replay. It uses retained physical
board logs and machine summaries; it is not presented as a live board capture.
