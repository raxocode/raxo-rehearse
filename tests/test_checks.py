"""Tests for aggregate checks parsing, validation, and read-only execution."""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from raxorehearse.checks import (
    evaluate_checks,
    execute_check_query,
    parse_and_validate_checks_json,
)
from raxorehearse.copies import create_isolated_copies, open_working_connection
from raxorehearse.demo_data import (
    BAD_SQL,
    CHECKS_JSON,
    GOOD_SQL,
)
from raxorehearse.limits import Limits
from raxorehearse.migrate import apply_migrations, verify_after_integrity
from raxorehearse.models import (
    CheckExecutionError,
    Deadline,
    InputError,
    MigrationRecord,
)
from raxorehearse.sql_statements import split_statements


def test_t33_config_validation() -> None:
    """T33: Wrong version, duplicate keys/IDs, unknown keys, booleans rejected."""
    limits = Limits()

    # Wrong version
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json('{"version": 2, "checks": []}', limits)
    assert "version" in str(exc.value)

    # Boolean as version
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json('{"version": true, "checks": []}', limits)
    assert "version" in str(exc.value)

    # Unknown top-level key
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json('{"version": 1, "checks": [], "extra": 123}', limits)
    assert "extra" in str(exc.value)

    # Duplicate JSON key
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json('{"version": 1, "version": 1, "checks": []}', limits)
    assert "Duplicate key" in str(exc.value)

    # Invalid ID regex (starts with number or uppercase)
    bad_id_json = '{"version": 1, "checks": [{"id": "1bad", "sql": "SELECT 1", "expect": {"kind": "unchanged"}}]}'
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json(bad_id_json, limits)
    assert "invalid" in str(exc.value)

    # Duplicate check ID
    dup_id_json = '''{"version": 1, "checks": [
        {"id": "test_id", "sql": "SELECT 1", "expect": {"kind": "unchanged"}},
        {"id": "test_id", "sql": "SELECT 2", "expect": {"kind": "unchanged"}}
    ]}'''
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json(dup_id_json, limits)
    assert "Duplicate check id" in str(exc.value)

    # Boolean as value in equals
    bool_val_json = '{"version": 1, "checks": [{"id": "check_a", "sql": "SELECT 1", "expect": {"kind": "equals", "value": true}}]}'
    with pytest.raises(InputError) as exc:
        parse_and_validate_checks_json(bool_val_json, limits)
    assert "integer" in str(exc.value)


def test_t31_sql_read_checks(tmp_path: Path) -> None:
    """T31: Non-integer, zero/multiple rows/columns, null values produce error."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INT, txt TEXT, flt REAL);")
    conn.execute("INSERT INTO t VALUES (1, 'text', 1.5);")
    conn.execute("INSERT INTO t VALUES (2, 'two', 2.5);")
    conn.commit()

    conn.execute("PRAGMA query_only = ON")
    deadline = Deadline(timeout_seconds=5)

    # Zero rows
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT id FROM t WHERE id = 999", "c1", deadline)
    assert "0 rows" in str(exc.value)

    # Multiple rows
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT id FROM t", "c2", deadline)
    assert "multiple rows" in str(exc.value)

    # Multiple columns
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT id, txt FROM t WHERE id = 1", "c3", deadline)
    assert "columns" in str(exc.value)

    # Non-integer (text)
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT txt FROM t WHERE id = 1", "c4", deadline)
    assert "non-integer" in str(exc.value)

    # Non-integer (real)
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT flt FROM t WHERE id = 1", "c5", deadline)
    assert "non-integer" in str(exc.value)

    # Null value
    with pytest.raises(CheckExecutionError) as exc:
        execute_check_query(conn, "SELECT NULL", "c6", deadline)
    assert "non-integer" in str(exc.value)

    conn.close()


def test_fixture_d_checks_with_good_sql(seeded_db: Path) -> None:
    """Fixture D with good.sql: check 1 is 12->12 (pass), check 2 is null->0 (pass)."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("good.sql"),
            name="good.sql",
            sha256="good",
            statements=split_statements(GOOD_SQL, "good.sql"),
        )
        apply_migrations(conn_w, [mig], deadline)
        verify_after_integrity(conn_w, deadline)
        conn_w.close()

        specs = parse_and_validate_checks_json(CHECKS_JSON, limits)
        results, findings = evaluate_checks(
            specs, copies.before_path, copies.working_path, deadline
        )

        assert len(results) == 2
        assert len(findings) == 0

        # Check 1: published_profiles_preserved (unchanged)
        assert results[0].id == "published_profiles_preserved"
        assert results[0].before_value == 12
        assert results[0].after_value == 12
        assert results[0].passed is True

        # Check 2: no_empty_handles (equals 0)
        assert results[1].id == "no_empty_handles"
        assert results[1].before_value is None
        assert results[1].after_value == 0
        assert results[1].passed is True


def test_fixture_d_checks_with_bad_sql(seeded_db: Path) -> None:
    """Fixture D with bad.sql: check 1 is 12->9 (fail), check 2 is null->0 (pass)."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("bad.sql"),
            name="bad.sql",
            sha256="bad",
            statements=split_statements(BAD_SQL, "bad.sql"),
        )
        apply_migrations(conn_w, [mig], deadline)
        verify_after_integrity(conn_w, deadline)
        conn_w.close()

        specs = parse_and_validate_checks_json(CHECKS_JSON, limits)
        results, findings = evaluate_checks(
            specs, copies.before_path, copies.working_path, deadline
        )

        assert len(results) == 2
        assert len(findings) == 1
        assert findings[0].code == "CHECK_FAILED"
        assert findings[0].check_id == "published_profiles_preserved"

        # Check 1: published_profiles_preserved (12 -> 9)
        assert results[0].id == "published_profiles_preserved"
        assert results[0].before_value == 12
        assert results[0].after_value == 9
        assert results[0].passed is False

        # Check 2: no_empty_handles (null -> 0)
        assert results[1].id == "no_empty_handles"
        assert results[1].before_value is None
        assert results[1].after_value == 0
        assert results[1].passed is True
