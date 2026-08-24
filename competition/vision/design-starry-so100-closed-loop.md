# StarryOS camera-to-SO-100 closed-loop design

The build, topology, rehearsal, recording, and paired-comparison procedure is
in [`starry-so100-demo-runbook.md`](starry-so100-demo-runbook.md).

## Status and decision

This document freezes the implementation boundary for the competition take in
which one tennis ball drives the SO-100 shoulder-pan joint through a StarryOS
vision guest and an RTOS authorization guest. The software is default-off for
motion. Preparing, building, dry-running, and inspecting the USB topology do
not authorize a physical command.

The selected demonstration has exactly three stable outcomes:

| Scene | AI decision | RTOS authorization | ID1 outcome |
| --- | --- | --- | --- |
| tennis ball on the right | `right` | same frame and sequence | position `2074` |
| tennis ball on the left | `left` | same frame and sequence | position `2042` |
| tennis ball absent | `hold` | same frame and sequence | no new goal write |

The current assembled-arm safe corridor is only `2042..=2074`. No other motor,
position, velocity, acceleration, torque limit, register address, or arbitrary
serial packet is part of this profile.

## Problem, users, and success criteria

The existing competition artifacts prove fixed-image vision-to-RTOS messages,
and separate evidence proves one supervised ID1 cycle. They do not prove that
one live USB-camera frame caused one RTOS-authorized physical result. The
operator needs a bounded path for the take, and reviewers need an identity
that remains visible across the camera image, network decision, authorization,
and observed motor position.

Preparation succeeds when all of the following are true:

1. StarryOS recognizes the frozen CH343 USB Control device as CDC ACM and can
   expose its data interface through the existing USB serial TTY boundary at
   1,000,000 baud.
2. The live RKNN runner publishes only an inference frame with the bounding box
   calculated from that same frame; it emits a decision record carrying the
   capture frame ID and UVC sequence.
3. The controller streams decisions instead of waiting for the camera process
   to exit, and records the RTOS authorization with the same session, sequence,
   and frame ID.
4. The actuator boundary accepts only authenticated controller events, applies
   a consecutive-frame stability gate, and maps only `left`, `right`, `hold`,
   and `emergency-stop` to the frozen ID1 capability.
5. A recorder-side dashboard refuses to display an "in sync" state unless the
   JPEG frame ID, AI frame ID, RTOS frame ID, and actuator frame ID agree.
6. A preregistered paired campaign contains at least 30 scenes (10 left, 10
   right, and 10 absent) in a fixed order and reports action accuracy plus
   capture-to-stable latency for AI and fixed-safe policy runs.

Physical acceptance additionally requires a new supervised authorization, a
clean work area, a reachable 12 V cutoff, a passed current-pose preflight, an
uninterrupted external video, and a post-run torque-disabled probe.

## Non-goals

- This increment does not authorize motion, calibration, EEPROM writes,
  multi-joint poses, arbitrary Feetech access, or unattended repetition.
- It does not claim that the current AxVisor image already owns the SO-100
  xHCI controller. A build or dry-run is not a physical closed-loop result.
- It does not infer actuator completion from an RTOS log line. Completion must
  contain an observed ID1 position inside tolerance.
- It does not present generated, validation-set, or previously recorded images
  as a live USB-camera feed.
- It does not use a terminal animation as the primary video. The terminal and
  synchronized camera image remain bounded subpanels of an external take.

## Audited hardware topology

A read-only Orange Pi 5 Plus inspection on 2026-08-24 observed:

- Jieli UVC `4c4a:4a55` at
  `/sys/devices/platform/fc880000.usb/usb6/6-1`, driven by `uvcvideo`;
- QinHeng USB Single Serial `1a86:55d3`, serial `5A7C122017`, at
  `/sys/devices/platform/usbdrd3_1/fc400000.usb/.../1-1.4`, driven by
  `cdc_acm`;
- CDC control interface 0 (`02/02/01`) with interrupt IN endpoint `0x83`;
- CDC data interface 1 (`0a/00/00`) with bulk OUT `0x02` and bulk IN `0x82`;
- a CDC Union functional descriptor mapping master interface 0 to slave
  interface 1.

The two devices are therefore on different RK3588 host controllers. The
existing `fc880000` EHCI camera handoff cannot be used as evidence that the
SO-100 at `fc400000` is guest-owned. The final AxVisor profile must choose one
of these independently reviewed options:

1. move both devices behind the already audited exclusive EHCI tree and freeze
   the hub/device topology; or
2. add a host-prepared, exclusive `fc400000` xHCI handoff with provider, DMA,
   event-delivery, hub inventory, and Linux cold-boot recovery evidence.

Until one option passes, the AxVisor physical profile remains blocked. Native
StarryOS can be used for CDC ACM and actuator no-motion verification but cannot
be relabeled as the two-guest competition result.

## Prior art and fixed protocol facts

The USB implementation follows the USB-IF Communications Device Class 1.2
document set and the Linux CDC ACM host implementation. CDC line coding uses a
seven-byte little-endian payload and class/interface request `0x20`; DTR/RTS
uses request `0x22`. The reusable driver allowlists the observed
`1a86:55d3` identity and requires the CDC Union mapping instead of claiming any
generic communications device.

- USB-IF CDC 1.2 document set:
  <https://www.usb.org/documents?type%5B%5D=55>
- Linux CDC ACM driver:
  <https://github.com/torvalds/linux/blob/v6.18/drivers/usb/class/cdc-acm.c>
- Linux CDC definitions:
  <https://github.com/torvalds/linux/blob/v6.18/include/uapi/linux/usb/cdc.h>

