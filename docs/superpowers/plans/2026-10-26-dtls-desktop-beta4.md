# Boa Voice DTLS Desktop Beta 4 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a macOS Beta with BLE provisioning/upload status and a unified user-isolated audio service accepting App HTTPS and Clip DTLS uploads.

**Architecture:** Keep the pinned firmware/receiver modules unchanged at a2319ce. Add services/boa_server as the single service with HTTPS and UDP listeners, per-user existing audio storage, immutable device binding namespaces, and a durable file index. Reuse the Flutter desktop library/recorder and add provisioning, events and unified file listing.

**Tech Stack:** Python/FastAPI/SQLite/pyOpenSSL; Flutter/Dart/macOS.

**Spec:** docs/product/boa-voice-overview.md and docs/contracts/roger-base-extension-v1.md, updated to the verified DTLS v3 and encrypted BLE commands in feature/dtls-upload-core-0.1.2.

## Global Constraints

- One Boa Server; App HTTPS, Clip DTLS/UDP, App-to-Clip encrypted BLE.
- Keep applications/clip and tools/https_poc identical to a2319ce.
- Two roles: user and developer. Developer provisions credentials through CLI. Each user sees only their own audio.
- Preserve desktop recording/playback/import/automatic upload/download and legacy server compatibility.
- No embedded credentials, TLS bypass, release publication or device flashing.
- Build 1.0.1-beta.4+4; local DMG and installation validation.

## Review Focus

- Cross-user access through metadata/content/HEAD/Range/upload IDs must fail.
- Interrupted Clip receive/index update must recover without duplicate or misowned files.
- BLE commands must fit a single negotiated GATT write; credentials must not enter logs/errors.
- Wi-Fi check/received progress must not be displayed as end-to-end upload completion.
- Changing server identity must not resume another user's upload/backup session.

### Task 1: DTLS foundation and service

Files: add services/boa_server/{registry.py,receiver.py,app.py,run.py,manage.py,tests/test_service.py,README.md,requirements.txt}.
Interfaces: create_app(root), Registry.register_user/register_device, file list GET /api/boa/v1/audio-files; existing /api/audio APIs scoped to user; DTLS v3 OPEN/DATA/COMPLETE unchanged.
- [ ] Add failing tests for per-user upload/list/content/HEAD/Range, device credentials, raw completion, duplicate, restart, binding namespaces and missing/invalid token.
- [ ] Implement private registry and per-user audio service adapter; receiving/ready index and reconciliation; DTLS session/receiver subclass using the base writer.
- [ ] Add single lifecycle HTTPS + DTLS launcher, controlled CLI enrollment, source pin and deployment instructions.
- [ ] Run new tests plus existing audio storage tests; commit service.

### Task 2: Desktop device and file integration

Files: desktop/clip_upload_protocol.dart, desktop/clip_upload_panel.dart, desktop_clip_page.dart, clip_protocol.dart, storage_client.dart, desktop_page.dart, server_config.dart; relevant tests.
Interfaces: BLE AT provisioning (NETCFG/UPLOADCFG/NETCHECK/UPLOADAUTO/UPLOAD?/UPLOADCANCEL), upload/wifi_check events; HTTPS file list with legacy fallback and raw file export.
- [ ] Add failing protocol/ownership cache/list fallback/CA trust tests.
- [ ] Add validated commands, redacted errors, GATT byte-limit check, events/progress/resync, supported recording buttons.
- [ ] Add unified file list/source display/raw export and optional custom CA import with full TLS verification; bind upload/backup cache to credentials.
- [ ] Run desktop/client tests and targeted static analysis; commit App.

### Task 3: End-to-end and packaging

Files: update docs/product/boa-voice-overview.md, docs/contracts/roger-base-extension-v1.md, README-desktop.md, release notes, packaging metadata/scripts.
- [ ] Run real HTTP upload/download/Range/SHA and user isolation against the running service and DTLS integration on a capable runtime; verify recovery.
- [ ] Build macOS release, verify portable libraries and signatures, launch local app, package/verify DMG, copy App from mounted DMG and launch it.
- [ ] Record exact checks and hardware limitations, obtain one fresh whole-branch review, fix material findings with regression tests, deliver local installer.
