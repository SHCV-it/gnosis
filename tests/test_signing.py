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
    private_pem, _ = keypair
    signed = sign_document(make_doc(), private_pem)
    ok, reason = verify_document(signed)
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
