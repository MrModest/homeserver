# Mail relay

This role runs one SMTP-to-Telegram gateway. Apps will send notifications to
`mail-relay:2525` on `nginxnetwork`, using plain SMTP without authentication.
The gateway forwards them only to the configured Telegram chat. Envelope sender
and recipient addresses are message metadata: nothing is delivered to email
recipients, no external MX is contacted, and no email bounces are generated.
The gateway is deployed; app SMTP settings are managed by their own roles.

## Container and delivery

The image is `kostyaesmukov/smtp_to_telegram`, pinned to digest
`sha256:44ae24d5ed375343faec3c9093afbd5d74b133c87482f81ad70fef3091fd5a24`.
It joins only the existing `nginxnetwork`, publishes no host ports and has no
Caddy route. Any container on that network can submit notifications. Outbound
HTTPS to Telegram is required; no email account or DNS records are needed.

Postfix was removed because email delivery is no longer wanted. Gmail rejected
our earlier direct-MX test with `550 5.7.1` (IP not authorized for direct sending).
There is no persistent queue: Telegram or attachment-upload errors return SMTP
`421`, so sending apps must retry. Apps that do not retry can lose notifications
while Telegram is unavailable. Retrying after partial success can duplicate
messages or attachments. SMTP success means Telegram accepted the notification,
not that someone read it.

Telegram receives the envelope sender and recipients, subject and plain-text
body. HTML-only mail is converted to text; long messages get a shortened preview
plus the full text as a file. Attachments are uploaded as files or photos, up to
50 MiB per file (photos use the gateway's 10 MiB default); complete SMTP messages
are limited to the gateway's 50 MiB default, including MIME encoding. This is a
rendered notification, not an archive of the original MIME message. Bot chats
are not end-to-end encrypted, so reset links and documents also go there.

## Setup and deployment

Create a dedicated bot with BotFather's `/newbot`, open the new bot and send
`/start`. Obtain the destination chat ID from the bot's `getUpdates` response.
Add these values to the encrypted vault yourself:

```yaml
v_mail_relay:
  telegram_bot_token: '123456789:replace-with-the-bot-token'
  telegram_chat_id: '123456789'
```

`main.yml` passes these as `mlr_telegram_bot_token` and `mlr_telegram_chat_id`.
The shared `tasks/compose_up.yml` flow renders Compose and `.env` with mode `0600`
for this role only. It creates the usual role dataset, but the gateway stores no
persistent data and mounts no volumes.

After approval, deploy only this role:

```sh
ansible-playbook main.yml --tags mail_relay
```

For the first test, submit one plain-text message from a container on
`nginxnetwork` to `mail-relay:2525`, using `notify@telegram.invalid` as the
recipient, then check the SMTP response, container logs and Telegram chat. Follow
with an HTML message and a small attachment, and confirm that a Telegram outage
returns an SMTP error before enabling more notifications.

## Sending apps

These apps use `mail-relay:2525` on the shared `nginxnetwork`, without SMTP
credentials. Each sends as `<app>@modestlab.dev`; the relay treats recipients as
metadata and sends everything to Telegram.

| App | Plain SMTP setting | Authentication |
| --- | --- | --- |
| Grafana | `GF_SMTP_STARTTLS_POLICY=NoStartTLS` | Empty user/password |
| Forgejo | `FORGEJO__mailer__PROTOCOL=smtp` | Empty mailer user/password |
| Authentik server and worker | `AUTHENTIK_EMAIL__USE_TLS=false`, `USE_SSL=false` | Empty username/password |
| Paperless | `PAPERLESS_EMAIL_USE_TLS=false`, `USE_SSL=false` | Empty host user/password |
| n8n user management | `N8N_SMTP_SSL=false`, `N8N_SMTP_STARTTLS=false` | Empty SMTP user/password |
| Mealie | `SMTP_AUTH_STRATEGY=NONE` | Empty user/password |
| Planka | `SMTP_SECURE=false` | Empty user/password |
| OpenCloud | `NOTIFICATIONS_SMTP_ENCRYPTION=none` | `NOTIFICATIONS_SMTP_AUTHENTICATION=none`, empty credentials |
| Linkwarden | `EMAIL_SERVER=smtp://mail-relay:2525/?ignoreTLS=true` | No URL credentials |

Planka does not expose a separate STARTTLS-disable setting in this version.
With implicit TLS off, its mail client stays in plaintext because
the gateway does not advertise STARTTLS. WUD has no notification triggers; it
only supplies container versions to glance-ext. OpenCloud's notifications service is
enabled. The n8n settings cover account emails only; workflow email nodes still
need an SMTP credential configured in n8n.

Public email links use the apps' HTTPS domains from `g_services`. n8n sets
`N8N_EDITOR_BASE_URL` and `WEBHOOK_URL` on server and worker; Grafana sets
`GF_SERVER_ROOT_URL`. Linkwarden sets `BASE_URL` to its public origin and
`NEXTAUTH_URL` to that origin plus `/api/v1/auth`, as required by v2.12.2.

Paperless uses `paperless-app` as its internal hostname so Python sends a valid
SMTP EHLO name; its `paperless_app` container name and proxy address are unchanged.

For apps managed through their UI/database (Immich, Wallos, Sonarr, Prowlarr,
changedetection, Readeck and Backrest), enter `mail-relay` as host, port `2525`,
TLS/SSL/STARTTLS off, and no username/password. Use `<app>@modestlab.dev` as sender
and `notify@modestlab.dev` as recipient where a recipient is required.
Backrest uses a Shoutrrr email hook; disable encryption and authentication there.
Tududi is disabled and has not been changed. Grist's SMTP notifications are
edition-dependent and were not changed.
