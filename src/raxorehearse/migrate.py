"""Migration execution runner with per-file transactions and guards."""

from __future__ import annotations

import sqlite3
from typing import Any

from raxorehearse.limits import Limits
from raxorehearse.models import (
    Deadline,
    DeadlineExceeded,
    MigrationError,
    MigrationExecution,
    MigrationRecord,
    RehearseError,
    UnsupportedSql,
)
from raxorehearse.sql_guard import migration_authorizer, validate_statement_tokens


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: list[MigrationRecord],
    deadline: Deadline,
) -> None:
    """Apply migrations in command-line order, one transaction per file.

    Guards execution with the migration authorizer.
    Drains returned rows in bounded batches.
    Rolls back on error and stops sequence.
    """
    for mig in migrations:
        deadline.check()

        # Step 1: Pre-validate statement tokens
        for stmt in mig.statements:
            validate_statement_tokens(stmt.sql, filename=mig.name, line=stmt.line)

        # Step 2: Begin file-level transaction
        connection.set_authorizer(None)
        try:
            connection.execute("BEGIN IMMEDIATE")
        except Exception as exc:
            mig.execution = MigrationExecution.FAILED
            raise MigrationError(
                f"Failed to begin transaction for migration '{mig.name}': {exc}",
                migration_name=mig.name,
                statement_index=None,
                line=None,
                sqlite_errorname=getattr(exc, "sqlite_errorname", "MIGRATION_FAILED"),
            )

        # Step 3: Install authorizer and execute statements
        connection.set_authorizer(migration_authorizer)
        try:
            for stmt in mig.statements:
                deadline.check()
                try:
                    cursor = connection.execute(stmt.sql)
                    # Exhaust any returned rows (e.g. RETURNING clauses or SELECT)
                    while True:
                        deadline.check()
                        rows = cursor.fetchmany(500)
                        if not rows:
                            break
                except Exception as exc:
                    mig.execution = MigrationExecution.FAILED
                    err_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
                    raise MigrationError(
                        f"SQLite rejected statement {stmt.index} in {mig.name}; inspect that statement locally.",
                        migration_name=mig.name,
                        statement_index=stmt.index,
                        line=stmt.line,
                        sqlite_errorname=err_name,
                    )
        except Exception:
            connection.set_authorizer(None)
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            connection.set_authorizer(None)

        # Step 4: Commit transaction
        try:
            connection.execute("COMMIT")
            mig.execution = MigrationExecution.APPLIED
        except Exception as exc:
            mig.execution = MigrationExecution.FAILED
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            err_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
            raise MigrationError(
                f"Failed to commit migration '{mig.name}': {exc}",
                migration_name=mig.name,
                statement_index=None,
                line=None,
                sqlite_errorname=err_name,
            )


def verify_after_integrity(connection: sqlite3.Connection, deadline: Deadline) -> None:
    """Validate integrity and FK consistency on final working database."""
    deadline.check()
    connection.set_progress_handler(deadline.sqlite_progress_handler, 10000)
    try:
        try:
            qc = connection.execute("PRAGMA quick_check").fetchall()
        except sqlite3.OperationalError as exc:
            if deadline.is_expired():
                raise DeadlineExceeded("Timeout during final integrity check.")
            raise MigrationError(
                f"Final database integrity check failed: {exc}",
                sqlite_errorname="AFTER_INTEGRITY_FAILED",
            )

        if qc != [("ok",)]:
            raise MigrationError(
                f"Final database integrity check failed: {qc}",
                sqlite_errorname="AFTER_INTEGRITY_FAILED",
            )

        try:
            connection.execute("PRAGMA foreign_keys = ON")
            fk = connection.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.OperationalError as exc:
            if deadline.is_expired():
                raise DeadlineExceeded("Timeout during final foreign key check.")
            raise MigrationError(
                f"Final database foreign key check failed: {exc}",
                sqlite_errorname="AFTER_FOREIGN_KEYS_FAILED",
            )

        if fk:
            raise MigrationError(
                f"Final database has foreign key violations: {len(fk)} violations found.",
                sqlite_errorname="AFTER_FOREIGN_KEYS_FAILED",
            )
    finally:
        connection.set_progress_handler(None, 0)
