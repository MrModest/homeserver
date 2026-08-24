# CLI Proxy API Role

## Overview

Turns a ChatGPT/Codex subscription into a local OpenAI-compatible API, with a
management panel and a chat UI on top. Three containers in one compose stack:

- **[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)** (`cli-proxy-api`)
  logs into ChatGPT (and optionally Gemini, Claude, xAI, Kimi) with OAuth and
  re-exposes those subscriptions as OpenAI-, Gemini- and Claude-compatible HTTP
  endpoints on `:8317`. No provider API key is involved; requests are billed
  against each subscription's quota.
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
| `cpa_api_keys` | `{open-webui: placeholder}` | Client keys for the proxy's API, keyed by tool |
| `cpa_open_webui_api_key_name` | `open-webui` | Which entry Open WebUI authenticates with |
| `cpa_manager_admin_key` | placeholder | Logs into the CPAMP panel |
| `cpa_open_webui_secret_key` | placeholder | Signs Open WebUI's JWTs |
| `cpa_open_webui_enable_signup` | `true` | Leave open until the admin account exists, then set to `false` |

The four secrets come from `v_cliproxy.*` in `vars/vault.yml`:

```yaml
v_cliproxy:
  management_key: '...'
  api_keys:
    open-webui: 'owui-...'
    codex-cli: 'codex-...'
  manager_admin_key: '...'
  open_webui_secret_key: '...'
```

Generate them with `openssl rand -hex 32` (any opaque string works).

## Deploy

```bash
ansible-playbook main.yml --tags cliproxy
```

## Add provider accounts

Nothing works until at least one account is logged in — the proxy starts fine
with zero credentials and simply serves an empty model list. Accounts are
additive: CLIProxyAPI serves whatever the logged-in accounts expose, across
providers, and load-balances across accounts of the same provider.

### From the CPAMP panel

`https://cpamp.<domain>/management.html` → OAuth Login lists an entry per
provider (Codex, Claude, Antigravity, Kimi, xAI, iFlow, plus anything a plugin
adds). Click one, authorise in the provider's page, and the panel polls until
the credential is saved into `auths/`.

The provider redirects to `http://localhost:...`, which reaches nothing when the
proxy runs on the server. CPAMP handles that with its **remote browser
callback**: copy the *entire* URL out of the browser's address bar — the dead
one it just landed on — and paste it into the panel's callback URL field. Paste
it whole; extracting `code` or `state` by hand breaks state matching.

Treat that URL as a secret while you are moving it around: it carries the
authorisation code.

### Codex, from the container

The panel handles Codex too, through the same paste-back. To skip the copy-paste
entirely, the CLI has a device-code flow — no callback and no dead redirect, at
the cost of needing shell access to the container:

```bash
cd /mnt/pools/fast/docker/compose-files/cliproxy
docker compose exec cli-proxy-api /CLIProxyAPI/CLIProxyAPI -codex-device-login
```

It prints:

```
Starting Codex device authentication...
Codex device URL: https://auth.openai.com/codex/device
Codex device code: XXXX-XXXXX
```

Open that URL on any machine, enter the code, approve. The command returns once
authorised.

`-claude-login`, `-antigravity-login`, `-xai-login` and `-kimi-login` are the CLI
equivalents for the other providers, and `-oauth-callback-port` moves the
callback port for the flows that use one.

### By moving a credential file

CLIProxyAPI watches `auth-dir`, so a JSON file copied into `auths/` is registered
within seconds, and the Management API accepts one directly:

```bash
curl -X POST -F 'file=@codex.json' \
  -H "Authorization: Bearer $CPA_MANAGEMENT_KEY" \
  https://cliproxy.<domain>/v0/management/auth-files
```

Useful for moving an account between machines.

A successful login is not proof of a working account: send one cheap request
afterwards and confirm it lands in CPAMP's Monitoring view. Provider routing,
model rules and quota state can each still block a credential that authorised
cleanly.

