"""Tests for the signing CLI (gnosis-keygen / gnosis-verify entry points)."""

from click.testing import CliRunner

from gnosis.cli.signing_cli import keygen, verify
from gnosis.core.signing import generate_keypair, sign_document


def make_doc() -> str:
    return (
        "---\nurl: https://x\ncontent_hash: abc\nbytes_sha256: def\n"
        "status_code: 200\nfetched_at: '2026-09-03T00:00:00Z'\ngenerator: gnosis/2.0.0\n"
        "---\n\n# Body\n"
    )


def test_keygen_outputs_keypair():
    result = CliRunner().invoke(keygen)
    assert result.exit_code == 0
    assert "Public key" in result.output
    assert "BEGIN PRIVATE KEY" in result.output


def test_verify_pinned_valid_exits_zero(tmp_path):
    priv, pub = generate_keypair()
    f = tmp_path / "doc.md"
    f.write_text(sign_document(make_doc(), priv))
    result = CliRunner().invoke(verify, [str(f), "--public-key", pub])
    assert result.exit_code == 0
    assert "identity pinned" in result.output


def test_verify_unpinned_exits_nonzero(tmp_path):
    """Regression (external audit): unpinned verify must NOT exit 0, because
    origin is precisely what it does not establish."""
    priv, _ = generate_keypair()
    f = tmp_path / "doc.md"
    f.write_text(sign_document(make_doc(), priv))
    result = CliRunner().invoke(verify, [str(f)])
    assert result.exit_code != 0
    assert "NOT pinned" in result.output


def test_verify_tampered_fails(tmp_path):
    priv, pub = generate_keypair()
    f = tmp_path / "doc.md"
    f.write_text(sign_document(make_doc(), priv).replace("# Body", "# TAMPERED"))
    result = CliRunner().invoke(verify, [str(f), "--public-key", pub])
    assert result.exit_code != 0
    assert "INVALID" in result.output


def test_verify_wrong_key_fails(tmp_path):
    priv, _ = generate_keypair()
    _, other_pub = generate_keypair()
    f = tmp_path / "doc.md"
    f.write_text(sign_document(make_doc(), priv))
    result = CliRunner().invoke(verify, [str(f), "--public-key", other_pub])
    assert result.exit_code != 0
    assert "public key mismatch" in result.output
