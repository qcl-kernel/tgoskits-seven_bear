# Evidence archive packaging

`package.py` creates a deterministic `.tar.gz` archive for a completed local
campaign and writes two sidecars: a per-file JSON manifest and the archive's
SHA-256. It rejects links and special files, refuses overwrites, normalizes tar
metadata, and re-reads every archived payload before publishing the output.

```sh
python3 competition/evidence/package.py \
  competition/results/orangepi-5-plus \
  tmp/publish/tgoskits-competition-full-evidence.tar.gz

cd tmp/publish
sha256sum -c tgoskits-competition-full-evidence.tar.gz.sha256
```

Upload all three files to one immutable release or dataset record. The public
URL and returned service-side checksum are external publication evidence; this
local tool cannot create or claim them.

Run the contract tests with:

```sh
python3 -m unittest discover \
  -s competition/evidence/tests -p 'test_*.py'
```

## Delivery verification gate

The compact formal RT campaign, RTOS Guest/IVC, and three-guest isolation
evidence is part of the submission, but a plain `sha256sum -c` only proves that
listed bytes did not change. It does not reject unlisted files, false campaign
counters, missing terminal markers, disagreement between evidence sets, or
runtime changes made after the recorded source commit.

Run the cross-platform, standard-library-only gate from the repository root:

```sh
python3 competition/evidence/verify_delivery.py
```

The command fails closed unless all of the following hold:

- each checksum manifest covers every regular file exactly once;
- all five gzip logs stay within the 16 MiB safety limit and match both their
  compressed and decompressed identities;
- RT-Thread and FreeRTOS contain exactly normal and ACK-loss results with the
  declared 100/100 success and 0/20 reliability counters;
- the isolation log contains every declared terminal marker, including zero
  received cross-segment probes;
- both QEMU evidence sets name the same clean source commit;
- the formal RT evidence contains the preregistered five-pair AB/BA matrix,
  10,000 samples per metric and half, both 30-minute soaks, the passing M2
  decision, twelve source/board-bound receipts, and 113 archive entries;
- all receipt artifacts match the full archive manifest, and all 34
  preregistered runtime inputs still match their source-commit and `HEAD` Git
  blobs even when unrelated runtime paths changed later;
- the QEMU commit is an ancestor of `HEAD`, with descendants limited to
  competition documentation, evidence, verification tooling, CI, the reviewed
  evidence-only Git attributes, and one exact `rsext4` `#[cfg(test)]` fixture
  transition that cannot enter a measured runtime image.

For the complete dependency-free host regression used by CI, run:

```sh
bash competition/evidence/run-host-validation.sh
```

This also executes the 36 focused RTOS Guest/IVC tests, the common VirtIO/IVC
and Zephyr C host tests, native RTOS analyzer/configuration tests, and evidence
tool tests before checking the retained delivery artifacts. The delivery
verifier has 23 deterministic positive and negative cases; together with the
four archive-packager cases, the evidence tool suite contains 27 tests.

CI runs this command from the path-scoped `competition-delivery.yml` workflow
when competition content, reviewed evidence attributes, or that workflow
changes. It is intentionally separate from the global runtime matrix so a
historical competition snapshot does not freeze unrelated repository work.

### Design boundary

Keeping only the existing shell checksum commands was rejected because they
do not validate claim semantics or source freshness. Reusing `package.py`
alone was also insufficient: it verifies a newly created generic archive, not
the domain-specific counters and pass conditions of the tracked compact
evidence. The selected verifier reuses the existing artifact formats, adds no
third-party dependency, and does not alter a runtime protocol or image.

The gate does not rerun QEMU or a physical board, publish the full raw archive,
or convert QEMU evidence into a board/performance claim. Those remain separate
campaign and publication steps.

The narrowly reviewed `rsext4` test repair is not covered by a path-wide
exception. The gate requires the measured source blob
`b5471e08cb7db1d168628a5a94ae89e9e9ea1b6e` and the reviewed test-only target
blob `7b94e102a9ae424dbfc1aebed38e90b3aba59f35` exactly. Any other committed or
uncommitted change to that source file remains runtime-relevant and is rejected.
The current `c82da8464` evidence source already contains the reviewed target
blob, so the exception is not exercised by this delivery.

The current formal RT raw payload has already been packaged locally as
`axvisor-rt-formal-20260816-c82da8464.tar.gz` (42,722,019 bytes compressed). Its
SHA-256 is
`68c1efb1ae0338692a84943c7056e104e2abed9e62a89dcdb0e2540ea1f9859e`;
the tracked compact set at
[`../results/axvisor-rt-formal-20260816`](../results/axvisor-rt-formal-20260816/)
contains the sidecar and 113-file manifest. Publishing the archive to an
immutable URL remains an external release step.
