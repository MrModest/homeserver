# Portabase DB Backups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Portabase (dashboard + agent) as a containerized replacement for the Cronicle `d-db-dump` jobs, reaching every application's PostgreSQL container over a dedicated internal `db_backup` network.

**Architecture:** A new `deploy_portabase` role runs three upstream containers — dashboard, its own PostgreSQL, and the Rust agent. The agent runs `pg_dump` as a network client, so each application's DB service opts into a new `internal: true` docker network called `db_backup`; no docker socket is mounted. Dumps land on the slow pool at `{{ p_dirs.backups_root }}/portabase`, leaving Cronicle's `db_dumps/` untouched so both systems run in parallel.

**Tech Stack:** Ansible, Docker Compose v2 (`community.docker.docker_compose_v2`), `portabase/portabase:1.30.2`, `portabase/agent:1.21.2`, `postgres:17-alpine`.

Spec: `docs/superpowers/specs/2026-09-20-portabase-db-backups-design.md`

---

## Conventions this plan follows

- Variable prefixes: `g_*` global, `v_*` vault, `p_*` playbook, `<role>_*` role defaults, `t_*` task-scoped. The role prefix here is `pbs_`.
- Permissions come from `p_default_permissions` (`0644` files, `0754` directories).
- Roles deploy through `tasks/compose_up.yml`, which needs `t_app_name` and `t_app_data_dirs`.
- **No Ansible run in this plan touches the server without the user explicitly asking.** Every deploy step is marked "USER RUNS THIS" and must be handed to the user rather than executed.

---

### Task 1: Create the `db_backup` network in `setup_docker`

The network must exist before any application role deploys, including single-app runs like
`ansible-playbook main.yml --tags planka`. `setup_docker` runs inside `server_init`, before all
application roles, which is why it lives here rather than in `deploy_portabase`.

**Files:**
- Modify: `roles/setup_docker/tasks/main.yml`

- [ ] **Step 1: Add the network task**

Insert this task immediately after the existing `- name: Add user to Docker group` task and before
`- name: Assure that 'docker-py' python module is absent`:

```yaml
- name: Create the 'db_backup' network
  # Dedicated path for the Portabase agent to reach application databases with
  # pg_dump. 'internal: true' means no route off the host: the only things on
  # this network are the agent and the DB containers that opt into it. Created
  # here rather than in deploy_portabase so it exists before any app role runs,
  # including a single-app run like `--tags planka`.
  community.docker.docker_network:
    name: db_backup
    internal: true
  become: true
```

