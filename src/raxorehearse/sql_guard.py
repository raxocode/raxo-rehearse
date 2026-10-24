"""SQL guards and authorizers for migration and check execution."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from raxorehearse.models import UnsupportedSql

BANNED_FUNCTIONS = {
    "load_extension",
    "readfile",
    "writefile",
    "fts3_tokenizer",
}

# Regex for stripping leading comments and finding leading tokens
LEADING_COMMENT_RE = re.compile(
    r"^(?:\s+|--[^\n]*\n|/\*.*?\*/)+",
    re.DOTALL,
)


def validate_statement_tokens(sql: str, filename: str = "", line: int = 1) -> None:
    """Pre-check statement leading tokens to provide friendly unsupported SQL errors.

    Does not ban WITH, triggers, quoted identifiers, or ordinary DDL/DML.
    """
    clean_sql = LEADING_COMMENT_RE.sub("", sql).strip()
    if not clean_sql:
        return

    # Extract first 3 tokens
    words = clean_sql.split(maxsplit=3)
    first = words[0].upper().rstrip(";")
    second = words[1].upper().rstrip(";") if len(words) > 1 else ""
    third = words[2].upper().rstrip(";") if len(words) > 2 else ""

    ctx = f" in {filename}:{line}" if filename else ""

    if first in ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE") or (
        first == "END" and second in ("TRANSACTION", "WORK")
    ):
        raise UnsupportedSql(
            f"Explicit transaction control statement '{first}'{ctx} is not allowed. "
            "Raxo Rehearse automatically wraps each migration file in a transaction."
        )

    if first == "VACUUM":
        raise UnsupportedSql(f"VACUUM statement{ctx} is not supported in migration rehearsals.")

    if first == "ANALYZE":
        raise UnsupportedSql(f"ANALYZE statement{ctx} is not supported in migration rehearsals.")

    if first == "ATTACH":
        raise UnsupportedSql(f"ATTACH DATABASE statement{ctx} is not allowed in migration rehearsals.")

    if first == "DETACH":
        raise UnsupportedSql(f"DETACH DATABASE statement{ctx} is not allowed in migration rehearsals.")

    if first == "CREATE" and second == "VIRTUAL" and third.startswith("TABLE"):
        raise UnsupportedSql(
            f"CREATE VIRTUAL TABLE statement{ctx} is not supported in migration rehearsals."
        )


def migration_authorizer(
    action_code: int,
    arg1: str | None,
    arg2: str | None,
    dbname: str | None,
    source: str | None,
) -> int:
    """SQLite authorizer callback for migration execution on working database."""
    # Deny external database operations and transaction escape
    if action_code in (
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_SAVEPOINT,
        sqlite3.SQLITE_CREATE_VTABLE,
        sqlite3.SQLITE_DROP_VTABLE,
    ):
        return sqlite3.SQLITE_DENY

    # Deny PRAGMAs except defer_foreign_keys = ON / TRUE / 1
    if action_code == sqlite3.SQLITE_PRAGMA:
        pragma_name = (arg1 or "").lower()
        pragma_val = (arg2 or "").lower()
        if pragma_name == "defer_foreign_keys" and pragma_val in ("on", "true", "1"):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    # Deny prohibited functions
    if action_code == sqlite3.SQLITE_FUNCTION:
        func_name = (arg2 or arg1 or "").lower()
        if func_name in BANNED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return sqlite3.SQLITE_OK


def read_only_authorizer(
    action_code: int,
    arg1: str | None,
    arg2: str | None,
    dbname: str | None,
    source: str | None,
) -> int:
    """SQLite authorizer callback for read-only aggregate checks."""
    # Only allow SELECT, READ, recursive, and safe functions
    if action_code in (
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        getattr(sqlite3, "SQLITE_RECURSIVE", 33),
    ):
        return sqlite3.SQLITE_OK

    if action_code == sqlite3.SQLITE_FUNCTION:
        func_name = (arg2 or arg1 or "").lower()
        if func_name in BANNED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return sqlite3.SQLITE_DENY
