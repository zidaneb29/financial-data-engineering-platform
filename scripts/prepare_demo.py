"""Build a local, validated deployment plan without cloud clients or provisioning."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from storage.local import LocalStore, json_bytes
from storage.manifest import digest
from storage.transfer import prepare_batch
from scripts.validate_sources import inspect_batch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / ".local/live-validation-66995445b3f349a2a380442d675db077/archive"


def prepare(archive: Path, namespace: str) -> dict:
    store = LocalStore(archive)
    files = [path for path in store.root.rglob("*") if path.is_file()]
    before = {path.relative_to(store.root).as_posix(): digest(path.read_bytes()) for path in files}
    batches = []
    unique_objects = {}
    for source, entity in (("fred", "DGS10"), ("sec", "0000789019")):
        manifests = store.manifests(source, entity)
        if len(manifests) != 2:
            raise ValueError("Expected the two reviewed live batches per source")
        for index, manifest in enumerate(manifests):
            validated = inspect_batch(store, manifest)
            prepared = prepare_batch(store, manifest, namespace)
            for relative, body in prepared.artifacts.items():
                unique_objects[f"{namespace}/{relative}"] = len(body)
            unique_objects[f"{namespace}/ready/{prepared.batch_id}.json"] = len(json_bytes(prepared.receipt))
            commands = {}
            for operation in ("transfer", "load"):
                commands[operation] = [
                    str(ROOT / ".venv/Scripts/python.exe"), "-m", "ingestion", operation,
                    "--source", source, "--entity", entity, "--run-id", manifest["run_id"],
                    "--data-dir", str(store.root),
                ]
            batches.append({
                "stage": "initial" if index == 0 else "optional_snapshot_repeat",
                "source": source, "entity": entity, "run_id": manifest["run_id"],
                "batch_id": prepared.batch_id, "manifest": manifest["manifest"],
                "manifest_file_sha256": prepared.receipt["manifest_file_sha256"],
                "expected": validated["loader_input"], "commands": commands,
            })
    after = {path.relative_to(store.root).as_posix(): digest(path.read_bytes()) for path in files}
    if before != after:
        raise OSError("Source archive changed while preparing the plan")
    return {
        "schema_version": 1, "archive": str(store.root), "namespace": namespace,
        "approval_status": "not_authorized_for_execution",
        "archive_hashes": before, "archive_unchanged": True, "batches": batches,
        "all_four_batches": {
            "s3_objects": len(unique_objects), "s3_bytes": sum(unique_objects.values()),
            "changes": sum(item["expected"]["changes"] for item in batches),
            "snapshot_members": sum(item["expected"]["snapshot_members"] for item in batches),
            "quarantined": sum(item["expected"]["quarantined"] for item in batches),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--namespace", default="fdep-demo")
    args = parser.parse_args()
    report = prepare(args.archive, args.namespace)
    directory = ROOT / ".local" / f"deployment-preparation-{uuid4().hex}"
    directory.mkdir()
    target = directory / "plan.json"
    target.write_bytes(json_bytes(report))
    print(target)
    print(json.dumps(report["all_four_batches"], sort_keys=True))


if __name__ == "__main__":
    main()