- [ ] **Step 2: Verify the file still parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('roles/setup_docker/tasks/main.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Verify the playbook still compiles**

Run: `ansible-playbook main.yml --syntax-check`
Expected: exit code 0, a `playbook: main.yml` line, no error output. This parses files locally and
does not connect to the server.

- [ ] **Step 4: Commit**

```bash
git add roles/setup_docker/tasks/main.yml
git commit -m "Add internal 'db_backup' docker network"
```

---

### Task 2: Opt every application database into `db_backup`

Ten compose files each get the same two edits. Every one of them currently ends with an identical
four-line `networks:` block, so the second edit is character-identical across all ten.

**Important:** a compose service that declares its own `networks:` key stops implicitly joining
`default`. Both networks must therefore be listed on the DB service, or the application loses its
connection to its own database.

**Files (modify):**

| File | DB service key | Container name |
|---|---|---|
| `roles/deploy_authentik/files/compose.yml` | `authentik-postgres` | `authentik-postgres` |
| `roles/deploy_forgejo/files/compose.yml` | `forgejo-db` | `forgejo_pg` |
| `roles/deploy_ghostfolio/files/compose.yml` | `postgres` | `ghostfolio-postgres` |
| `roles/deploy_immich/files/compose.yml` | `database` | `immich_postgres` |
| `roles/deploy_koillection/files/compose.yml` | `postgres` | `koillection_db` |
| `roles/deploy_linkwarden/files/compose.yml` | `postgres` | `linkwarden_db` |
| `roles/deploy_n8n/files/compose.yml` | `n8n-db` | `n8n-db` |
| `roles/deploy_paperless/files/compose.yml` | `db` | `paperless_db` |
| `roles/deploy_planka/files/compose.yml` | `planka-db` | `planka-db` |
| `roles/deploy_semaphore/files/compose.yml` | `semaphore_pg` | `semaphore_pg` |

- [ ] **Step 1: Add the `networks` key to each DB service**

For each file in the table, add a `networks` block as the last key of that DB service's definition,
at the same indentation as its `image:` key. For example, in
`roles/deploy_planka/files/compose.yml` the `planka-db` service ends with its `healthcheck:` block;
append after it:

```yaml
    networks:
      # 'default' must stay listed: a service that declares networks no longer
      # joins it implicitly, and the app reaches its DB over 'default'.
      - default
      # Dump-only path for the Portabase agent. Internal network, no egress.
      - db_backup
```

Apply the same block to the DB service named in the table for each of the ten files. Add it to the
DB service only — application containers are not touched.

- [ ] **Step 2: Declare the external network in each file**

Every one of the ten files currently ends with exactly:

```yaml
networks:
  default:
    external: true
    name: nginxnetwork
```

Replace that block, in each file, with:

```yaml
networks:
  default:
    external: true
    name: nginxnetwork
  db_backup:
    external: true
    name: db_backup
```

- [ ] **Step 3: Verify every file still parses and declares the network**

```bash
for a in authentik forgejo ghostfolio immich koillection linkwarden n8n paperless planka semaphore; do
  f="roles/deploy_$a/files/compose.yml"
  python3 -c "
import yaml,sys
d = yaml.safe_load(open('$f'))
assert 'db_backup' in d['networks'], 'missing network declaration'
svcs = [s for s,v in d['services'].items() if 'db_backup' in (v.get('networks') or [])]
assert len(svcs) == 1, f'expected exactly 1 service on db_backup, got {svcs}'
print('$a OK ->', svcs[0])
"
done
```

Expected: ten lines, each `<app> OK -> <db service key>`, matching the table above. Any
`AssertionError` names the file that is wrong.

- [ ] **Step 4: Confirm no application service was changed**

```bash
git diff --numstat -- 'roles/deploy_*/files/compose.yml' | awk '{a+=$1; d+=$2} END {print a, d}'
```

Expected: `90 0` — ten files × nine added lines (six for the service `networks` block, three for the
`db_backup` declaration), and zero deletions. A higher count means a non-DB service was edited;
inspect `git diff` and revert the extra edit. Any deletion at all means an existing line was
clobbered.

- [ ] **Step 5: Commit**

```bash
git add roles/deploy_*/files/compose.yml
git commit -m "Join application databases to the 'db_backup' network"
```

---

### Task 3: Create the `deploy_portabase` role skeleton and defaults

**Files:**
- Create: `roles/deploy_portabase/defaults/main.yml`

- [ ] **Step 1: Create the role directories**

```bash
mkdir -p roles/deploy_portabase/{defaults,files,tasks,templates}
```

- [ ] **Step 2: Write the defaults**

Create `roles/deploy_portabase/defaults/main.yml`:

```yaml
---
# Dashboard (Next.js control plane) and its own PostgreSQL.
pbs_app_version: '1.30.2'
pbs_db_version: '17-alpine'

# Rust agent: runs pg_dump against the application databases.
pbs_agent_version: '1.21.2'

pbs_app_host: placeholder

# Pairing token minted by the dashboard when an agent is created in its UI.
# Empty on a first deploy — the agent cannot pair until this is filled in from
# the vault. See the role README for the two-phase bootstrap.
pbs_edge_key: ''

# Retention sweep for expired backups, as a cron expression.
pbs_retention_cron: '0 * * * *'
```

- [ ] **Step 3: Verify it parses**

Run: `python3 -c "import yaml; print(yaml.safe_load(open('roles/deploy_portabase/defaults/main.yml')))"`
Expected: a dict printed with `pbs_app_version` set to `1.30.2`.

- [ ] **Step 4: Commit**

```bash
git add roles/deploy_portabase/defaults/main.yml
git commit -m "Add deploy_portabase role defaults"
```

---

### Task 4: Write the Portabase compose file

The dashboard holds the local storage channel: Portabase's "local" provider writes inside the
**dashboard** container at `PRIVATE_PATH/uploads`, not in the agent. That is why the slow-pool path
is mounted on `portabase-app` and not on `portabase-agent`.

**Files:**
- Create: `roles/deploy_portabase/files/compose.yml`

- [ ] **Step 1: Write the compose file**

```yaml
services:
  portabase-app:
    image: portabase/portabase:${APP_VERSION}
    container_name: 'portabase-app'
    hostname: 'portabase-app'
    env_file:
      - .env
    environment:
      TZ: ${TZ}
    volumes:
      # Portabase's 'local' storage channel writes to PRIVATE_PATH/uploads
      # inside THIS container (not the agent), so the slow-pool backup path is
      # mounted here. Dumps land in ${BACKUPS_PATH}/uploads on the host.
      - ${BACKUPS_PATH}:/data
    networks:
      - default
      - portabase
    restart: unless-stopped
    depends_on:
      portabase-pg:
        condition: service_healthy
    healthcheck:
      test: ['CMD-SHELL', 'curl -f http://localhost/api/health']
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

  portabase-pg:
    image: postgres:${DB_VERSION}
    container_name: 'portabase-pg'
    hostname: 'portabase-pg'
    user: '${APP_USER}:${APP_GROUP}'
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ${APP_DATA_PATH}/db:/var/lib/postgresql/data
    # Deliberately NOT on 'default' (nginxnetwork): Portabase's own state is
    # reachable only by the dashboard.
    networks:
      - portabase
    restart: unless-stopped
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}']
      interval: 10s
      timeout: 5s
      retries: 5

  portabase-agent:
    image: portabase/agent:${AGENT_VERSION}
    container_name: 'portabase-agent'
    hostname: 'portabase-agent'
    environment:
      EDGE_KEY: ${EDGE_KEY}
      LOG: info
      TZ: ${TZ}
    # No docker socket: the agent runs pg_dump as a network client
    # (agent-rust/src/domain/postgres/backup.rs). The socket is only needed for
    # Docker Volume backups, which are out of scope.
    networks:
      # Reaches the dashboard to poll for jobs...
      - portabase
      # ...and the application databases to dump them. No egress from here.
      - db_backup
    restart: unless-stopped
    depends_on:
      portabase-app:
        condition: service_healthy

networks:
  default:
    external: true
    name: nginxnetwork
  db_backup:
    external: true
    name: db_backup
  portabase:
```

- [ ] **Step 2: Verify structure**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('roles/deploy_portabase/files/compose.yml'))
assert set(d['services']) == {'portabase-app','portabase-pg','portabase-agent'}
assert d['services']['portabase-agent']['networks'] == ['portabase','db_backup']
assert 'volumes' not in d['services']['portabase-agent']
assert d['services']['portabase-pg']['networks'] == ['portabase']
print('OK')
"
```

Expected: `OK`. The third assertion is the guard against a docker socket sneaking onto the agent.

- [ ] **Step 3: Commit**

```bash
git add roles/deploy_portabase/files/compose.yml
git commit -m "Add Portabase compose file"
```

---

### Task 5: Write the Portabase env template

`compose_up.yml` rewrites the `APP_USER`/`APP_GROUP`/`SMB_USER`/`SMB_GROUP` lines in place after
templating, so those four keys must be present with placeholder values.

**Files:**
- Create: `roles/deploy_portabase/templates/.env.j2`

- [ ] **Step 1: Write the template**

```jinja
APP_VERSION={{ pbs_app_version }}
DB_VERSION={{ pbs_db_version }}
AGENT_VERSION={{ pbs_agent_version }}

