# Current-source Orange Pi evidence bundle

This directory binds the post-rebase runtime source to two physical Orange Pi
5 Plus smoke workflows executed on 2026-08-12 (Asia/Shanghai): an IVC guest
restart/recovery run and one StarryOS RT shared/partitioned pair. Both command
wrappers asserted source commit
`069c911c1de02cecdc0c1fe891f5d5a288065ef0` before acquiring the board.

The bundle is intentionally compact. It contains the machine summaries, raw
samples, compressed serial/trace inputs, exact command wrappers, source/input
manifests, and compact indexes copied from the earlier formal campaigns. It
does not duplicate the approximately 844 MiB full historical board archive.

## What the current-source runs prove

| Run | Result | Scope |
| --- | --- | --- |
| IVC `fault-restart` | PASS | Actual VM reset on pCPU3; 20 pre-reset and 100 post-reset commands; new session accepted; retired CONTROL, stale STATUS, and stale ACK each rejected once; safe fallback observed; clean 64 MiB snapshot; Linux restored |
| RT `shared` | PASS | 3 metrics × 100 samples under guest CPU1 stress; lossless direct guest/host IRQ traces; clean snapshot; Linux restored |
| RT `partitioned` | PASS | Same inputs and sample contract, with `dedicated_cpus=true`; lossless traces; clean snapshot; Linux restored |
| RT pair comparison | Pipeline PASS, performance gate FAIL | One uncontrolled pair cannot satisfy the five-pair M2 gate, and this pair contains tail regressions |

The current pair must not be presented as a latency-improvement result.
Partitioned versus shared changed p99 by `-53.710%` for periodic jitter,
`-154.925%` for dispatch latency, `+1.856%` for the timerfd proxy, and
`-5.714%` for direct virtual-timer-injection-to-guest-IRQ latency. Positive
means partitioned is lower. The exact values are in
[`rt/comparison.json`](rt/comparison.json).

The performance claim in the scorecard instead uses the preregistered
five-pair controlled-host-interference campaign. Its compact machine summary
is retained under [`historical-formal/rt-host-noise`](historical-formal/rt-host-noise/).
Those historical files remain tied to their recorded clean source commits;
they are not relabelled as current-source captures.

## Source and artifact chain

[`provenance.json`](provenance.json) records the tested commit/tree, upstream
base, Git archive hash, upstream diff hash, board identity, staged binary
hashes, snapshot hashes, and result hashes. [`runtime-inputs.sha256`](runtime-inputs.sha256)
hashes the actual configuration, stager, runner, analyzer, guest script, model
source, and probe bytes. [`source-files.git-ls-tree.txt`](source-files.git-ls-tree.txt)
maps the relevant committed paths to Git blob IDs.

The original IVC metadata is preserved byte-for-byte as
[`ivc/metadata.original.json`](ivc/metadata.original.json). Its `dirty=true`
field came from invoking WSL Git against a Windows `core.autocrlf` checkout:
WSL counted line-ending-only differences and generated evidence, while the
Windows Git instance owning the checkout filters reported no tracked changes.
The additive clarification is in `provenance.json`; the captured metadata was
not rewritten.

## Directory guide

```text
commands/                 exact source-asserting run wrappers
ivc/                      restart summary, original metadata, raw CSVs, serial log
rt/shared/                full summary, raw samples, guest IRQ, host trace, serial log
rt/partitioned/           same artifact set for dedicated CPU placement
rt/comparison.json        fail-closed one-pair comparison
historical-formal/        compact preregistrations/summaries, without the large raw archive
validation/               final repository and analyzer validation logs
demo-5min.mp4             300-second H.264/AAC post-run evidence replay
provenance.json           source, board, input, output, and scope attestation
runtime-inputs.sha256     runtime input byte hashes
checksums.sha256          bundle integrity manifest
```

## Verify

From the repository root in WSL/Linux:

```sh
bundle=competition/results/current-source-smoke-20260812
(cd "$bundle" && sha256sum -c checksums.sha256)

test "$(git rev-parse 069c911c1^{tree})" = \
  c13efe6409b3a720828c224147bc1e2ca5682ffe

git archive --format=tar 069c911c1 | sha256sum
# expected: 6b65153c727a31edebf3829ef02e34a65090450d98042f1d8d6fbe0256581102

sha256sum -c "$bundle/runtime-inputs.sha256"
python3 -m json.tool "$bundle/provenance.json" >/dev/null
python3 -m json.tool "$bundle/ivc/summary.json" >/dev/null
python3 -m json.tool "$bundle/rt/comparison.json" >/dev/null
```

`runtime-inputs.sha256` checks the current working files and therefore should
be run from source commit `069c911c1`; later documentation-only commits may
legitimately change files outside that manifest.

The checksum files nested below `historical-formal/` are original manifests
from the complete historical archives. They intentionally reference raw files
that are not duplicated in this compact directory, so they are provenance
indexes rather than standalone compact-bundle check commands. The top-level
`checksums.sha256` is the self-contained integrity command for every file that
is delivered here.

## Retention boundary

The compact historical summaries are sufficient to inspect gates and hashes,
but not to recompute every historical statistic because their complete raw
archive is intentionally not committed here. Before final submission, publish
the full `competition/results/orangepi-5-plus/` archive as a checksummed GitHub
Release/LFS object or an immutable external dataset, then record its download
URL and top-level SHA-256 in the scorecard. Until then, the raw-archive
availability item remains an explicit documentation gap.
