# Docker proxy

This role runs a read-only Docker API proxy on the Caddy network. The endpoint is available at `docker.modestlab.dev` and the corresponding DuckDNS domain. It has no authentication by choice, so anyone who can reach either Caddy domain can access the API and its container information.
