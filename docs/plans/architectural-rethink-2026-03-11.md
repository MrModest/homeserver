# Homeserver Repository - Architectural Rethink

## Context

The repo automates a single Docker homeserver + a Pi running Pi-hole. It works, but suffers from two structural problems:

1. **47% of the codebase is boilerplate** - adding a new Docker service requires creating 4-6 files with 45-60 lines, most of which is copy-paste
2. **Tightly coupled to one machine** - `group_vars/all.yml` contains homeserver-specific disk IDs, all `p_*` vars assume ZFS+Docker, the Pi playbook is a disconnected afterthought, and adding a Proxmox host would mean yet another isolated playbook

This plan proposes an architecture that eliminates repetition and scales to N machines with different purposes.

---

## Problem 1: Repetition When Adding Services

### Current State

Adding a simple Docker app (e.g., readeck) requires:

```
roles/deploy_readeck/
  tasks/main.yml          (7 lines - 5 boilerplate, 2 unique)
  defaults/main.yml       (2 lines - version only)
  files/compose.yml       (20 lines - 8 boilerplate, 12 unique)
  templates/.env.j2       (5 lines - 3 boilerplate, 2 unique)
+ main.yml edit            (6 lines - 4 boilerplate, 2 unique)
```

**40 lines total, 22 are boilerplate (55%)**. For complex apps like immich it's worse: 150+ lines across 6+ files.

Across 28 deploy roles: ~1,874 lines of eliminable boilerplate.

### What Repeats

| Pattern | Where | Frequency |
|---------|-------|-----------|
| `import_tasks: compose_up.yml` + set `t_app_name` | Every `tasks/main.yml` | 27/28 roles |
| `networks: nginxnetwork: external: true` | Every `compose.yml` | 28/28 |
| `restart: unless-stopped` | Every `compose.yml` | 27/28 |
| `user: '${APP_USER}:${APP_GROUP}'` | Every `compose.yml` | 25/28 |
| `APP_VERSION`, `APP_DATA_PATH`, `TIMEZONE`, `COMPOSE_PROJECT_NAME` | Every `.env.j2` | 28/28 |
| `import_role` + `tags: [applications, app_name]` block | `main.yml` | 22 entries |
| `[prefix]_app_version: 'x.y.z'` | Every `defaults/main.yml` | 28/28 |

### Proposed Solution: App Registry + Templated Compose

#### A. Central App Registry (`vars/apps.yml` or `apps/`)

Instead of 28 role directories with near-identical structure, define simple apps declaratively:

```yaml
# vars/apps/media.yml
readeck:
  image: codeberg.org/readeck/readeck
  version: "0.19.2"
  data_dirs: [data]
  pool: fast

wallos:
  image: bellamy/wallos
  version: "2.48.2"
  data_dirs: [db]
  pool: fast

silverbullet:
  image: zefhemel/silverbullet
  version: "0.9.5"
  data_dirs: [space]
  pool: fast
```

For apps with extra services (databases, redis, ML):

```yaml
# vars/apps/data.yml
paperless:
  image: ghcr.io/paperless-ngx/paperless-ngx
  version: "2.18.4"
  pool: slow
  data_dirs: [redisdata, pgdata, data, media, trash, export]
  compose_file: roles/deploy_paperless/files/compose.yml  # custom compose
  env_template: roles/deploy_paperless/templates/.env.j2   # custom env
  vault_vars:
    ppls_secret_key: "{{ v_paperless.secret_key }}"
    ppls_admin_password: "{{ v_paperless.admin_password }}"
```

#### B. Generic Deploy Role

One role replaces 18+ identical simple roles:

```yaml
# roles/deploy_app/tasks/main.yml
- name: Set app name
  ansible.builtin.set_fact:
    t_app_name: "{{ app_name }}"

- name: Copy custom compose file
  ansible.builtin.copy:
    src: "{{ app.compose_file }}"
    dest: "{{ p_dirs.compose_files }}/{{ app_name }}/compose.yml"
  when: app.compose_file is defined

- name: Template default compose file
  ansible.builtin.template:
    src: compose.yml.j2
    dest: "{{ p_dirs.compose_files }}/{{ app_name }}/compose.yml"
  when: app.compose_file is not defined

- name: Import shared compose up
  ansible.builtin.import_tasks: tasks/compose_up.yml
```

#### C. What Stays as Individual Roles

