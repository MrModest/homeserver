ARG VERSION=2

FROM caddy:${VERSION}-builder AS builder

RUN xcaddy build \
	--with github.com/caddy-dns/cloudflare \
	--with github.com/caddy-dns/duckdns

FROM caddy:${VERSION}

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
