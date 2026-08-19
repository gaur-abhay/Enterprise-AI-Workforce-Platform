"""CLI entrypoint for the ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from ai_employee.config import get_settings
from ai_employee.db import init_schema
from ai_employee.ingestion.pipeline import ingest

DEFAULT_SOURCE = Path("data/documents")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index documents into PGVector.")
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"file or directory to ingest (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-index even when the content hash is unchanged",
    )
    parser.add_argument(
        "--acl",
        action="append",
        default=[],
        metavar="PRINCIPAL",
        help="restrict the ingested documents to this principal (repeatable)",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="do not apply schema.sql before ingesting",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.source.exists():
        print(f"error: {args.source} does not exist", file=sys.stderr)
        return 1

    if not args.skip_schema:
        init_schema()

    results = ingest(args.source, force=args.force, acl_principals=args.acl)
    if not results:
        print(f"no supported documents found under {args.source}")
        return 1

    counts = Counter(result.status for result in results)
    chunks = sum(result.chunk_count for result in results)
    print(
        f"{counts['indexed']} indexed ({chunks} chunks), "
        f"{counts['skipped']} skipped, {counts['empty']} empty, {counts['unsupported']} unsupported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())