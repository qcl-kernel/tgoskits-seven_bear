# TGOSKits RT-IVC competition submission

This directory is a reproducible presentation layer over immutable repository evidence. It does not replace physical-board reruns or widen the claims made by the underlying result JSON files.

## Primary deliverables

| Artifact | Path |
| --- | --- |
| Design document | `design-document.md` and `output/pdf/tgoskits-competition-design-zh.pdf` |
| Test report | `test-report.md` and `output/pdf/tgoskits-competition-test-report-zh.pdf` |
| Reproduction guide | `reproduction-guide.md` |
| Five-minute demo | `output/video/tgoskits-ivc-competition-demo.mp4` |
| Chinese subtitles | `output/video/tgoskits-ivc-competition-demo.zh-CN.srt` |
| Evidence snapshot | `data/evidence-snapshot.json` |
| Content provenance | `agy-polish-manifest.json` |
| Visual QA record | `visual-qa.json` |
| Upstream PR #2182 CI evidence | `../results/upstream-pr-2182-ci-20260825/summary.json` |
| Final checksums | `output/SHA256SUMS` |

## Rebuild and verify

Run from the repository root:

```text
python competition/submission/tools/extract_evidence.py
python competition/submission/tools/generate_charts.py
python competition/submission/tools/assemble_documents.py
powershell -ExecutionPolicy Bypass -File competition/submission/tools/build-pdfs.ps1
python competition/submission/tools/build_video.py
python -m unittest discover -s competition/submission/tests -p "test_*.py"
python competition/submission/tools/verify_submission.py
```

PDF generation uses the vendored `ilm-zh` template pinned in `vendor/ilm-zh/UPSTREAM.md`. Chinese source, labels, captions, subtitles, and narration were polished through the exact model and effort recorded in `agy-polish-manifest.json`.

## Claim boundaries

- Upstream PR #2182 CI run `32794757246` completed successfully at code HEAD `75d8f3918580471a3451b29ca5d33a015bd5bb81` with 35/35 workflow jobs passing; this is integration evidence, not a current-HEAD formal RT board rerun.
- Formal RT figures belong to frozen source commit `c82da8464ab69e7da95e9be08293559e67b28fac`; they are not a current-HEAD board rerun and observed maxima are not WCET.
- The continuous vision loop reports virtual actuator state only.
- The SO-100 result is a supervised ID1 single-cycle pilot without camera synchronization or an RTOS mediator.
- The labeled tennis pilot has three positive samples and does not establish overall AI superiority.
- Historical terminal footage is identified in-frame as post-hoc evidence visualization rather than synchronized physical footage.
