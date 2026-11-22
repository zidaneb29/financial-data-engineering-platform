"""Create an encrypted local RSA key and public-key binding SQL, without connecting."""

import argparse
import base64
import getpass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(directory: Path, passphrase: str) -> dict:
    if len(passphrase) < 12:
        raise ValueError("Use a passphrase of at least 12 characters")
    directory.mkdir(parents=True, exist_ok=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path = directory / "loader.p8"
    with private_path.open("xb") as stream:
        stream.write(private)
    private_path.chmod(0o600)
    (directory / "loader.pub").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    encoded = base64.b64encode(public).decode("ascii")
    statement = (
        "-- Public-key registration only. Execute after deployment approval.\n"
        "USE ROLE SECURITYADMIN;\n"
        f"ALTER USER FDEP_DEMO_INGEST SET RSA_PUBLIC_KEY = '{encoded}';\n"
        "DESC USER FDEP_DEMO_INGEST;\n"
    )
    (directory / "bind-public-key.sql").write_text(statement, encoding="utf-8")
    fingerprint = hashes.Hash(hashes.SHA256())
    fingerprint.update(public)
    return {
        "private_key_file": str(private_path.resolve()),
        "public_key_fingerprint": "SHA256:" + base64.b64encode(fingerprint.finalize()).decode("ascii"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="New directory beneath a protected local credentials folder")
    args = parser.parse_args()
    first = getpass.getpass("Private-key encryption passphrase: ")
    if first != getpass.getpass("Confirm passphrase: "):
        parser.error("Passphrases differ")
    try:
        result = generate(args.directory, first)
    except (OSError, ValueError):
        parser.error("Key generation failed. Use a fresh private directory and a strong passphrase.")
    print(result["private_key_file"])
    print(result["public_key_fingerprint"])


if __name__ == "__main__":
    main()