Complex apps that need **custom pre/post tasks** keep their own roles:
- `deploy_immich` (ML setup, multi-service orchestration)
- `deploy_opencloud` (5+ config files, Collabora, Radicale)
- `deploy_backrest` (rclone config templating)
- `deploy_authentik` (SSO setup, part of infrastructure)
- `deploy_hoarder` (permission fixes, Telegram bot config)

Simple apps (~18 of them) collapse into the generic deploy role driven by the app registry.

#### D. Main Playbook Simplification

Before (22 repeated blocks, ~170 lines):
```yaml
- name: Deploy 'readeck'
  ansible.builtin.import_role:
    name: deploy_readeck
  tags: [applications, readeck]

- name: Deploy 'wallos'
  ansible.builtin.import_role:
    name: deploy_wallos
  tags: [applications, wallos]
# ... 20 more identical blocks
```

After (loop over registry):
```yaml
- name: Deploy simple apps
  ansible.builtin.include_role:
    name: deploy_app
  vars:
    app_name: "{{ item.key }}"
    app: "{{ item.value }}"
  loop: "{{ apps_simple | dict2items }}"
  loop_control:
    label: "{{ item.key }}"
  tags: [applications]

- name: Deploy complex apps
  # Keep individual import_role blocks only for apps with custom logic
```

> **Note**: Using `include_role` (dynamic) instead of `import_role` (static) means per-app tags like `--tags readeck` won't work with the loop. Trade-off: either keep per-app `import_role` blocks with the registry eliminating the role directories, or use `include_role` loop and select apps via `--extra-vars "apps_filter=[readeck,wallos]"` instead. A middle ground: tag the loop with `applications` and add a `when: apps_filter is not defined or item.key in apps_filter` guard.

#### E. Estimated Impact

| Metric | Before | After |
|--------|--------|-------|
| Role directories for simple apps | 18 | 1 (generic) |
| Lines to add a simple app | 40-60 | 5-10 (registry entry) |
| Total lines in deploy roles | 3,555 | ~1,200 |
| Boilerplate percentage | 47% | ~15% |

---

## Problem 2: Single-Machine Coupling

### Current State

- `group_vars/all.yml` contains homeserver disk serial numbers, IPs, and ZFS pool config
- `main.yml` targets `hosts: homeserver` with 30+ hardcoded role imports
- `pi_main.yml` is a separate 52-line playbook with its own variable definitions
- Inventory has an orphaned `gateway` group with no playbook
- Adding Proxmox = creating `proxmox_main.yml` = more duplication

### What's Actually Global vs. Host-Specific

Current `group_vars/all.yml` analysis:

| Variable | Truly Global? | Should Live In |
|----------|--------------|----------------|
| `g_hostname` | No - "HomeServer" | `host_vars/homeserver.yml` |
| `g_local_domain` | Yes | `group_vars/all.yml` |
| `g_duckdns_domain` | Yes | `group_vars/all.yml` |
| `g_cloudflare_domain` | Unused | Delete |
| `g_timezone` | Yes | `group_vars/all.yml` |
| `g_ips` | Mixed - network-wide | `group_vars/all.yml` (as reference) |
| `g_ssh_user` | Yes | `group_vars/all.yml` |
| `g_smb_user` | No - homeserver only | `group_vars/docker_hosts.yml` |
| `g_apps_user` | No - homeserver only | `group_vars/docker_hosts.yml` |
| `g_pools.fast` (with disk IDs) | No - hardware-specific | `host_vars/homeserver.yml` |
| `g_pools.slow` (with disk IDs) | No - hardware-specific | `host_vars/homeserver.yml` |

### Proposed Architecture

#### A. Inventory Restructuring

```yaml
# inventory.yml
all:
  children:
    # --- Functional groups (what capabilities a host has) ---
    docker_hosts:
      hosts:
        homeserver:
          ansible_host: 192.168.178.34

    zfs_hosts:
      hosts:
        homeserver:  # same host, different capability

    bare_metal:
      hosts:
        pi4b:
          ansible_host: 192.168.178.55

    # --- Future groups ---
    # proxmox_hosts:
    #   hosts:
    #     proxmox01:
    #       ansible_host: 192.168.178.XX
    #
    # lxc_hosts:
    #   hosts:
    #     proxmox01:  # Proxmox manages LXC too
```

#### B. Variable Hierarchy

