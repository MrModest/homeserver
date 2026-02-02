# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an Ansible-based home server configuration project that automates the deployment and management of a self-hosted infrastructure running on Ubuntu Server 22.04 LTS. The server uses ZFS storage pools and Docker Compose to run 25+ applications including Immich, Paperless, Jellyfin, Portainer, and more.

## Common Commands

### Running Playbooks

```bash
# Deploy full home server configuration
ansible-playbook main.yml

# Deploy specific application using tags
ansible-playbook main.yml --tags immich
ansible-playbook main.yml --tags paperless
ansible-playbook main.yml --tags observability

# Deploy to Raspberry Pi (Pi-hole, Tailscale)
ansible-playbook pi_main.yml

# Check mode (dry run)
ansible-playbook main.yml --check

# Deploy only environment setup (users, pools, docker, proxy)
ansible-playbook main.yml --tags server_init
```

### Common Tags
- `server_init` - Initial server setup (users, ZFS, Docker, proxy)
- `applications` - All application deployments
- `[app_name]` - Individual apps (immich, paperless, jellyfin, etc.)
- `observability` - Prometheus, Loki, Grafana stack
- `reverse_proxy` - Nginx proxy with DuckDNS
- `docker` - Docker daemon setup
- `samba` - SMB file sharing
- `zfs_pools` - ZFS pool creation

### Installing Dependencies

```bash
# Install Ansible collections and roles
ansible-galaxy install -r requirements.yml
```

## Architecture

### Variable Hierarchy

Variables follow a strict naming convention:

- **`g_*` (Global)**: Defined in `group_vars/all.yml`. Infrastructure-wide settings like pools, users, IPs, timezone.
- **`v_*` (Vault)**: Defined in `vars/vault.yml`. Encrypted secrets (passwords, API tokens). Uses `.vault_pass` file.
- **`p_*` (Playbook)**: Defined in playbook `vars` section. Playbook-scoped runtime variables.
- **`[role]_*` (Role)**: Defined in `roles/[role]/defaults/main.yml`. Role-specific input parameters.
- **`t_*` (Task)**: Temporary variables used within tasks.

### Storage Architecture

The server uses ZFS pools with specific purposes:

- **`fast`** (SSD mirror): High-performance pool for app data, Docker root, compose files
  - Path: `/mnt/pools/fast`
  - Structure: `apps-data/[app]`, `docker/data-root`, `docker/compose-files`

- **`slow`** (HDD mirror): Large storage for media, backups, SMB shares
  - Path: `/mnt/pools/slow`
  - Structure: `apps-data/[app]`, `backups/`, `shared/`

### User Architecture

Three specialized system users:

- **`apps`** (UID/GID fetched dynamically): Runs all non-privileged containers
- **`homessh`**: SSH access user
- **`sambashare`**: SMB share access user

### Docker Architecture

- Data root: `/mnt/pools/fast/docker/data-root` (not `/var/lib/docker`)
- Compose files: `/mnt/pools/fast/docker/compose-files/[app]/`
- Storage driver: overlay2 (ZFS native driver not needed since ZFS 2.0)
- Logging: json-file driver for Loki/Promtail integration
- Metrics: Docker metrics exposed on port 9323 for Prometheus

### Role Structure

Roles follow two main patterns:

1. **`deploy_*` roles**: Application deployments using the common deployment flow
2. **`setup_*` roles**: Infrastructure setup (pools, docker, proxy, users)

### Common Deployment Flow

Most `deploy_*` roles use the shared task file `tasks/compose_up.yml` which:

1. Creates ZFS dataset at `[pool]/apps-data/[app]`
2. Creates data directories with proper ownership (apps user/group)
3. Creates compose directory at `/mnt/pools/fast/docker/compose-files/[app]/`
4. Copies `compose.yml` from role's `files/`
5. Templates `.env` file from `.env.j2` in role's `templates/`
6. Fetches UIDs/GIDs for `apps` and `sambashare` users
7. Replaces user/group placeholders with actual UIDs/GIDs in `.env`
8. Runs `docker compose up` using `community.docker.docker_compose_v2`

Key convention: Each role sets `t_app_name` variable before importing `compose_up.yml`.

### Inventory

- `inventory.yml.example`: Template inventory file
- `inventory.yml`: Actual inventory (gitignored)
- Default host group: `homeserver`
- Pi group: `pi4b`

### Observability Stack

Located in `roles/setup_observability/`:
- **Prometheus**: Metrics collection (Docker metrics on :9323, app metrics)
- **Loki**: Log aggregation (Docker json-file logs)
- **Promtail**: Log shipper for host logs (`/var/log/*`)
- **Grafana**: Visualization dashboard

All containers use json-file logging driver for Loki integration.

### Reverse Proxy & DNS

- **Nginx Proxy Manager**: Reverse proxy with automatic HTTPS via Let's Encrypt
- **DuckDNS**: Dynamic DNS integration (domain in `g_duckdns_domain`)
- Apps exposed via subdomains: `[app].mrmodest.duckdns.org`
- Local DNS: Pi-hole (deployed on separate Pi4)

### Network Architecture

From `group_vars/all.yml`:
- Router: 192.168.178.1
- Home server: 192.168.178.34
- DNS (Pi-hole): 192.168.178.48
- Remote access: Tailscale VPN (no public exposure)

### Permissions Convention

- Files: `0644` (owner rw, group/other r)
- Directories: `0754` (owner rwx, group rx, other x)

## Important Notes

### Security

- **Never commit `vars/vault.yml`** - contains encrypted secrets
- **Never commit `inventory.yml`** - contains actual IP addresses
- **Never commit `.vault_pass`** - vault password file
- All secrets must use `v_*` variables from vault

### ZFS Datasets

Apps use dedicated ZFS datasets under `[pool]/apps-data/[app]` for:
- Snapshot capability
- Per-app quota management
- Independent backup/restore

### Environment Files

`.env` files are templated from roles' `templates/.env.j2` files. They contain:
- `APP_USER` and `APP_GROUP`: Replaced with actual UIDs/GIDs during deployment
- `SMB_USER` and `SMB_GROUP`: Samba user UIDs/GIDs
- App-specific variables (passwords, API keys from vault)

### Running vs Editing

- **Editing roles**: Modify files in `roles/[role]/`
- **Testing single app**: Use `ansible-playbook main.yml --tags [app_name]`
- **Adding new app**: Create new `deploy_[app]` role following the pattern in existing deploy roles
- **Secrets**: Use `ansible-vault edit vars/vault.yml` to modify encrypted variables

### Docker Compose Management

The playbook uses `community.docker.docker_compose_v2` module, which:
- Requires Docker Compose V2 (not legacy docker-compose)
- Automatically pulls images
- Recreates containers on config changes
- Does not run in check mode (`when: ansible_check_mode is false`)

### Main Playbook Structure

`main.yml` has two main sections:
1. Environment setup (`tasks/setup_environment.yml`) - runs first, sets up infrastructure
2. Application deployments - each as separate role import with app-specific variables from vault

## File Locations

- Global config: `group_vars/all.yml`
- Secrets: `vars/vault.yml` (encrypted)
- App configs: `vars/apps.yml`
- Main playbook: `main.yml`
- Pi playbook: `pi_main.yml`
- Shared tasks: `tasks/`
- Role definitions: `roles/*/`
- Documentation: `docs/Files Structure.md`
