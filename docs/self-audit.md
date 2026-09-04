# My scraper's completeness metric was certifying garbage

*A self-audit of gnosis-markdown, and what it means for every team shipping
agent-written code.*

**4 September 2026 · Ali Zahid Raja · SHCV.IT**

---

## The claim, and the test that broke it

gnosis-markdown fetches web pages into Markdown for LLM/RAG pipelines and
stamps every file with a provenance record: source URL, UTC fetch time,
SHA-256 of the response body, redirect chain, WARC archive — and a number
called `retention_ratio`, meant to say *how much of the source text survived
conversion*.

I wrote a test. I fed it a page I had written myself, with a data table and
two paragraphs whose CSS classes happened to contain the words `share` and
`cookie`.

The converter deleted the table and both paragraphs. The record it emitted
reported:

```
retention_ratio: 1.06
```

Above 100%. On a document that had lost a third of its text.

The number was arithmetically valid: Markdown length divided by source-text
length, and link syntax (the absolute-URL expansion in Markdown) padded the
numerator enough to hide the loss. The test suite was green throughout.
Nothing anywhere checks *extracted* text against *source* text — unless you
write that test yourself, and you don't write it until you already suspect
the failure.

---

## The two claims, separated

The bug forced a distinction that turned out to be the whole point. A
provenance record makes **two** claims, and the field routinely conflates
them:

| Claim | Question | Status |
|---|---|---|
| **Custody** | What was fetched, from where, when, and is the stored copy unaltered? | Solved. Hash the bytes. |
| **Fidelity** | Of the content present at the source, how much survived into the derived text? | Not solved. Heuristic, lossy, usually unmeasured. |

A record can be *cryptographically sound* about the bytes and *completely
wrong* about the content. The SHA-256 was never the problem. The problem was
that a completeness metric was reporting a percentage while measuring the
wrong thing — and nothing in the toolchain noticed.

The fix was to compare normalised text to normalised text and clamp at 1.0.
But the deeper gap — *which* text was lost, not just *how much* — doesn't
have a clean answer, so I wrote it into the spec as an open problem instead of
hiding it. It's §4.4 of the [Capture Record Specification](capture-record-spec.md),
with the limitation stated plainly.

---

## What this says about agent-written code

Most of gnosis-markdown v2 was written by an agent harness over roughly twenty
hours, with me directing rather than typing. The bugs above shipped with a
passing test suite and a commit message that said they were fixed.

The pattern is the thing worth paying attention to: **an agent harness closes
the implementation gap and widens the verification gap.** The harness is very
good at making the code do what the test says. It is not good at noticing
that the test asserts the code does what the code does, rather than what the
*product* claims. Those two sentences are different things, and the difference
is where every silent failure lives.

The lesson is not "don't use agents." It's that, when you do, verification is
no longer a step in the pipeline — it is the whole job, and the tests have to
be written *against the claim*, not against the code.

---

## Reproduce it

```bash
pip install gnosis-markdown
gnosis https://example.com/ -o out/ --warc
shasum -a 256 out/.gnosis-store/<bytes_sha256>   # matches the frontmatter
```

The repo is MIT, on PyPI, with a citable DOI
([10.5281/zenodo.22276101](https://doi.org/10.5281/zenodo.22276101)). The
record format is open and tool-agnostic: [docs/capture-record-spec.md](capture-record-spec.md).