```
group_vars/
  all.yml                  # Truly global: timezone, domain, network IPs
  docker_hosts.yml         # Docker-specific: apps_user, smb_user, docker paths
  zfs_hosts.yml            # ZFS-specific: pool naming conventions
  bare_metal.yml           # Bare-metal specific settings

host_vars/
  homeserver.yml           # Disk IDs, pool definitions, host-specific overrides
  pi4b.yml                 # Pi-specific: pihole config, local IP
  # proxmox01.yml          # Future: Proxmox API, VM definitions
```

Variable prefix evolution:

| Current | Proposed | Scope |
|---------|----------|-------|
| `g_*` | `g_*` (keep) | Truly global only (timezone, domain, IPs) |
| `g_pools` | `h_pools` | Host-specific (move to host_vars) |
| `g_hostname` | `h_hostname` | Host-specific |
| `p_*` | `p_*` (keep) | Playbook-scoped derived vars |
| `v_*` | `v_*` (keep) | Vault secrets |
| `t_*` | `t_*` (keep) | Task temporaries |
| New: `h_*` | `h_*` | Host-specific vars in host_vars/ |

#### C. Unified Playbook Architecture

Replace `main.yml` + `pi_main.yml` with a structured approach:

```
site.yml                    # Master entry point - imports all plays
playbooks/
  setup_infrastructure.yml  # Layer 0-1: system, users, storage, docker
  deploy_services.yml       # Layer 2: all app deployments
  setup_observability.yml   # Cross-cutting: monitoring on any host
```

**`site.yml`** (master):
```yaml
---
# Run everything: ansible-playbook site.yml
# Run one host: ansible-playbook site.yml --limit homeserver
# Run one service: ansible-playbook site.yml --tags immich

- import_playbook: playbooks/setup_infrastructure.yml
- import_playbook: playbooks/deploy_services.yml
- import_playbook: playbooks/setup_observability.yml
```

**`playbooks/setup_infrastructure.yml`**:
```yaml
---
# Common setup for ALL hosts
- hosts: all
  tasks:
    - import_role: init_setup
      tags: [setup, init]
    - import_role: setup_users
      tags: [setup, users]

# ZFS hosts get pool setup
- hosts: zfs_hosts
  tasks:
    - import_role: setup_pools
      tags: [setup, zfs]

# Docker hosts get Docker + proxy + auth
- hosts: docker_hosts
  tasks:
    - import_role: setup_docker
      tags: [setup, docker]
    - import_role: setup_socket_proxy
      tags: [setup, docker]
    - import_role: setup_proxy
      tags: [setup, proxy]
    - import_role: deploy_authentik
      tags: [setup, auth]
```

**`playbooks/deploy_services.yml`**:
```yaml
---
# Docker Compose apps - only on docker_hosts
- hosts: docker_hosts
  tasks:
    - name: Deploy simple apps from registry
      include_role:
        name: deploy_app
      vars:
        app_name: "{{ item.key }}"
        app: "{{ item.value }}"
      loop: "{{ apps_registry | dict2items }}"
      when: apps_filter is not defined or item.key in apps_filter
      tags: [applications]

    - name: Deploy complex apps
      # Individual import_role blocks for immich, opencloud, etc.

# Bare-metal services
- hosts: bare_metal
  tasks:
    - import_role: deploy_pihole
      tags: [pihole]
      when: "'pi4b' in group_names"
```

#### D. Role Taxonomy

```
roles/
  # LAYER 0: System foundation (any host)
  init_setup/                 # System checks, packages, aliases
  setup_users/                # User/group creation

  # LAYER 1: Storage & platform (host-type specific)
  setup_zfs/                  # ZFS pools (was setup_pools)
  setup_docker/               # Docker daemon + networking
  setup_smb/                  # Samba file sharing

  # LAYER 2: Infrastructure services (run once, used by many)
  deploy_authentik/           # SSO (complex - keeps own role)
  setup_proxy/                # Reverse proxy
  setup_socket_proxy/         # Docker socket proxy

  # LAYER 3: Generic app deployer
  deploy_app/                 # Generic role driven by app registry
    tasks/main.yml
    templates/compose.yml.j2  # Default compose template
    templates/.env.j2         # Default env template

  # LAYER 3: Complex apps (keep individual roles)
  deploy_immich/              # Photo management (ML, multi-service)
  deploy_opencloud/           # Cloud suite (5+ config files)
  deploy_backrest/            # Backup (rclone config)
  deploy_hoarder/             # Bookmarking (permission fixes)
  deploy_paperless/           # Documents (multi-service)
  deploy_jellyfin/            # Media (GPU passthrough)
  deploy_pihole/              # DNS (bare-metal, Pi-specific)

  # OBSERVABILITY (cross-cutting)
  setup_observability/        # Prometheus/Loki/Grafana

  # DEPRECATED (delete)
  deploy_pihole_old/          # Superseded
  setup_proxy_v2/             # Unused Caddy alternative
  setup_timemachine/          # Never deployed
```

