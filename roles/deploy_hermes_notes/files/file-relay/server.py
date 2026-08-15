"""Minimal MCP server that relays a file from a read-only local directory to a
multipart HTTP upload endpoint.

Exists because Hatchdoor v2.4.0 removed its shared attachment-inbox staging
directory: agents must now send the file bytes themselves, either base64-inline
over MCP or as a multipart HTTP POST. hermes can do neither — its `file`, `web`,
and `terminal` toolsets are disabled on purpose (see config.yaml), and an image
reaches the model as vision tokens, not as bytes it can re-emit.

This relay restores the old ergonomics: the agent passes a *filename*, never any
bytes, no URL, and no credential. Everything else is env-configured, so it is
not tied to Hatchdoor or to images.
"""

import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

SOURCE_DIR = Path(os.environ.get("RELAY_SOURCE_DIR", "/files")).resolve()
UPLOAD_URL = os.environ["RELAY_UPLOAD_URL"]
UPLOAD_TOKEN = os.environ.get("RELAY_UPLOAD_TOKEN", "")
FILE_FIELD = os.environ.get("RELAY_FILE_FIELD", "file")
PATH_FIELD = os.environ.get("RELAY_PATH_FIELD", "target_relative_path")
MAX_BYTES = int(os.environ.get("RELAY_MAX_BYTES", 10 * 1024 * 1024))
# Destination folder on the receiving side. Deployment config, not an agent
# concern — the agent never names a destination.
TARGET_DIR = os.environ.get("RELAY_TARGET_DIR", "").strip("/")
# Regex for a cache-uniqueness prefix to drop from the stored filename. Whatever
# writes the source dir may rename files to keep them unique on disk; that is its
# business, not something the destination should inherit. Empty disables.
STRIP_PREFIX = os.environ.get("RELAY_STRIP_NAME_PREFIX", "")
_STRIP_RE = re.compile(STRIP_PREFIX) if STRIP_PREFIX else None
# The calling agent sees these files at a different absolute path than the relay
# does (hermes is told `/opt/data/cache/...`; the relay mounts that same tree at
# SOURCE_DIR). Paths under this root are rewritten instead of being rejected as
# traversal. Empty disables the rewrite.
AGENT_ROOT = os.environ.get("RELAY_AGENT_ROOT", "").rstrip("/")

# No auth: this listens only on an internal compose network with no published
# port, and its one client already holds every credential the relay does. Add a
# bearer token if it ever gains a published port or a second network.
mcp = FastMCP(name="file-relay")


def _clean_name(name: str) -> str:
    """Drop the source cache's uniqueness prefix, unless that leaves nothing."""
    if not _STRIP_RE:
        return name
    stripped = _STRIP_RE.sub("", name, count=1)
    return stripped or name


def _safe_name(filename: str) -> str:
    """Reduce a caller-supplied name to a bare filename, or refuse.

    The caller picks a name, never a location: anything that could climb out of
    TARGET_DIR is rejected rather than silently flattened.
    """
    name = filename.strip()
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise ToolError(f"filename must be a bare filename, not a path: {filename}")
    return name


def _resolve(source_path: str) -> Path:
    """Resolve a caller-supplied path inside SOURCE_DIR, or refuse.

    Accepts both a path relative to SOURCE_DIR and the absolute path the agent
    was shown (see AGENT_ROOT), so an agent can paste the path out of its own
    context without translating it.
    """
    if AGENT_ROOT and (source_path == AGENT_ROOT or source_path.startswith(AGENT_ROOT + "/")):
        source_path = source_path[len(AGENT_ROOT) :].lstrip("/")
    candidate = (SOURCE_DIR / source_path).resolve()
    if not candidate.is_relative_to(SOURCE_DIR):
        raise ToolError(f"path escapes the source directory: {source_path}")
    if not candidate.is_file():
        raise ToolError(f"no such file: {source_path}")
    return candidate


@mcp.tool
def list_files(limit: int = 20) -> list[dict]:
    """List files available to upload, newest first.

    Returns each file's `source_path` (pass it to `upload_file`), size, and
    modification time. Use this when you do not already know the exact filename
    of something the user just sent.
    """
    files = [
        path
        for path in SOURCE_DIR.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "source_path": str(path.relative_to(SOURCE_DIR)),
            "size_bytes": path.stat().st_size,
            "modified": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
            "too_large": path.stat().st_size > MAX_BYTES,
        }
        for path in files[:limit]
    ]


@mcp.tool
def upload_file(source_path: str, filename: str | None = None) -> dict:
    """Upload a file from the relay's source directory to the configured endpoint.

    `source_path` is the path the file was reported at, or one relative to the
    source directory as returned by `list_files`. The destination folder is
    fixed by the deployment — you do not choose it. Optionally pass `filename`
    to store it under a meaningful name instead of the cached one (keep the
    extension); omit it to reuse the cached filename as-is.
    """
    path = _resolve(source_path)
    name = _safe_name(filename) if filename else _clean_name(path.name)
    target_relative_path = f"{TARGET_DIR}/{name}" if TARGET_DIR else name
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ToolError(f"file is {size} bytes, over the {MAX_BYTES} byte limit")

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Authorization": f"Bearer {UPLOAD_TOKEN}"} if UPLOAD_TOKEN else {}

    response = httpx.post(
        UPLOAD_URL,
        headers=headers,
        data={PATH_FIELD: target_relative_path},
        files={FILE_FIELD: (path.name, path.read_bytes(), content_type)},
        timeout=120,
    )
    if response.is_error:
        raise ToolError(f"upload failed ({response.status_code}): {response.text}")

    try:
        return {"status": response.status_code, "response": response.json()}
    except ValueError:
        return {"status": response.status_code, "response": response.text}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("RELAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("RELAY_PORT", 8000)),
    )
