# Deploy Hermes Notes to homelab — design

## Background

`hermes-notes` is a working 2-container Docker Compose stack (Hermes Agent +
Hatchdoor, talking over HTTP MCP) currently running ad hoc on Kamil's
MacBook, fully E2E-verified there (Telegram → Hermes → Hatchdoor → note
committed and pushed to the `knowledge-vault` GitHub repo). This spec covers
deploying the same stack via this repo's existing Ansible IaC, as a new
role following the established `deploy_*` conventions.

Source repo: `/Users/me/Projects/hermes-notes` (GitHub
`MrModest/hermes-notes`, `main`, `405a020`). Full context captured in
`/tmp/hermes-notes-to-homelab-handoff-2026-07-19.md`.

## Role

New role: `roles/deploy_hermes_notes/`, variable prefix `hnts_`, tag
`hermes_notes`. Single role for both containers — matches the existing
pattern for multi-container single-purpose stacks (`deploy_paperless`,
`deploy_hoarder`), not a git-clone-the-app-repo approach. One ZFS dataset:
`fast/apps-data/hermes_notes`.

### Files vendored into the role

- `files/compose.yml` — the two services (see Networking below for the one
  change vs. the Mac version).
- `files/config.yaml`, `files/SOUL.md`, `files/memories/MEMORY.md`,
  `files/memories/USER.md` — copied verbatim from
  `hermes-notes/data/hermes/` (the narrowed single-purpose config/persona/
  memory, already committed and stable there).
- `templates/.env.j2` — secrets templated in from vault vars; static
  (non-secret) values templated from role defaults.

### Directory layout on the host

```
{{ p_dirs.apps_data }}/hermes_notes/
  hermes/                       # bind-mounted to hermes:/opt/data, apps-owned
    config.yaml
    SOUL.md
    memories/MEMORY.md
    memories/USER.md
    .no-bundled-skills          # empty marker file, written before first boot
  hatchdoor/
    knowledge-vault/            # git clone of MrModest/knowledge-vault, 65532:65532
    cache/                      # empty, regenerates at runtime, 65532:65532
```

### Task order (must not be reordered)

1. Create ZFS dataset `fast/apps-data/hermes_notes` (state: present).
2. Create `hermes/` dir (apps-owned). Copy `config.yaml`, `SOUL.md`,
   `memories/*.md` into it. Write an empty `.no-bundled-skills` marker file
   into it.
   - Per Kamil's call: the marker alone, present before the container's
     first startup, is sufficient to stop the bundled-skills sync from
     seeding the default 72 skills. No `hermes skills opt-out` command
     needed. (Re-adding the one wanted skill, `note-taking/obsidian`, is a
     manual follow-up post-deploy — not automated by this role; see Out of
     scope.)
3. `git clone` `https://{{ hnts_github_username }}:{{ hnts_github_pat }}@github.com/MrModest/knowledge-vault.git`
   into `hatchdoor/knowledge-vault/` (`no_log: true` on this task — the URL
   contains the PAT). Create `hatchdoor/cache/` empty.
4. `chown -R 65532:65532` both `hatchdoor/` subdirectories (distroless
   nonroot UID, confirmed via `docker inspect` in the prior session).
5. Import the shared `tasks/compose_up.yml` with `t_app_name: hermes_notes`
   and `t_app_data_dirs: []` (directories are already created with correct,
   deliberately-different ownership by steps 2–4; passing an empty list
   here means compose_up's own directory loop has nothing to do and won't
   touch anything). This step uploads `compose.yml` + templates `.env`,
   then runs `docker compose up -d`.

Rationale for the ordering: reversed, either container starts wrong.
Hermes syncing skills before the marker exists re-seeds all 72 folders.
Hatchdoor starting before the clone completes, or before the chown, means
it either can't read its vault or (worse) fails startup entirely as
distroless nonroot can't write root-owned dirs.

### Networking

