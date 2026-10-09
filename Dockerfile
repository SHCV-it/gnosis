FROM python:3.12-slim

LABEL org.opencontainers.image.title="gnosis"
LABEL org.opencontainers.image.description="Web scraping → LLM-ready Markdown with byte-level provenance (MCP server)"
LABEL org.opencontainers.image.source="https://github.com/SHCV-it/gnosis"

WORKDIR /app

COPY pyproject.toml README.md ./
COPY gnosis/ gnosis/

# `gnosis-mcp` is a core dependency, so a plain `pip install .` pulls in the
# MCP SDK and installs the `gnosis-mcp` console script to /usr/local/bin.
RUN pip install --no-cache-dir .

# Serve `gnosis-mcp` over stdio (CMD, not ENTRYPOINT, so Glama can wrap it
# with mcp-proxy). For the CLI: docker run --entrypoint gnosis ...
CMD ["gnosis-mcp"]
