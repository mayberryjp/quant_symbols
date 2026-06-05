"""Manual Massive/Polygon client commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from quant_symbols.symbol_master.fixtures import load_massive_fixture_pages
from quant_symbols.symbol_master.massive_raw_storage import MassiveRawPayloadStorageJob
from quant_symbols.vendors.massive.client import MassiveClient
from quant_symbols.vendors.massive.errors import MassiveError
from quant_symbols.vendors.massive.models import TickerReferencePage


ClientFactory = Callable[[], MassiveClient]
EngineFactory = Callable[[], Any]
RawStorageJobFactory = Callable[[Any], MassiveRawPayloadStorageJob]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Massive/Polygon reference-data utilities")
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow a real Massive/Polygon API request; disabled by default",
    )
    parser.add_argument(
        "--ticker",
        help="ticker to request or select from fixtures; live default: AAPL",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=1,
        help="maximum ticker records to request; default: 1",
    )
    parser.add_argument(
        "--raw-fetch",
        action="store_true",
        help="fetch one tiny ticker-reference page and store raw provider payload rows",
    )
    parser.add_argument(
        "--fixture",
        help="Massive fixture JSON file or directory to use with --raw-fetch fixture mode",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    engine_factory: EngineFactory | None = None,
    raw_storage_job_factory: RawStorageJobFactory | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.raw_fetch:
        return _run_raw_fetch(
            args,
            client_factory=client_factory,
            engine_factory=engine_factory,
            raw_storage_job_factory=raw_storage_job_factory,
        )

    if not args.live:
        print("live check disabled; pass --live with MASSIVE_API_KEY set")
        return 0

    return _run_live_smoke(args, client_factory=client_factory)


def _run_live_smoke(args: argparse.Namespace, *, client_factory: ClientFactory | None) -> int:
    try:
        factory = client_factory or MassiveClient.from_env
        client = factory()
        page = next(client.iter_ticker_pages(ticker=_live_ticker(args), limit=args.limit, max_pages=1))
    except StopIteration:
        print("no ticker results returned")
        return 1
    except MassiveError as exc:
        print(f"massive client error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": page.status,
                "count": page.count,
                "request_id": page.request_id,
                "tickers": [result.ticker for result in page.results],
            },
            sort_keys=True,
        )
    )
    return 0


def _run_raw_fetch(
    args: argparse.Namespace,
    *,
    client_factory: ClientFactory | None,
    engine_factory: EngineFactory | None,
    raw_storage_job_factory: RawStorageJobFactory | None,
) -> int:
    mode = "live" if args.live else "fixture"
    if not args.live and not args.fixture:
        print("massive raw fetch error: --fixture is required unless --live is set", file=sys.stderr)
        return 2

    try:
        if args.live:
            factory = client_factory or MassiveClient.from_env
            client = factory()
            pages = client.iter_ticker_pages(ticker=_live_ticker(args), limit=args.limit, max_pages=1)
        else:
            pages = _load_raw_fetch_fixture_pages(Path(args.fixture), ticker=args.ticker, limit=args.limit)
    except MassiveError as exc:
        print(f"massive client error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"massive raw fetch error: {exc}", file=sys.stderr)
        return 2

    try:
        engine = (engine_factory or _engine)()
        job = (
            raw_storage_job_factory(engine)
            if raw_storage_job_factory is not None
            else MassiveRawPayloadStorageJob(engine=engine)
        )
        summary = job.store_pages(
            pages,
            request_params=_raw_fetch_request_params(args, mode=mode),
        )
    except Exception as exc:
        print(f"massive raw fetch error: {exc}", file=sys.stderr)
        return 2

    print(_format_raw_fetch_summary(summary, mode=mode))
    return 0 if summary.status == "ok" else 1


def _raw_fetch_request_params(args: argparse.Namespace, *, mode: str) -> dict[str, object]:
    params: dict[str, object] = {
        "mode": mode,
        "limit": args.limit,
    }
    if args.ticker is not None or args.live:
        params["ticker"] = _live_ticker(args) if args.live else args.ticker
    if args.fixture:
        params["fixture"] = args.fixture
    return params


def _load_raw_fetch_fixture_pages(
    path: Path,
    *,
    ticker: str | None,
    limit: int,
) -> tuple[TickerReferencePage, ...]:
    pages = load_massive_fixture_pages(path)
    records = [
        reference.raw
        for page in pages
        for reference in page.results
        if ticker is None or reference.ticker == ticker
    ][:limit]
    request_url = pages[0].request_url if pages else f"fixture://{path.as_posix()}"
    return (
        TickerReferencePage.from_payload(
            {
                "status": "OK",
                "request_id": "fixture",
                "count": len(records),
                "results": records,
            },
            request_url=request_url,
        ),
    )


def _live_ticker(args: argparse.Namespace) -> str:
    return args.ticker or "AAPL"


def _format_raw_fetch_summary(summary: Any, *, mode: str) -> str:
    run_id = summary.run_id if summary.run_id is not None else "none"
    return (
        f"massive_raw_fetch={summary.status} "
        f"run_id={run_id} "
        f"mode={mode} "
        f"status={summary.status} "
        f"records_seen={summary.records_seen} "
        f"raw_payloads_inserted={summary.raw_payloads_inserted} "
        f"errors={summary.errors}"
    )


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
    )


def _engine() -> Any:
    try:
        from sqlalchemy import create_engine
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLAlchemy is required for --raw-fetch storage") from exc
    return create_engine(_database_url(), pool_pre_ping=True)


if __name__ == "__main__":
    raise SystemExit(main())
