FROM python:3.12-slim

LABEL org.opencontainers.image.title="gnosis"
LABEL org.opencontainers.image.description="Web scraping → LLM-ready Markdown with byte-level provenance (MCP server)"
LABEL org.opencontainers.image.source="https://github.com/SHCV-it/gnosis"

WORKDIR /app

COPY pyproject.toml README.md ./
COPY gnosis/ gnosis/

RUN pip install --no-cache-dir '.[mcp]'

# The MCP server (stdio) is the default entrypoint so that MCP clients and
# directories (e.g. Glama) can `docker run` the image and introspect it.
# For the CLI, override the entrypoint: docker run --entrypoint gnosis ...
ENTRYPOINT ["gnosis-mcp"]
