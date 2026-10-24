"""Tests for database comparison, typed encoding, schema changes, and coverage gaps."""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from raxorehearse.compare import compare_databases, encode_cell, encode_tuple
from raxorehearse.copies import create_isolated_copies, open_working_connection
from raxorehearse.demo_data import (
    BAD_SQL,
    CASCADE_REBUILD_BAD_SQL,
    GOOD_SQL,
)
from raxorehearse.inspect_db import inspect_database
from raxorehearse.limits import Limits
from raxorehearse.migrate import apply_migrations, verify_after_integrity
from raxorehearse.models import (
    CoverageStatus,
    Deadline,
    MigrationRecord,
)
from raxorehearse.sql_statements import split_statements


def test_t13_typed_encoding() -> None:
    """T13: Distinguish None, empty text, empty BLOB, text '1', integer 1, real 1.0."""
    enc_none = encode_cell(None)
    enc_empty_str = encode_cell("")
    enc_empty_blob = encode_cell(b"")
    enc_text_one = encode_cell("1")
    enc_int_one = encode_cell(1)
    enc_real_one = encode_cell(1.0)

    # All must be distinct
    distinct = {
        enc_none,
        enc_empty_str,
        enc_empty_blob,
        enc_text_one,
        enc_int_one,
        enc_real_one,
    }
    assert len(distinct) == 6

    assert enc_none.startswith(b"N")
    assert enc_empty_str.startswith(b"T")
    assert enc_empty_blob.startswith(b"B")
    assert enc_text_one.startswith(b"T")
    assert enc_int_one.startswith(b"I")
    assert enc_real_one.startswith(b"R")

    # Composite tuples do not collide
    t1 = encode_tuple(("a,b", "c"))
    t2 = encode_tuple(("a", "b,c"))
    assert t1 != t2


def test_t02_good_migration_comparison(seeded_db: Path) -> None:
    """T02: Good migration has complete coverage, no error/warning findings, all keyed change counts zero."""
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

        # Open read-only inspection connections
        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.COMPLETE
            assert len(gaps) == 0

            # No errors or warnings
            severities = {f.severity for f in findings}
            assert "error" not in severities
            assert "warning" not in severities

            # All keyed change counts zero
            for tc in tcs:
                assert tc.comparison == "EXACT"
                assert tc.removed_keys == 0
                assert tc.added_keys == 0
                assert tc.changed_rows == 0
        finally:
            conn_b.close()
            conn_a.close()


def test_t03_bad_migration_comparison(seeded_db: Path) -> None:
    """T03: Bad migration matches exact metrics from fixture contract."""
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

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.COMPLETE
            assert len(gaps) == 0

            tc_map = {tc.name: tc for tc in tcs}

            # profiles: 12 -> 12, removed 3, added 3, changed 0
            prof = tc_map["profiles"]
            assert prof.before_rows == 12
            assert prof.after_rows == 12
            assert prof.removed_keys == 3
            assert prof.added_keys == 3
            assert prof.changed_rows == 0
            assert "bio" in prof.before_columns
            assert "bio" not in prof.after_columns

            # users: 15 -> 15, removed 0, added 0, changed 0
            users = tc_map["users"]
            assert users.before_rows == 15
            assert users.after_rows == 15
            assert users.removed_keys == 0
            assert users.added_keys == 0
            assert users.changed_rows == 0

            # work_samples: 24 -> 18, removed 6, added 0, changed 0
            ws = tc_map["work_samples"]
            assert ws.before_rows == 24
            assert ws.after_rows == 18
            assert ws.removed_keys == 6
            assert ws.added_keys == 0
            assert ws.changed_rows == 0

            finding_codes = {(f.code, f.table, f.column) for f in findings}
            assert ("COLUMN_REMOVED", "profiles", "bio") in finding_codes
            assert ("ROWS_REMOVED", "profiles", None) in finding_codes
            assert ("ROWS_REMOVED", "work_samples", None) in finding_codes
            assert ("ROWS_ADDED", "profiles", None) in finding_codes
            # No ROWS_CHANGED finding
            assert not any(f.code == "ROWS_CHANGED" for f in findings)
        finally:
            conn_b.close()
            conn_a.close()


