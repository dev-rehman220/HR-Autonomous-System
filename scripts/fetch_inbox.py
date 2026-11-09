"""CLI utility to fetch from mailbox and ingest into roster."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import ROSTER_DB_PATH
from src.ingest import build_email_source, ingest
from src.logging_config import configure_logging
from src.roster.store import SqliteApplicantStore


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Fetch inbox applications and upsert into roster")
    parser.add_argument("--source", default="local", choices=["local", "mcp"],
                        help="Ingestion source (default: local)")
    parser.add_argument("--maildir", default="tests/fixtures/mail",
                        help="Local mailbox directory when source=local")
    parser.add_argument("--label", default="", help="Gmail label filter")
    parser.add_argument("--query", default="", help="Gmail query filter")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--db", default=ROSTER_DB_PATH, help="Roster SQLite path")

    args = parser.parse_args()

    if args.source == "local":
        from src.ingest.local_source import LocalFileSource
        source = LocalFileSource(args.maildir)
    else:
        source = build_email_source("mcp")

    store = SqliteApplicantStore(args.db)
    try:
        result = ingest(
            source,
            store,
            label=args.label or None,
            query=args.query or None,
            max_results=args.max_results,
            lookback_days=args.lookback_days,
        )
    finally:
        store.close()

    print(result.summary)
    for error in result.errors:
        print(f"ERROR: {error}")
    if result.new == 0 and result.duplicates == 0 and result.fetched > 0:
        print("(no CV attachments detected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