APP_USER=placeholder
APP_GROUP=placeholder
SMB_USER=placeholder
SMB_GROUP=placeholder

APP_DATA_PATH={{ p_dirs.apps_data }}/portabase
BACKUPS_PATH={{ p_dirs.backups_root }}/portabase
TZ={{ p_timezone }}

# Portabase's own database.
POSTGRES_DB=portabase
POSTGRES_USER=portabase
POSTGRES_PASSWORD={{ v_portabase.pg_password }}
DATABASE_URL=postgresql://portabase:{{ v_portabase.pg_password }}@portabase-pg:5432/portabase?schema=public

PROJECT_NAME=Portabase
PROJECT_URL=https://{{ pbs_app_host }}
PROJECT_SECRET={{ v_portabase.project_secret }}
TRUSTED_DOMAINS=https://{{ pbs_app_host }}

# Seeded on a fresh instance only; later changes happen in the UI.
AUTH_DEFAULT_USER_NAME={{ v_admin_login_user.display_name }}
AUTH_DEFAULT_USER={{ v_portabase.admin_email }}
AUTH_DEFAULT_PASSWORD={{ v_portabase.admin_password }}
AUTH_SIGNUP_ENABLED=false

# Where the 'local' storage channel writes inside the dashboard container.
# Left at the image's own default (/data/private) on purpose: the entrypoint
# hardcodes `mkdir -p /data/private/uploads/tmp` for tusd regardless of this
# variable, so overriding it would split the storage layout in two. /data is
# the BACKUPS_PATH mount, so dumps land in BACKUPS_PATH/private/uploads.
PRIVATE_PATH=/data/private