Both containers currently sit on a single private compose network with no
host ports published. Homelab deploy needs Hatchdoor reachable by Caddy
(Kamil's call: expose via Caddy rather than keep fully private) while
Hermes has no reason to ever touch the proxy network. Compose supports
per-service network membership, so:

```yaml
services:
  hermes:
    networks:
      - notes-net
  hatchdoor:
    networks:
      - notes-net
      - nginxnetwork

networks:
  notes-net:
  nginxnetwork:
    external: true
```

`notes-net` keeps the same name/purpose as the Mac's private network
(continuity with the already-verified setup). It is **not** marked
`internal: true` — Hermes still needs outbound egress (Telegram API, OpenAI
Codex). Only Hatchdoor joins `nginxnetwork`, and only it gets a Caddy
route. No host ports published on either container, same as the Mac.

### Caddy exposure

One new entry in `vars/apps.yml`'s `g_services` list:

```yaml
  - slug: hatchdoor
    hostname: hatchdoor
    port: 42824
```

`setup_proxy_v2`'s `Caddyfile.j2` already loops over `g_services` for both
the DuckDNS and Cloudflare domain blocks — no template change needed.
Result: `hatchdoor.mrmodest.duckdns.org` and `hatchdoor.modestlab.dev` both
reverse-proxy to `hatchdoor:42824` inside `nginxnetwork`.
`HATCHDOOR_WEB_BEARER_TOKEN` (already required in the current `.env`,
independent of exposure — Hatchdoor refuses non-loopback binds without it)
is the auth gate at the app layer; Caddy itself adds no additional auth.

### Secrets

New `v_hermes_notes` block in `vars/vault.yml` (edited via
`ansible-vault edit vars/vault.yml`, house convention):

- `telegram_bot_token`
- `telegram_allowed_users`
- `hatchdoor_web_bearer_token`
- `hatchdoor_mcp_bearer_token`
- `github_pat` — the fine-grained PAT scoped to `knowledge-vault` only,
  reused for both the Ansible git clone (step 3 above) and Hatchdoor's own
  git-sync push (`HATCHDOOR_GIT_HTTPS_TOKEN` in `.env`).

Non-secret static values — `hnts_github_username: MrModest` (used in the
git clone URL in step 3 above and in `.env`'s
`HATCHDOOR_GIT_HTTPS_USERNAME`), git remote/branch, debounce seconds,
author name/email, `HATCHDOOR_MCP_ENABLED`, etc. — live as ordinary role
defaults in `roles/deploy_hermes_notes/defaults/main.yml`, not in vault.
They match the values already in the Mac's `.env` and aren't sensitive.

### `main.yml` wiring

New role import in the applications section:

```yaml
    - name: Deploy 'hermes-notes'
      ansible.builtin.import_role:
        name: deploy_hermes_notes
      vars:
        hnts_telegram_bot_token: '{{ v_hermes_notes.telegram_bot_token }}'
        hnts_telegram_allowed_users: '{{ v_hermes_notes.telegram_allowed_users }}'
        hnts_hatchdoor_web_bearer_token: '{{ v_hermes_notes.hatchdoor_web_bearer_token }}'
        hnts_hatchdoor_mcp_bearer_token: '{{ v_hermes_notes.hatchdoor_mcp_bearer_token }}'
        hnts_github_pat: '{{ v_hermes_notes.github_pat }}'
      tags:
        - applications
        - hermes_notes
```

## Known side-effect, not fixed

`compose_up.yml` unconditionally appends `APP_USER`/`APP_GROUP`/
`SMB_USER`/`SMB_GROUP` lines to `.env` via `lineinfile` regardless of
whether the app's compose file references them. Neither Hermes nor
Hatchdoor's compose services use these (Hermes runs as root in-image,
Hatchdoor's UID is baked into the distroless image) — the lines will be
present in `.env` but unused. Cosmetic only; not worth special-casing the
shared task file for one role.

## Out of scope (manual, not automated by this role)

- **OpenAI Codex OAuth login.** Interactive browser flow — has to be run
  by hand on the new host after first boot (`docker exec -it hermes hermes
  auth` or equivalent). Expected to invalidate the Mac's active session.
- **Re-adding the `note-taking/obsidian` skill.** With the bundled-skills
  marker in place from first boot, zero skills sync down, including the
  one Hermes actually uses. Re-adding it (however that's done — manual
  copy, or a `hermes skills` subcommand) is a manual post-deploy step, not
  part of this playbook.
- **End-to-end verification.** Send a real Telegram note, confirm it lands
  in `97_Notes/` with correct frontmatter, confirm the push shows up on
  `github.com/MrModest/knowledge-vault`. Manual, same as the Mac session.
- **Retiring the Mac stack.** Kamil's call, after verification passes.

## Testing

This is infrastructure/config work, not application code with
unit-testable logic — no TDD. Verification is `ansible-playbook main.yml
--tags hermes_notes --check` (dry run) followed by a real run and the
manual E2E check above.
