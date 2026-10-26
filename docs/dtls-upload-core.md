# DTLS recording upload core

This opt-in full-application build replaces the recording upload transport with
DTLS 1.2 over UDP. Audio, buttons, display and BLE remain in the application.
It is separate from `experiment/upload-bench-0.1.2`, which intentionally removes
product features for transport experiments.

## Scope

The performance path is SD → bounded read cache → 1 KiB application packets →
one DTLS connection → receiver file. Upload jobs acquire the existing 128 MHz
CPU boost and release it during cleanup. The connection is reused across files.

The base overlay starts with16 packets and grows to64. The measured candidate
starts at128 with a128-packet ceiling. These are logical outstanding packets:
RAM holds128 retransmission records, not128KiB of file data. Missing payload is reread from SD. Selective receipts
permit continuous sending without waiting for an HTTP response per chunk.
Loss reduces the congestion window; adaptive retransmission starts at a minimum
of 1 second and backs off to at most 8 seconds.

This iteration retains the existing configuration format, automatic queue and
recording priority. Production defaults to whole-session deletion after upload
confirmation (see below). Charging policy, periodic reconciliation and App/cloud
UI integration remain outside this firmware feature. The broader deferred implementation is saved
on `archive/dtls-auto-upload-wip-0.1.2`.

## Automatic deletion after upload

`CONFIG_CLIP_UPLOAD_AUTODELETE` defaults on with the baseline production
configuration (UART logging off), and off in the default diagnostic build. It
can be disabled explicitly at build time. No App code is changed.

A successful COMPLETE response, successful file close and durable upload journal
save nominate only that recording session. The uploader scans its canonical
sealed segments and requires all expected contiguous segment numbers, matching
session count/bytes, and valid complete journals bound to the current receiver.
It never deletes a partial recording or sweeps unrelated historical uploaded
sessions merely because their old journals say uploaded.

A CRC-protected deletion intent is synced and closed before moving the whole
session from REC into `/SD:/UPDEL/<session>`. This avoids exposing missing middle
segments in the device recording list. Physical removal checks recording-priority
cancellation between operations; interrupted cleanup resumes from valid staged
intents during later automatic scheduling. A failed move can be retried using
its intent in REC. Invalid or corrupt staged intents retain data for inspection.
The last-marker/empty-directory case is also recoverable. These are software
recovery guarantees, not guarantees against FAT media corruption or arbitrary
power loss during filesystem metadata writes.

`UPLOAD?` and BLE upload events add `delete_after_upload` and `delete_error`.
`session_deleted` reports completed cleanup; `session_delete_failed` reports a
separate cleanup error, without changing successful file-upload status. Whole
session deletion removes its audio and sidecars; its old local LIST/UPLOADSTATE
entries are gone. The server copy remains, and cloud listing/playback needs App
and server integration. The feature does not implement periodic reconciliation
or protect against the server losing data after acknowledging durable completion.

## Receipts and recovery

Each transfer opens with device credentials, recording session/segment, length,
SHA256 and a random transfer nonce, inside a certificate-verified DTLS channel.
The server returns its durable offset. A new connection resumes there.

Receipts distinguish received contiguous bytes, selective future packets, and
bytes durably checkpointed to disk. Received credit frees the sending window;
it never marks a recording uploaded. The server syncs file data before atomically
publishing a checkpoint, after 64 KiB or 500 ms of contiguous progress. QUERY
forces a checkpoint. A crash may require retransmitting the volatile tail.

The server verifies the entire file SHA256 and publishes the final file before
sending COMPLETE. Only a valid identity-bound COMPLETE marks the local A/B
upload record stored. Duplicate completion queries are idempotent. Recording
cancellation closes the session; a later attempt asks the server for its offset.

## Build and operate

Use `--preset dtls-single --production` for the maintained configuration:80KiB application
heap, direct DTLS over UDP, hardware GCM,128-packet window and8KiB synchronous
read-ahead. Files upload serially over one reused DTLS connection. The active
source no longer contains the dual-channel, file-multiplexing or asynchronous
SD producer experiments; their source and results remain in local archives.
Recording hash caches, final server SHA256 verification, cancellation/resume,
automatic queueing and completed DATA timing snapshots remain supported.

