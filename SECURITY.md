# Security Policy

## Reporting a vulnerability

Please report security issues privately to the maintainer, Steffen Hoehne
(steffen.hoehne@shcv.it). Do not open a public issue for a suspected
vulnerability.

## Security posture

Gnosis fetches untrusted web content and is hardened by default:

- **SSRF / private-network guard** — loopback, RFC 1918, link-local, multicast,
  reserved, and unspecified addresses are blocked on every request and every
  redirect hop. Hostnames are resolved **once**, *every* returned address is
  validated, and the connection is pinned to a validated IP — closing the
  DNS-rebinding TOCTOU (no second, racy resolution at connect time). Opt out
  explicitly with `--allow-private-network` / the `allow_private_network`
  setting.
- **Secrets via environment variables** — tokens are referenced as `${ENV_VAR}`
  in config files and headers; keep them out of config files, shell history, and
  process tables.
- **robots.txt** — respected by default, with `Crawl-delay` politeness.

## Known limitations (honest disclosure)

- **Proxies / Unix domain sockets are not SSRF-guarded** — IP pinning works
  for direct connections (the only path gnosis configures). An HTTP/HTTPS
  proxy moves DNS resolution to the proxy, so client-side pinning cannot
  enforce the target address; and a Unix domain socket bypasses TCP/IP
  addressing entirely. Both are unsupported while the guard is enabled and
  fail closed.
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

## Plugins execute arbitrary code

The `plugins:` config entry loads Python files and runs them. This is arbitrary
local code execution by design. Only load plugin files you authored or fully
trust — a malicious plugin can read any file, exfiltrate data, or run commands.
