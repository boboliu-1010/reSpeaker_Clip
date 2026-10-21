# Desktop Beta 3 Implementation Plan

> For agentic workers: use superpowers:executing-plans inline; complete the approved scope without repeated approval requests.

**Goal:** Complete daily recording, local file management, explicit upload tasks and readable Clip status in the macOS app.
**Architecture:** Extend existing LocalLibrary/BackupQueue with compatible metadata and recoverable operations; split reusable dialogs/status models out of DesktopPage. Reuse record, FFprobeKit, file_picker and existing BLE SDK. Keep the HTTP server protocol unchanged.
**Tech Stack:** Flutter/Dart, macOS CocoaPods, record, just_audio, FFmpegKit 4.6.2, existing HTTP client.
**Spec:** docs/product/desktop-beta3-review.md (four-group scope approved in chat).

## Global Constraints

Preserve existing audio/configuration; no permanent deletion; retain sandbox; no secret logging; no new firmware commands. Export streaming, read/write selected-file entitlement. Version 1.0.1-beta.3+3. No upload before local installation acceptance.

## Review Focus

- Rename/trash/restore preserve bytes, time and source; invalid names and duplicate restore are handled without loss.
- Automatic off allows exactly explicit manual jobs; retry does not reset unrelated jobs or send to a different destination.
- Recording save cancellation/interruption retains staging data and exposes recovery; missing microphone selection falls back clearly.
- Missing/false firmware fields remain unknown; command success still requires ok=true.
- New UI fits the desktop minimum size; export/microphone/native dependencies are checked in the actual installed release app.

## Tasks

- [x] 1. Extend library metadata/rename/export/trash/restore. First write real-file tests and observe failure; implement and verify compatibility. Files: local_library.dart, local_library_management_test.dart.
- [x] 2. Add explicit manual jobs, per-item retry, progress/errors and removal guard. First write queue-policy/restart tests; update backup_queue.dart and retain previous tests.
- [x] 3. Integrate details/actions/trash and synchronization views, input selection/electric level/save/recovery, readable Clip status. Test firmware parser and helper behavior; use existing packages. Files: desktop_page.dart, desktop_clip_page.dart plus focused dialogs/helpers; macOS entitlements read-write.
- [x] 4. Run scoped tests/analysis and native regression audit; build Beta 3, package new DMG, install and operate recording/file/sync UI. Record evidence and hardware limits, request user installation acceptance before publication.

## Ledger

- Scope: user approved all four groups, inline execution.
- Ruling: local rename does not mutate the immutable server file name; remote deletion is outside this round because the current storage protocol has no completed-file deletion API.
- Ruling: keep recoverable local trash without a purge command; preserve staging data when saving is cancelled or fails.

- Task 1: complete. Real-file library/presence tests 7 passed, bytes and metadata preservation verified.
- Task 2: complete. Queue/restart/manual policy tests 4 passed.
- Task 3: parser and recording recovery tests RED to GREEN, 4 passed. RecordConfig uses `device` (installed API); no new dependency.
- Ruling: do not start startup uploads before successful remote inventory, to avoid resetting completed jobs on stale empty inventory.

- Final review: fixed three Important findings (private-directory export overwrite; historical manual authorization inherited by automatic reconciliation; startup worker readiness before inventory). Added real-file and complete job lifecycle regressions, RED to GREEN.
- Native diagnosis: recorder creation completed; macOS permission callback remained pending. Kept explicit-only lazy microphone initialization, added non-prompt refresh and bounded permission wait. Removed temporary tracing from desktop_main.dart.
- Second review: fixed recorder identity capture in timeout callback and input/record mutual exclusion; widget regression reproduced enabled refresh during pending record authorization, then both directions passed. Scoped analysis now clean.
- Baseline test limitation: test/widget_test.dart unchanged from 54d6158; mobile smoke lacks ProviderScope and fails independently of the desktop entry point. Keep this failure explicit in acceptance report.

- Task 4: automated checks and final local DMG/install completed; 31 Flutter tests pass, unchanged mobile smoke fails; desktop analysis clean and native scanner 2 pass. Installed native audit: 45 Mach-O, zero external dependency errors.
- Task 4: BLOCKED UI continuation: CUA reports Mac locked. Requested user manual unlock; final payload launch, recovery UI and microphone acceptance remain pending. No push/publication.

- Task 4 resumed: user unlocked and confirmed microphone permission action. Final installed payload launched/restarted; actual mic recording/electric level/pause/resume/cancel then restart/recovery/playback passed; exact bytes/hash/source preserved. Device enumeration 2 inputs and explicit MacBook mic recording/save passed.
- Task 4 local acceptance: complete within the four-group scope. Known unchanged mobile smoke failure and real Clip hardware limit remain explicit. No publication; new user workflow is direct Flutter local development, DMG only for delivery after readiness.
