FROM python:3.13-slim

RUN pip install --no-cache-dir "fastmcp>=3.2,<4" "httpx>=0.28,<1"

COPY server.py /app/server.py

# Overridden by compose to match the UID that owns the mounted source dir.
USER 10000:10000

CMD ["python", "/app/server.py"]
