# Validation index

These logs validate the runtime commits recorded in `../provenance.json`, not
the later documentation-only evidence commit. Commands ran in the native Linux
clean clone at IVC commit `598b357f92c848e669c12cca830a4d08d0a50e36`
unless a log says otherwise.

| File | Contract |
| --- | --- |
| `ivc-tests.log` | complete `competition/ivc/tests` discovery |
| `ivc-reanalysis.log` / `reanalyzed-ivc.json` | archived UART/raw passes the final analyzer and agrees after relocatable path normalization |
| `zephyr-host-tests.log` | protocol/guest host regression |
| `rt-tests.log` | RT Python analyzer plus both maintained shell runners |
| `rustfmt.log` | workspace formatting check |
| `clippy-*.log` | targeted Rust lint for changed runtime boundaries |
| `qemu-axtest.log` | AArch64 AxVisor QEMU `axtest`, 80/80 |
| `qemu-dedicated-smp2.log` | AArch64 dedicated two-vCPU placement marker, 1/1 |
| `source-boundary.sh` / `.log` | upstream ancestry, clean source, tree IDs, runtime-input hashes and four-path C-RT→C-IVC delta |
| `verify-source-index.sh` / `source-object-index.log` | every source-index entry resolves to the recorded blob at the runtime commit |
| `verify-evidence.log` | JSON/gzip integrity and repository-relative Markdown link audit |
| `board-health.log` / `power-status.json` | post-run Linux/rootfs and non-mutating smart-plug health |
| `media.log` / `frames/` | exact duration/codecs/dimensions, audio QA, and start/middle/end plus RT-M2-fail visual samples for the five-minute video |

`verify-evidence.py` is the fail-closed JSON/gzip/link checker. It also binds
the final IVC commit and zero-exit validation to provenance and requires the
current RT comparison to preserve its observed M2 failure.

`compare-ivc-summary.py` removes only three absolute input path fields; all
protocol, lifecycle, board, hashes, counts and measurements must match exactly.
