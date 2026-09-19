FROM python:3.13-slim

# fastmcp 4.x is the release built for MCP protocol 2026-07-28, serving it and
# older revisions from one deployment via per-connection negotiation. Its
# breaking changes (FastMCPOpenAPI, mount(prefix=), as_proxy(), transport kwargs
# on the constructor) touch nothing this relay uses.
RUN pip install --no-cache-dir "fastmcp==4.0.5" "httpx==0.28.1"

COPY server.py /app/server.py

# Overridden by compose to match the UID that owns the mounted source dir.
USER 10000:10000

CMD ["python", "/app/server.py"]
