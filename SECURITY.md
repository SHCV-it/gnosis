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

## Treat fetched content as untrusted

Downloaded HTML/Markdown and documents are untrusted input. The opt-in
`--render` path executes third-party JavaScript in a sidecar binary — only
enable it for sources you trust, and treat rendered output as untrusted.