RETENTION_CRON={{ pbs_retention_cron }}
LOG_LEVEL=warn
TELEMETRY=false

# Pairing token for the agent. Empty until an agent is created in the UI.
EDGE_KEY={{ pbs_edge_key }}
```

- [ ] **Step 2: Verify every referenced variable is defined somewhere**

Run: `grep -o '{{ [a-z_.]* }}' roles/deploy_portabase/templates/.env.j2 | sort -u`

Expected exactly these, and nothing else:

```
{{ p_dirs.apps_data }}
{{ p_dirs.backups_root }}
{{ p_timezone }}
{{ pbs_agent_version }}
{{ pbs_app_host }}
{{ pbs_app_version }}
{{ pbs_db_version }}
{{ pbs_edge_key }}
{{ pbs_retention_cron }}
{{ v_admin_login_user.display_name }}
{{ v_portabase.admin_email }}
{{ v_portabase.admin_password }}
{{ v_portabase.pg_password }}
{{ v_portabase.project_secret }}
```

The `pbs_*` names come from Task 3, the `p_*` names from `main.yml`, and the `v_*` names from
Task 7. `v_admin_login_user` already exists in the vault (it is used by `deploy_planka`).

- [ ] **Step 3: Commit**

```bash
git add roles/deploy_portabase/templates/.env.j2
git commit -m "Add Portabase env template"
```

---

### Task 6: Write the role tasks

**Files:**
- Create: `roles/deploy_portabase/tasks/main.yml`

- [ ] **Step 1: Write the tasks**

```yaml
---
- name: Create the Portabase backups directory on the slow pool
  # Not part of t_app_data_dirs below: that list is relative to the fast pool's
  # apps-data, while the dumps belong on the slow pool next to Cronicle's
  # existing db_dumps/ tree. Docker would otherwise create the missing bind
  # mount source as a root-owned directory.
  ansible.builtin.file:
    path: '{{ p_dirs.backups_root }}/portabase'
    state: directory
    owner: '{{ p_apps_user.user }}'
    group: '{{ p_apps_user.group }}'
    mode: '{{ p_default_permissions.directory }}'
  become: true

- name: Warn when the agent has no pairing key yet
  # First deploy always lands here: EDGE_KEY is minted by the dashboard, so it
  # cannot exist before the dashboard runs. The agent will start and fail to
  # pair; that is expected. See README.md for the two-phase bootstrap.
  ansible.builtin.debug:
    msg: >-
      pbs_edge_key is empty: the agent will start but cannot pair. Create an
      agent in the Portabase UI, store its key as v_portabase.edge_key, and
      re-run this role.
  when: pbs_edge_key | length == 0

- name: Start 'portabase'
  ansible.builtin.import_tasks: tasks/compose_up.yml
  vars:
    t_app_name: 'portabase'
    t_app_data_dirs:
      - '{{ p_dirs.apps_data }}/portabase/db'
```

- [ ] **Step 2: Verify it parses**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('roles/deploy_portabase/tasks/main.yml')); print(len(d), 'tasks')"`
Expected: `3 tasks`

- [ ] **Step 3: Commit**

```bash
git add roles/deploy_portabase/tasks/main.yml
git commit -m "Add Portabase role tasks"
```

---

### Task 7: Add the vault variables

Vault edits are interactive and touch encrypted secrets, so the user performs this task.

**Files:**
- Modify: `vars/vault.yml` (encrypted)

- [ ] **Step 1: Generate two secrets**

Run: `openssl rand -hex 32; openssl rand -hex 32`
Expected: two 64-character hex strings. The first becomes `project_secret`, the second
`pg_password`.

- [ ] **Step 2: USER RUNS THIS — add the block to the vault**

```bash
ansible-vault edit vars/vault.yml
```

Add, using the generated values and an admin password of your choosing (Portabase requires at
least 8 characters with an uppercase letter, a lowercase letter, a number and a special
character):

```yaml
v_portabase:
  project_secret: '<first hex string>'
  pg_password: '<second hex string>'
  admin_email: '<your email>'
  admin_password: '<strong password>'
  edge_key: ''
```

