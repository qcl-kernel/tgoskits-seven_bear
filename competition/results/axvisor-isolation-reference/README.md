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
61,141-byte console/build log. Its compressed SHA-256 is
`18a03f8e40935d2e449030c55420f892912aaa007aefc2bff78cfffc08c8ad12`;
the decompressed SHA-256 is
`d5bb1accf92147289f62ded947155211c6d0f7ce177634be0eb8ede8c3e47a27`.
[`summary.json`](summary.json) records the topology, exact pass markers,
environment, command, and clean source commit
`c82da8464ab69e7da95e9be08293559e67b28fac`.

This is dynamic QEMU evidence for segment separation and absence of a default
route. It does not claim a physical-board result, firewall/NAT validation,
dynamic MAC-spoof rejection, or dynamic unknown-unicast rejection. Those last
two policies remain covered by the lower-layer `axvm-net` tests.
