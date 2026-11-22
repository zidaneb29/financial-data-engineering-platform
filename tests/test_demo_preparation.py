import base64

import pytest
from cryptography.hazmat.primitives import serialization

from scripts.generate_demo_key import generate


def test_generated_key_is_encrypted_and_existing_directory_is_preserved(tmp_path):
    directory = tmp_path / "synthetic-test-key"
    result = generate(directory, "synthetic-passphrase-for-unit-test")
    private = (directory / "loader.p8").read_bytes()
    with pytest.raises(TypeError):
        serialization.load_pem_private_key(private, password=None)
    loaded = serialization.load_pem_private_key(private, password=b"synthetic-passphrase-for-unit-test")
    assert loaded.key_size == 2048
    encoded = base64.b64encode(loaded.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode("ascii")
    binding = (directory / "bind-public-key.sql").read_text()
    assert encoded in binding and "PRIVATE KEY" not in binding
    assert "DISABLED" not in binding
    assert result["public_key_fingerprint"].startswith("SHA256:")
    with pytest.raises(FileExistsError):
        generate(directory, "synthetic-passphrase-for-unit-test")
    assert (directory / "loader.p8").read_bytes() == private