`edge_key` stays empty until Task 11.

- [ ] **Step 3: Verify the block decrypts and reads back**

Run: `ansible-vault view vars/vault.yml | grep -A5 '^v_portabase:'`
Expected: the five keys, with `edge_key: ''` last.

- [ ] **Step 4: Commit**

```bash
git add vars/vault.yml
git commit -m "Add Portabase vault secrets"
```

---

### Task 8: Wire the role into the playbook and the proxy

**Files:**
- Modify: `main.yml`
- Modify: `vars/apps.yml`

- [ ] **Step 1: Add the role import**

In `main.yml`, add after the `Deploy 'planka'` block (which ends with its `tags:` list):

```yaml
    - name: Deploy 'portabase'
      ansible.builtin.import_role:
        name: deploy_portabase
      vars:
        pbs_app_host: 'portabase.{{ p_base_domain }}'
        pbs_edge_key: '{{ v_portabase.edge_key }}'
      tags:
        - applications
        - portabase
```

- [ ] **Step 2: Add the proxy entry**

In `vars/apps.yml`, add to the `g_services` list:

```yaml
  - slug: portabase
    hostname: portabase-app
    port: 80
```

- [ ] **Step 3: Verify both files parse and the playbook compiles**

```bash
python3 -c "import yaml; yaml.safe_load(open('vars/apps.yml'))" && \
ansible-playbook main.yml --syntax-check && echo OK
```

Expected: `OK`. This is local parsing only — no connection to the server.

- [ ] **Step 4: Verify the tag resolves to the new role**

Run: `ansible-playbook main.yml --list-tasks --tags portabase`
Expected: the listed tasks include `deploy_portabase : Start 'portabase'`. Listing does not
connect to the server.

- [ ] **Step 5: Commit**

```bash
git add main.yml vars/apps.yml
git commit -m "Deploy Portabase and expose it through the proxy"
```

---

### Task 9: Put the bare-metal Cronicle install behind a flag

Cronicle keeps running for now. The flag makes retiring it a one-line change later.

The spec calls this flag `is_cronicle_enabled`; the plan names it `isu_cronicle_enabled` so it
carries the `isu_` prefix that every other `init_setup` default uses, per the repo's role-variable
convention.

**Files:**
- Modify: `roles/init_setup/defaults/main.yml`
- Modify: `roles/init_setup/tasks/main.yml`

- [ ] **Step 1: Add the default**

Append to `roles/init_setup/defaults/main.yml`:

```yaml

# Bare-metal Cronicle (and the host Node.js install it needs). Kept on while
# Portabase runs in parallel; set to false to stop managing it. Turning it off
# does not uninstall anything — the service and /opt/cronicle stay on the host.
isu_cronicle_enabled: true
```

- [ ] **Step 2: Gate the import**

In `roles/init_setup/tasks/main.yml`, replace this task:

```yaml
- name: Install Node.js & Cronicle
  ansible.builtin.import_tasks: cronicle.yml
  become: true
  tags:
    - cronicle
```

with:

```yaml
- name: Install Node.js & Cronicle
  ansible.builtin.import_tasks: cronicle.yml
  become: true
  when: isu_cronicle_enabled | bool
  tags:
    - cronicle
```

- [ ] **Step 3: Verify the guard is applied to every imported task**

Run: `ansible-playbook main.yml --list-tasks --tags cronicle`
Expected: the Cronicle tasks are still listed (`import_tasks` is static, so `when` becomes a
condition on each imported task rather than skipping the import). Listing does not connect to the
server.

- [ ] **Step 4: Commit**

```bash
git add roles/init_setup/defaults/main.yml roles/init_setup/tasks/main.yml
git commit -m "Gate bare-metal Cronicle behind 'isu_cronicle_enabled'"
```

---

### Task 10: Write the role README

**Files:**
- Create: `roles/deploy_portabase/README.md`

- [ ] **Step 1: Write the README**

````markdown
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
the agent, so files appear at `{{ p_dirs.backups_root }}/portabase/private/uploads/`.

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
````

- [ ] **Step 2: Commit**

```bash
git add roles/deploy_portabase/README.md
git commit -m "Document the Portabase role"
```

---

### Task 11: Deploy and bootstrap

Every step here touches the live server, so **the user runs all of them.** Do not run these.

- [ ] **Step 1: USER RUNS THIS — create the network**

```bash
ansible-playbook main.yml --tags docker
```

