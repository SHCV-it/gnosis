# Security Policy

## Reporting a vulnerability

Please report security issues privately to the maintainer, Steffen Hoehne
(steffen.hoehne@shcv.it). Do not open a public issue for a suspected
vulnerability.

## Security posture

Gnosis fetches untrusted web content and is hardened by default:

- **SSRF / private-network guard** — loopback, RFC 1918, link-local, multicast,
  reserved, and unspecified addresses are blocked on every request and every
  redirect hop. Opt out explicitly with `--allow-private-network` / the
  `allow_private_network` setting.
- **Secrets via environment variables** — tokens are referenced as `${ENV_VAR}`
  in config files and headers; keep them out of config files, shell history, and
  process tables.
- **robots.txt** — respected by default, with `Crawl-delay` politeness.

## Known limitations (honest disclosure)

- **DNS-rebinding TOCTOU** — the SSRF guard resolves and validates a hostname,
  then httpx resolves again independently at connect time. A resolver that
  returns a public address to the guard and a private address to the transport
  (rebinding) could slip a private address through. This is inherent to
  validate-then-connect designs and is not yet mitigated with IP pinning.
- **No end-to-end redirect-to-private SSRF test** — hermetic localhost fixtures
  cannot simulate a public → private redirect hop; the guard's redirect logic is
  covered by unit tests and a direct hook test.
- **No end-to-end render test** — the Obscura sidecar binary is not present in
  CI, so `--render` is tested only for the missing-binary path and provenance
  fields.
- **Sitemap XML** is parsed with stdlib `ElementTree` (no external-entity
  hardening); only enable sitemap ingestion for trusted inputs.

## Treat fetched content as untrusted

Downloaded HTML/Markdown and documents are untrusted input. The opt-in
`--render` path executes third-party JavaScript in a sidecar binary — only
enable it for sources you trust, and treat rendered output as untrusted.