However they arrive, credentials live in `auths/`, which is bind-mounted, so they
survive restarts and image upgrades. They are runtime state, not configuration:
CLIProxyAPI refreshes the OAuth tokens every 15 minutes and rewrites the files,
so what protects them is your backup of that dataset, not the vault.

Adding a second provider widens what every client sees — `/v1/models` returns the
union, and Open WebUI's model picker fills up accordingly. The client API keys
are not scoped per provider; anything holding a key can reach any logged-in
account.

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

## One key per tool

`api-keys` is a list, and CPAMP attributes every request to the key it arrived
with, so issuing a separate key per tool makes its usage, cost and failure
breakdowns separable. Add an entry per tool to `v_cliproxy.api_keys` and re-run:

```yaml
v_cliproxy:
  api_keys:
    open-webui: 'owui-...'
    codex-cli: 'codex-...'
    claude-code: 'cc-...'
```

Each renders into `config.yaml` with its name as a trailing comment, so the file
stays readable. Give the keys recognisable prefixes: CPAMP identifies a key by
its value, so `codex-<random>` is far easier to pick out of a dashboard than a
bare hex string.

Keys can also be changed at runtime through `PUT`/`PATCH /v0/management/api-keys`
or the panel, but `config.yaml` is templated from this role, so the next playbook
run restores the set defined here.

## Using it

- **Open WebUI**: `https://chat.<domain>`. The first account to sign up becomes
  the admin; set `cpa_open_webui_enable_signup: false` in `main.yml` afterwards
  and re-run.
- **CPAMP**: `https://cpamp.<domain>/management.html`, log in with
  `cpa_manager_admin_key`. The CPA connection is supplied through the
  environment, so there is no setup wizard to walk. Also where you add provider
  accounts and read per-key usage.
- **CLIProxyAPI's own panel**: `https://cliproxy.<domain>/management.html`, log
  in with `cpa_management_key`.
- **Coding CLIs**: point them at `https://cliproxy.<domain>/v1` with that
  tool's entry from `cpa_api_keys` as the API key.

## Notes

- **All three containers run as the `apps` user**, though all three images
  default to root. Two environment variables are load-bearing for that and must
  not be dropped: `MANAGEMENT_STATIC_PATH` (cli-proxy-api), without which the
  management panel asset cannot be written and `/management.html` returns 404;
  and `STATIC_DIR` (open-webui), without which it cannot seed its branding
  assets and logs a permission error per file on every start. `cpa-manager-plus`
  needs nothing beyond a writable `/data`.
- **Secrets reach each service through `environment`, not a shared `env_file`**,
  so Open WebUI never receives the CPA management key. Compose still reads
  `.env` for the `${...}` values.
- **Open WebUI runs with `ENABLE_PERSISTENT_CONFIG=False`**, so this role stays
  the source of truth for its settings. The trade-off: settings changed in its
  admin UI look like they save but are discarded on restart. Change them here.
- **CLIProxyAPI's management panel can rewrite `config.yaml`** at runtime. That
  file is templated from this role, so any such change is reverted on the next
  playbook run.
- **`auth-dir` is `/CLIProxyAPI/auths`.** Every path the container writes to
  lives under its own directory, which is what lets it run as a non-root user;
  the upstream default, `~/.cli-proxy-api`, resolves to root's home.
- **`config.yaml` is mode `0600`** where the repo uses `0644`: it holds both the
  management key and the client API key.
- **No container publishes a host port**, and none needs to — the device-code
  login makes the OAuth callback listener irrelevant. Everything is reached
  through Caddy over `nginxnetwork`, including the Management API. Keep it that
  way: the management key is the only thing guarding config and credential
  access.
- **Back up `cpa-manager-plus/data.key` together with `usage.sqlite`.** The key
  decrypts the CPA management key stored in the database; without it the panel's
  saved connection cannot be recovered.
- **The Codex credential is runtime state, not configuration.** CLIProxyAPI
  refreshes the OAuth token every 15 minutes and rewrites the file in `auths/`,
  so what protects it is your backup of that dataset.
