"""Tests for SQL guards and authorizers."""

import sqlite3
import pytest

from raxorehearse.models import UnsupportedSql
from raxorehearse.sql_guard import (
    migration_authorizer,
    read_only_authorizer,
    validate_statement_tokens,
)


def test_t23_transaction_escape_rejected() -> None:
    """T23: Explicit BEGIN/COMMIT/SAVEPOINT rejected."""
    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("BEGIN TRANSACTION;")
    assert "Explicit transaction" in str(exc.value)

    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("SAVEPOINT sp1;")
    assert "Explicit transaction" in str(exc.value)

    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("COMMIT;")
    assert "Explicit transaction" in str(exc.value)


def test_t24_external_effects_denied() -> None:
    """T24: ATTACH, VACUUM INTO, forbidden function calls denied."""
    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("ATTACH DATABASE 'other.db' AS other;")
    assert "ATTACH" in str(exc.value)

    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("VACUUM INTO 'dump.db';")
    assert "VACUUM" in str(exc.value)

    with pytest.raises(UnsupportedSql) as exc:
        validate_statement_tokens("CREATE VIRTUAL TABLE v USING fts5(data);")
    assert "CREATE VIRTUAL TABLE" in str(exc.value)

    # Authorizer checks
    assert (
        migration_authorizer(sqlite3.SQLITE_ATTACH, "other.db", None, None, None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_FUNCTION, None, "load_extension", None, None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_FUNCTION, None, "readfile", None, None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_FUNCTION, None, "writefile", None, None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_PRAGMA, "writable_schema", "1", None, None)
        == sqlite3.SQLITE_DENY
    )


def test_defer_foreign_keys_allowed() -> None:
    """defer_foreign_keys = ON is allowed, but OFF is denied."""
    assert (
        migration_authorizer(sqlite3.SQLITE_PRAGMA, "defer_foreign_keys", "ON", None, None)
        == sqlite3.SQLITE_OK
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_PRAGMA, "defer_foreign_keys", "1", None, None)
        == sqlite3.SQLITE_OK
    )
    assert (
        migration_authorizer(sqlite3.SQLITE_PRAGMA, "defer_foreign_keys", "OFF", None, None)
        == sqlite3.SQLITE_DENY
    )


def test_read_only_authorizer_denies_writes() -> None:
    """Read-only authorizer permits SELECT/READ and denies INSERT/UPDATE/DELETE."""
    assert (
        read_only_authorizer(sqlite3.SQLITE_SELECT, None, None, None, None)
        == sqlite3.SQLITE_OK
    )
    assert (
        read_only_authorizer(sqlite3.SQLITE_READ, "users", "id", "main", None)
        == sqlite3.SQLITE_OK
    )
    assert (
        read_only_authorizer(sqlite3.SQLITE_INSERT, "users", None, "main", None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        read_only_authorizer(sqlite3.SQLITE_UPDATE, "users", "id", "main", None)
        == sqlite3.SQLITE_DENY
    )
    assert (
        read_only_authorizer(sqlite3.SQLITE_PRAGMA, "query_only", "ON", "main", None)
        == sqlite3.SQLITE_DENY
    )
