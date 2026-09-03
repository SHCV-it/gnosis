# Design notes (historical)

This directory holds planning scratch from earlier development. These
documents are **historical** — they describe alternatives that were
considered, including features that were **never built** (notably the HTTP
API/server mode, which does not exist in the codebase or `pyproject.toml`).

They are **not** part of the published documentation. For what gnosis
actually does today, see the top-level docs:

- [Getting started](../getting-started.md)
- [Provenance](../provenance.md)
- [Capture Record Specification](../capture-record-spec.md)
- [CLI reference](../cli-reference.md)
- [Architecture](../architecture.md)

Nothing here is authoritative. Several documents contradict each other (for
example, four separate SSRF design notes were written before the final
IP-pinned transport landed) and none of them is guaranteed to match the
shipped code.
