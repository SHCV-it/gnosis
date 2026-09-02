"""Ed25519 cryptographic signing of gnosis output packages (seal of origin).

Signs a canonical manifest of a document's provenance fields so a consumer can
verify (1) the identity of the producer and (2) that neither the markdown body
nor the provenance metadata changed after signing.

`cryptography` is imported lazily so signing stays an optional extra
(`pip install 'gnosis-markdown[sign]'`).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

import yaml

_MANIFEST_FIELDS = (
    "title",
    "url",
    "fetched_at",
    "content_hash",
    "bytes_sha256",
    "status_code",
    "generator",
    "etag",
    "last_modified",
    "language",
    "author",
    "published_time",
    "modified_time",
    "site_name",
    "description",
)


def _ed25519():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - exercised via [sign] extra
        raise ImportError(
            "Signing requires the 'cryptography' package. "
            "Install it with: pip install 'gnosis-markdown[sign]'"
        ) from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def canonical_manifest(markdown: str, metadata: dict) -> str:
    """Canonical JSON of the provenance fields that define a document."""
    manifest = {k: metadata[k] for k in _MANIFEST_FIELDS if k in metadata}
    # content_hash is always recomputed from the body so body tampering is caught
    manifest["content_hash"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"))


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair; return (private_pem, public_b64)."""
    serialization, Ed25519PrivateKey, _ = _ed25519()
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    return private_pem, public_b64


def public_key_from_private(private_key_pem: str) -> str:
    """Return the base64 public key for a PEM private key."""
    serialization, _, _ = _ed25519()
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    return base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()


def sign_manifest(markdown: str, metadata: dict, private_key_pem: str) -> dict:
    """Sign a document's canonical manifest; return the signature fields."""
    serialization, _, _ = _ed25519()
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    manifest_bytes = canonical_manifest(markdown, metadata).encode("utf-8")
    signature = key.sign(manifest_bytes)
    return {
        "signature": base64.b64encode(signature).decode(),
        "public_key": public_key_from_private(private_key_pem),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "signed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def verify_signature(
    markdown: str, metadata: dict, signature: str, public_key_b64: str
) -> bool:
    """Verify a signature against a document's canonical manifest."""
    _, _, Ed25519PublicKey = _ed25519()
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        manifest_bytes = canonical_manifest(markdown, metadata).encode("utf-8")
        public_key.verify(base64.b64decode(signature), manifest_bytes)
        return True
    except Exception:
        return False


def split_frontmatter(document: str) -> tuple[dict, str]:
    """Split a rendered document into (metadata dict, markdown body)."""
    if not document.startswith("---"):
        return {}, document
    lines = document.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, document
    metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(metadata, dict):
        return {}, document
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return metadata, body


def sign_document(document: str, private_key_pem: str) -> str:
    """Sign a rendered document; return a new document with signature fields."""
    metadata, markdown = split_frontmatter(document)
    sig = sign_manifest(markdown, metadata, private_key_pem)
    if not document.startswith("---"):
        # no frontmatter: prefix one carrying only the signature
        front = yaml.safe_dump(sig, sort_keys=False).rstrip("\n")
        return f"---\n{front}\n---\n\n{document}"
    lines = document.split("\n")
    # insert signature fields at the end of the existing frontmatter block
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines) - 1
    )
    sig_lines = yaml.safe_dump(sig, sort_keys=False).rstrip("\n").split("\n")
    return "\n".join(lines[:end] + sig_lines + lines[end:])


def verify_document(document: str) -> tuple[bool, str]:
    """Verify a signed document; return (ok, reason)."""
    metadata, markdown = split_frontmatter(document)
    signature = metadata.get("signature")
    public_key = metadata.get("public_key")
    if not signature or not public_key:
        return False, "document is not signed (missing signature/public_key)"
    if verify_signature(markdown, metadata, signature, public_key):
        return True, f"signature valid (manifest {metadata.get('manifest_sha256', '?')})"
    return False, "signature INVALID — body or provenance was modified after signing"
