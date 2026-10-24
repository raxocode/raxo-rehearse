"""Database isolation, backups, and integrity verification."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from raxorehearse.limits import Limits
from raxorehearse.models import (
    Deadline,
    DeadlineExceeded,
    MigrationError,
    RehearseError,
)


@dataclass
class DatabaseCopies:
    """Paths and connections to isolated before and working copies."""

    temp_dir: Path
    before_path: Path
    working_path: Path


def create_isolated_copies(
    source_path: Path,
    temp_dir: Path,
    limits: Limits,
    deadline: Deadline,
) -> DatabaseCopies:
    """Create isolated before.sqlite and working.sqlite using SQLite Backup API.

    The source is opened read-only and immutable.
    Source is backed up into before.sqlite, then before.sqlite is backed up into working.sqlite.
    The source is never opened writable.
    """
    deadline.check()

    resolved_source = source_path.resolve()
    source_uri = resolved_source.as_uri() + "?mode=ro&immutable=1"

    before_path = temp_dir / "before.sqlite"
    working_path = temp_dir / "working.sqlite"

    def progress_check(status: int, remaining: int, total: int) -> None:
        deadline.check()

    # Step 1: Open source read-only immutable
    try:
        source_conn = sqlite3.connect(source_uri, uri=True)
    except Exception as exc:
        raise RehearseError(f"Failed to open source database read-only: {exc}")

    try:
        # Step 2: Backup source -> before.sqlite
        before_conn = sqlite3.connect(str(before_path))
        try:
            source_conn.backup(before_conn, progress=progress_check)
        finally:
            before_conn.close()
    finally:
        source_conn.close()

    deadline.check()

    # Step 3: Backup before.sqlite -> working.sqlite
    before_conn = sqlite3.connect(str(before_path))
    try:
        working_conn = sqlite3.connect(str(working_path))
        try:
            before_conn.backup(working_conn, progress=progress_check)
        finally:
            working_conn.close()
    finally:
        before_conn.close()

    deadline.check()

    # Step 4: Validate baseline integrity on before.sqlite
    verify_baseline_integrity(before_path, deadline)

    return DatabaseCopies(
        temp_dir=temp_dir,
        before_path=before_path,
        working_path=working_path,
    )


def verify_baseline_integrity(db_path: Path, deadline: Deadline) -> None:
    """Run PRAGMA quick_check and foreign_key_check on baseline database."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.set_progress_handler(deadline.sqlite_progress_handler, 10000)

        # Quick check
        try:
            qc = conn.execute("PRAGMA quick_check").fetchall()
        except sqlite3.OperationalError as exc:
            if deadline.is_expired():
                raise DeadlineExceeded("Timeout during baseline integrity check.")
            raise MigrationError(
                f"Baseline database integrity check failed: {exc}",
                sqlite_errorname="BASELINE_INTEGRITY_FAILED",
            )

        if qc != [("ok",)]:
            raise MigrationError(
                f"Baseline database integrity check failed: {qc}",
                sqlite_errorname="BASELINE_INTEGRITY_FAILED",
            )

        # Foreign key check
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.OperationalError as exc:
            if deadline.is_expired():
                raise DeadlineExceeded("Timeout during baseline foreign key check.")
            raise MigrationError(
                f"Baseline database foreign key consistency check failed: {exc}",
                sqlite_errorname="BASELINE_FOREIGN_KEYS_FAILED",
            )

        if fk:
            raise MigrationError(
                f"Baseline database has foreign key violations: {len(fk)} violations found.",
                sqlite_errorname="BASELINE_FOREIGN_KEYS_FAILED",
            )
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def open_working_connection(
    working_path: Path, limits: Limits, deadline: Deadline
) -> sqlite3.Connection:
    """Open working database with isolation_level=None and size cap."""
    conn = sqlite3.connect(str(working_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        page_size_row = conn.execute("PRAGMA page_size").fetchone()
        page_size = page_size_row[0] if page_size_row else 4096
        max_pages = limits.max_working_db_bytes // page_size
        conn.execute(f"PRAGMA max_page_count = {max_pages}")
        conn.set_progress_handler(deadline.sqlite_progress_handler, 10000)
    except Exception:
        conn.close()
        raise
    return conn
