"""Tests for Ed25519 signing (seal of origin)."""

import hashlib

import pytest

from gnosis.core.signing import (
    generate_keypair,
    sign_document,
    sign_manifest,
    split_frontmatter,
    verify_document,
    verify_signature,
)

BODY = "# Hello\n\nThis is the document body.\n"


def make_doc(body: str = BODY) -> str:
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return (
        "---\n"
        "title: Test\n"
        "url: https://example.com/page\n"
        "fetched_at: '2026-01-01T00:00:00Z'\n"
        f"content_hash: {content_hash}\n"
        "bytes_sha256: a9ab6cf07d6c6083d17e83cd13b9fbd1f7b499fb266ac76c099580bdb32f5c02\n"
        "status_code: 200\n"
        "generator: gnosis/1.4.3\n"
        "retention_ratio: 0.9137\n"
        "stripped_elements: 4\n"
        "redirect_chain:\n- https://example.com/page\n"
        "---\n\n"
        + body
    )


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()


def test_generate_keypair_derives_public_key(keypair):
    private_pem, public_b64 = keypair
    assert "BEGIN PRIVATE KEY" in private_pem
    # public key must be stable: sign_manifest reports the same key
    sig = sign_manifest(BODY, {"url": "https://example.com/"}, private_pem)
    assert sig["public_key"] == public_b64


def test_sign_verify_roundtrip(keypair):
    private_pem, public_b64 = keypair
    signed = sign_document(make_doc(), private_pem)
    ok, reason = verify_document(signed, expected_public_key=public_b64)
    assert ok, reason
    assert "signature valid" in reason


def test_signature_fields_present(keypair):
    private_pem, public_b64 = keypair
    signed = sign_document(make_doc(), private_pem)
    assert "signature:" in signed
    assert "public_key:" in signed
    assert "signed_at:" in signed
    assert "manifest_sha256:" in signed
    metadata, body = split_frontmatter(signed)
    assert metadata["public_key"] == public_b64
    assert body == BODY


def test_tampered_body_invalidates(keypair):
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    tampered = signed.replace("This is the document body.", "This is the TAMPERED body.")
    ok, reason = verify_document(tampered)
    assert not ok
    assert "INVALID" in reason


def test_tampered_provenance_invalidates(keypair):
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    # change the source URL (a provenance field in the canonical manifest)
    tampered = signed.replace("url: https://example.com/page", "url: https://evil.example.com/")
    ok, _ = verify_document(tampered)
    assert not ok


def test_wrong_public_key_fails(keypair):
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    metadata, markdown = split_frontmatter(signed)
    other_priv, _ = generate_keypair()
    assert not verify_signature(
        markdown, metadata, metadata["signature"], sign_manifest(markdown, metadata, other_priv)["public_key"]
    )


def test_unsigned_document_rejected():
    ok, reason = verify_document(make_doc())
    assert not ok
    assert "not signed" in reason


def test_sign_preserves_frontmatter_body_order(keypair):
    """Regression: signing must not corrupt the frontmatter or body bytes."""
    private_pem, _ = keypair
    doc = make_doc()
    signed = sign_document(doc, private_pem)
    # the original body must appear verbatim in the signed document
    assert BODY in signed
    # frontmatter still parses as YAML and ends with the signature fields
    metadata, body = split_frontmatter(signed)
    assert metadata["url"] == "https://example.com/page"
    assert body == BODY

def test_retention_ratio_tamper_invalidates(keypair):
    """Regression (reviewer P1): every provenance field must be signed, not just
    a fixed allow-list. retention_ratio was previously NOT in the manifest."""
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    tampered = signed.replace("retention_ratio: 0.9137", "retention_ratio: 0.1")
    ok, _ = verify_document(tampered)
    assert not ok


def test_stripped_elements_tamper_invalidates(keypair):
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    tampered = signed.replace("stripped_elements: 4", "stripped_elements: 99")
    ok, _ = verify_document(tampered)
    assert not ok


