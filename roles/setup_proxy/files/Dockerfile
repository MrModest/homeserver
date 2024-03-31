ARG VERSION=2

FROM caddy:${VERSION}-builder AS builder

# We need this plugin to obtain SSL certificates from Cloudflare
RUN xcaddy build \
	--with github.com/caddy-dns/cloudflare

FROM caddy:${VERSION}

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