Expected: `Create the 'db_backup' network` reports `changed`.

Verify: `ssh homessh@192.168.178.34 'docker network inspect db_backup -f "{{.Internal}}"'` → `true`

- [ ] **Step 2: USER RUNS THIS — redeploy one app and confirm nothing broke**

Start with the lowest-risk database:

```bash
ansible-playbook main.yml --tags planka
```

Expected: `planka-db` is recreated; `planka` stays healthy.

Verify both networks are attached:

```bash
ssh homessh@192.168.178.34 \
  'docker inspect planka-db -f "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}} {{end}}"'
```

Expected: `db_backup nginxnetwork` (order may vary). If `nginxnetwork` is missing, the `default`
entry was dropped from the service's `networks` list — fix Task 2 for that file before continuing.

Confirm the app still reaches its database by opening Planka and loading a board.

- [ ] **Step 2b: USER RUNS THIS — redeploy the remaining nine apps**

```bash
for app in authentik forgejo ghostfolio immich koillection linkwarden n8n paperless semaphore; do
  ansible-playbook main.yml --tags "$app"
done
```

Expected: each run recreates only that app's DB container. Spot-check each app's UI afterwards.

- [ ] **Step 3: USER RUNS THIS — deploy Portabase**

```bash
ansible-playbook main.yml --tags portabase
```

Expected: the debug task prints the "cannot pair" warning (`pbs_edge_key` is still empty), and three
containers start.

Verify: `ssh homessh@192.168.178.34 'docker ps --filter name=portabase --format "{{.Names}} {{.Status}}"'`
Expected: `portabase-app` and `portabase-pg` healthy/up; `portabase-agent` up but logging a pairing
failure.

- [ ] **Step 4: Complete the bootstrap**

Follow `roles/deploy_portabase/README.md` "First-time bootstrap" steps 2 through 7: log in, create
the agent, store `edge_key` in the vault, re-run `--tags portabase`, create the local storage
channel, then add the ten databases.

- [ ] **Step 5: USER RUNS THIS — verify a real dump lands on disk**

Trigger one backup from the UI, then:

```bash
ssh homessh@192.168.178.34 'sudo ls -lh /mnt/pools/slow/backups/portabase/private/uploads/'
```

Expected: a dump file, non-zero size, timestamped just now.

---

### Task 12: Restore drill

A backup that has never been restored is not yet a backup. Do this once, by hand, before trusting
the new system. The user runs these.

- [ ] **Step 1: USER RUNS THIS — start a throwaway PostgreSQL**

```bash
ssh homessh@192.168.178.34 \
  'docker run -d --rm --name pbs-restore-test -e POSTGRES_PASSWORD=test postgres:17-alpine'
```

- [ ] **Step 2: USER RUNS THIS — restore the Koillection dump into it**

Use the dump file name from Task 11 Step 5:

```bash
ssh homessh@192.168.178.34 \
  'sudo cat /mnt/pools/slow/backups/portabase/private/uploads/<dump file> | \
   docker exec -i pbs-restore-test pg_restore -U postgres -d postgres --clean --if-exists'
```

Expected: exit code 0. `pg_restore` may print warnings about missing roles — those are harmless;
errors about missing extensions are not.

- [ ] **Step 3: USER RUNS THIS — confirm the tables arrived**

```bash
ssh homessh@192.168.178.34 \
  'docker exec pbs-restore-test psql -U postgres -d postgres -c "\dt" | head -20'
```

Expected: a table listing, not `Did not find any relations`.

- [ ] **Step 4: USER RUNS THIS — clean up**

```bash
ssh homessh@192.168.178.34 'docker stop pbs-restore-test'
```

- [ ] **Step 5: Record the result**

Note the outcome in `roles/deploy_portabase/README.md` under a new `## Verified restores` heading —
which database, which date, which Portabase version — and commit. A restore drill nobody wrote down
gets repeated or, worse, assumed.

---

## What this plan deliberately does not do

- Retire Cronicle, remove Node.js, or delete `/opt/cronicle`. The flag from Task 9 is the whole
  retirement mechanism; flipping it is a later decision.
- Migrate Cronicle job history or statistics. Portabase starts with fresh history.
- Fix the broader `nginxnetwork` over-exposure. `db_backup` is a first step in that direction.
- Manage per-database backup definitions from Ansible — they are UI state in Portabase's database.
- Enable Docker Volume backups, which would require mounting the docker socket on the agent.
