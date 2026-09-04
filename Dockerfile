FROM python:3.12-slim

LABEL org.opencontainers.image.title="gnosis"
LABEL org.opencontainers.image.description="Web scraping → LLM-ready Markdown with byte-level provenance"
LABEL org.opencontainers.image.source="https://github.com/SHCV-it/gnosis"

WORKDIR /app

COPY pyproject.toml README.md ./
COPY gnosis/ gnosis/

RUN pip install --no-cache-dir .

ENTRYPOINT ["gnosis"]
