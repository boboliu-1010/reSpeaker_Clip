# Boa development server deployment plan

> **For agentic workers:** Use superpowers:executing-plans inline. This is deployment of existing server code, not a new API implementation.

**Goal:** Deploy the current integration audio Server to `bobo@100.58.19.213` and verify actual remote HTTP audio behavior.

**Architecture:** Versioned source archive under `/home/bobo/apps/boa-voice/releases`, independent Python venv and persistent data, user systemd unit, localhost HTTP exposed to this Mac by SSH forwarding. Preserve existing services; no firmware, App installer or AI deployment.

**Tech Stack:** Ubuntu 24.04, Python 3.12, pinned FastAPI dependencies, systemd user service, SSH.

**Spec:** User explicitly designated this machine as development server and authorized deployment/testing.

## Global Constraints

- Work on existing isolated `boa/desktop-https-integration` worktree; do not change App or firmware runtime.
- No sudo-dependent global changes; user linger is enabled for persistence.
- Existing service on 9527 untouched; audio service binds `127.0.0.1:18765` only.
- Secrets outside Git, mode 0600, never printed; persistent audio separate from releases.
- No GitHub Release, DMG, firmware flash, public endpoint or production-readiness claim.

## Review Focus

- Code identity: deployed files must match fixed commit hashes; archive excludes local data and credentials.
- Lifecycle: check enabled/active unit, linger, restart persistence, and SSH disconnect survival; reboot is not performed.
- Network: localhost binding, unauthenticated requests return 401, SSH tunnel fails rather than hijacking occupied ports.
- Content: actual remote upload/Range/download hashes, multi-format decode and large file, not only health checks.
- Scope/data: test data distinguishable, no deletion of user audio; future raw ingest and AI remain unimplemented.

## Task 1: Deploy preserved Server as user service

**Files:** `deploy/systemd/boa-audio-storage.service`, deployment runbook, this plan. Existing `services/audio_storage` unchanged.

**Interfaces:** Existing run.py CLI and pinned requirements consume versioned source; produces persistent localhost service and local SSH-forwarded endpoint.

- [x] Commit unit/runbook; validate CLI paths and source revision before upload.
- [x] Transfer only Git-tracked Server via archive, establish user venv with verified bootstrap if pip absent, install pinned dependencies and run Server tests on Linux.
- [x] Verify systemd unit, start/enable it, check localhost bind, token permissions, process revision, linger and unauthorized response.

## Task 2: Exercise remote behavior and retain development environment

**Files:** Verification report/runbook and temporary test harness; no new App/Server API.

**Interfaces:** Task 1 remote service and SSH tunnel consumed by HTTP and Dart clients.

- [x] Attempted private SSH forward and copied token privately; SSH administratively prohibits forwarding. Replaced cross-machine test with server-internal client tests per ledger ruling; administrator decision pending.
- [x] Upload generated audio including 101 MiB and 1 GiB, validate resume/idempotency/hash/Range and local/HTTP decode on the deployed server; restart and verify persistence.
- [x] Verify existing Dart storage client and backup queue against the remote service using isolated test paths.
- [x] Fresh read-only deployment review, document evidence/limits and repeat code identity/active service checks. Preserve local branch and remote service, no publication.
