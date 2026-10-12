"""CLI entrypoint for the ingestion pipeline."""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from ai_employee.db import init_schema
from ai_employee.ingestion.pipeline import IngestResult, ingest
from ai_employee.ingestion.sources import Source, SourceConfigError, from_spec
from ai_employee.observability import configure_logging, request_context

DEFAULT_SOURCE = "data/documents"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index documents into PGVector.")
    parser.add_argument(
        "source",
        nargs="?",
        default=DEFAULT_SOURCE,
        help=(
            "file or directory to ingest, or azure://CONTAINER/PREFIX for Azure Blob Storage "
            f"(default: {DEFAULT_SOURCE})"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-index every document, ignoring the change checks",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete indexed documents that no longer exist in the source",
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
    configure_logging()

    # One id for the whole run, so every document's line can be traced back to the run that
    # produced it in a shared log.
    with request_context():
        try:
            source = from_spec(args.source)
        except SourceConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        if not args.skip_schema:
            init_schema()

        try:
            results = ingest(source, force=args.force, acl_principals=args.acl, prune=args.prune)
        except SourceConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        return _report(results, source, prune=args.prune)


def _report(results: list[IngestResult], source: Source, *, prune: bool) -> int:
    """Print the one-line summary and pick the exit code."""
    if not results:
        print(f"no supported documents found in {source.label}")
        return 1

    counts = Counter(result.status for result in results)
    chunks = sum(result.chunk_count for result in results)
    summary = (
        f"{counts['indexed']} indexed ({chunks} chunks), "
        f"{counts['skipped']} skipped, {counts['empty']} empty, {counts['unsupported']} unsupported"
    )
    if prune:
        summary += f", {counts['pruned']} pruned"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