def test_t04_cascade_rebuild_comparison(seeded_db: Path) -> None:
    """T04: Cascade rebuild leaves profiles at 12, but work_samples drops from 24 to 0 (24 removed)."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("cascade.sql"),
            name="cascade.sql",
            sha256="cas",
            statements=split_statements(CASCADE_REBUILD_BAD_SQL, "cascade.sql"),
        )
        apply_migrations(conn_w, [mig], deadline)
        verify_after_integrity(conn_w, deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            tc_map = {tc.name: tc for tc in tcs}
            ws = tc_map["work_samples"]
            assert ws.before_rows == 24
            assert ws.after_rows == 0
            assert ws.removed_keys == 24
            assert ws.added_keys == 0
        finally:
            conn_b.close()
            conn_a.close()


def test_t05_non_key_update(seeded_db: Path) -> None:
    """T05: Update one bio field produces changed_rows = 1, no removed/added keys."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("update.sql"),
            name="update.sql",
            sha256="upd",
            statements=[
                split_statements(
                    "UPDATE profiles SET bio = 'new bio' WHERE id = 1;", "update.sql"
                )[0]
            ],
        )
        apply_migrations(conn_w, [mig], deadline)
        verify_after_integrity(conn_w, deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            tc_map = {tc.name: tc for tc in tcs}
            prof = tc_map["profiles"]
            assert prof.removed_keys == 0
            assert prof.added_keys == 0
            assert prof.changed_rows == 1

            rows_changed_f = [f for f in findings if f.code == "ROWS_CHANGED"]
            assert len(rows_changed_f) == 1
            assert rows_changed_f[0].table == "profiles"
            assert rows_changed_f[0].count == 1
        finally:
            conn_b.close()
            conn_a.close()


def test_t09_composite_pk_without_rowid(tmp_path: Path) -> None:
    """T09: Composite PK and WITHOUT ROWID tables compare correctly."""
    db_path = tmp_path / "composite.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE items (org_id INT, item_id INT, val TEXT, PRIMARY KEY (org_id, item_id)) WITHOUT ROWID;"
    )
    conn.execute("INSERT INTO items VALUES (1, 10, 'A'), (1, 20, 'B'), (2, 10, 'C');")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[
                split_statements(
                    "DELETE FROM items WHERE org_id = 1 AND item_id = 10; "
                    "INSERT INTO items VALUES (1, 30, 'D'); "
                    "UPDATE items SET val = 'B_updated' WHERE org_id = 1 AND item_id = 20;",
                    "m.sql",
                )[0],
                split_statements("INSERT INTO items VALUES (1, 30, 'D');", "m.sql")[0],
                split_statements("UPDATE items SET val = 'B_updated' WHERE org_id = 1 AND item_id = 20;", "m.sql")[0],
            ],
        )
        apply_migrations(conn_w, [mig], deadline)
        verify_after_integrity(conn_w, deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.COMPLETE
            tc = tcs[0]
            assert tc.name == "items"
            assert tc.removed_keys == 1
            assert tc.added_keys == 1
            assert tc.changed_rows == 1
        finally:
            conn_b.close()
            conn_a.close()


def test_t10_no_primary_key_gap(tmp_path: Path) -> None:
    """T10: Table without PK yields visible NO_PRIMARY_KEY gap and UNAVAILABLE comparison."""
    db_path = tmp_path / "no_pk.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE logs (msg TEXT);")
    conn.execute("INSERT INTO logs VALUES ('log 1');")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[split_statements("INSERT INTO logs VALUES ('log 2');", "m.sql")[0]],
        )
        apply_migrations(conn_w, [mig], deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.PARTIAL
            gap_codes = [g.code for g in gaps]
            assert "NO_PRIMARY_KEY" in gap_codes
            assert tcs[0].comparison == "UNAVAILABLE"
            assert tcs[0].removed_keys is None
        finally:
            conn_b.close()
            conn_a.close()


def test_t15_generated_columns_gap(tmp_path: Path) -> None:
    """T15: Generated columns produce visible GENERATED_COLUMN gap."""
    db_path = tmp_path / "gen_col.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE items (id INT PRIMARY KEY, price INT, tax INT AS (price * 0.1) STORED);"
    )
    conn.execute("INSERT INTO items (id, price) VALUES (1, 100);")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[split_statements("UPDATE items SET price = 200 WHERE id = 1;", "m.sql")[0]],
        )
        apply_migrations(conn_w, [mig], deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.PARTIAL
            gap_codes = [g.code for g in gaps]
            assert "GENERATED_COLUMN" in gap_codes
            assert tcs[0].comparison == "UNAVAILABLE"
        finally:
            conn_b.close()
            conn_a.close()


def test_t11_changed_pk_name_or_type(tmp_path: Path) -> None:
    """T11: Changed PK name/type yields KEY_DEFINITION_CHANGED warning and coverage gap."""
    db_path = tmp_path / "changed_pk.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
    conn.execute("INSERT INTO t VALUES (1, 'val');")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[
                split_statements(
                    "CREATE TABLE t_new (uuid TEXT PRIMARY KEY, v TEXT); "
                    "INSERT INTO t_new SELECT cast(id as text), v FROM t; "
                    "DROP TABLE t; "
                    "ALTER TABLE t_new RENAME TO t;",
                    "m.sql",
                )[0],
                split_statements("INSERT INTO t_new SELECT cast(id as text), v FROM t;", "m.sql")[0],
                split_statements("DROP TABLE t;", "m.sql")[0],
                split_statements("ALTER TABLE t_new RENAME TO t;", "m.sql")[0],
            ],
        )
        apply_migrations(conn_w, [mig], deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.PARTIAL
            gap_codes = [g.code for g in gaps]
            assert "KEY_DEFINITION_CHANGED" in gap_codes
            finding_codes = [f.code for f in findings]
            assert "KEY_DEFINITION_CHANGED" in finding_codes
            assert tcs[0].comparison == "UNAVAILABLE"
        finally:
            conn_b.close()
            conn_a.close()


def test_t12_nullable_pk_data(tmp_path: Path) -> None:
    """T12: SQLite table with primary key containing NULL produces NULL_KEY gap."""
    db_path = tmp_path / "null_pk.sqlite"
    conn = sqlite3.connect(str(db_path))
    # In SQLite, a non-INTEGER PRIMARY KEY column can contain NULL unless marked NOT NULL!
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT);")
    conn.execute("INSERT INTO t VALUES (NULL, 'val');")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[split_statements("UPDATE t SET v = 'v2';", "m.sql")[0]],
        )
        apply_migrations(conn_w, [mig], deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.PARTIAL
            gap_codes = [g.code for g in gaps]
            assert "NULL_KEY" in gap_codes
            assert tcs[0].comparison == "UNAVAILABLE"
        finally:
            conn_b.close()
            conn_a.close()


def test_t14_large_key_limit(tmp_path: Path) -> None:
    """T14: Key exceeding 1,024 bytes produces KEY_SIZE_LIMIT gap."""
    db_path = tmp_path / "large_key.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT);")
    large_key = "k" * 2000
    conn.execute("INSERT INTO t VALUES (?, 'val')", (large_key,))
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(db_path, Path(td), limits, deadline)
        conn_w = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("m.sql"),
            name="m.sql",
            sha256="m",
            statements=[split_statements("UPDATE t SET v = 'new_val';", "m.sql")[0]],
        )
        apply_migrations(conn_w, [mig], deadline)
        conn_w.close()

        conn_b = sqlite3.connect(copies.before_path.as_uri() + "?mode=ro", uri=True)
        conn_a = sqlite3.connect(copies.working_path.as_uri() + "?mode=ro", uri=True)
        try:
            inv_b = inspect_database(conn_b, deadline)
            inv_a = inspect_database(conn_a, deadline)
            tcs, findings, gaps, cov_status = compare_databases(
                conn_b, conn_a, inv_b, inv_a, limits, deadline
            )

            assert cov_status == CoverageStatus.PARTIAL
            gap_codes = [g.code for g in gaps]
            assert "KEY_SIZE_LIMIT" in gap_codes
            assert tcs[0].comparison == "UNAVAILABLE"
        finally:
            conn_b.close()
            conn_a.close()

