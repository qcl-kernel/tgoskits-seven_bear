# AxVisor formal real-time campaign (Orange Pi 5 Plus)

This compact evidence set records the preregistered five-pair AB/BA campaign
and two 30-minute soak runs completed on 2026-08-16. The source was the clean
commit `c82da8464ab69e7da95e9be08293559e67b28fac` with tree
`424d62d908518601acf8c4e8debea6a0662e9522`.

The aggregate M2 exit gate passed:

| Metric | Max: improved pairs | Max: worst-of-runs improvement | P99: all pairs within 5% limit |
| --- | ---: | ---: | ---: |
| Dispatch latency | 5/5 | 99.331% | 5/5 |
| Emulated IRQ response | 5/5 | 99.444% | 5/5 |
| Periodic jitter | 5/5 | 99.548% | 5/5 |
| Virtual timer injection to guest IRQ | 5/5 | 43.443% | 5/5 |

Each short run collected 10,000 samples per metric. The shared and partitioned
soaks ran for 1,864.677 s and 1,845.735 s respectively and collected 229,099
and 434,108 direct IRQ pairs. The observed host-noise pCPU masks were `0x2`
for shared placement and `0x8` for partitioned placement.

`campaign-summary.json` contains the aggregate decision, `pair-*/comparison.json`
contains each independent comparison, and the twelve `receipt.json` files bind
every run to its board, source tree, raw artifacts, byte counts, and SHA-256
values. `preregistration.json` fixes the order, thresholds, source inputs, and
artifact identities before measurement.

The raw 541,817,801-byte payload is intentionally not duplicated in Git. Its
deterministic archive is named
`axvisor-rt-formal-20260816-c82da8464.tar.gz`, has SHA-256
`68c1efb1ae0338692a84943c7056e104e2abed9e62a89dcdb0e2540ea1f9859e`,
and is described file-by-file by `archive.manifest.json`. `archive.sha256`
is the sidecar used after obtaining the archive. `SHA256SUMS` covers every
compact file in this directory except the checksum list itself.

The 113-file archive retains one incomplete first attempt that failed during
the U-Boot command handshake before measurement; it has no receipt and did not
advance the preregistered campaign. The subsequent retry and all twelve frozen
measurement slots completed normally.

The campaign is physical-board evidence for the specified Orange Pi 5 Plus;
it does not generalize to every RK3588 board, workload, or thermal condition.
