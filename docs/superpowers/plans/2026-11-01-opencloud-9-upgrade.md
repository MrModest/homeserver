# OpenCloud 9 staged upgrade implementation plan

> **For agentic workers:** Use executing-plans to execute stages sequentially. Never advance past a failed verification gate.

**Goal:** Upgrade the existing deployment from 6.1.0 to 9.0.0, including installed web extensions, without losing users, files, shares, or integration settings.

**Architecture:** Deploy rolling versions 7.5.0, 8.1.0, then 9.0.0 using `ansible-playbook main.yml --tags opencloud`. Apply generated configuration diffs explicitly over SSH while the application is stopped. Preserve secrets and external Authentik configuration.

**Tech stack:** Ansible, Docker Compose, OpenCloud, ZFS, Authentik, Collabora, Radicale.

**Spec:** User-approved staged upgrade in this conversation, including remote preparation, playbook execution, and verification before each version bump.

## Global constraints

- Change only OpenCloud role files needed for compatibility and this operational record. Preserve unrelated Tududi edits.
- Keep Collabora 25.04.9.4.1 and Radicale 3.5.7 unchanged.
- Do not enable guest access, Yjs, or additional applications.
- Never print credentials or generated secret-bearing config patches.
- Keep the existing IDM database, user identifiers, and existing secrets intact.
- Retain rollback snapshots and old images. Do not prune Docker or delete old search/thumbnail caches.
- Root disk initially has about 4 GB free; check free space before pulls.
- Slow data lives on shared `slow` dataset. Snapshot it, but never roll back the entire dataset. Recovery must restore only OpenCloud's directory while its services are stopped.
- No commits, pushes, or unrelated deployments.

## Review focus

- Config diff must preserve all existing secrets and identity data.
- Migration must finish before testing shares and moving to the next stage.
- Authenticated reads and search must work, not merely HTTP landing pages.
- Existing Collabora, DAV, and extension integrations must remain reachable.
- Record limits of automated checks; do not claim interactive browser flows were verified without evidence.

### Task 1: Preflight and rollback

- [x] Verify SSH/sudo, running version, core service health, mounts, disk space, and pools.
- [x] Establish baseline HTTP/authenticated checks and inventory counts without logging personal data.
- [x] Verify rolling image tags 7.5.0, 8.1.0, 9.0.0 exist.
- [x] Pull required images before downtime; abort if insufficient space.
- [x] Stop OpenCloud and collaboration/Radicale writers. Back up Compose and configuration; create pre-stage ZFS snapshots for config, Compose, and slow data.

### Task 2: OpenCloud 7.5.0

**Modify:** `roles/deploy_opencloud/defaults/main.yml`.

- [x] Set app version to 7.5.0 and extensions to unzip 2.2.1, jsonviewer 2.1.0, drawio 2.2.0.
- [x] Run syntax validation and confirm the scoped task selection.
- [x] Run `opencloud init --diff` with mounted config and actual apps UID/GID; validate and apply patch without logging values.
- [x] Run tagged playbook; verify version, migration completion, core health, authenticated reads, shares, and integration endpoints.

### Task 3: OpenCloud 8.1.0

- [x] Snapshot verified 7.5.0 state with services stopped.
- [x] Set app version to 8.1.0; inspect/apply config migration if required.
- [x] Run scoped playbook and `opencloud search index --all-spaces --force-rescan --insecure`.
- [x] Confirm all-space indexing completion; verify authenticated search, reads, counts, service health, and integrations.

### Task 4: OpenCloud 9.0.0

- [x] Snapshot verified 8.1.0 state with services stopped.
- [x] Set app version to 9.0.0; inspect config diff and thumbnail settings. Apply only required migration while preserving existing secrets.
- [x] Run scoped playbook; verify version, core services, users/files/shares, search, thumbnails, extension assets, Collabora discovery, and Radicale routes.
- [x] Repeat playbook check for final configuration consistency, inspect final diff, and document evidence and limitations.

## Execution record

