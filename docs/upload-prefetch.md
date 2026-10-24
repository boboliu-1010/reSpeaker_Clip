# Optional SD upload prefetch experiment

This experiment preserves the complete recording application, DTLS protocol,
server verification, upload window and existing synchronous read path. It is
disabled in the ordinary `dtls-optimized` preset and disabled at runtime after
every reboot. Build it with the preset plus both app-only overlays:

```
--extra-conf applications/clip/dtls-prepare-profile.conf
--extra-conf applications/clip/dtls-prefetch-profile.conf
```

Use the existing diagnostic resource configuration, including thread stack
information and stack initialization. The implementation uses the SDK's dynamic
thread/stack support. It requires an 8 KiB DATA cache; larger or smaller cache
settings do not enable this producer. Files at most 8 KiB use synchronous reads.

## Ownership and lifetime

The upload worker keeps the current 8 KiB block. A temporary producer owns one
additional 8 KiB block, a 4 KiB heap stack, its thread object and a separate
read-only file handle. It reads the next sequential block while the uploader
encrypts/sends the current one. A request/ready semaphore pair transfers buffer
ownership. Swapping buffers avoids copying an entire block between them.

The synchronous uploader handle remains independent: retransmission/random
reads cannot move the producer's file position. Unrelated requests can use the
synchronous fallback, and completed stale prefetches can be discarded/replanned.
Optional allocation/open/read failure retains the mandatory synchronous path;
the final server SHA-256 check remains required. Inspect the diagnostic errors
before interpreting a trial as an active prefetch trial.

Cancellation stops requesting work, lets any in-progress filesystem call finish
and joins the producer before closing its handle or freeing either owned block.
The worker never aborts a thread inside FatFS. Only then may recording resume or
the next file be prepared. Close/join failures propagate through upload cleanup
rather than permitting an unverified recording handoff. There is no persistent
background reader and no thread while idle or recording.

## USB controls

All settings are RAM-only. Setting changes require upload/recording handoff idle.

| Command | Meaning |
|---|---|
| `AT+UPLOADNET=prefetch` | Read current configuration and last completed file counters; allowed while the next file uploads |
| `AT+UPLOADNET=prefetch,off` | Disable for subsequent files |
| `AT+UPLOADNET=prefetch,on` | Enable using the currently selected priority, initially 8 |
| `AT+UPLOADNET=prefetch,6` | Enable with producer priority 6 |
| `AT+UPLOADNET=prefetch,7` | Enable with producer priority 7 |
| `AT+UPLOADNET=prefetch,8` | Enable with producer priority 8 |

The uploader has priority 7; smaller numbers preempt it. Priority 8 provides a
low-priority control, not an assumption of optimal overlap. Equal-priority
threads also depend on the scheduler time slice. Priority 6 can start the next
SD request immediately and then let the uploader run while the SD driver waits.
Use same-image, interleaved trials to determine the actual effect.

`enabled` and `priority` report the current configuration; the remaining fields
describe the last completed file. Match stable `UPLOADNET?` statistics, timing
and completed phase events to collect each file. Missing snapshots invalidate
an aggregate comparison. Microseconds are emitted as bounded 32-bit integers,
with `saturated` indicating overflow; this avoids unsupported `%llu` formatting
in the target libc. Internal totals retain 64-bit precision.

## Interpreting measurements

`read_us` is background SD-call wall time; `wait_us` is the explicit wait on the
ready semaphore, after dispatching a request. It excludes producer preemption
during request dispatch. They overlap with other work and must not be added to
DATA time. Existing DATA source counters measure the worker's full callback
critical path, including preemption, waits and synchronous fallback. Encryption/UDP wall-time counters
also include time when a higher-priority producer preempts the upload worker;
they do not isolate the algorithm's CPU cost.

Count the extra thread object, file/FatFS state and allocator overhead as well
as the nominal 8 KiB block and 4 KiB stack. Record sampled minimum free heap,
stack peak, CPU utilization, retransmissions, DATA time, complete task time and
server hashes. Heap peak is cumulative since boot. Include slow/negative trials;
less SD waiting alone does not establish higher end-to-end throughput.

Host tests execute the actual producer and datagram reader with pthread-backed
semaphores, sanitizers and adversarial reads: sequential/tail reads, partial
reads, retransmissions, allocation/open/read errors, cancellation during blocked
I/O, join/close failures, buffer ownership and query saturation. Device acceptance
also requires complete-file hashes, safe recording interruption/resume and
bounded resource use. These tests do not establish physical battery power-loss
recovery, prolonged weak-network reliability or energy consumption.
