"""Cloud command wiring. SDK imports occur only inside cloud commands."""

import argparse
import json
import os
from pathlib import Path

from filelock import Timeout

from storage.local import LocalStore
from storage.manifest import IntegrityError, parse_json, safe_path
from storage.transfer import CloudError, S3Transfer


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CloudError(f"Configure {name} locally. See docs/cloud-integration.md.")
    return value


def _s3_client():
    if not os.environ.get("AWS_PROFILE") and not (
        os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
    ):
        raise CloudError("Set AWS_PROFILE for a configured local profile, or standard AWS credential environment variables.")
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise CloudError("Install requirements-cloud.txt in the project environment.") from None
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE") or None)
    if session.get_credentials() is None:
        raise CloudError("AWS credentials are unavailable. Configure or refresh the selected profile locally.")
    return session.client("s3", region_name=_required("AWS_REGION"), config=Config(
        connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1},
    ))


def _snowflake_factory():
    configuration = {
        "account": _required("SNOWFLAKE_ACCOUNT"), "user": _required("SNOWFLAKE_USER"),
        "database": _required("SNOWFLAKE_DATABASE"), "warehouse": _required("SNOWFLAKE_WAREHOUSE"),
        "role": _required("SNOWFLAKE_ROLE"), "private_key_file": _required("SNOWFLAKE_PRIVATE_KEY_FILE"),
    }
    if not Path(configuration["private_key_file"]).is_file():
        raise CloudError("The configured Snowflake private key file is unavailable.")
    try:
        import snowflake.connector
    except ImportError:
        raise CloudError("Install requirements-cloud.txt in the project environment.") from None
    if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
        configuration["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]

    def connect():
        return snowflake.connector.connect(
            **configuration, autocommit=False, paramstyle="pyformat",
            login_timeout=15, network_timeout=30,
            session_parameters={
                "QUERY_TAG": "financial-data-platform-raw",
                "STATEMENT_TIMEOUT_IN_SECONDS": 120,
                "LOCK_TIMEOUT": 30,
                "PYTHON_CONNECTOR_QUERY_RESULT_FORMAT": "JSON",
            },
        )

    target = "|".join(configuration[name] for name in ("account", "database", "role", "warehouse"))
    return connect, target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion", description="Transfer or load validated local v2 batches.")
    parser.add_argument("command", choices=("transfer", "load"))
    parser.add_argument("--source", choices=("fred", "sec"), required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--run-id", help="Select one committed run. Otherwise process all committed batches in order.")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("FIN_DATA_DIR") or ".local/data")
    args = parser.parse_args(argv)
    try:
        store = LocalStore(args.data_dir)
        manifests = store.manifests(args.source, args.entity)
        if args.run_id:
            manifests = [batch for batch in manifests if batch["run_id"] == args.run_id]
        if not manifests:
            raise CloudError("No matching committed batches were found.")
        if any(batch["schema_version"] != 2 for batch in manifests):
            raise CloudError("Selected batches include v1 artifacts. Establish a v2 baseline before cloud transfer.")
        bucket, namespace = _required("FIN_S3_BUCKET"), _required("FIN_ARCHIVE_NAMESPACE")
        factory = target = None
        if args.command == "load":
            factory, target = _snowflake_factory()
        transfer = S3Transfer(store, _s3_client(), bucket=bucket, namespace=namespace)
        if args.command == "load":
            from warehouse.loader import SnowflakeLoader
            loader = SnowflakeLoader(store, transfer, factory, target_id=target)
        failures = 0
        for manifest in manifests:
            try:
                report = transfer.transfer(manifest) if args.command == "transfer" else loader.load(manifest)
            except (CloudError, OSError) as error:
                failures += 1
                report = {"run_id": manifest["run_id"], "status": "failed",
                          "error": str(error) if isinstance(error, CloudError) else "Batch integrity or local storage failed."}
            print(json.dumps(report))
        return 1 if failures else 0
    except (CloudError, IntegrityError, Timeout) as error:
        print(str(error) if isinstance(error, CloudError) else "Batch validation failed or the archive is in use.")
        return 1
    except Exception:
        print("Cloud configuration or connection failed. Check local configuration and attempt journals.")
        return 1
