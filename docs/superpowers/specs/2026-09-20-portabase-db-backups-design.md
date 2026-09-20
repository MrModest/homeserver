# Portabase DB backups — design

Date: 2026-09-20
Status: approved, not yet implemented

## Problem

All Cronicle jobs on the home server run the same thing: `d-db-dump <app> <pg container>`,
an alias that shells out to `docker exec ... pg_dumpall` and gzips the result into
`{{ p_dirs.backups_root }}/db_dumps/<app>/`. Cronicle itself is installed bare-metal at
`/opt/cronicle`, which drags a host-level Node.js install (and the NodeSource apt repo)
along with it. Keeping Node on the host purely to schedule database dumps is the cost we
want to remove.

Cronicle is also stuck at v0.9.59: `roles/init_setup/tasks/cronicle.yml` only imports the
installer `when: cronicle_service_check_result.failed`, and the installer's unarchive task
is additionally guarded by `creates: /opt/cronicle/package.json`. A healthy service is
therefore never upgraded.

[Portabase](https://github.com/Portabase/portabase) (Apache-2.0, actively developed) does
the specific job Cronicle is being used for — scheduled PostgreSQL dumps with retention,
restore and a UI — as containers.

## Decisions

- **Replace the DB-dump use case with Portabase; do not containerize Cronicle.** A
  general-purpose scheduler is not needed if the only jobs are database dumps.
- **Run both systems in parallel.** Cronicle keeps dumping to `db_dumps/`, Portabase writes
  to `portabase/`. Retirement is a later, separate decision.
- **Do not migrate Cronicle job history or stats.** Portabase starts with fresh history.
  Existing dumps stay on disk.
- **Do not rely on `nginxnetwork`.** That network is currently joined by every service in
  every app's compose file, which is a known security problem to be fixed separately. The
  agent gets a dedicated network instead.
- **No docker socket on the agent.** The agent runs `pg_dump --host <host> --port <port>`
  as a client (verified in `agent-rust/src/domain/postgres/backup.rs`); the socket is only
  needed for Docker Volume backups, which are out of scope.

## Architecture

### The `db_backup` network

A new external docker network named `db_backup`, created with `internal: true` — it has no
route off the host, so it is a dump-only path between the agent and the database
containers.

Created in `roles/setup_docker`, alongside the existing docker daemon setup, so it exists
before any application role runs (including when a single app is deployed with
`--tags <app>`). This mirrors how `setup_proxy_v2` creates `nginxnetwork`.

### Database containers opt in

Each app's PostgreSQL service joins `db_backup` in addition to its existing default
network. Only the DB service changes; application containers are untouched.

```yaml
  authentik-postgres:
    # ...
    networks:
      - default
      - db_backup

networks:
  default:
    external: true
    name: nginxnetwork
  db_backup:
    external: true
    name: db_backup
```

A service that declares `networks:` stops implicitly joining `default`, so both must be
listed explicitly.

Affected roles (10): `deploy_authentik`, `deploy_forgejo`, `deploy_ghostfolio`,
`deploy_immich`, `deploy_koillection`, `deploy_linkwarden`, `deploy_n8n`,
`deploy_paperless`, `deploy_planka`, `deploy_semaphore`.

Each edit recreates that database container on the next deploy of its app.

### The `deploy_portabase` role

Follows the standard flow: `tasks/compose_up.yml` with `t_app_name: portabase`. Upstream
images only — no Dockerfile, no Node on the host.

| Service | Image | Networks |
|---|---|---|
| `portabase-app` | `portabase/portabase:${PORTABASE_VERSION}` | `nginxnetwork`, `portabase-net` |
| `portabase-pg` | `postgres:17-alpine` | `portabase-net` |
| `portabase-agent` | `portabase/agent:${AGENT_VERSION}` | `portabase-net`, `db_backup` |

No published host ports: the dashboard is reached through the proxy, the agent talks only
to the dashboard and to database containers.

### Storage

Portabase's "local" storage channel writes inside the **dashboard** container, at
`PRIVATE_PATH/uploads` (`src/features/channel/components/storages/local/local.ts`), not in
the agent. So the host path is bind-mounted into the dashboard:

- `{{ p_dirs.backups_root }}/portabase` → `/data` on `portabase-app`
- dumps land in `{{ p_dirs.backups_root }}/portabase/uploads/`
- `{{ p_dirs.backups_root }}/db_dumps` stays Cronicle's, untouched

Portabase's own state (its PostgreSQL) lives on the fast pool as a dedicated ZFS dataset at
`fast/apps-data/portabase/db`, per the per-app dataset convention.

### Role layout

```
roles/deploy_portabase/
  defaults/main.yml     # pbs_* image versions and tunables
  files/compose.yml
  templates/.env.j2
  tasks/main.yml
  README.md             # bootstrap runbook + restore caveats
```

### Secrets

New vault variables: `v_portabase_project_secret`, `v_portabase_pg_password`,
`v_portabase_admin_email`, `v_portabase_admin_password`, `v_portabase_edge_key`.

Per-database credentials are **not** stored in Ansible — they are entered in the Portabase
UI and live in Portabase's own database. The role deploys the platform, not the backup
definitions.

### Proxy

`vars/apps.yml` gains: `slug: portabase`, `hostname: portabase-app`, `port: 80`.

### Cronicle stays, behind a flag

`roles/init_setup` gains an `is_cronicle_enabled` flag, defaulting to `true`, gating the
Node.js and Cronicle task imports. Flipping it to `false` is the first step of retirement,
taken later and separately.

Unrelated fix already applied: NodeSource is no longer a per-distribution repository, so
`install_node.yml` must use the suite `nodistro` rather than the distribution codename
(`dists/jammy` returns 404, `dists/nodistro` returns 200).

## Bootstrap

`EDGE_KEY` is minted by the dashboard, so first deployment is necessarily two-phase:

1. Deploy the role. Dashboard and its database come up; the agent starts but cannot pair.
2. Log into the dashboard, create an agent, copy its `EDGE_KEY` into the vault.
3. Re-run the role. The agent pairs.
4. In the UI: create the local storage channel, add each database (host = the container
   name on `db_backup`, credentials from that app's `.env`), set schedule and retention.

## Verification

- Agent pairing status is visible in the dashboard's agent list and in
  `docker logs portabase-agent`.
- A failed dump appears as a failed job with `pg_dump` stderr captured — the agent logs
  command output, exit code and duration explicitly.
- Before trusting the new system, restore one small database (planka or koillection) into
  a throwaway container by hand.

## Known caveats

- **Immich** uses `ghcr.io/immich-app/postgres` (VectorChord). `pg_dump` works, but a
  restore requires an image carrying the same extension — a stock `postgres:17` will fail.
  Documented in the role README.
- Redis and Valkey containers are not enrolled: Portabase supports backing them up but not
  restoring them, so there is no benefit over the current arrangement.
- Job history and statistics do not carry over from Cronicle.

## Out of scope

- Retiring Cronicle, removing Node.js from the host, or deleting `/opt/cronicle`.
- Fixing the broader `nginxnetwork` over-exposure. The `db_backup` network is a first step
  in that direction, not the fix.
- Docker Volume backups (would require giving the agent the docker socket).
- Managing per-database backup definitions from Ansible.
