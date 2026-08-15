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
