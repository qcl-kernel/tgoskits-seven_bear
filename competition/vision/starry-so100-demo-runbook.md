# StarryOS live-camera and SO-100 demonstration runbook

## Outcome and current boundary

This runbook prepares one auditable identity chain:

```text
USB camera frame
  -> StarryOS RKNN decision(frame_id)
  -> IVC/1 request(session_id, sequence, frame_id)
  -> Zephyr RTOS authorization(session_id, sequence, frame_id)
  -> fixed SO-100 ID1 policy
  -> position 2042 / 2074 / HOLD
```

The preparation path is implemented but intentionally stops before physical
motion. `ivc-vision-actuator --execute` remains locked. The preparation image
uses `--dry-run`, reports `physical_applied=0 physical_verified=0`, and never
opens the arm device.

A read-only Linux audit on 2026-08-24 found the camera (`4c4a:4a55`) below
`/usb@fc880000`, while SO-100 USB Control (`1a86:55d3`) was below
`/usbdrd3_1/usb@fc400000`. They are different host controllers. The checked-in
AxVisor preparation profile passes through only `/usb@fc880000`; therefore the
hardware preflight must fail until both devices are deliberately connected
below that same controller. This audit is a readiness observation, not a
physical closed-loop result.

## Prepared components

| Component | State | Evidence boundary |
| --- | --- | --- |
| Live UVC inference frame | Ready for board validation | The annotated JPEG is the exact image used for inference. |
| AI decision identity | Implemented and host-tested | Every decision carries capture time and `frame_id`. |
| RTOS mediation | Implemented and host-tested | Authorization repeats `session_id`, IVC `sequence`, and `frame_id`. |
| SO-100 policy | Implemented and host-tested | Only ID1 2042, ID1 2074, HOLD, and emergency stop are representable. |
| CDC ACM recognition | Implemented and host-tested | Restricted to audited USB identity `1a86:55d3` and its Union descriptor. |
| Physical motion | Locked | Requires shared-controller board validation and a separately reviewed executor gate. |
| Picture-in-picture monitor | Implemented and host-tested | Refreshes only after exact camera/AI/RTOS/actuator identity join. |
| AI versus fixed campaign | Preregistered | No chart is accepted until all 30 paired trials have verified physical outcomes. |

## 1. Build preparation artifacts

Run in the repository's WSL environment. The dependency builders use pinned
upstream commits and refuse to overwrite existing evidence directories.

If the Zephyr checkout, cross toolchain, or managed BusyBox image lives outside
the current worktree, declare each boundary explicitly. Keep `/usr/sbin` in
`PATH` so the ext4 inspection tools are available:

```sh
export PATH="/absolute/path/to/zephyr-venv/bin:/usr/sbin:$PATH"
export ZEPHYR_BASE=/absolute/path/to/zephyr-v4.3.0
export ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
export IVC_ZEPHYR_CROSS_COMPILE=/absolute/path/to/toolchain/bin/aarch64-zephyr-
export IVC_LINUX_CROSS_COMPILE=aarch64-linux-gnu-
export IVC_VISION_BASE_IMAGE=/absolute/path/to/rootfs-aarch64-busybox.img
```

The build invokes the Zephyr prefix only for `west build` and the Linux prefix
only for the RK3588 camera runner. This prevents one toolchain environment from
silently compiling the other guest's executable.

```sh
bash competition/vision/build-libusb-aarch64.sh

bash competition/vision/build-libuvc-aarch64.sh \
  tmp/competition/vision/libusb-aarch64-4239bc3a5001/install/lib/libusb-1.0.so.0

export IVC_VISION_LIBUSB="$PWD/tmp/competition/vision/libusb-aarch64-4239bc3a5001/install/lib/libusb-1.0.so.0"
export IVC_VISION_LIBUVC="$PWD/tmp/competition/vision/libuvc-aarch64-047920bcdfb1/install/lib/libuvc.so"
bash competition/ivc/build-vision-so100-prep.sh
```

The last command builds:

- a two-vCPU StarryOS Guest with VirtIO block/network, RKNN, and RK3588 EHCI;
- a rootfs containing the live RKNN runner, IVC controller, dry-run actuator,
  model, and audited USB runtime libraries;
- a Zephyr RTOS Guest frozen to the same 180-decision finite profile.

## 2. Put both USB devices under one exclusive controller

1. Keep the 12 V cutoff reachable and turn arm power off before moving USB
   cables.
2. Connect a powered USB 2 hub to the Orange Pi port currently used by the
   camera.
3. Connect both the camera and SO-100 **USB Control** to that hub. Do not mix
   UART Control and USB Control.
4. Restore USB and 12 V power, but do not run a serial command.
5. Run the read-only topology gate:

```sh
export ORANGEPI_SSH_IDENTITY=/absolute/path/to/board-key
bash competition/ivc/preflight-vision-so100.sh
```

