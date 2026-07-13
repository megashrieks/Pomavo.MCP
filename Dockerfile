# Pomavo MCP server (HTTP + SSE transport) packaged as a container.
# Run with: docker run --rm -p 8000:8000 -e POMAVO_API_URL -e POMAVO_VERIFY_SSL \
#           pomavo-mcp:latest
# Per-request auth (X-API-Key + X-Org-Short-Name) is supplied by the caller.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    POMAVO_MCP_HOST=0.0.0.0 \
    POMAVO_MCP_PORT=8000

# Install dependencies first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Install the project itself.
COPY src ./src
COPY skills ./skills
COPY README.md ./
RUN uv sync --frozen --no-dev

EXPOSE 8000

# The MCP server speaks JSON-RPC over HTTP (streamable) at /mcp and SSE at /sse.
ENTRYPOINT ["pomavo-mcp"]
