"""Command-line entry point for local FRED and SEC ingestion."""

import argparse
import logging
import os
import sys
import tomllib
from datetime import date
from functools import partial
from pathlib import Path

import requests
from filelock import Timeout

from ingestion import fred, sec
from ingestion.http import IngestionError, JsonClient
from ingestion.pipeline import IngestionTask, run_ingestion
from storage.local import LocalStore


SCOPE_PATH = Path(__file__).resolve().parents[1] / "config" / "source_scope.toml"


def _args(argv: list[str] | None) -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(
        prog="python -m ingestion", description="Archive and normalize FRED and SEC data locally.",
        epilog="Cloud operations have separate help: python -m ingestion transfer --help; python -m ingestion load --help",
    )
    parser.add_argument("source", choices=("fred", "sec", "all"))
    parser.add_argument("--mode", choices=("incremental", "backfill"), default="incremental")
    parser.add_argument("--fred-series", action="append", metavar="ID", help="Select a configured series (repeatable)")
    parser.add_argument("--sec-issuer", action="append", metavar="TICKER_OR_CIK", help="Select a configured issuer (repeatable)")
    parser.add_argument("--start", type=date.fromisoformat, help="Backfill start, inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="Window end, inclusive (YYYY-MM-DD)")
    parser.add_argument("--lookback-days", type=int, default=730, help="FRED revision overlap (default: 730 days)")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("FIN_DATA_DIR") or ".local/data")
    args = parser.parse_args(argv)
    if args.start and args.mode != "backfill":
        parser.error("--start requires --mode backfill")
    if args.lookback_days < 1:
        parser.error("--lookback-days must be positive")
    if (args.source == "sec" and args.fred_series) or (args.source == "fred" and args.sec_issuer):
        parser.error("Entity selection must match the requested source")
    return parser, args


def _selected(parser, requested: list[str] | None, choices: dict) -> list[str]:
    if requested is None:
        return list(choices)
    for name in requested:
        if name not in choices:
            parser.error(f"Unknown configured entity: {name}")
    return list(dict.fromkeys(requested))


def _fetch_unconfigured(_batch, variable: str, message: str):
    raise IngestionError("missing_configuration", f"{variable}: {message}")


def _task_list(args, parser, session: requests.Session, scope: dict, today: date) -> list[IngestionTask]:
    tasks = []
    end = args.end or today
    if end > today or (args.start is not None and args.start > end):
        parser.error("Specify a window ending today or earlier, with start on or before end")

    if args.source in {"all", "fred"}:
        series = scope["fred"]["series"]
        configured = scope["fred"]["observation_start"]
        start = max(configured, args.start or configured)
        if start > end:
            parser.error(f"FRED windows must end on or after {configured}")
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        client = JsonClient(session, rate=1)

        def fred_window(store: LocalStore, series_id: str) -> tuple[date, date]:
            if args.mode == "backfill":
                return start, end
            uncovered = store.coverage("fred", series_id, configured)
            return fred.incremental_start(configured, uncovered, end, args.lookback_days), end

        for series_id in _selected(parser, args.fred_series, series):
            fetch = partial(fred.fetch, client, api_key=api_key, frequency=series[series_id], snapshot=today)
            tasks.append(IngestionTask(
                "fred", series_id, partial(fred_window, series_id=series_id),
                fetch if api_key else partial(
                    _fetch_unconfigured, variable="FRED_API_KEY", message="Set an application key locally",
                ),
            ))

    if args.source in {"all", "sec"}:
        companies = scope["sec"]["companies"]
        sec_lower = scope["sec"]["period_end_start"]
        sec_start = max(sec_lower, args.start or sec_lower)
        if sec_start > end:
            parser.error(f"SEC windows must end on or after {sec_lower}")
        forms = set(scope["sec"]["forms"])
        user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
        choices = {**{cik: cik for cik in companies.values()}, **companies}
        requested = [name.upper() for name in args.sec_issuer] if args.sec_issuer else None
        issuers = list(dict.fromkeys(choices[name] for name in _selected(parser, requested, choices)))
        client = JsonClient(session, rate=2)
        valid_contact = sec.valid_user_agent(user_agent)
        for cik in issuers:
            fetch = partial(sec.fetch, client, user_agent=user_agent, forms=forms)
            tasks.append(IngestionTask(
                "sec", cik, lambda _store: (sec_start, end),
                fetch if valid_contact else partial(
                    _fetch_unconfigured, variable="SEC_USER_AGENT",
                    message="Set an application name followed by a monitored contact email",
                ),
            ))
    return tasks


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] in {"transfer", "load"}:
        from storage.cloud_cli import main as cloud_main
        return cloud_main(arguments)
    parser, args = _args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        scope = tomllib.loads(SCOPE_PATH.read_text(encoding="utf-8"))
        with requests.Session() as session:
            tasks = _task_list(args, parser, session, scope, date.today())
            run = run_ingestion(LocalStore(args.data_dir), tasks, mode=args.mode)
    except Timeout:
        print("The data directory is already in use by another ingestion run.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Could not read configuration or local ingestion metadata, or write local results.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0 if run["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
