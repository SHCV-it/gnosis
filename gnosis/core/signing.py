"""Ed25519 cryptographic signing of gnosis output packages (seal of origin).

Signs a canonical manifest of a document's full provenance frontmatter (minus
the signature block itself) plus a recomputed body hash, so a consumer can
verify (1) the identity of the producer and (2) that neither the markdown body
nor ANY provenance field changed after signing.

`cryptography` is imported lazily so signing stays an optional extra
(`pip install 'gnosis-markdown[sign]'`).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime

import yaml

# Fields excluded from the canonical manifest (they ARE the signature block).
_SIGNATURE_FIELDS = frozenset({"signature", "public_key", "manifest_sha256"})
# Fields stripped when RE-signing (superset: signed_at is signed content but the
# old one must be removed so re-signing replaces rather than duplicates).
_STRIP_FIELDS = _SIGNATURE_FIELDS | {"signed_at"}


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


def _json_safe(value):
    """Coerce a YAML-parsed value to a JSON-serialisable one (dates etc.)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {_json_safe(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def canonical_manifest(markdown: str, metadata: dict) -> str:
    """Canonical JSON of every provenance field, with the body hash recomputed.

    Every frontmatter key is signed EXCEPT the signature block, so tampering any
    provenance field invalidates the signature. `content_hash` is always
    recomputed from the body so body tampering is caught too. Non-JSON YAML
    values (e.g. unquoted dates) are coerced to strings.
    """
    manifest = {
        k: _json_safe(v) for k, v in metadata.items() if k not in _SIGNATURE_FIELDS
    }
    # The STORED content_hash is signed as-is; the body is bound independently
    # via a recomputed hash, so tampering either one invalidates the signature.
    manifest["body_sha256"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
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
    signed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_bytes = canonical_manifest(
        markdown, {**metadata, "signed_at": signed_at}
    ).encode("utf-8")
    signature = key.sign(manifest_bytes)
    return {
        "signature": base64.b64encode(signature).decode(),
        "public_key": public_key_from_private(private_key_pem),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "signed_at": signed_at,
    }


def verify_signature(
    markdown: str, metadata: dict, signature: str, public_key_b64: str
) -> bool:
    """Verify a signature against a document's canonical manifest."""
    _, _, Ed25519PublicKey = _ed25519()
    try:
        manifest_bytes = canonical_manifest(markdown, metadata).encode("utf-8")
        stored = metadata.get("manifest_sha256")
        if stored and hashlib.sha256(manifest_bytes).hexdigest() != stored:
            return False
        declared = metadata.get("content_hash")
        if declared and declared != hashlib.sha256(markdown.encode("utf-8")).hexdigest():
            return False
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
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


def _is_signature_line(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(f"{f}:") for f in _STRIP_FIELDS)


def sign_document(document: str, private_key_pem: str) -> str:
    """Sign a rendered document; return a new document with signature fields.

    Re-signing replaces any existing signature block (no duplicate YAML keys).
    """
    metadata, markdown = split_frontmatter(document)
    sig = sign_manifest(markdown, metadata, private_key_pem)
    if not document.startswith("---"):
        front = yaml.safe_dump(sig, sort_keys=False).rstrip("\n")
        return f"---\n{front}\n---\n\n{document}"
    lines = document.split("\n")
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines) - 1
    )
    kept = [ln for ln in lines[:end] if not _is_signature_line(ln)]
    sig_lines = yaml.safe_dump(sig, sort_keys=False).rstrip("\n").split("\n")
    return "\n".join(kept + sig_lines + lines[end:])


def verify_document(
    document: str, expected_public_key: str | None = None
) -> tuple[bool, str]:
    """Verify a signed document; return (ok, reason).

    When `expected_public_key` is provided, the embedded key must match it,
    so producer identity is actually pinned (not just self-consistent).
    """
    try:
        metadata, markdown = split_frontmatter(document)
    except yaml.YAMLError:
        return False, "signature INVALID — malformed frontmatter"
    signature = metadata.get("signature")
    public_key = metadata.get("public_key")
    if not signature or not public_key:
        return False, "document is not signed (missing signature/public_key)"
    if expected_public_key and public_key != expected_public_key:
        return False, "public key mismatch — NOT signed by the expected producer"
    if not verify_signature(markdown, metadata, signature, public_key):
        return False, "signature INVALID — body or provenance was modified after signing"
    if not expected_public_key:
        return False, "signature valid but identity NOT pinned — pass --public-key to verify the producer"
    return True, "signature valid (identity pinned)"
