# CLI Proxy API Role

## Overview

Turns a ChatGPT/Codex subscription into a local OpenAI-compatible API, with a
management panel and a chat UI on top. Three containers in one compose stack:

- **[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)** (`cli-proxy-api`)
  logs into ChatGPT with OAuth and re-exposes the subscription as
  OpenAI-, Gemini- and Claude-compatible HTTP endpoints on `:8317`. No OpenAI
  API key is involved; requests are billed against the subscription's quota.
- **[CPA-Manager-Plus](https://github.com/seakee/CPA-Manager-Plus)** (`cpa-manager-plus`)
  on `:18317` — usage statistics, cost estimates, per-request monitoring and
  account/quota health. It reads CLIProxyAPI's Management API and usage queue;
  it does not proxy model traffic itself.
- **[Open WebUI](https://github.com/open-webui/open-webui)** (`open-webui`) on
  `:8080` — a ChatGPT-like interface pointed at the proxy as if it were OpenAI.

```
open-webui ──┐
coding CLIs ─┼──> cli-proxy-api :8317 ──> ChatGPT / Codex (OAuth)
             │           ^
      cpa-manager-plus :18317
```

`cpa-net` carries traffic between the three; Caddy reaches each of them over
`nginxnetwork` and serves them as `cliproxy.`, `cpamp.` and `chat.` on the
domains in `vars/apps.yml`.

## Role Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `cpa_cliproxy_version` | `v7.2.141` | CLIProxyAPI image tag. CPAMP needs `v7.1.39+` |
| `cpa_manager_version` | `v1.12.3` | CPA-Manager-Plus image tag |
| `cpa_open_webui_version` | `v0.11.0` | Open WebUI image tag |
| `cpa_open_webui_host` | placeholder | Public hostname, used for `WEBUI_URL` |
| `cpa_management_key` | placeholder | CLIProxyAPI Management API key; CPAMP authenticates with it |
| `cpa_api_key` | placeholder | Client key for the proxy's API — Open WebUI and any CLI send this |
| `cpa_manager_admin_key` | placeholder | Logs into the CPAMP panel |
| `cpa_open_webui_secret_key` | placeholder | Signs Open WebUI's JWTs |
| `cpa_open_webui_enable_signup` | `true` | Leave open until the admin account exists, then set to `false` |
| `cpa_codex_auth_src` | `''` | Optional: path (on the Ansible control machine) to a Codex credential JSON, seeded into `auths/` on first deploy |
| `cpa_codex_auth_name` | `codex.json` | Filename for the seeded credential |

The four secrets come from `v_cliproxy.*` in `vars/vault.yml`:

```yaml
v_cliproxy:
  management_key: '...'
  api_key: '...'
  manager_admin_key: '...'
  open_webui_secret_key: '...'
```

Generate them with `openssl rand -hex 32` (any opaque string works).

## Deploy

```bash
ansible-playbook main.yml --tags cliproxy
```

## Log in to the ChatGPT account (one-time)

Nothing works until an account is logged in — the proxy starts fine with zero
credentials and simply serves an empty model list.

OpenAI's OAuth client for Codex (`app_EMoamEEZ73f0CkXaXp7hrann`) has exactly one
registered redirect URI, `http://localhost:1455/auth/callback`, and it cannot be
changed. The management panel's `?is_webui=true` flow does not help here: it
returns the same `redirect_uri`. So the browser that completes the login must be
able to reach *something* on its own `localhost:1455`. Two ways to arrange that
without publishing a port on the server.

### A. Seed a credential from elsewhere (unattended)

Log in on a machine where the browser and the callback listener are the same
host — your laptop, using the Codex CLI or a throwaway local CLIProxyAPI — then
move the resulting credential JSON to the server. No interactive step on the
server at all.

Either drop it straight into the bind mount, where CLIProxyAPI's directory
watcher picks it up within seconds, no restart needed:

```bash
scp codex.json homessh@192.168.178.34:/tmp/
sudo install -o apps -g apps -m 0600 /tmp/codex.json \
  /mnt/pools/fast/apps-data/cliproxy/cli-proxy-api/auths/
```

…or upload it through the Management API, which registers it immediately:

```bash
curl -X POST -F 'file=@codex.json' \
  -H "Authorization: Bearer $CPA_MANAGEMENT_KEY" \
  https://cliproxy.<domain>/v0/management/auth-files
```

…or let this role place it, by pointing it at the file on the machine you run
Ansible from:

```bash
ansible-playbook main.yml --tags cliproxy -e cpa_codex_auth_src=~/.codex/auth.json
```

The task writes it with `force: false`, and the file is deliberately referenced
by path rather than stored in the vault. CLIProxyAPI refreshes the OAuth token
every 15 minutes and rewrites the file, so a vaulted copy would be stale almost
immediately — and if the provider rotates refresh tokens, invalid rather than
merely old. Treat the credential as runtime state, not configuration: it lives
in `auths/`, and the thing that protects it is your backup of that dataset, not
`vault.yml`. To re-seed, delete the file on the server first.

### B. Log in interactively, still with no published port

The callback listener binds `0.0.0.0:1455` *inside the container* and only
exists while a login is in flight. The host can reach it directly on the
container's bridge address, so tunnel to that rather than to a published port:

```bash
# On your laptop — leave running for the whole login
CPA_IP=$(ssh homessh@192.168.178.34 \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' cli-proxy-api | awk '{print \$1}'")
ssh -L 1455:$CPA_IP:1455 homessh@192.168.178.34
```

Then, in that SSH session:

```bash
cd /mnt/pools/fast/docker/compose-files/cliproxy
docker compose exec cli-proxy-api /CLIProxyAPI/CLIProxyAPI -no-browser --codex-login
```

Open the printed URL in your laptop's browser and finish the ChatGPT login; the
redirect to `localhost:1455` follows the tunnel into the container. The
container's bridge IP changes when the container is recreated, hence looking it
up each time.

Either way the credential lands in `auths/`, which is bind-mounted, so it
survives restarts and image upgrades. Add more accounts the same way and
CLIProxyAPI load-balances across them.

Other providers use their own callback ports (Gemini 8085, AI Studio 54545,
Antigravity 51121, Claude 11451) and would need the same treatment.

## Verify

```bash
# From the server: no key -> 401, valid key -> the account's models
curl -s -o /dev/null -w '%{http_code}\n' http://cli-proxy-api:8317/v1/models
curl -s -H "Authorization: Bearer $CPA_API_KEY" http://cli-proxy-api:8317/v1/models

# CPAMP's collector should report the CPA upstream and a running collector
curl -s -H "Authorization: Bearer $CPA_MANAGER_ADMIN_KEY" \
  http://cpa-manager-plus:18317/status
```

An empty `{"data":[],"object":"list"}` from `/v1/models` means the proxy is
healthy but no account is logged in yet.

## Using it

- **Open WebUI**: `https://chat.<domain>`. The first account to sign up becomes
  the admin; set `cpa_open_webui_enable_signup: false` in `main.yml` afterwards
  and re-run.
- **CPAMP**: `https://cpamp.<domain>/management.html`, log in with
  `cpa_manager_admin_key`. The CPA connection is supplied through the
  environment, so there is no setup wizard to walk.
- **CLIProxyAPI's own panel**: `https://cliproxy.<domain>/management.html`, log
  in with `cpa_management_key`.
- **Coding CLIs**: point them at `https://cliproxy.<domain>/v1` with
  `cpa_api_key` as the API key.

## Notes

- **Open WebUI runs with `ENABLE_PERSISTENT_CONFIG=False`**, so this role stays
  the source of truth for its settings. The trade-off: settings changed in its
  admin UI look like they save but are discarded on restart. Change them here.
- **CLIProxyAPI's management panel can rewrite `config.yaml`** at runtime. That
  file is templated from this role, so any such change is reverted on the next
  playbook run.
- **`auth-dir` is set to `/CLIProxyAPI/auths`**, not the default
  `~/.cli-proxy-api`. Upstream's examples mount the credentials into root's
  home; there is no requirement to, and keeping every mount under the app's own
  directory is what lets the container run as a non-root user.
- **`config.yaml` is mode `0600`**, not the repo-wide `0644`: it holds both the
  management key and the client API key.
- **All three containers run as the `apps` user**, even though all three images
  default to root. Two environment variables make that possible and must not be
  dropped: `MANAGEMENT_STATIC_PATH` (cli-proxy-api), without which the
  management panel asset cannot be written and `/management.html` returns 404;
  and `STATIC_DIR` (open-webui), without which it cannot seed its branding
  assets and logs a permission error per file on every start. `cpa-manager-plus`
  needs nothing beyond a writable `/data`.
- **If you ever deployed this stack as root**, files already written into
  `apps-data/cliproxy/` are root-owned and the non-root containers will fail on
  them. `chown -R apps:apps` that tree once; `compose_up.yml` only creates
  directories that do not already exist, so it will not fix ownership for you.
- **No container publishes a host port.** Everything is reached through Caddy
  over `nginxnetwork`, including the Management API. Keep it that way — the
  management key is the only thing guarding config and credential access.
- **Back up `cpa-manager-plus/data.key` together with `usage.sqlite`.** The key
  decrypts the CPA management key stored in the database; without it the panel's
  saved connection cannot be recovered.
