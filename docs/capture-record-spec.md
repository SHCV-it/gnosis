# Capture Record Specification

**Version:** 1.0 (Draft)
**Date:** 2026-09-03
**Editor:** Ali Zahid Raja, SHCV IT OÜ
**License:** MIT
**Reference implementation:** [gnosis](https://github.com/SHCV-it/gnosis) v2.0.0
**Status:** Draft. Open for comment. Field names are stable within v1.x; breaking changes increment the major version.

---

## 1. Purpose and scope

This document defines a **Capture Record**: a machine-readable statement of where a
document obtained from the public web came from, when, and how its stored form can be
verified against the original response.

It is written for two readers who will never run the reference implementation:

- Someone assessing whether a body of web-sourced data can be evidenced.
- Someone implementing capture in a different tool, in a different language.

The record is deliberately small. It describes **one HTTP fetch and one derived text
document**. It says nothing about datasets, corpora, licensing, consent, or model
training, and it confers no legal presumption of anything.

### 1.1 What this specification is not

- It is not a compliance artifact. Producing a conformant record does not satisfy any
  obligation under any regulation.
- It is not a quality measure. A record can be perfectly conformant and describe a
  worthless capture.
- It is not a licensing or rights statement. It records what was fetched, not what may
  be done with it.

### 1.2 Terminology

**MUST**, **SHOULD**, and **MAY** are used as in RFC 2119.

- **Capture** — a single HTTP request/response pair against one URL.
- **Response body bytes** — the entity body after transfer and content decoding has
  been applied, before any parsing or transformation. See §3.2 for why this is not
  "wire bytes."
- **Derived text** — the text document produced from the response body, typically
  Markdown.
- **Producer** — the tool emitting the record.
- **Consumer** — anything reading the record: a pipeline, an auditor, a person.

---

## 2. The two claims

The core design assumption of this specification is that provenance for web-sourced
data is **two separate claims**, routinely conflated:

| Claim | Question | Status |
|---|---|---|
| **Custody** | What was fetched, from where, when, and is the stored copy unaltered? | Solved. Hash the bytes. |
| **Fidelity** | Of the content present at the source, how much survived into the derived text? | Not solved. Heuristic, lossy, and usually unmeasured. |

A record that carries only custody fields is a record that can attest, with
cryptographic confidence, to a document that lost a third of its content during
extraction.

Sections 3 and 4 separate these deliberately. **A producer MUST NOT present fidelity
fields as integrity guarantees, or vice versa.**

---

## 3. Custody fields

Serialised as YAML frontmatter delimited by `---` fences at the head of the derived
text document, or as an equivalent JSON object in a sidecar. Field names and semantics
are identical in both.

### 3.1 Required fields

A conformant record **MUST** contain all of the following.

#### `url`
**Type:** string (absolute URL)
**Semantics:** The URL of the response that produced this record, **after** all
redirects. Where the requested URL differs, `requested_url` **MUST** also be present.

#### `fetched_at`
**Type:** string, ISO 8601, UTC, second precision, `Z` suffix
**Semantics:** When the response was received. UTC is required; local times are
non-conformant.

#### `status_code`
**Type:** integer
**Semantics:** HTTP status of the final response.
**Note:** A `200` says the server answered. It does not say the answer was the content.
Bot challenges, consent walls, and soft-404s all return `200`. Consumers **MUST NOT**
treat `status_code: 200` as evidence of successful capture. See `low_content` (§4.4).

#### `bytes_sha256`
**Type:** string, lowercase hex, 64 chars
**Semantics:** SHA-256 over the **response body bytes** as defined in §1.2.

**Covers:** the complete entity body, byte for byte, as the producer received it after
transfer and content decoding.

**Explicitly does not cover:**
- The derived text (that is `content_hash`)
- The frontmatter or record itself
- HTTP headers or status line (those live in the WARC `response` record, §5)
- Sub-resources: images, stylesheets, scripts, iframe contents

**Verification procedure.** A consumer holding the record and the stored body:

```
sha256(stored_body) == bytes_sha256
```

If the producer also maintains a content-addressed store keyed on this digest (§6),
the digest is the filename and verification requires no index.

**Re-fetch caveat.** Re-fetching the URL and comparing digests proves change, not
tampering. Digest mismatch on re-fetch is the expected outcome for most live pages and
**MUST NOT** be interpreted as evidence of alteration.

#### `content_hash`
**Type:** string, lowercase hex, 64 chars
**Semantics:** SHA-256 over the UTF-8 encoding of the derived text body, excluding the
frontmatter block.

This is a **secondary** digest. It identifies the derived artifact, which is a function
of both the source and the producer's extraction logic. Two producers reading identical
bytes will legitimately emit different `content_hash` values. It is useful for
deduplication and change detection within one pipeline. It is not a source integrity
claim.

#### `generator`
**Type:** string, `name/version`
**Semantics:** Producer identity and version. Required because extraction is
producer-specific: `content_hash`, `retention_ratio`, and `stripped_elements` are only
interpretable if the consumer knows what produced them.

### 3.2 A note on "byte-level"

This specification says **response body bytes**, not wire bytes.

Most HTTP clients transparently reverse `Content-Encoding` (gzip, br) before exposing
the body. The digest therefore covers the decoded entity body, not the compressed
octets that crossed the network. This is the correct scope for the purpose — it is
stable across servers that recompress differently — but producers **MUST NOT** describe
it as a hash of wire bytes. Claiming more than the digest covers is the most common
error in this space.

### 3.3 Conditional fields

**MUST** be present when the condition holds; omitted otherwise.

| Field | Type | Condition | Semantics |
|---|---|---|---|
| `requested_url` | string | Final URL ≠ requested URL | The URL originally requested |
| `redirect_chain` | list of strings | Any redirect occurred | Every URL traversed, final URL last |
| `content_type` | string | Header present | Response `Content-Type` verbatim |
| `etag` | string | Header present | Response `ETag` verbatim |
| `last_modified` | string | Header present | Response `Last-Modified` verbatim |

### 3.4 Render fields

When the derived text was produced from a JavaScript-rendered DOM rather than the
response body, the producer **MUST** emit all of:

| Field | Type | Semantics |
|---|---|---|
| `render_engine` | string | Renderer identity |
| `render_version` | string | Renderer version |
| `render_timestamp` | string, ISO 8601 UTC | When rendering occurred |
| `js_executed` | boolean | Whether scripts ran |

**This is a provenance discontinuity and consumers MUST treat it as one.** When these
fields are present, `bytes_sha256` covers the pre-render response body, while the
derived text descends from a post-render DOM that was never hashed and is not
reproducible. Custody of the input survives. Custody of the artifact does not.

A future version may define a digest over the serialised post-render DOM. v1.0 does not.

---

## 4. Fidelity fields

These describe the lossy step. They are measurements, not guarantees.

### 4.1 `retention_ratio`
**Type:** float, `0.0`–`1.0`, 4 decimal places
**Required:** SHOULD

**Definition.** Let `S` be the whitespace-normalised visible text of the source
document before any stripping. Let `D` be the whitespace-normalised text of the derived
document with markup syntax removed. Then:

```
retention_ratio = min(1.0, len(D) / len(S))
```

**Both sides MUST be measured in the same units.** Comparing derived-text length
against source length without removing markup produces values above 1.0, because link
syntax and absolute URL expansion inflate the numerator. A ratio above 1.0 is not a
good result; it is a defective measurement, which is why the clamp exists.

**Failure modes a consumer MUST account for:**

- **Boilerplate-heavy sources.** A page that is 80% navigation yields a low ratio for a
  correct extraction. Low is not automatically bad.
- **Uniform loss.** The ratio measures volume, not importance. Dropping one critical
  table in a long document barely moves it.
- **Not comparable across producers.** Different extractors, different denominators.
  Compare a ratio only against others from the same `generator`.

**What it is for:** detecting the case where a producer silently discarded substantial
content while reporting success. It is a smoke alarm, not a quality score.

### 4.2 `stripped_elements`
**Type:** integer
**Required:** SHOULD
**Semantics:** Count of source elements removed by boilerplate heuristics before
extraction. A count, not a size. Ten navigation links and one data table both remove
elements; only one matters.

### 4.3 `low_content`
**Type:** boolean, present only when `true`
**Required:** SHOULD
**Semantics:** The producer's own assessment that the capture is suspect — derived text
implausibly short for the source, or below a producer-defined threshold.

Consumers **SHOULD** treat presence of this field as requiring review regardless of
`status_code`.

### 4.4 Open problem

There is currently no interoperable measure of *which* content was lost, only how much.
A producer that discards a single critical element reports a ratio close to 1.0. Closing
this gap likely requires recording the identity of stripped regions rather than a
count. **This is the principal known weakness of v1.0 and comment is specifically
invited on it.**

---

## 5. WARC archival

Where evidence must survive independently of the derived text, the producer **SHOULD**
write a WARC file conformant with ISO 28500.

**Per capture, the producer MUST write:**

| Record | Contents |
|---|---|
| `warcinfo` | Once per file. Producer identity and version. |
| `request` | Request line and outgoing headers. |
| `response` | Status line, response headers, and the response body bytes as payload. |

The `response` payload **MUST** be byte-identical to the input of `bytes_sha256`, so
the digest verifies against the WARC without a separate copy.

**Header handling.** `Content-Encoding` and `Transfer-Encoding` **MUST** be removed from
the recorded headers, and `Content-Length` **MUST** be recalculated, because the stored
payload is decoded (§3.2). Recording the original encoding headers alongside a decoded
payload produces a WARC that standard replay tools cannot read.

**Append semantics.** WARC files are append-only. A producer writing into an existing
output location **MUST** append and **MUST NOT** truncate. Truncating destroys the
evidence the format exists to preserve.

---

## 6. Content-addressed store (optional)

A producer **MAY** maintain a store where each unique response body is written once at
a path equal to its `bytes_sha256`.

Properties: identical captures stored once; verification needs no index, because the
filename is the claim; and any consumer with the record can locate the bytes.

---

## 7. Chunk records (optional)

For retrieval pipelines, a producer **MAY** emit per-chunk records anchoring citations
to spans of the derived text:

| Field | Type | Semantics |
|---|---|---|
| `doc_id` | string | The parent record's `url` |
| `content_hash` | string | The parent's `content_hash`, binding chunk to exact document version |
| `chunk_id` | string | Stable within the document |
| `heading_path` | list of strings | Heading ancestry |
| `start`, `end` | integer | Character offsets into the derived text body |
| `char_count`, `token_count` | integer | Size |
| `chunk_sha256` | string | SHA-256 of the chunk text |

**Invariant.** `derived_text[start:end]` **MUST** equal the chunk text, and its SHA-256
**MUST** equal `chunk_sha256`. This is what makes a retrieval citation checkable rather
than asserted.

---

## 8. Conformance

A **conformant record** carries every field in §3.1, and every applicable field in §3.3
and §3.4.

A **conformant producer** emits conformant records, obeys §3.2 (never overstating digest
scope), and obeys §5 append semantics where WARC is written.

Conformance is self-asserted. There is no certification, no registry, and no authority.
This specification confers no presumption of conformity with any regulation.

---

## 9. Extension

Producers **MAY** add fields. Added fields **MUST NOT** reuse a name defined here with
different semantics, and **MUST NOT** override a core field in §3.1.

---

## 10. Comment

Comment is invited, particularly on §4.4 (loss identity), §3.4 (post-render custody),
and whether §7 belongs in this specification at all.

Open an issue at https://github.com/SHCV-it/gnosis/issues with the label `spec`, or
write to the editor.

## Changelog

**v1.0 (2026-09-03)** — Initial draft.