The fixed STS3215 facts remain bound to the previously reviewed SO-100 design:
protocol 0, model 777, ID1 shoulder pan, 4096 steps per turn, 1,000,000 baud,
and the volatile ID1-only motion registers. The implementation reuses the
existing, physically revalidated `2042 -> 2074 -> 2042` limits; it does not
derive a wider range from the servo's hardware limits.

## Alternatives

| Alternative | Decision | Reason |
| --- | --- | --- |
| Keep fixed validation images | reject for the take | It cannot show live camera causality. |
| Draw the latest detection on the latest capture | reject | Frame identity can be false when capture outruns inference. |
| Treat the RTOS virtual action as physical completion | reject | It hides USB, servo, and mechanical faults. |
| Give the RTOS arbitrary serial access | reject | It expands the RTOS and wire protocol to motor/register-level authority. |
| Run the complete LeRobot Python stack in StarryOS | reject | The rootfs has a small native runtime and does not need training dependencies. |
| Native, fixed-capability StarryOS actuator bridge after RTOS authorization | select | It preserves typed RTOS policy while keeping USB and servo ownership in one guest. |
| Pass through `fc400000` immediately | reject for preparation | Its provider, event, DMA, and external-hub ownership have not passed an independent handoff review. |

## Ownership and data flow

```text
USB camera -> StarryOS UVC/RKNN -> decision(frame, camera_sequence)
                                      |
                                      v UDP/IP
                              RTOS validate + authorize
                                      |
                                      v typed status
StarryOS fixed actuator bridge -> CDC ACM -> STS3215 ID1 -> read-back position
             |
             +-> loop event(session, sequence, frame, target, observed)

serial JPEG(frame) + loop event(frame) -> recorder dashboard -> synchronized PIP
```

StarryOS owns camera capture, inference, and the physical bus. The RTOS owns
the accepted action vocabulary, freshness, replay window, timeout, and
authorization result. AxVisor owns the exclusive device assignment and DMA
boundary. The recorder is evidence-only and has no control path.

## State and failure policy

The actuator state is monotonic within one invocation:

```text
Locked -> ReadOnlyVerified -> Armed -> StableHold/Moving
   \            \              \          \
    +------------+--------------+-----------> FaultLatched -> Disarmed
```

- Startup is `Locked`; reconnect never restores `Armed`.
- Dry-run never opens a device and emits `device_io_attempted=0`.
- Execute mode requires a hash-bound policy, an explicit one-invocation
  authorization, operator/workspace/cutoff acknowledgements, and an exact
  confirmation phrase.
- Three consecutive, increasing frames must carry the same RTOS-authorized
  action before a transition. Repeated authorization of the current state does
  not repeat a goal write.
- `hold` issues no goal write. `emergency-stop`, timeout, malformed identity,
  unexpected position, status fault, torque loss, serial error, or interrupt
  latches the bridge and performs at most one best-effort torque-disable write.
- Goal writes are never retried because a missing response is ambiguous.
- `physical_applied=1` means the executor issued one frozen ID1 goal write;
  it never means that motion completed. `physical_verified=1` is emitted only
  after the requested physical outcome is observed. LEFT/RIGHT require ID1
  read-back inside the frozen tolerance with no status fault. HOLD is verified
  without a goal write, so its successful record is
  `physical_applied=0 physical_verified=1`.

## Frame and sequence identity

`frame_id` is the StarryOS capture counter. `camera_sequence` is the UVC
sequence delivered by the camera. `sequence` is the IVC request sequence. All
three are printed in the decision record; session, IVC sequence, and frame ID
are repeated by the RTOS authorization and physical-status records.

The serial JPEG publisher exports only the exact inference image used to make
the decision. The dashboard joins records by frame ID and shows `SYNC WAIT`
for missing or disagreeing identities. It never substitutes a repository
sample when the live frame is absent.

## Preregistered comparison

Before recording outcomes, freeze a 30-scene ordered manifest: ten left, ten
right, and ten absent scenes, with the order interleaved and reused unchanged
for both policies. The AI policy is YOLO class 32 plus center-region mapping.
The fixed-safe baseline always returns `hold`; this is intentionally the
non-adaptive fail-safe policy, not a second vision model.

The two primary metrics are:

1. action accuracy: stable physical action equals the preregistered expected
   action; and
2. capture-to-stable latency: matching physical stable timestamp minus camera
   capture timestamp, reported as median and p95.

Also report absent-scene false-motion rate and all rejected/missing trials.
The analyzer rejects fewer than 30 paired samples, duplicate trial IDs, changed
order, unmatched identities, or a claim of latency for a non-applied event.
No expected direction or trial may be edited after observing AI results.

## Validation and rollout

Deterministic validation covers CDC descriptor pairing and class requests,
multi-interface claim/release behavior, action debounce and fixed target
mapping, protocol packet checksums, streaming record order, JPEG/event identity
joins, campaign completeness, and deliberate mismatches. Run repository
formatting, targeted `usb-serial` and `ivcproto` Clippy, C/C++ host self-tests,
and competition Python tests before any board action.

Board rollout is gated in this order:

1. Linux topology and stable identity read-only probe;
2. native StarryOS CDC ACM enumeration and read-only ID1 status;
3. native StarryOS dry-run with live camera and RTOS simulator, no torque;
4. reviewed AxVisor USB ownership design and cold-boot recovery;
5. AxVisor two-guest no-motion run with synchronized frame identities;
6. separately authorized, supervised physical rehearsal;
7. paired campaign and one uninterrupted external competition take.

Rollback removes the dedicated CDC allowlist/profile and actuator bridge. No
persistent servo register is changed by preparation or dry-run.
