# Docker Socket Proxy Role

## Overview

This role deploys [wollomatic/socket-proxy](https://github.com/wollomatic/socket-proxy), a lightweight, secure-by-default Docker socket proxy. It provides an additional security layer between Docker-dependent applications (like Traefik, Portainer, Dozzle, Watchtower) and the Docker socket.

## Why Use Socket Proxy?

Exposing the Docker socket (`/var/run/docker.sock`) directly to containers is a security risk, as it grants full control over the Docker daemon. Socket proxy mitigates this by:

- **Fine-grained access control**: Allow only specific API endpoints via regex patterns
- **IP/hostname filtering**: Restrict which containers can connect
- **Read-only by default**: Mounted socket is read-only
- **Method-based filtering**: Control GET, POST, HEAD requests independently
- **Minimal attack surface**: Runs as `nobody` user with all capabilities dropped
- **Zero external dependencies**: Built from-scratch image using only Go stdlib

## Architecture

The role creates:
- A dedicated bridge network `socket-proxynet` (internal only)
- Socket proxy container listening on port 2375 within that network
- Health checks and watchdog monitoring for reliability

Applications that need Docker socket access should:
1. Connect to `socket-proxy:2375` instead of mounting `/var/run/docker.sock`
2. Join the `socket-proxynet` network
3. Be explicitly allowed via `sp_allowfrom` parameter

## Requirements

- Docker and Docker Compose V2 installed (via `setup_docker` role)
- User in the `docker` group (role fetches GID automatically)

## Role Variables

All variables are optional with secure defaults. The Docker group ID is fetched automatically by the role.

### Optional Variables (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `sp_version` | `1.10.0` | Socket proxy image version |
| `sp_loglevel` | `info` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `sp_allowfrom` | `127.0.0.1/32` | Comma-separated hostnames or IP networks allowed to connect |
| `sp_allow_get` | `/v1\..{1,2}/(version\|containers/.*\|networks/.*\|services/.*\|tasks/.*\|nodes/.*\|events.*)` | Regex for allowed GET requests |
| `sp_allow_head` | `.*` | Regex for allowed HEAD requests |
| `sp_allow_post` | `` (empty) | Regex for allowed POST requests |
| `sp_watchdog_interval` | `3600` | Socket availability check interval (seconds) |

## Usage Examples

### Basic Setup (Default - Very Restrictive)

```yaml
- name: Setup Docker socket proxy
  ansible.builtin.import_role:
    name: setup_socket_proxy
```

This creates a proxy that only allows localhost connections - not very useful in practice but secure by default.

### Allow Specific Containers (Recommended)

```yaml
- name: Setup Docker socket proxy
  ansible.builtin.import_role:
    name: setup_socket_proxy
  vars:
    sp_allowfrom: 'portainer,traefik,dozzle'
```

This allows only containers named `portainer`, `traefik`, and `dozzle` to connect.

### Enable Container Management (POST requests)

```yaml
- name: Setup Docker socket proxy
  ansible.builtin.import_role:
    name: setup_socket_proxy
  vars:
    sp_allowfrom: 'portainer'
    sp_allow_post: '/v1\..{1,2}/(containers/.*/start|containers/.*/stop|containers/.*/restart|containers/.*/pause|containers/.*/unpause)'
```

This enables Portainer to start/stop/restart containers.

### Debug Mode

```yaml
- name: Setup Docker socket proxy
  ansible.builtin.import_role:
    name: setup_socket_proxy
  vars:
    sp_loglevel: 'debug'
    sp_allowfrom: 'portainer'
```

Enable debug logging to see all API calls and troubleshoot connection issues.

## Connecting Applications to Socket Proxy

### Example: Portainer

Instead of mounting the Docker socket directly:

```yaml
# DON'T DO THIS (insecure):
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Configure to use socket proxy:

```yaml
services:
  portainer:
    # ... other config ...
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
    networks:
      - nginxnetwork  # Your app network
      - socket-proxynet  # Socket proxy network
    # No docker.sock volume needed!

networks:
  nginxnetwork:
    external: true
  socket-proxynet:
    external: true
```

### Example: Traefik

```yaml
services:
  traefik:
    # ... other config ...
    command:
      - --providers.docker.endpoint=tcp://socket-proxy:2375
    networks:
      - traefik-public
      - socket-proxynet
    # No docker.sock volume needed!

networks:
  traefik-public:
    external: true
  socket-proxynet:
    external: true
```

## Security Considerations

1. **Never expose socket-proxy to the internet** - The network is marked `internal: true` for this reason
2. **Use hostname filtering** - Prefer `sp_allowfrom: 'container1,container2'` over IP ranges
3. **Minimize POST access** - Only enable write operations if absolutely necessary
4. **Regular updates** - Keep socket-proxy updated to latest version
5. **Audit logs** - Periodically check logs with `sp_loglevel: debug` to verify expected API usage

## Deployment Tags

```bash
# Deploy socket proxy as part of server init
ansible-playbook main.yml --tags socket_proxy

# Deploy socket proxy standalone
ansible-playbook main.yml --tags socket_proxy --skip-tags server_init
```

## Troubleshooting

### Container can't connect to socket-proxy

1. Check container is on `socket-proxynet` network:
   ```bash
   docker inspect <container_name> | grep socket-proxynet
   ```

2. Check container hostname is in allowlist:
   ```bash
   docker logs socket-proxy | grep "denied"
   ```

3. Verify endpoint configuration:
   ```bash
   # From inside container
   curl -s http://socket-proxy:2375/version
   ```

### Permission denied errors

- Ensure the role correctly fetched Docker GID
- Check socket-proxy container user: should be `65534:<docker_gid>`
- Verify `/var/run/docker.sock` is mounted read-only

### API endpoint blocked

- Check logs: `docker logs socket-proxy`
- Enable debug: Set `sp_loglevel: debug` and check what regex patterns are needed
- Adjust `sp_allow_get`, `sp_allow_post` patterns accordingly

## Files Structure

```
roles/setup_socket_proxy/
├── README.md                 # This file
├── defaults/
│   └── main.yml             # Default variables
├── files/
│   └── compose.yml          # Docker Compose file
├── tasks/
│   └── main.yml             # Role tasks
└── templates/
    └── .env.j2              # Environment template
```

## References

- [wollomatic/socket-proxy GitHub](https://github.com/wollomatic/socket-proxy)
- [Docker Socket Security Best Practices](https://docs.docker.com/engine/security/)
- [Go Regexp Syntax](https://golang.org/pkg/regexp/syntax/) (for pattern matching)
