# AxVM target-vCPU wakeup and phase tracing

## Problem and users

AxVM currently uses one VM-wide wait queue for both lifecycle coordination and guest WFI waits.
An interrupt for one vCPU therefore calls `notify_all()`, waking unrelated vCPU tasks before sending
the target pCPU an IPI. The same limitation prevents an SMP console notification from publishing a
durable device-poll request for vCPU0: `notify_one()` may select another sleeping vCPU.

The direct users are AxVM architecture interrupt backends, architectural timers, virtual devices,
and SMP guests. For the competition workload, unnecessary sibling wakeups are a plausible source of
dispatch-tail interference, but any performance claim still requires paired measurements from the
final commit.

## Success criteria

- An IRQ or timer wake for vCPU N advances and wakes only vCPU N's guest-event channel.
- VM stop, pause/resume, reset, and other lifecycle transitions still wake every participant.
- An SMP device notification durably requests polling and targets vCPU0.
- Publication-before-wait races remain closed with Acquire/Release generation checks.
- The RT trace can distinguish deferred publication, worker dispatch, runtime notification, IPI
  delivery, and the next target-vCPU run.
- Host unit tests cover target isolation, broadcast behavior, and both sides of the WFI wait race.
- The `axvm` host-test suite and targeted clippy check pass.

## Non-goals

- This change does not remove the deferred hard-IRQ worker or the unconditional VM-exit yield.
- It does not redesign the host scheduler, VGIC pending-state ownership, or timer queue.
- It does not claim a latency improvement without final-commit RK3588 AB/BA evidence.
- It does not change StarryOS syscall or Linux ABI behavior.

## Prior art and existing boundaries

- Commit `640fd75bd` documents the current shared-queue limitation and explicitly defers SMP device
  polling until AxVM has a per-vCPU wake path.
- `VmRuntimeHandle` already owns vCPU task registration, interrupt queues, and lifecycle wakeups, so
  the event channel belongs to the same runtime lifetime rather than a new global registry.
- ArceOS `WaitQueue` already provides the required block/notify synchronization. No new scheduler or
  public host-task API is required.
- `DeferredVcpuKick` already guarantees that hard IRQ handlers only publish atomics and wake a
  pre-created worker. The design preserves that boundary.

No external ABI or hardware semantic is introduced, so external specifications are not normative
for this change. The relevant prior art is the repository's existing runtime, wait-queue, IRQ-worker,
and trace contracts.

## Alternatives

| Alternative | Benefit | Cost or rejection reason |
| --- | --- | --- |
| Keep `notify_all()` | No implementation risk | Preserves sibling wakeups and the SMP vCPU0 notification gap |
| Add targeted removal to ArceOS `WaitQueue` | Reuses one queue | Expands a shared scheduler API and requires an O(vCPU count) waiter scan |
| Force-wake `AxTaskRef` directly | Small AxVM diff | Leaves stale wait-queue entries and uses task interruption semantics intended for signals |
| Per-vCPU AxVM event channels | O(1) target wake, local lifetime, no scheduler API change | Adds one wait queue and generation counter per registered vCPU |

The selected design uses per-vCPU event channels while retaining the VM-wide queue exclusively for
lifecycle waits and broadcasts.

## Ownership and synchronization

`VmRuntimeHandle` preallocates one event channel for every configured vCPU when the runtime is
created. The channels live for the entire runtime lifetime, so CPU_OFF/CPU_ON task-registration
changes cannot invalidate an in-progress wait and the wake path does not allocate or search a map.

A target notification performs these steps:

1. Resolve the registered vCPU task's current pCPU under the runtime task-map lock.
2. Release the map lock.
3. Resolve the preallocated event channel by vCPU index, increment its generation with Release
   ordering, and notify its wait queue.
4. Send an IPI to the task's current pCPU so a running guest exits promptly.

The waiter snapshots the channel generation with Acquire ordering, rechecks architectural pending
state after arming its timer, and blocks only while the generation is unchanged. A VM-wide broadcast
wakes lifecycle waiters and notifies every preallocated event channel. No wake callback runs while
the task-map lock is held.

Hard IRQ behavior is unchanged: it only updates `DeferredVcpuKick` atomics and `IrqNotify`; runtime
lookup and wait-queue operations remain in the worker task.

## Trace contract

With `rt-trace`, each wake carries a capture-local ID and emits allocation-free phase records:

1. `publish`, with source `deferred_irq` or `timer_deadline`
2. `deferred_worker` when applicable
3. `runtime_notify`
4. `ipi_sent`
5. `vcpu_run`

Records use the host architectural counter and include VM, vCPU, pCPU, source, and phase. Multiple
publications may legitimately coalesce before one vCPU run; the snapshot reports incomplete wake
pipelines separately and does not reinterpret them as completed latency samples.

## Validation and rollback

The deterministic host tests must fail if target notification advances a sibling channel, if a
broadcast misses a channel, or if publication at either WFI race boundary permits sleeping. The RT
trace buffer tests verify sequence assignment and overflow accounting.

After host tests and clippy, the performance gate is the existing same-board campaign: at least five
AB/BA pairs with 10,000 samples per metric per run plus shared/partitioned soak. The report must
include P50/P95/P99/max, incomplete/dropped trace counts, migrations, thermal/frequency settings,
and console/device progress. If correctness regresses or tail latency does not improve, the change
is isolated to the runtime event channel and can be reverted without a config or data migration.
