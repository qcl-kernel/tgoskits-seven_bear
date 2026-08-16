# AxVisor formal real-time campaign (Orange Pi 5 Plus)

This compact evidence set records the preregistered five-pair AB/BA campaign
and two 30-minute soak runs completed on 2026-08-16. The source was the clean
commit `77704718a1b46fc2fbf51ea6a184aa1071eee0ac` with tree
`f65ec1707eb91c92183064a29b3a6a860382cc68`.

The aggregate M2 exit gate passed:

| Metric | Max: improved pairs | Max: worst-of-runs improvement | P99: all pairs within 5% limit |
| --- | ---: | ---: | ---: |
| Dispatch latency | 5/5 | 99.504% | 5/5 |
| Emulated IRQ response | 5/5 | 99.465% | 5/5 |
| Periodic jitter | 5/5 | 99.513% | 5/5 |
| Virtual timer injection to guest IRQ | 5/5 | 47.234% | 5/5 |

Each short run collected 10,000 samples per metric. The shared and partitioned
soaks ran for 1,864.332 s and 1,845.872 s respectively and collected 229,046
and 440,413 direct IRQ pairs. The observed host-noise pCPU masks were `0x2`
for shared placement and `0x8` for partitioned placement.

`campaign-summary.json` contains the aggregate decision, `pair-*/comparison.json`
contains each independent comparison, and the twelve `receipt.json` files bind
every run to its board, source tree, raw artifacts, byte counts, and SHA-256
values. `preregistration.json` fixes the order, thresholds, source inputs, and
artifact identities before measurement.

The raw 543,799,035-byte payload is intentionally not duplicated in Git. Its
deterministic archive is named
`axvisor-rt-formal-20260816-77704718a.tar.gz`, has SHA-256
`60fedba15032a7d5a036355102859571a6bfec628d61676fffaa3d312d398ba9`,
and is described file-by-file by `archive.manifest.json`. `archive.sha256`
is the sidecar used after obtaining the archive. `SHA256SUMS` covers every
compact file in this directory except the checksum list itself.

The campaign is physical-board evidence for the specified Orange Pi 5 Plus;
it does not generalize to every RK3588 board, workload, or thermal condition.
