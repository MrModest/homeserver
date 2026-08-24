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

## Log in to the ChatGPT account (one-time, manual)

Nothing works until an account is logged in — the proxy starts fine with zero
credentials and simply serves an empty model list. The OAuth redirect always
targets `localhost:1455` on whatever machine runs the browser, so tunnel that
port to the server and log in from your own laptop:

```bash
# On your laptop — leave this running for the whole login
ssh -L 1455:localhost:1455 homessh@192.168.178.34
```

Then, in that SSH session:

```bash
cd /mnt/pools/fast/docker/compose-files/cliproxy
docker compose exec cli-proxy-api /CLIProxyAPI/CLIProxyAPI -no-browser --codex-login
```

Open the printed URL in your laptop's browser, complete the ChatGPT login, and
the redirect reaches the container through the tunnel. The credentials are
written to `auths/`, which is bind-mounted, so this survives restarts and image
upgrades. Repeat the command to add more accounts — CLIProxyAPI load-balances
across them.

Other providers use their own callback ports (Gemini 8085, AI Studio 54545,
Antigravity 51121, Claude 11451); publish those in `compose.yml` first if you
ever add those accounts.

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
- **`config.yaml` is mode `0600`**, not the repo-wide `0644`: it holds both the
  management key and the client API key.
- **None of the three containers set `user:`**. All three images run as root and
  manage their own data directories, so the repo's usual
  `user: '${APP_USER}:${APP_GROUP}'` is deliberately omitted.
- **Back up `cpa-manager-plus/data.key` together with `usage.sqlite`.** The key
  decrypts the CPA management key stored in the database; without it the panel's
  saved connection cannot be recovered.