def test_signed_at_tamper_invalidates(keypair):
    """signed_at must be part of the signed manifest."""
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    tampered = signed.replace("signed_at: '2026-", "signed_at: '2099-")
    ok, _ = verify_document(tampered)
    assert not ok


def test_expected_public_key_pinning(keypair):
    private_pem, public_b64 = keypair
    signed = sign_document(make_doc(), private_pem)
    # correct pin -> valid, identity pinned
    ok, reason = verify_document(signed, expected_public_key=public_b64)
    assert ok and "identity pinned" in reason
    # wrong pin -> rejected even though the signature is self-consistent
    other_priv, other_pub = generate_keypair()
    ok, reason = verify_document(signed, expected_public_key=other_pub)
    assert not ok
    assert "public key mismatch" in reason


def test_attacker_resign_rejected_when_pinned(keypair):
    """Reviewer P1: an attacker re-signing with their own key must fail against
    the real producer's pinned key."""
    _, real_public = keypair
    attacker_priv, _ = generate_keypair()
    forged = sign_document(make_doc(), attacker_priv)
    # unpinned verify is NOT success (origin not established)
    ok, reason = verify_document(forged)
    assert not ok and "NOT pinned" in reason
    ok, reason = verify_document(forged, expected_public_key=real_public)
    assert not ok
    assert "public key mismatch" in reason


def test_sign_handles_unquoted_dates(keypair):
    """Regression: YAML coerces unquoted dates to date objects, which must not
    crash the JSON manifest builder."""
    private_pem, public_b64 = keypair
    body_hash = hashlib.sha256(b"# Body\n").hexdigest()
    doc = (
        "---\nurl: https://x\n"
        "published_time: 2026-01-15\n"
        "modified_time: 2026-02-20\n"
        f"content_hash: {body_hash}\nbytes_sha256: def\nstatus_code: 200\n"
        "fetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n---\n\n# Body\n"
    )
    signed = sign_document(doc, private_pem)
    ok, _ = verify_document(signed, expected_public_key=public_b64)
    assert ok


def test_resign_replaces_not_duplicates(keypair):
    """Regression: re-signing must replace the signature block, not emit
    duplicate signature/public_key keys."""
    private_pem, public_b64 = keypair
    once = sign_document(make_doc(), private_pem)
    twice = sign_document(once, private_pem)
    assert twice.count("signature:") == 1
    assert twice.count("public_key:") == 1
    assert twice.count("signed_at:") == 1
    ok, _ = verify_document(twice, expected_public_key=public_b64)
    assert ok


def test_content_hash_tamper_invalidates(keypair):
    """Regression (judge P1): the STORED content_hash field must be authenticated,
    not silently overwritten by the recomputed body hash."""
    private_pem, public_b64 = keypair
    signed = sign_document(make_doc(), private_pem)
    declared = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    tampered = signed.replace(f"content_hash: {declared}", "content_hash: " + "0" * 64)
    ok, _ = verify_document(tampered, expected_public_key=public_b64)
    assert not ok


def test_datetime_canonicalized_to_z():
    """Regression: quoted and unquoted ISO dates must canonicalise identically,
    so a consumer with a different YAML parser computes the same manifest."""
    from datetime import UTC, date, datetime

    from gnosis.core.signing import _json_safe

    assert _json_safe(datetime(2026, 9, 3, 0, 0, tzinfo=UTC)) == "2026-09-03T00:00:00Z"
    assert _json_safe(datetime(2026, 9, 3, 0, 0)) == "2026-09-03T00:00:00Z"  # naive -> UTC
    assert _json_safe(date(2026, 9, 3)) == "2026-09-03"


