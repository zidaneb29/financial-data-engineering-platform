"""Build and publish dbt analytics from an already captured local archive."""

import argparse
import logging
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from filelock import FileLock

from orchestration.local import build_analytics
from scripts.phase4_fixture import source_scope
from storage.local import LocalStore
from warehouse.local_archive import load_archive


def publish_history(
    archive: Path, output: Path, window: tuple[str, str] | None, namespace: str = "local-history",
) -> None:
    scope = source_scope()
    entities = [("fred", code) for code in scope["fred"]["series"]]
    entities.extend(("sec", cik) for cik in scope["sec"]["companies"].values())
    output = output.resolve()
    if namespace == "fixture":
        raise ValueError("The fixture archive namespace is reserved")
    if output.is_relative_to(archive.resolve()):
        raise ValueError("Place the dashboard database outside the source archive")
    if not archive.is_dir():
        raise FileNotFoundError("Source archive directory does not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output.with_suffix(output.suffix + ".lock")), timeout=5):
        with TemporaryDirectory(dir=output.parent) as directory:
            raw = Path(directory) / "archive_input.duckdb"
            load_archive(LocalStore(archive), raw, entities, window=window, namespace=namespace)
            build_analytics(raw, output)
    logging.info("Published %s after dbt validation", output.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--window", nargs=2, type=date.fromisoformat, metavar=("START", "END"))
    scope.add_argument("--partial-replay", action="store_true", help="Replay a known incomplete historical archive")
    parser.add_argument("--namespace", default="local-history")
    args = parser.parse_args()
    if args.window and args.window[0] > args.window[1]:
        parser.error("Window start must be on or before its end")
    if args.namespace == "fixture":
        parser.error("The fixture archive namespace is reserved")
    window = tuple(day.isoformat() for day in args.window) if args.window else None
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    publish_history(args.archive, args.output, window, args.namespace)


if __name__ == "__main__":
    main()
