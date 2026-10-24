"""Command-line interface for Raxo Rehearse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from raxorehearse import __version__
from raxorehearse.limits import (
    DEFAULT_TIMEOUT_SECONDS,
    MIN_SQLITE_VERSION,
    MIN_SQLITE_VERSION_STR,
    MIN_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
)
from raxorehearse.models import RunOptions


def check_sqlite_version() -> None:
    """Validate SQLite version >= 3.37.0."""
    import sqlite3

    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        sys.stderr.write(
            f"Error: SQLite version {sqlite3.sqlite_version} is unsupported. "
            f"Raxo Rehearse requires SQLite {MIN_SQLITE_VERSION_STR} or newer.\n"
        )
        sys.exit(20)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="raxorehearse",
        description="Rehearse SQLite migrations on disposable snapshots.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # demo subcommand
    demo_parser = subparsers.add_parser(
        "demo",
        help="Run rehearsal on synthetic demo fixtures (deliberate data loss, exits 10).",
    )
    demo_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="New output directory for reports.",
    )

    # check subcommand
    check_parser = subparsers.add_parser(
        "check",
        help="Rehearse migrations on a closed SQLite snapshot.",
    )
    check_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to closed standalone SQLite snapshot.",
    )
    check_parser.add_argument(
        "--migration",
        dest="migrations",
        type=Path,
        action="append",
        required=True,
        help="Path to migration SQL file (can be repeated, executes in order).",
    )
    check_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="New output directory for reports.",
    )
    check_parser.add_argument(
        "--checks",
        type=Path,
        default=None,
        help="Optional path to aggregate checks JSON file.",
    )
    check_parser.add_argument(
        "--fail-on",
        choices=["warning", "error"],
        default="warning",
        help="Finding threshold to trigger REVIEW (exit 10). Default: warning.",
    )
    check_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Cooperative timeout budget in seconds ({MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS}). Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    check_sqlite_version()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        options = RunOptions(
            database=None,
            migrations=[],
            out=args.out,
            checks=None,
            fail_on="warning",
            timeout=DEFAULT_TIMEOUT_SECONDS,
            is_demo=True,
        )
    elif args.command == "check":
        if args.timeout < MIN_TIMEOUT_SECONDS or args.timeout > MAX_TIMEOUT_SECONDS:
            sys.stderr.write(
                f"Error: --timeout must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}.\n"
            )
            return 20

        options = RunOptions(
            database=args.database,
            migrations=args.migrations,
            out=args.out,
            checks=args.checks,
            fail_on=args.fail_on,
            timeout=args.timeout,
            is_demo=False,
        )
    else:
        parser.print_help(sys.stderr)
        return 2

    from raxorehearse.service import run_rehearsal

    try:
        result = run_rehearsal(options)
        return result.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("\nRehearsal interrupted.\n")
        return 130
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 20
