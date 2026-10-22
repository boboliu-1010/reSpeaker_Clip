# Boa desktop and HTTPS experiment integration plan

> **For agentic workers:** Use superpowers:executing-plans inline for this migration. Preserve existing code; do not implement the future ingest/AI bridge.

**Goal:** Create `boa/desktop-https-integration` from HTTPS experiment `cfff60539d94c6d3e43f788592b97a76547278fe`, transplant the fixed Boa desktop/audio-storage code from `c69830b`, and verify both sets still work independently.

**Architecture:** Replay only the desktop-line commits after `95db10b`, preserving the experimental firmware/receiver subtree. The branch contains both implementations; raw Clip uploads still do not automatically appear in the Boa audio library. Future bridge implementation remains separately reviewed scope.

**Tech Stack:** Git, Flutter/Dart, macOS/Xcode, Python/FastAPI and standard-library HTTPS receiver.

**Spec:** Human request: new `boa` integration branch, fixed desktop/Server onto experimental firmware, retain functionality, no release. Existing design reference after transplant: `docs/contracts/clip-ingest-app-server-bridge.md`; its runtime implementation is explicitly excluded here.

## Global Constraints

- Retain original branches/checkouts, installed app, user recordings, credentials and existing server processes.
- No firmware flash, dependency upgrades, DMG, GitHub Release, tag or deployment.
- Desktop remains `1.0.1-beta.3+3`; preserve its pinned portable FFmpeg dependency and sandbox settings.
- Firmware/HTTPS receiver code remains identical to cfff605 unless an integration failure proves a required fix.
- Import source commits with provenance; do not merge the unrelated main/release firmware over the experiment.
- Use isolated temporary data and localhost endpoints for verification. No existing device/private server credentials.

## Review Focus

- Desktop/native dependency regressions: verify portable FFmpeg and macOS debug build, not merely Dart tests.
- Accidental firmware overwrite: compare experimental firmware/receiver Git trees exactly after transplant.
- Conflicting ignore/config/docs rules: preserve both experimental tooling and desktop paths; list runtime boundaries clearly.
- HTTP content corruption/recovery: run real upload/download/Range/hash verification on isolated storage.
- Unrelated mobile smoke baseline failures: run the full app suite and name any pre-existing failure; do not call targeted desktop checks a fully green mobile suite.

## Task 1: Establish experimental baseline and transplant preserved commits

**Files:** Existing desktop `mobile/app`, SDK BLE fix, `services/audio_storage`, desktop scripts/config/docs; experimental firmware and `tools/https_poc` preserved.

**Interfaces:** Consumes cfff605 and source desktop c69830b; produces a single branch with both independent sets of entry points.

- [ ] Run HTTPS host baseline `python3 -m unittest discover -s tools/https_poc -p 'test_*.py'`; expect 90 run, 89 pass, 1 missing SDK-fixture skip, with known disconnect-test diagnostic output.
- [ ] Cherry-pick -x the ordered desktop commits `1c75058` through `c69830b` excluding main firmware ancestry; resolve only additive integration conflicts.
- [ ] Compare imported desktop/client/Server trees with source and firmware/receiver trees with cfff605; expect exact runtime subtree preservation.
- [ ] Run targeted desktop/storage regressions after dependency resolution; expect green.

## Task 2: Verify preserved behavior and document runnable integration boundary

**Files:** New integration README, verification record; corrections only when checks expose integration failures.

**Interfaces:** Consumes Task 1 branch; produces reproducible start commands and evidence with no claim that the future bridge is implemented.

- [ ] Run Python storage tests and full HTTPS host suite; run Flutter desktop/storage tests and the full app suite; record exact counts, skips and failures.
- [ ] Run isolated live storage upload/download/Range/checksum and Dart client checks with generated audio; no persistent user-data modifications.
- [ ] Build macOS debug desktop target and run native bundle checks; no install or launch of the app.
- [ ] Document separate desktop, storage service and experimental receiver entry points, pinned baselines, unsupported bridge, no-release state and actual verification limits.

## Task 3: Review and retain integration branch

**Files:** Branch documentation/verification and any minimal regression fixes.

**Interfaces:** Consumes reviewed tree and test outputs; produces a clean committed local branch.

- [ ] Fresh whole-branch review checks preservation, dependencies, startup docs and unimplemented-bridge boundary.
- [ ] Resolve material integration findings with a reproducing test before fixes; defer minor observations explicitly.
- [ ] Confirm experiment ancestry, clean worktree and unchanged original desktop branch; do not publish or rewrite existing remote branches.
