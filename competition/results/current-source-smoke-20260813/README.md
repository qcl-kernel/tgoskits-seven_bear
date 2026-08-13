# Current-source Orange Pi evidence bundle

This compact bundle records physical Orange Pi 5 Plus / RK3588 runs after the
RT/IVC device-graph work was rebased onto `upstream/dev`
`56f8bfc8207f38d4b395dae0cf533ecdb079fca8`. All timestamps are UTC on
2026-08-13. The physical hardware ID is `bf61f4d4a1d994ad`.

## Evidence levels

| Level | Clean source | What was run |
| --- | --- | --- |
| C-RT | `077ba386c20c29b84749f509b29e8a3f6f76e1e2` | Same-build StarryOS 2-vCPU shared and partitioned RT smoke; three guest metrics × 100 samples per side plus lossless direct IRQ traces |
| C-IVC | `598b357f92c848e669c12cca830a4d08d0a50e36` | StarryOS + Zephyr fault-restart loop; same-commit build, runner, analyzer, metadata, and exit status |
| F | Historical clean commits | Preregistered multi-run campaign indexes copied from the earlier compact bundle; never relabelled as current-source results |

Only four `competition/ivc/` paths changed between C-RT and C-IVC. The exact
boundary is in [`source-delta.txt`](source-delta.txt); no RT runtime or RT
configuration path changed after the C-RT run.

## Physical results

| Run | Result | Machine-verifiable facts |
| --- | --- | --- |
| RT shared | Pipeline PASS | StarryOS 2 vCPU; masks `0x2`/`0x4`; migrations 0/0; 3×100 guest samples; guest/host IRQ records 880/1,094 with zero drops; clean snapshot; Linux restored |
| RT partitioned | Pipeline PASS | StarryOS 2 vCPU; masks `0x2`/`0x4`; migrations 0/0; 3×100 guest samples; guest/host IRQ records 888/1,097 with zero drops; clean snapshot; Linux restored |
| RT single-pair M2 | FAIL | `m2_exit_gate_met=false`; periodic p99 -55.718%, dispatch p99 -122.727%, timerfd proxy p99 +1.739%, direct timer→IRQ p99 +8.373%; one uncontrolled pair cannot satisfy the five-pair matrix |
| IVC fault-restart | PASS | Actual VM reset on pCPU3 after 20,000 ms; 20 pre-reset + 100 post-reset samples; accepted/applied 120/120; safe fallback, stale STATUS/ACK rejection, retired CONTROL rejection; clean snapshot; host fs synced; Linux restored |

Positive RT improvement percentages mean partitioned is lower. The negative
single-pair result is retained as observed; it is not replaced by the separate
historical formal campaign. IVC post-reset full-loop p50/p95/p99/max is
`2,340/2,551/24,692/344,033 us`, with 100/100 acknowledgements and zero
controller errors, timeouts, or retransmissions. These are smoke observations,
not WCET bounds.

## Layout

```text
commands/                  source-asserting reproduction wrappers
ivc/                       final same-commit metadata, summary, raw CSVs, serial log
rt/shared/                 current C-RT shared raw, traces, serial log, summary
rt/partitioned/            current C-RT partitioned raw, traces, serial log, summary
rt/comparison.json         fail-closed single-pair comparison
historical-formal/         compact immutable indexes from historical campaigns
validation/                reanalysis, tests, source, integrity, board and media checks
provenance.json            commit/tree/upstream, artifact, board, and result chain
source-delta.txt           exact C-RT to C-IVC path delta
source-files.git-ls-tree.txt  source path to Git blob mapping at C-IVC
runtime-inputs.sha256      hashes of runtime/analyzer inputs at their source commits
checksums.sha256           all delivered files except the manifest itself
demo-5min.mp4              exactly 300-second H.264/AAC evidence replay
```

## Verify

From the repository root on Linux/WSL:

```sh
bundle=competition/results/current-source-smoke-20260813
(cd "$bundle" && sha256sum -c checksums.sha256)
(cd "$bundle/ivc" && sha256sum -c runner-checksums.sha256)

mkdir -p tmp

python3 competition/ivc/analyze_board.py \
  "$bundle/ivc/console.log.gz" \
  --raw-csv "$bundle/ivc/raw.csv.gz" \
  --pre-reset-raw-csv "$bundle/ivc/raw-before-reset.csv.gz" \
  --expected-count 100 --expected-pre-reset-count 20 \
  --profile restart --output tmp/current-source-ivc-reanalyzed.json

python3 "$bundle/validation/compare-ivc-summary.py" \
  "$bundle/ivc/summary.json" tmp/current-source-ivc-reanalyzed.json
python3 "$bundle/validation/verify-evidence.py" .
sh "$bundle/validation/verify-source-index.sh" . \
  598b357f92c848e669c12cca830a4d08d0a50e36 \
  "$bundle/source-files.git-ls-tree.txt"
python3 -m json.tool "$bundle/provenance.json" >/dev/null
python3 -m json.tool "$bundle/rt/comparison.json" >/dev/null
```

The nested IVC runner manifest preserves the original filenames and hashes.
Bundle-local `.gitattributes` disables line-ending conversion so evidence bytes
remain stable across Windows and Linux clones. The local historical raw archive
is intentionally not duplicated here; an immutable public URL and top-level
digest remain a submission gap.
