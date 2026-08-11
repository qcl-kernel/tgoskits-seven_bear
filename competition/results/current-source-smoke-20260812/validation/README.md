# Final validation index

Validation date: 2026-08-12 (Asia/Shanghai). The runtime source under test is
commit `069c911c1de02cecdc0c1fe891f5d5a288065ef0`; subsequent working-tree
changes in this validation pass are documentation, compact evidence, and video
production files. [`source-attestation.log`](source-attestation.log) confirms
that every runtime input still matches the recorded bytes.

| Gate | Result | Log |
| --- | --- | --- |
| Rust format, pinned `nightly-2026-07-15` | PASS | [`cargo-fmt.log`](cargo-fmt.log) |
| `cargo xtask clippy --package axbuild` | PASS, 1/1 | [`clippy-axbuild.log`](clippy-axbuild.log) |
| Orange Pi AxVisor target clippy | PASS, exit 0 | [`clippy-axvisor-board.log`](clippy-axvisor-board.log) |
| Four current typed device configurations | PASS, 4/4 | `check-config-*.log` |
| IVC Python discovery | PASS, 183/183 | [`test-ivc-python.log`](test-ivc-python.log) |
| RT Python discovery | PASS, 64/64 | [`test-rt-python.log`](test-rt-python.log) |
| RT generic shell runner | PASS | [`test-rt-runner.log`](test-rt-runner.log) |
| RT Starry shell runner | PASS | [`test-rt-starry-runner.log`](test-rt-starry-runner.log) |
| Zephyr/C host logic | PASS | [`test-ivc-zephyr-host.log`](test-ivc-zephyr-host.log) |
| `axbuild` AxVisor-focused host tests | PASS, 107/107 | [`test-axbuild-axvisor.log`](test-axbuild-axvisor.log) |
| AxVisor AArch64 QEMU axtest | PASS, 79/79 | [`test-axvisor-axtest-aarch64.log`](test-axvisor-axtest-aarch64.log) |
| Current IVC archive reanalysis | PASS | [`reanalyze-ivc.log`](reanalyze-ivc.log) |
| Current RT comparison recomputation | PASS, byte-identical | [`reanalysis-crosscheck.log`](reanalysis-crosscheck.log) |
| Source/tree/archive/diff/runtime inputs | PASS | [`source-attestation.log`](source-attestation.log) |
| All compact-bundle JSON and gzip files | PASS | [`json-integrity.log`](json-integrity.log), [`gzip-integrity.log`](gzip-integrity.log) |
| Competition Markdown local links | PASS | [`markdown-links.log`](markdown-links.log) |
| 300-second MP4 probe and full decode | PASS | [`video-integrity.log`](video-integrity.log) |

The board-target clippy command applies `-D warnings` to the `axvisor` binary
and returned zero. Its log also contains non-fatal dead-code warnings emitted
while checking dependency crates; those are retained rather than filtered.
Some WSL login-shell logs end with an unrelated user-profile message about an
inaccessible Linuxbrew path after the successful command summary. It did not
change the command exit status.

This directory validates the delivered source and evidence. It does not claim
that the current-source single RT pair passed M2, nor does it claim that the
historical five-pair/soak campaigns were rerun on the documentation commit.
