# Tududi

This role deploys Tududi 2.0.1 with PostgreSQL 18.6 (`18.6-bookworm`).
PostgreSQL runs as the shared application UID/GID. Tududi's entrypoint uses
`PUID`/`PGID` to drop privileges before starting the application. Both services
join `nginxnetwork`; no host ports are published.

## Configuration

`main.yml` passes `v_tududi.db_password` as `tdu_db_password`, alongside the
existing user email, password and session secret. The role generates `.env`
and Compose files under `{{ p_dirs.compose_files }}/tududi`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `tdu_app_version` | `2.0.1` | Tududi image tag |
| `tdu_pg_version` | `18.6-bookworm` | PostgreSQL image tag |
| `tdu_db_password` | `placeholder` | Database password, supplied from the vault |

## Persistent data

Paths are relative to `{{ p_dirs.apps_data }}/tududi`, on the app's ZFS dataset.

| Host directory | Container path | Use |
| --- | --- | --- |
| `postgres18` | `/var/lib/postgresql` | PostgreSQL cluster |
| `uploads` | `/app/uploads` | Attachments and images |
| `backups` | `/app/backups` | Tududi JSON backups |
| `db` | Not mounted | Original SQLite database, retained unchanged |

The SQLite data was migrated using the official 1.15.0 admin instance export
and 2.0.1 import services. The export ran against a copy. Backups and row-count
verification are under
`/mnt/pools/fast/upgrade-backups/tududi-20261106T153114Z/`.
The main table counts match between the original SQLite database and PostgreSQL.

The official import does not carry over sessions, API tokens, CalDAV sync state,
audit logs or notification history. Users must sign in again and recreate API
tokens and CalDAV connections. Other integrations such as two-factor sign-in,
SSO links and push notifications also require setup again if previously used.

## Enabling

Tududi is disabled by `when: false` on its role import in `main.yml` because of
the [DST scheduler bug](https://github.com/chrisvel/tududi/issues/2085).
The app and PostgreSQL containers are stopped; PostgreSQL data remains on disk.

To enable, remove that condition and deploy:

```sh
ansible-playbook main.yml --tags tududi
```

Compose starts PostgreSQL first and waits for its health check before starting
Tududi. No further SQLite migration is needed.
