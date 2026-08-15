# Three-guest AxVisor network-isolation reference

This directory retains one QEMU/AArch64 run of the competition isolation
case. VM1 and VM2 share virtual-switch segment 1 and complete a 64 KiB TCP
exchange. VM3 belongs to segment 2, has no default route, and transmits 100
directed-broadcast UDP probes toward VM1's subnet. VM1 observes UDP port 5002
for seven seconds and receives zero probes.

The run passed all of these independent postconditions:

- VM2 transmitted 65,536 bytes with checksum `0x7f8000` and VM1 received the
  same length and checksum;
- VM3 reported zero default routes and 100 frames accepted by its guest NIC
  transmit path;
- VM1 reported `received_cross_segment_probes=0` after the complete
  observation window;
- all three guests reached their terminal pass markers and no fail/panic
  marker matched.

Reproduce from a Linux shell at the repository root:

```sh
bash apps/arceos/virtio-net-peer/run-isolation.sh
```

The runner builds the three ArceOS images and starts AxVisor through
`cargo xtask`. Its QEMU contract uses four Cortex-A72 CPUs and 4 GiB RAM;
AxVisor runs on pCPU0, while VM1, VM2, and VM3 are pinned to pCPU1, pCPU2, and
pCPU3 respectively.

## Evidence boundary

[`qemu.log.gz`](qemu.log.gz) is a deterministic `gzip -n -9` copy of the full
60,342-byte console/build log. Its compressed SHA-256 is
`16059aa0660c59d37010f5837578ce79e6cae71bed2463a15ca80de916e88ab4`;
the decompressed SHA-256 is
`56157cf655b53ea48d642b4cda0e4213521a0d2b59c4e0c4c3338c7af7c0665d`.
[`summary.json`](summary.json) records the topology, exact pass markers,
environment, command, and clean source commit
`ec3c363b1a61956069365a06c262091ce847b335`.

This is dynamic QEMU evidence for segment separation and absence of a default
route. It does not claim a physical-board result, firewall/NAT validation,
dynamic MAC-spoof rejection, or dynamic unknown-unicast rejection. Those last
two policies remain covered by the lower-layer `axvm-net` tests.
