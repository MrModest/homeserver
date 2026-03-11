# Homeserver Ansible Repository - Comprehensive Review

## Context

This is an Ansible-based home server configuration project that automates deployment of 25+ self-hosted Docker applications on Ubuntu Server 22.04 LTS with ZFS storage. It also manages a Raspberry Pi running Pi-hole/Tailscale. The review covers purpose alignment, code quality, dead code, and maintainability improvements.

---

## 1. Purpose & How Well It Serves It

**Purpose**: Infrastructure-as-code for a self-hosted home server with 25+ Docker apps, ZFS storage, observability, and reverse proxy.

**Strengths**:
- Well-structured role hierarchy with clear `deploy_*` / `setup_*` separation
- Shared `tasks/compose_up.yml` eliminates boilerplate across 27 deploy roles
- Strict variable naming convention (`g_*`, `v_*`, `p_*`, `t_*`) makes scope immediately clear
- ZFS-backed storage with per-app datasets enables snapshots and independent management
- Full observability stack (Prometheus, Loki, Grafana, Promtail, cAdvisor)
- Vault-encrypted secrets with clean separation from code
- `.fttemplates/` scaffolding for adding new apps quickly

**Weaknesses**:
- No CI/CD pipeline (no linting on push, no syntax validation)
- No automated testing or molecule tests
- Several roles exist but are never deployed (dead weight)
- A critical variable reference bug exists in production config

---

## 2. Code Quality Issues

### CRITICAL: Broken Variable References
**File**: `main.yml:254-257` (ghostfolio deployment)
```yaml
gfl_redis_password: v_ghostfolio.redis_password          # BUG: missing {{ }}
gfl_postgres_password: v_ghostfolio.postgres_password     # BUG: missing {{ }}
gfl_access_token_salt: v_ghostfolio.access_token_salt     # BUG: missing {{ }}
gfl_jwt_secret_key: v_ghostfolio.jwt_secret_key           # BUG: missing {{ }}
```
These pass literal strings instead of vault values. Should be `'{{ v_ghostfolio.redis_password }}'`, etc.

### HIGH: Hardcoded Database Passwords in Compose Files
- `roles/deploy_paperless/files/compose.yml:24` - `POSTGRES_PASSWORD: paperless`
- `roles/deploy_forgejo/files/compose.yml:33` - `POSTGRES_PASSWORD=forgejo`
These should reference `.env` variables from vault.

### HIGH: Hardcoded Domain in Glance Services
- `roles/deploy_glance/files/services.yml` - 32 hardcoded `mrmodest.duckdns.org` URLs
- Should be templated (convert to `.j2`) using `{{ p_base_domain }}`

### MEDIUM: Deprecated Ansible Modules
- `roles/setup_docker/tasks/main.yml` - `ansible.builtin.apt_key` (deprecated since 2.9)
- `roles/init_setup/tasks/install_node.yml` - same
- `roles/init_setup/tasks/install_eza.yml` - same
- `roles/deploy_pihole/handlers/main.yml` - `ansible.builtin.systemd` (use `systemd_service`)
- `roles/setup_timemachine/handlers/main.yml` - same

### MEDIUM: Variable Naming Typo
- `roles/deploy_ghostfolio/defaults/main.yml:2` - `gfl_posgres_version` (should be `postgres`)

### MEDIUM: Root-Running Containers (9 roles)
Some are justified (Docker socket access), but others should use `${APP_USER}:${APP_GROUP}`:
- `deploy_paperless`, `deploy_jellyfin` (2 containers), `deploy_wallos`, `deploy_semaphore`

### LOW: Inconsistent Jinja2 Spacing
- `roles/deploy_hoarder/templates/.env.j2:6` - `{{ hrdr_nextauth_secret}}` (missing trailing space)

---

## 3. Dead Code

### Unused Roles (never imported in any playbook)
| Role | Reason |
|------|--------|
| `deploy_pihole_old` | Superseded by `deploy_pihole` (bare metal) |
| `deploy_dockge` | Exists but not in `main.yml` |
| `deploy_kopia` | Exists but not in `main.yml` (backrest used instead) |
| `deploy_semaphore` | Exists but not in `main.yml` |
| `setup_proxy_v2` | Caddy alternative, not used (Nginx Proxy Manager active) |
| `setup_timemachine` | Never imported anywhere |

