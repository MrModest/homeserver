# Forgejo

This role deploys Forgejo and PostgreSQL with Docker Compose.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `frgj_app_version` | `17.0.1-rootless` | Forgejo image tag |
| `frgj_pg_version` | `18.6-bookworm` | PostgreSQL image tag |
| `frgj_app_host` | `placeholder` | Hostname used for Forgejo's root URL and domains; set this for the deployment |

The role copies the Compose file and generates `.env` in `{{ p_dirs.compose_files }}/forgejo`. Both containers run with the numeric UID and GID of the shared application user. Forgejo connects to the `forgejo` database at `forgejo-db:5432`.

## Persistent data

Paths on the host are relative to `{{ p_dirs.apps_data }}/forgejo`.

| Host directory | Container path | Use |
| --- | --- | --- |
| `data` | `/var/lib/gitea` | Forgejo data and default configuration |
| `conf` | `/etc/gitea` | Configuration mount |
| `postgres18` | `/var/lib/postgresql` | PostgreSQL data |

The default Forgejo configuration file is `data/custom/conf/app.ini`, mounted at `/var/lib/gitea/custom/conf/app.ini`.

Both services join the external `nginxnetwork` network. Compose publishes no host ports.

## Deployment

`main.yml` sets `frgj_app_host` from `p_base_domain`. Run the tagged role with the project's inventory and variables:

```sh
ansible-playbook main.yml --tags forgejo
```