Apps that collapse into the generic `deploy_app` role (~18):
`changedetection`, `dockge`, `forgejo`, `ghostfolio`, `glance`, `grist`, `homepage`, `koillection`, `kopia`, `linkwarden`, `mealie`, `n8n`, `planka`, `portainer`, `readeck`, `semaphore`, `silverbullet`, `stirling_pdf`, `wallos`

#### E. Adding a New Machine (Proxmox Example)

With the new architecture, adding Proxmox requires:

1. Add to inventory under `proxmox_hosts` group
2. Create `host_vars/proxmox01.yml` with machine-specific vars
3. Create `group_vars/proxmox_hosts.yml` if shared settings exist
4. Add a play in `playbooks/setup_infrastructure.yml`:
   ```yaml
   - hosts: proxmox_hosts
     tasks:
       - import_role: setup_proxmox
         tags: [setup, proxmox]
   ```
5. Create `roles/setup_proxmox/` for Proxmox-specific setup

No existing playbooks need modification. No variable conflicts.

---

## Migration Path

### Phase 1: Quick Wins (no structural change)
1. Fix ghostfolio broken `{{ }}` variable references in `main.yml:254-257`
2. Delete unused roles: `deploy_pihole_old`, `setup_proxy_v2`, `setup_timemachine`
3. Delete unused variable `g_cloudflare_domain`
4. Move hardcoded DB passwords to `.env` (paperless, forgejo)
5. Clean `.DS_Store` files from git

### Phase 2: Variable Restructuring
1. Create `host_vars/homeserver.yml` - move `g_pools`, `g_hostname`
2. Create `group_vars/docker_hosts.yml` - move `g_apps_user`, `g_smb_user`
3. Slim down `group_vars/all.yml` to truly global vars only
4. Update role references to match new variable locations

### Phase 3: App Registry
1. Create `vars/apps/` directory with app definitions
2. Create `roles/deploy_app/` generic deploy role
3. Migrate simplest apps first (readeck, wallos, silverbullet)
4. Gradually migrate more apps, keeping complex ones as individual roles
5. Remove empty role directories after migration

### Phase 4: Playbook Unification
1. Create `site.yml` + `playbooks/` directory
2. Split `main.yml` into infrastructure + services playbooks
3. Absorb `pi_main.yml` into the unified structure
4. Update inventory with functional groups
5. Test with `--limit` to verify host targeting works

### Phase 5: Future Machines
1. When adding Proxmox: create group, host_vars, and setup role
2. Observability can target multiple hosts via group membership
3. Backup roles can run on any host with the right group

---

## Also Fix (from code review)

These are the bugs and quality issues from the initial review that should be addressed alongside the architecture work:

- **CRITICAL**: `main.yml:254-257` - ghostfolio vars missing `{{ }}`
- **HIGH**: Hardcoded DB passwords in paperless and forgejo compose files
- **HIGH**: 32 hardcoded domain URLs in `deploy_glance/files/services.yml` (templateize)
- **MEDIUM**: Deprecated `apt_key` module in 3 roles
- **MEDIUM**: Deprecated `systemd` module in 2 roles
- **MEDIUM**: `gfl_posgres_version` typo in ghostfolio defaults
- **MEDIUM**: `:latest` tag on node-exporter in observability
- **LOW**: Commented code in `deploy_linkwarden/tasks/main.yml`
- **LOW**: Duplicate cronicle task files in `init_setup`

---

## Verification

After each phase:
- `ansible-lint` passes
- `ansible-playbook site.yml --syntax-check` passes
- `ansible-playbook site.yml --check --limit homeserver` runs without errors
- `ansible-playbook site.yml --check --limit pi4b` runs without errors
- `grep -r "mrmodest.duckdns.org" roles/` returns only templates (no hardcoded domains)
- `grep -r "placeholder" roles/*/defaults/` is documented/expected
- Individual app deployment still works: `ansible-playbook site.yml --tags immich --limit homeserver`