### Unused Variables
- `g_cloudflare_domain` in `group_vars/all.yml` - defined but never referenced

### Commented-Out Code
- `roles/deploy_linkwarden/tasks/main.yml:12-24` - Commented playwright workaround (also references wrong container name "hoarder_app")

### Duplicate Task Files
- `roles/init_setup/tasks/cronicle.yml` and `install_Cronicle.yml` - same purpose, inconsistent naming

### Stale Artifacts
- 20 `.DS_Store` files in role directories (in `.gitignore` but not cleaned from repo)

---

## 4. Maintainability Improvement Guide

### Priority 1: Fix Critical Bugs
1. **Fix ghostfolio variables** in `main.yml:254-257` - add `{{ }}` delimiters
2. **Move hardcoded DB passwords** to `.env` via vault variables (paperless, forgejo)

### Priority 2: Remove Dead Code
1. Delete unused roles: `deploy_pihole_old`, `setup_proxy_v2`, `setup_timemachine`
2. Decide on `deploy_dockge`, `deploy_kopia`, `deploy_semaphore` - deploy or delete
3. Remove `g_cloudflare_domain` from `group_vars/all.yml`
4. Clean commented code in `deploy_linkwarden/tasks/main.yml`
5. Consolidate `init_setup` cronicle task files
6. Run `git rm --cached` on `.DS_Store` files

### Priority 3: Templateize Hardcoded Values
1. Convert `roles/deploy_glance/files/services.yml` to a Jinja2 template using `{{ p_base_domain }}`
2. Replace hardcoded IPs in `deploy_pihole/defaults/main.yml` with references to `g_ips`

### Priority 4: Security Hardening
1. Add `security_opt: [no-new-privileges:true]` and `cap_drop: [ALL]` to compose files (currently only ghostfolio does this)
2. Add resource limits (`deploy.resources.limits`) to all compose services (currently only immich and mealie have them)
3. Review which root-running containers truly need root

### Priority 5: Module & Version Updates
1. Replace `apt_key` with `ansible.builtin.deb822_repository` or download GPG keys directly
2. Replace `ansible.builtin.systemd` with `ansible.builtin.systemd_service`
3. Pin `node-exporter` version in `setup_observability/files/compose.yml` (currently `:latest`)
4. Fix `gfl_posgres_version` typo

### Priority 6: Add Validation
1. Add `assert` tasks to roles that require vault variables:
   ```yaml
   - name: Validate required variables
     ansible.builtin.assert:
       that:
         - authk_secret_key != 'placeholder'
         - authk_pg_pass != 'placeholder'
       fail_msg: "Required vault variables not set"
   ```
2. This prevents silent failures from missing vault configuration

### Priority 7: CI/CD Pipeline
1. Add a GitHub Actions workflow with:
   - `ansible-lint` on push/PR
   - `yamllint` validation
   - `ansible-playbook --syntax-check main.yml`
   - Check for `placeholder` strings in non-vault files
2. Add pre-commit hooks (`.pre-commit-config.yaml`) for local linting

### Priority 8: Add Health Checks
Add Docker health checks to compose files missing them:
- `deploy_dockge`, `deploy_glance`, `deploy_grist`
- Follow the pattern used by other roles (e.g., `curl -f http://localhost:PORT/health`)

### Priority 9: Standardize Patterns
1. Ensure all `.env.j2` templates include `APP_USER` and `APP_GROUP` lines (currently missing in `deploy_hoarder`, `deploy_mealie`)
2. Standardize restart policy to `unless-stopped` everywhere (jellyfin's aria2 uses `always`)
3. Add `handlers/` with restart notifications for config template changes

### Priority 10: Documentation
1. Document which roles are intentionally unused vs. deprecated
2. Update `README.md` to clear stale "in progress" items
3. Add a `CONTRIBUTING.md` or section on how to add new apps using `.fttemplates/`

---

## Verification
- Run `ansible-lint` to catch additional issues
- Run `ansible-playbook main.yml --syntax-check` to validate syntax
- Run `ansible-playbook main.yml --check --tags ghostfolio` after fixing variables
- Grep for remaining hardcoded domains: `grep -r "mrmodest.duckdns.org" roles/`
- Grep for remaining `placeholder` values: `grep -r "placeholder" roles/*/defaults/`
