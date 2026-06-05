"""Manual Massive/Polygon client commands."""

from __future__ import annotations

import argparse
import json
import sys

from quant_symbols.vendors.massive.client import MassiveClient
from quant_symbols.vendors.massive.errors import MassiveError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Massive/Polygon reference-data utilities")
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow a real Massive/Polygon API request; disabled by default",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.live:
        print("live check disabled; pass --live with MASSIVE_API_KEY set")
        return 0

    try:
        client = MassiveClient.from_env()
        page = next(client.iter_ticker_pages(ticker="AAPL", limit=1, max_pages=1))
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


if __name__ == "__main__":
    raise SystemExit(main())