The only passing terminal record is:

```text
SO100_PREFLIGHT_PASS controller=/usb@fc880000 topology=exclusive-shared-ehci motion_attempted=0
```

The preflight requires exactly one camera with `uvcvideo`, exactly one arm
adapter with `cdc_acm`, `/dev/ttyACM0`, and the same `/usb@fc880000` provider.
It performs no serial read or write.

## 3. Run the complete no-motion StarryOS rehearsal

After committing the preparation source so the worktree is clean:

```sh
export ORANGEPI_AXVISOR_HOST_ROOT='PARTUUID=<board-linux-root>'
export ORANGEPI_SSH_IDENTITY=/absolute/path/to/board-key
bash competition/ivc/run-vision-so100-prep.sh
```

Open `http://127.0.0.1:8765/` as a browser source or capture it in a small
window. The rehearsal runs 180 live inferences and then powers both guests off.
Its final record is explicit about the boundary:

```text
VISION_SO100_PREP_RUN_PASS ... frames=180 physical_applied=0 physical_verified=0
```

The monitor never reads a repository sample. It extracts a JPEG only from the
live serial stream and refreshes only when all of these refer to the same
identity:

- `VISION_CAPTURE_IDENTITY.frame_id` and camera sequence;
- `VISION_DECISION_RECORD.frame_id`;
- `VISION_RTOS_AUTH_RECORD.session_id/sequence/frame_id`;
- `VISION_ACTUATOR_RECORD.session_id/sequence/frame_id`;
- `STARRY_JPEG_BEGIN/END.frame`.

An incomplete, corrupt, reordered, or cross-frame tuple remains `SYNC WAIT`.

## 4. Gate before enabling physical motion

Do not modify the dry-run script in place. Physical execution needs a separate
reviewable profile and all of the following evidence:

1. the shared `/usb@fc880000` topology passes before and after the run;
2. native StarryOS enumerates the CDC ACM function and performs a no-motion ID1
   status read;
3. the arm starts within `2042 +/- 8`, all other joints remain unchanged, and
   the work area is clear;
4. the 12 V cutoff is reachable and a supervised emergency-stop test has been
   recorded;
5. the executor permits only the frozen ID1 packet set and verifies read-back;
6. loss, expiry, session change, mismatched action, or three-frame instability
   results in HOLD or torque disable, never a guessed goal;
7. every physical executor record distinguishes a servo write
   (`physical_applied`) from an observed correct outcome (`physical_verified`);
   a verified HOLD has `physical_applied=0 physical_verified=1` because it must
   not issue a new goal;
8. the final monitor is launched with `--require-physical`, which gates on
   `physical_verified=1`, so neither a dry-run frame nor an unverified write can
   appear as physical evidence.

## 5. Recording layout and action sequence

Use a phone or second camera for the main image. Keep the tennis ball, USB
camera, complete SO-100 arm, its 12 V cutoff, and the operator's hands visible.
Place the browser monitor in a smaller sub-window; do not show a full-screen
terminal.

The sub-window must continuously show one joined identity line such as
`FRAME 417 · CAMERA 992 · IVC 38`. Record one continuous take:

1. Move the ball to the right. Wait for three matching authorizations, show
   `AI RIGHT -> RTOS RIGHT`, and show ID1 reaching 2074.
2. Move the ball to the left. Show `AI LEFT -> RTOS LEFT` and ID1 returning to
   2042.
3. Remove the ball. Show `AI HOLD -> RTOS HOLD`; no new goal write or arm motion
   is permitted.
4. Keep the main image and identity bar visible through every transition. Do
   not splice a sample image into the USB-camera sub-window.

## 6. Preregistered AI-versus-fixed comparison

The manifest
[`ball-campaign-preregistration.json`](ball-campaign-preregistration.json)
freezes 30 balanced trials: 10 left, 10 right, and 10 absent. Each trial runs
both strategies in the recorded AB/BA order. The fixed strategy is always HOLD
and cannot be adapted after seeing a label.

Each JSONL record must contain exactly:

```json
{"trial_id":"T01","strategy":"ai","frame_id":417,"session_id":1447646040,"sequence":38,"actual_action":"right","captured_at_us":1000000,"stable_at_us":1210000,"physical_result_verified":true}
```

Generate the two-panel competition chart only after all 60 records exist:

```sh
python3 competition/vision/analyze_ball_campaign.py \
  --manifest competition/vision/ball-campaign-preregistration.json \
  --records /path/to/physical-paired-records.jsonl \
  --source-commit "$(git rev-parse HEAD)" \
  --output-dir /path/to/campaign-result
```

The two preregistered primary displays are action accuracy and
capture-to-stable p95. The report also retains absent-ball false motion. The
analyzer rejects fewer than 30 pairs, reordered records, duplicate identities,
an adapted fixed policy, unverified physical outcomes, and latency outside the
five-second evidence gate.
