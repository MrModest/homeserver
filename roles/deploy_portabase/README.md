# deploy_portabase

Scheduled PostgreSQL backups with retention and restore, replacing the Cronicle `d-db-dump` jobs.

Three containers: the dashboard (`portabase-app`), its own PostgreSQL (`portabase-pg`), and the
agent (`portabase-agent`) that actually runs `pg_dump`.

## Networking

The agent is a plain PostgreSQL client — it runs `pg_dump --host <container> --port 5432`. It
reaches application databases over the `db_backup` network, created by `setup_docker` with
`internal: true` so it has no route off the host. The agent is deliberately **not** on
`nginxnetwork`, and has **no docker socket** (that is only needed for Docker Volume backups).

A database joins by listing both `default` and `db_backup` on its own service in the app's
`compose.yml`. A service that declares `networks:` stops joining `default` implicitly, so both must
be listed.

## Storage

Dumps go to `{{ p_dirs.backups_root }}/portabase`, mounted as `/data` on the dashboard. Portabase's
`local` storage provider writes to `PRIVATE_PATH/uploads` **inside the dashboard container**, not
the agent. `PRIVATE_PATH` is left at the image default `/data/private`, so files appear at
`{{ p_dirs.backups_root }}/portabase/private/uploads/`. The dashboard container runs as root
(upstream's prod stage ends with `USER root`), so the dumps it writes are root-owned.

Cronicle's `{{ p_dirs.backups_root }}/db_dumps` is untouched; both systems run in parallel.

## First-time bootstrap

`EDGE_KEY` is minted by the dashboard, so the first deploy is necessarily two-phase.

1. Deploy: `ansible-playbook main.yml --tags portabase`. The dashboard and its database come up.
   The agent starts and fails to pair — expected.
2. Open `https://portabase.<domain>`, log in with `v_portabase.admin_email` /
   `v_portabase.admin_password`.
3. Create an agent in the UI, copy its `EDGE_KEY`, store it as `v_portabase.edge_key`:
   `ansible-vault edit vars/vault.yml`.
4. Re-deploy: `ansible-playbook main.yml --tags portabase`. Confirm pairing with
   `docker logs portabase-agent` and the agent list in the UI.
5. In the UI, create a storage channel of type **local**.
6. Add each database. Host is the container name, port `5432`; credentials come from that app's
   `.env` in `/mnt/pools/fast/docker/compose-files/<app>/.env`:

   | App | Host | User variable | Password variable | Database variable |
   |---|---|---|---|---|
   | authentik | `authentik-postgres` | `PG_USER` | `PG_PASS` | `PG_DB` |
   | forgejo | `forgejo_pg` | `forgejo` (literal) | `forgejo` (literal) | `forgejo` (literal) |
   | ghostfolio | `ghostfolio-postgres` | `POSTGRES_USER` | `POSTGRES_PASSWORD` | `POSTGRES_DB` |
   | immich | `immich_postgres` | `DB_USERNAME` | `DB_PASSWORD` | `DB_DATABASE_NAME` |
   | koillection | `koillection_db` | `DB_USER` | `DB_PASSWORD` | `DB_NAME` |
   | linkwarden | `linkwarden_db` | `postgres` (literal) | `POSTGRES_PASSWORD` | `postgres` (literal) |
   | n8n | `n8n-db` | `DB_USER` | `DB_PASSWORD` | `DB_NAME` |
   | paperless | `paperless_db` | `paperless` (literal) | `paperless` (literal) | `paperless` (literal) |
   | planka | `planka-db` | `postgres` (literal) | *(none — trust auth)* | `planka` (literal) |
   | semaphore | `semaphore_pg` | `PG_USER` | `PG_PASSWORD` | `PG_DB_NAME` |

7. Set a schedule and retention per database, then run one backup by hand to confirm it lands in
   `{{ p_dirs.backups_root }}/portabase/private/uploads/`.

## Caveats

- **Immich** runs `ghcr.io/immich-app/postgres` (VectorChord). `pg_dump` works, but restoring needs
  an image carrying the same extension — a stock `postgres:17` will fail on restore.
- **Planka** uses `POSTGRES_HOST_AUTH_METHOD: trust` and has no password set.
- Redis and Valkey containers are not enrolled: Portabase can back them up but cannot restore them.
- Backup definitions live in Portabase's own database, not in Ansible. This role deploys the
  platform; the per-database configuration is UI state. Restoring Portabase itself means restoring
  `{{ p_dirs.apps_data }}/portabase/db`.

## Retiring Cronicle

Once the Portabase dumps have been trusted for a while: set `isu_cronicle_enabled: false` in
`roles/init_setup/defaults/main.yml`, delete the events in the Cronicle UI, then remove the host
install (`systemctl disable --now cronicle`, `rm -rf /opt/cronicle`) by hand.