- 2026-11-01: Live 6.1.0 confirmed. Graph, proxy, search, and sharing health commands returned 0. Both pools healthy. OpenCloud data about 43 GB on shared slow dataset. Apps UID/GID 1003:1002.
- Version choice: 7.2.4 is not available in `opencloud-rolling`; use verified rolling tag 7.5.0. Use 8.1.0 rather than initial 8.0 release. All three selected rolling tags confirmed through registry manifests.
- Pre-7 checkpoint: config and Compose copied under `/mnt/pools/fast/apps-data/opencloud/upgrade-backups/20261101/pre7`; snapshots `oc-upgrade-20261101-pre7` on `fast/apps-data/opencloud`, `fast/docker`, and `slow`. Snapshot commands must run individually on this host.
- Config migration: invoke `opencloud init --diff --insecure=true` noninteractively to preserve existing insecure settings; default interactive mode loops without stdin. Generated candidate validation confirmed no changed existing values. OCDAV insecure setting moved to frontend; sharing service account and URL-signing secret added.
- Compatibility finding: 7.5 collaboration service requires writable `/var/lib/opencloud/collaboration` for fonts. Added dedicated bind mount and apps-owned host directory. Regression check failed before change and passed after. Re-running playbook restored bridge health with zero restarts.
- Stage 7.5.0 verified: sharing migration logged `Migration finished`; 3 users, 1 group, 6 drives and identity identifiers match baseline. Ten core services plus collaboration healthy. Collabora discovery/capabilities, CalDAV/CardDAV, and all three updated extension entry modules pass. Playbook failed=0. Baseline checks cover admin-visible root contents, not an interactive regular-user SSO session.
- Stage 8.1.0: no configuration diff required. `init --diff` leaves an old patch file behind when no differences exist; archive old patches before invoking it, and use `patch --forward` to prevent accidental reverse application. Guard against removed/changed existing config values caught this before any change.
- Reindex command returned SUCCESS for all 5 physical spaces; search logs recorded 5 `finished indexing space` events. Versioned `bleve-v5` created; old `bleve` retained.
- Functional WOPI test exposed an unreachable localhost data-server URL from the separate collaboration container. Added `STORAGE_USERS_HTTP_ADDR=0.0.0.0:9158` and `STORAGE_USERS_DATA_SERVER_URL=http://opencloud:9158/data` to OpenCloud. No host port published. Regression assertions failed before, passed after; tagged playbook failed=0.
- Stage 8.1.0 functional gate passed: temporary ODT upload/download, authenticated search, Collabora app/open, WOPI CheckFileInfo/download, proof-key-signed lock/save/unlock, and WebDAV content readback. Test file removed from active files afterward; trash/revisions may retain test artifacts.
- All 13,036 pre-upgrade storage files (45,741,235,433 bytes) still present with matching sizes against pre-7 snapshot. Twenty small-file SHA-256 samples match. This includes actual POSIX user/project files, not only decomposed metadata blobs.
- Regular-user browser SSO remains unverified. Configured vault login credentials did not authenticate via basic auth; no password or identity changes made. Automated authenticated functional checks use existing admin account.

- Stage 9.0.0 configuration migration added the auth-guest service account and removed obsolete thumbnail transfer/insecure settings. All remaining existing values unchanged. Guest links remain disabled.
- Stage 9.0.0 tagged playbook: ok=20, failed=0, unreachable=0. Initial app/open returned app-not-found during collaboration's registration interval; subsequent complete WOPI test passed without configuration changes. Ten core services plus collaboration healthy, four stack containers running with zero restarts.
- Stage 9.0.0 functional gate: WebDAV upload/download, authenticated search, Collabora open, proof-key-signed WOPI info/download/lock/save/unlock, and content readback all pass. A generated 400x300 PNG produced a 64x64 PNG thumbnail; repeat request returned identical cached image. Test files removed from active files, but small trash/revision artifacts remain.
- Final original-storage comparison: 13,036 files, 45,741,235,433 bytes, no missing files or changed sizes; 20 SHA-256 samples match original snapshot.
- Authentik discovery and signing-key endpoints reachable. OIDC client configuration matches baseline. Actual browser SSO, interactive extension behavior, and permission-specific sharing UI were not tested.
- Final `ansible-playbook main.yml --tags opencloud --check`: failed=0, unreachable=0. It reports seven planned changes from the role's existing recursive permissions and template/UID replacement flow; this is not an idempotence proof. Compose file SHA-256 matches the checked-in source. Existing undefined START_ADDITIONAL_SERVICES warning remains harmless and unchanged.
- Final `git diff --check` passed. Self-review only; no independent reviewer dispatched. Unrelated Tududi changes preserved. No commit or push performed.
- Root filesystem remains 97% used, about 3.3 GB free. No Docker pruning performed; old images and caches retained for rollback.