def test_duplicate_keys_rejected(keypair):
    """Regression (#33): a document with duplicate frontmatter keys must be
    rejected, not silently resolved last-wins before signing."""
    private_pem, public_b64 = keypair
    body_hash = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    doc = (
        "---\nurl: https://a\nurl: https://b\n"
        f"content_hash: {body_hash}\nbytes_sha256: def\nstatus_code: 200\n"
        "fetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n---\n\n" + BODY
    )
    # verify rejects with a clear duplicate-key error
    ok, reason = verify_document(doc, expected_public_key=public_b64)
    assert not ok
    assert "duplicate" in reason.lower()
    # signing a duplicate-key doc also fails loudly
    import pytest
    with pytest.raises(ValueError):
        sign_document(doc, private_pem)


def test_nested_duplicate_keys_rejected(keypair):
    """Duplicate keys at any nesting depth are caught (not just top-level)."""
    private_pem, public_b64 = keypair
    body_hash = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    doc = (
        "---\nurl: https://a\nmeta:\n  x: 1\n  x: 2\n"
        f"content_hash: {body_hash}\nbytes_sha256: def\nstatus_code: 200\n"
        "fetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n---\n\n" + BODY
    )
    ok, reason = verify_document(doc, expected_public_key=public_b64)
    assert not ok
    assert "duplicate" in reason.lower()


def test_unhashable_key_rejected_cleanly():
    """An unhashable mapping key must be rejected cleanly, not raise a traceback."""
    doc = (
        "---\n? [a, b]\n: v\ncontent_hash: abc\nbytes_sha256: def\nstatus_code: 200\n"
        "fetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n---\n\n# Body\n"
    )
    ok, reason = verify_document(doc)
    assert not ok


def test_block_scalar_not_missplit(keypair):
    """Regression (#32): a block scalar containing '---' and 'signature: foo'
    lines must not be mistaken for the frontmatter fence or a signature field."""
    private_pem, public_b64 = keypair
    body_hash = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    doc = (
        "---\nurl: https://a\n"
        "notes: |\n  line one\n  ---\n  signature: not-a-sig\n  line four\n"
        f"content_hash: {body_hash}\nbytes_sha256: def\nstatus_code: 200\n"
        "fetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n---\n\n" + BODY
    )
    metadata, body = split_frontmatter(doc)
    assert metadata["notes"] == "line one\n---\nsignature: not-a-sig\nline four\n"
    # re-sign must preserve the block scalar body and not emit duplicate keys
    signed = sign_document(doc, private_pem)
    # exactly one column-0 signature field (block-scalar content must not match)
    sig_lines = [ln for ln in signed.split("\n") if ln.startswith("signature:")]
    assert len(sig_lines) == 1
    assert "signature: not-a-sig" in signed  # block scalar content preserved
    ok, _ = verify_document(signed, expected_public_key=public_b64)
    assert ok


def test_fractional_seconds_preserved(keypair):
    """Regression (#52): sub-second datetime tampering must invalidate."""
    from datetime import UTC, datetime

    from gnosis.core.signing import _json_safe

    assert "2026-09-03T00:00:00.123456Z" == _json_safe(
        datetime(2026, 9, 3, 0, 0, 0, 123456, tzinfo=UTC)
    )
    assert "2026-09-03T00:00:00Z" == _json_safe(datetime(2026, 9, 3, 0, 0, 0, 0, tzinfo=UTC))


def test_non_string_dict_keys_coerced(keypair):
    """Regression (#54): mixed-type YAML keys must not crash canonical_manifest."""
    from gnosis.core.signing import _json_safe

    out = _json_safe({1: "a", "url": "x", 2.5: "b"})
    assert out == {"1": "a", "url": "x", "2.5": "b"}


def test_horizontal_rule_not_frontmatter(keypair):
    """Regression (#55): a leading horizontal rule (----) must not be treated
    as a frontmatter fence."""
    doc = "----\n\n# Body\n"
    metadata, body = split_frontmatter(doc)
    assert metadata == {}
    assert body == doc
