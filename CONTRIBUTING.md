# Contributing

Contributions are welcome. Here's the short version.

## Getting started

```bash
git clone https://github.com/SHCV-it/gnosis.git
cd gnosis
pip install -e '.[test]'
python -m pytest tests/ -q      # offline suite (localhost fixtures)
ruff check .                    # lint
```

## Workflow

1. Open an issue first to discuss what you'd like to change.
2. Create a feature branch (`git checkout -b feature/amazing`).
3. Add or update tests for your change.
4. Run `pytest tests/ -q` and `ruff check .` until green.
5. Commit with a clear message and push.
6. Open a pull request against `main`.

## Conventions

- Keep the core pure-Python and dependency-light. Heavy integrations
  (torch, markitdown, a JS renderer binary) are optional extras behind a
  lazy import or a sidecar process.
- Preserve the provenance contract: every output file stays self-describing
  (see `gnosis/core/provenance.py`).
- New CLI flags need a README entry and a test.

## Security

Do not open public issues for security problems — see
[SECURITY.md](SECURITY.md).
