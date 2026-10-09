FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

LABEL org.opencontainers.image.title="gnosis"
LABEL org.opencontainers.image.description="Web scraping → LLM-ready Markdown with byte-level provenance (MCP server)"
LABEL org.opencontainers.image.source="https://github.com/SHCV-it/gnosis"

WORKDIR /app

# Install dependencies + the project into a project venv. `gnosis-mcp` is a
# core dependency, so a plain `uv sync` pulls in the MCP SDK.
COPY pyproject.toml uv.lock README.md ./
COPY gnosis/ gnosis/
RUN uv sync --frozen --no-dev

# Serve `gnosis-mcp` over stdio. Directories such as Glama wrap stdio servers
# with mcp-proxy; `uv run` resolves the console script inside the project venv.
# For the CLI, override the command: docker run --entrypoint gnosis ...
CMD ["uv", "run", "gnosis-mcp"]
