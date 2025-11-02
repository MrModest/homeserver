# Traefik Reverse Proxy Role

## Overview

This role deploys [Traefik v3](https://traefik.io/), a modern HTTP reverse proxy and load balancer. It's configured to run **alongside** Nginx Proxy Manager (not as a replacement) using different ports, allowing gradual migration or parallel operation of both proxies.

## Architecture

### Port Allocation

To coexist with Nginx Proxy Manager:

| Service | HTTP | HTTPS | Dashboard/Admin |
|---------|------|-------|-----------------|
| Nginx Proxy Manager | 80 | 443 | 81 |
| **Traefik** | **8080** | **8443** | **8081** |

### Network Architecture

- **traefik-public**: Bridge network for Traefik and backend services
- **socket-proxynet**: Internal network connecting Traefik to Docker socket proxy

### Security Features

1. **Docker Socket Proxy**: Traefik connects to Docker via socket-proxy (not direct socket mount)
2. **File-based Configuration**: Static config in `/etc/traefik/traefik.yml`, dynamic config in `/etc/traefik/dynamic/`
3. **No Docker Labels**: All routing configured in files (as requested)
4. **Automatic HTTPS**: Let's Encrypt certificates via DNS challenge (DuckDNS)
5. **Security Headers**: Predefined middleware for common security headers
6. **Rate Limiting**: Built-in middleware to prevent abuse

## Requirements

- Docker Socket Proxy (`setup_socket_proxy` role) must be deployed first
- DuckDNS domain and API token
- Valid email for Let's Encrypt notifications

## Role Variables

### Required Variables (from vault)

| Variable | Description | Example |
|----------|-------------|---------|
| `tfk_duckdns_token` | DuckDNS API token for DNS challenge | From `v_duckdns.api_token` |
| `tfk_acme_email` | Email for Let's Encrypt notifications | From `v_traefik.acme_email` |

### Optional Variables (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `tfk_version` | `v3.2` | Traefik Docker image version |
| `tfk_log_level` | `INFO` | Log level: DEBUG, INFO, WARN, ERROR |
| `tfk_network` | `traefik-public` | Docker network name for Traefik |
| `tfk_domain` | `mrmodest.duckdns.org` | Base domain for services |
| `tfk_acme_staging` | `false` | Use Let's Encrypt staging (for testing) |
| `tfk_cert_resolver` | `letsencrypt` | Certificate resolver name |
| `tfk_enable_https_redirect` | `true` | Redirect HTTP to HTTPS |
| `tfk_dashboard_host` | `traefik.{{ tfk_domain }}` | Dashboard hostname |
| `tfk_dashboard_auth_enabled` | `false` | Enable basic auth for dashboard |

## Configuration Files

### Static Configuration (`traefik.yml`)

Located at: `/mnt/pools/fast/apps-data/traefik/traefik/traefik.yml`

Defines:
- Entrypoints (web:8080, websecure:8443, traefik:8081)
- Docker provider (via socket-proxy)
- File provider (for manual configs)
- Let's Encrypt certificate resolver (DuckDNS DNS challenge)
- Prometheus metrics endpoint
- API/Dashboard

### Dynamic Configuration (`dynamic.yml`)

Located at: `/mnt/pools/fast/apps-data/traefik/traefik/dynamic/dynamic.yml`

Defines:
- Middlewares (security headers, rate limiting, auth)
- Manual routers and services
- Dashboard router configuration

This file is watched for changes and hot-reloaded.

## Usage Examples

### Basic Deployment

```yaml
- name: Setup Traefik reverse proxy
  ansible.builtin.import_role:
    name: setup_traefik
  vars:
    tfk_duckdns_token: '{{ v_duckdns.api_token }}'
    tfk_domain: '{{ g_duckdns_domain }}'
    tfk_acme_email: 'admin@example.com'
```

### Enable Dashboard Authentication

```yaml
- name: Setup Traefik reverse proxy
  ansible.builtin.import_role:
    name: setup_traefik
  vars:
    tfk_duckdns_token: '{{ v_duckdns.api_token }}'
    tfk_domain: '{{ g_duckdns_domain }}'
    tfk_acme_email: 'admin@example.com'
    tfk_dashboard_auth_enabled: true
    tfk_dashboard_user: 'admin'
    tfk_dashboard_password_hash: '$apr1$...'  # htpasswd hash
```

Generate password hash:
```bash
echo $(htpasswd -nB admin) | sed -e s/\\$/\\$\\$/g
```

### Testing with Staging Certificates

```yaml
- name: Setup Traefik reverse proxy
  ansible.builtin.import_role:
    name: setup_traefik
  vars:
    tfk_duckdns_token: '{{ v_duckdns.api_token }}'
    tfk_domain: '{{ g_duckdns_domain }}'
    tfk_acme_email: 'admin@example.com'
    tfk_acme_staging: true  # Use staging to avoid rate limits
```

## Configuring Services

Since Docker labels are disabled (`exposedByDefault: false`), you must configure routes manually in `dynamic.yml`.

### Example: Adding a Service

Edit `/mnt/pools/fast/apps-data/traefik/traefik/dynamic/dynamic.yml`:

```yaml
http:
  routers:
    myapp:
      rule: "Host(`myapp.mrmodest.duckdns.org`)"
      entryPoints:
        - websecure
      service: myapp-service
      middlewares:
        - security-headers
        - rate-limit
      tls:
        certResolver: letsencrypt

  services:
    myapp-service:
      loadBalancer:
        servers:
          - url: "http://myapp:8080"  # Container name or IP
```

Traefik will automatically reload this file within seconds.

### Example: External Service (IP-based)

```yaml
http:
  routers:
    external-app:
      rule: "Host(`external.mrmodest.duckdns.org`)"
      entryPoints:
        - websecure
      service: external-service
      tls:
        certResolver: letsencrypt

  services:
    external-service:
      loadBalancer:
        servers:
          - url: "http://192.168.178.100:3000"
```

### Available Middlewares

Predefined in `dynamic.yml`:

- **security-headers**: Standard security headers (HSTS, X-Frame-Options, etc.)
- **rate-limit**: 100 requests/second average, 50 burst
- **dashboard-auth**: Basic auth for dashboard (if enabled)

## Accessing Traefik

| Endpoint | URL | Description |
|----------|-----|-------------|
| Dashboard | `https://traefik.mrmodest.duckdns.org:8443` | Web UI |
| API | `http://192.168.178.34:8081/api` | REST API |
| Metrics | `http://192.168.178.34:8081/metrics` | Prometheus metrics |
| Ping | `http://192.168.178.34:8081/ping` | Health check |

## Monitoring

### Prometheus Integration

Traefik exposes metrics on the `traefik` entrypoint (port 8081):

```yaml
# Prometheus scrape config
scrape_configs:
  - job_name: 'traefik'
    static_configs:
      - targets: ['traefik:8081']
```

Metrics include:
- Request count, duration, size
- Entrypoint statistics
- Service/router status
- TLS certificate expiry

### Health Checks

```bash
# Health check endpoint
curl http://192.168.178.34:8081/ping

# Docker health check (built-in)
docker inspect traefik | grep -A5 Health
```

## Deployment Tags

```bash
# Deploy Traefik
ansible-playbook main.yml --tags traefik

# Deploy as part of server init
ansible-playbook main.yml --tags server_init
```

## Migration from Nginx Proxy Manager

Since both proxies run on different ports, you can migrate gradually:

1. **Phase 1**: Deploy Traefik, keep NPM running
2. **Phase 2**: Configure new services in Traefik's `dynamic.yml`
3. **Phase 3**: Test services on port 8443 (`https://app.domain.com:8443`)
4. **Phase 4**: Update router port forwarding from 443→8443
5. **Phase 5**: Remove NPM when all services migrated

Or run both indefinitely for different use cases.

## Troubleshooting

### Check Traefik logs

```bash
docker logs traefik -f
```

### Verify socket-proxy connectivity

```bash
# From Traefik container
docker exec traefik wget -O- http://socket-proxy:2375/version
```

### Test certificate issuance

1. Set `tfk_acme_staging: true` initially
2. Check logs for ACME challenge success
3. Verify certificate: `docker exec traefik cat /letsencrypt/acme.json`
4. Switch to production when working

### Common Issues

**"Cannot connect to socket-proxy"**
- Ensure `setup_socket_proxy` role ran successfully
- Check `sp_allowfrom` includes `traefik` hostname
- Verify both containers on `socket-proxynet` network

**"Rate limit exceeded" (Let's Encrypt)**
- Use `tfk_acme_staging: true` for testing
- Production rate limit: 50 certs/week per domain
- Delete `/letsencrypt/acme.json` to reset

**"Dynamic config not loading"**
- Check file syntax: `docker exec traefik cat /etc/traefik/dynamic/dynamic.yml`
- Watch logs for reload messages
- Ensure file permissions are correct (0644)

## Security Considerations

1. **Dashboard Access**: By default accessible on port 8081. Consider:
   - Enabling `tfk_dashboard_auth_enabled` with strong password
   - Restricting port 8081 via firewall (internal only)
   - Using Tailscale for secure remote access

2. **DuckDNS Token**: Stored in vault as `v_duckdns.api_token`
   - Required for DNS challenge
   - Keep encrypted in `vars/vault.yml`

3. **Certificate Storage**: `/letsencrypt/acme.json` contains private keys
   - Permissions: 0600
   - Backed up with ZFS snapshots

4. **Socket Proxy**: Never expose directly
   - Traefik connects via internal network only
   - Read-only access to Docker API

## Files Structure

```
roles/setup_traefik/
├── README.md                      # This file
├── defaults/
│   └── main.yml                   # Default variables
├── files/
│   └── compose.yml                # Docker Compose config
├── handlers/
│   └── main.yml                   # Restart handler
├── tasks/
│   └── main.yml                   # Role tasks
└── templates/
    ├── .env.j2                    # Environment variables
    ├── traefik.yml.j2             # Static configuration
    └── dynamic.yml.j2             # Dynamic configuration
```

## References

- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [DuckDNS DNS Challenge](https://go-acme.github.io/lego/dns/duckdns/)
- [Traefik File Provider](https://doc.traefik.io/traefik/providers/file/)
- [Let's Encrypt Rate Limits](https://letsencrypt.org/docs/rate-limits/)
