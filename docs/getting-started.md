# Getting Started

Requires Python 3.12+.

```bash
pip install gnosis-markdown
```

## First command

```bash
# One page → one markdown file (written to ./ by default)
gnosis https://docs.python.org/3/tutorial/

# Crawl an entire section
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/
```

## Optional extras

```bash
pip install gnosis-markdown[qmd]     # QMD vector-DB indexing
pip install gnosis-markdown[docs]    # document conversion (MarkItDown)
```

## Verify it yourself

```bash
gnosis https://docs.python.org/3/tutorial/ -o out/ --warc
shasum -a 256 out/.gnosis-store/<bytes_sha256>   # matches the hash in the .md
```

## The other CLIs

```bash
gnosis-bench --urls urls.txt         # reproducible scorecard (one URL per line)
gnosis-doc report.pdf -o report.md   # document → Markdown
```