An App may provision and persist the Station Wi-Fi over the encrypted BLE
command characteristic with `AT+NETCFG=ssid,password`. A successful BLE reply
contains `data.saved:true`; boot restores the same record automatically. The
receiver enrollment is also available over encrypted BLE with `CLIP_UPLOAD_APP`. BLE `NETCHECK` validates association/DHCP;
`UPLOADAUTO` persists the automatic-upload switch and `UPLOAD?` queries progress.
The existing response characteristic publishes throttled status and terminal
events without sending BLE messages from the DATA loop. See the
[BLE provisioning contract](protocol.md#station-wi-fi-provisioning-in-the-upload-build).

The helper selects `applications/clip/dtls.conf` when the ordered overlays
enable `CLIP_DTLS_UPLOAD`. DTLS uses direct mbedTLS over UDP: TCP and Zephyr's
TLS socket wrapper are disabled. Certificate verification, DTLS encryption,
Wi-Fi crypto and time synchronization remain enabled. HTTPS-only builds keep
`https.conf`. The optimized DTLS preset no longer includes the TCP connection
budget overlay. Its network recovery overlay enables DHCP remembered-lease
reuse with the pinned DHCP fixes and retains the ARP fixes; one unanswered
INIT-REBOOT probe falls back to discovery. Combined hardware recovery validation
is still required; see [network backports](network-backports-0.1.2.md).
Transport cleanup leaves TLS buffers unchanged; `dtls-single`
explicitly reserves an80KiB heap.
The maintained preset restores baseline HT receive STBC
(`CONFIG_NRF_WIFI_RX_STBC_HT=y`) and no longer includes the historical
`https-wifi-no-stbc.conf` comparison overlay. Station power policy remains
unchanged. This enables reception capability, not a measured throughput gain;
AP support and negotiated use still determine whether STBC is used on the link.

For the maintained configuration, run the helper with `--preset dtls-single --production`:

```sh
python tools/https_poc/build.py \
  --ncs /path/to/ncs --sdk /path/to/zephyr-sdk \
  --build /path/to/ncs/build-clip-dtls-candidate \
  --ca /path/to/public-test-ca.pem --preset dtls-single --production
```

There are only two build modes, matching the baseline. Without `--production`,
the helper uses the default build with UART logging, developer interfaces and
preset diagnostics. With `--production`, it uses the existing `production`
snippet, closes UART logging and defaults developer interfaces off; preset
diagnostics are omitted. `dtls-single` selects the upload feature set, not a
third build mode; `dtls-optimized` remains its compatibility alias. Direct west
builds also derive the developer-interface default from `LOG_BACKEND_UART`,
just as the baseline does for the SD-log default. No app-only Kconfig symbols
are added to the shared production snippet. Functional ARP fixes remain enabled
independently of diagnostics. Both modes retain the full recording application. It enables CryptoCell AEAD, initial/maximum
windows128/128, and8192-byte DATA read-ahead on every boot. Hashing retains its
4KiB buffer; DATA allocates an additional8KiB per file and frees it on all
transfer exits. The window/cache defaults also work with timing disabled.
The SDK groups CCM and GCM under its AEAD switch; other PSA driver categories
remain software-backed. This is a candidate for reliability validation, not
a release approval. Use `dtls-profile.conf` only with the pinned SDK: its build-local
TLS timing copy fails closed on source hash changes and never edits the SDK.

Switching between the baseline default and production modes changes
`BT_KEYS_OVERWRITE_OLDEST`. The pinned SDK includes that option in its stored
bond configuration flags and rejects records from the other configuration.
Re-pair the phone/Mac after switching modes; remove a stale host-side bond if
the host reports that the peer removed pairing information. This differs from
rebooting within the same mode, where the saved bond should be restored.

For the original baseline, use the helper without a preset, adding
`applications/clip/dtls-upload.conf` to the established runtime/network overlays.
Do not pass `--upload-only`. The overlay reserves TX 24 KiB, RX 4 KiB, heap
72 KiB and a 64-packet logical window. These are allocations, not measured peak
RAM use. The DTLS worker stack reservation is 12 KiB.

Run `tools/https_poc/dtls_upload_server.py --help` for the receiver command.
It requires pyOpenSSL with public DTLS APIs, the existing certificate root and
a private JSON mapping device IDs to tokens. Use a dedicated data directory:
the DTLS receiver must not share it with HTTP writers. A process lock enforces
one DTLS writer. The receiver has bounded concurrent peer workers and one authenticated writer
owner per device. New authenticated sessions hand over the previous writer
before loading durable progress; use the matching receiver code for persistent
service validation.
Opening TCP 9527 alone is insufficient; the service needs UDP 9527.

Encrypted BLE and USB configure Wi-Fi, receiver credentials, `AT+TIME` and automatic
upload. With developer interfaces enabled, USB `AT+UPLOADNET?` adds read-only statistics for the last DTLS file:
elapsed time, packets, retransmissions, receipts, received/durable progress,
resume offset, RTT, RTO and final window. `AT+UPLOAD?` reports protocol 3.
Both time validity and CA/host verification remain mandatory.

## Validation and performance evidence

Run the host suite from the repository root:

```sh
python -m unittest discover -s tools/https_poc -p 'test_*.py'
```

`test_upload_window.py` runs the actual C window core under sanitizers.
`test_dtls_uploader_c.py` runs the actual C sender against the Python session,
with a mock TLS boundary, to test packet loss, lost COMPLETE, cancellation and
resume. This test does not validate cryptography. Receiver tests inject storage
failures and verify publication and checkpoint rules. Batch tests exercise
both HTTPS and DTLS variants and verify cleanup before recording can proceed.

Host tests and compilation do not establish device throughput. For the first
hardware comparison, keep CPU, network, server, recording bytes and timing
boundaries fixed, and disable automatic upload during manual trials. Record
transfer-only and whole-job rates separately, plus retransmissions, RTT, window,
resume offset, runtime memory and final SHA256. Repeat the same file at least
three times; retain every result, including regressions. Add loss/reconnect
checks after establishing the main throughput result. Do not infer achievable
uplink from the earlier UDP RAM downlink benchmark.

## Measured candidate and diagnostic controls

The candidate was selected by controlled real-device experiments on a574179-byte
recording. Hardware GCM reduced measured encryption-call wall time from about
1.425s to0.125s. A128/128 window produced312.9–315.7KiB/s in three
window trials, with correct final SHA256 and no protocol retransmission.
With8KiB DATA read-ahead, six trials produced329.1–339.4KiB/s, all
with correct SHA256 and no protocol retransmission. Final confirmation averaged
335.23KiB/s for DATA only; connection and handshake time are excluded.

The cache matrix retains all results, including a16KiB trial with eight
retransmissions and slow4KiB trials without retransmissions.16KiB did not
improve the normal end-to-end DATA rate enough over8KiB to justify doubling
the additional cache. These samples do not establish long-run or weak-network
reliability. Raw records, ELF/map files and rollback images stay in the local
firmware version directories, not in Git.

When `CONFIG_CLIP_DEBUG_INTERFACES=y` and `CONFIG_CLIP_DTLS_PROFILE=y`,
the following USB performance controls are RAM-only and
reject SET while an upload or recording handoff is pending. The read-only
`timing` snapshot remains available during the next file's upload:

- `AT+UPLOADNET=timing`: read the last completed DATA-phase timing snapshot.
- `AT+UPLOADNET=window`: read initial and maximum packet counts.
- `AT+UPLOADNET=window,128,128`: change the next-file window, within16≤initial≤max≤128.
- `AT+UPLOADNET=cache`: read the DATA read-ahead size.
- `AT+UPLOADNET=cache,8`: choose4,8 or16KiB for the next file.

These controls do not persist; reboot restores the build defaults. The base
overlay restores16/64 and4KiB; the optimized preset restores128/128 and8KiB.
The existing `AT+UPLOADNET?` response is unchanged. Timing is buffered in RAM
without per-packet printing. The snapshot describes the last completed file,
not the file currently being sent. A collector should correlate stable statistics
and timing with completed DATA events and verify that every file was observed.
SD read/seek values are nested under source time;
window-full poll time is nested under poll time. Do not add nested values twice
or treat these wall-time counters as isolated CPU time.

Next acceptance focuses on a persistent receiver, repeated and batch uploads,
recording interruption/resume, controlled loss/disconnect, server restart and
real device power loss. Prior performance tests used fresh receiver instances
per trial, so they do not satisfy that acceptance. The earlier intermittent
Wi-Fi authentication failure remains unresolved.