## Retained evidence

On the server, `/mnt/pools/fast/apps-data/opencloud/upgrade-backups/20261101/` is root-only and contains:

- `pre7`, `pre8`, `pre9`: configuration and Compose copies taken while writers were stopped.
- Private init logs and validated config candidates. These contain secrets and must not be committed or pasted into reports.
- `checks/verify.py`, `functional.py`, `thumbnails.py`, `data.py`: repeatable verification scripts. The functional and thumbnail checks create temporary files in the admin account and remove them afterward. Their deleted files/versions may remain in trash.
- `checks/state/`: private baseline and stage inventory records. The verifier also uses the original state directory at `/var/tmp/opencloud-upgrade-20261101`.
- `checks/final.log`: final retained verification run, including 9.0.0 service health, zero restarts, baseline identity comparison, extension versions, and original-storage checks.

Snapshot suffixes `oc-upgrade-20261101-pre7`, `oc-upgrade-20261101-pre8`, and `oc-upgrade-20261101-pre9` exist on each of `fast/apps-data/opencloud`, `fast/docker`, and `slow`.

These are local rollback checkpoints, not independent/off-host backups. Keep them until browser checks and normal usage are confirmed.

## Rollback safety

Do not restore an older image against already-migrated state without restoring its matching configuration and data.

1. Stop OpenCloud, collaboration, and Radicale. Identify the checkpoint to restore and account for any user writes since it was taken.
2. Preserve the current directories before restoring. Restore the selected checkpoint's config, extension apps, Compose files, and only OpenCloud's slow-storage directory. The source for slow files is `/mnt/pools/slow/.zfs/snapshot/<snapshot>/apps-data/opencloud/`.
3. Never use a pool-wide `zfs rollback slow@...`: it would revert unrelated application data. Likewise, do not roll back the shared `fast/docker` dataset. Restore the OpenCloud Compose directory only.
4. Restore the matching repository version pin and start the matching Compose stack. Repeat health, identity, file, search, DAV, and WOPI checks.
5. Obtain confirmation before discarding current state or removing retained snapshots. No rollback was needed during this upgrade.

## Post-upgrade browser CSP correction

The browser reported that silent token renewal was blocked by `frame-src`. The CSP template allowed Authentik in `connect-src`, but not in `frame-src`. Added only the configured Authentik origin to `frame-src`; no wildcard sources or changes to `frame-ancestors` were introduced.

A regression test in `tests/test_opencloud_csp.py` renders the actual template for two domains and checks that the external issuer is allowed for renewal frames. It failed before the fix and passed afterward. Run it with Ansible's Python environment:

```bash
/opt/homebrew/opt/ansible/libexec/bin/python -m unittest discover -s tests -v
```

The tagged playbook deployed the file with failed=0, but live response headers initially retained the old policy. OpenCloud loads this policy at startup; an explicit `docker restart -t 45 opencloud` activated the change. Future CSP template changes also require a restart; the role currently has no automatic reload handler.

Verified afterward:

- Live main page and silent-redirect page policies include the exact Authentik origin.
- A fresh, isolated headless Chrome session successfully loaded the silent authorization iframe and returned to OpenCloud's callback with `login_required`, as expected without an authenticated Authentik session. No frame-src violations occurred. This tests the browser CSP path, not a logged-in user's successful token refresh.
- Authentik's framing protections were unchanged. Its authorization endpoint redirects the unauthenticated `prompt=none` request back to the callback rather than rendering a login page in the iframe.
- Proxy, Graph, IDM, search, and collaboration health checks passed after restart.
- The reported profile-photo request returns HTTP 404 with `generalException` / `failed to get photo`. This is separate from login and does not itself establish an authentication failure. No profile photo was changed or removed. An expected existing avatar would require separate investigation.
