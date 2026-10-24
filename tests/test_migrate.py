"""Tests for migration runner, transaction boundaries, and fixtures."""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from raxorehearse.copies import create_isolated_copies, open_working_connection
from raxorehearse.demo_data import (
    BAD_SQL,
    CASCADE_REBUILD_BAD_SQL,
    GOOD_SQL,
)
from raxorehearse.limits import Limits
from raxorehearse.migrate import apply_migrations, verify_after_integrity
from raxorehearse.models import (
    Deadline,
    MigrationError,
    MigrationExecution,
    MigrationRecord,
    SqlStatement,
)
from raxorehearse.sql_statements import split_statements


def test_t21_per_file_rollback(seeded_db: Path) -> None:
    """T21: Successful UPDATE then syntax failure rolls back to pre-state of that file."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        failing_migration = MigrationRecord(
            path=Path("001_fail.sql"),
            name="001_fail.sql",
            sha256="abc",
            statements=[
                SqlStatement(1, 1, "UPDATE profiles SET handle = 'modified' WHERE id = 1;"),
                SqlStatement(2, 2, "THIS IS TOTAL SYNTAX ERROR;"),
            ],
        )

        with pytest.raises(MigrationError) as exc_info:
            apply_migrations(conn, [failing_migration], deadline)
        assert failing_migration.execution == MigrationExecution.FAILED

        # Check that handle for id=1 was NOT modified (rolled back)
        row = conn.execute("SELECT handle FROM profiles WHERE id = 1").fetchone()
        assert row[0] == "member-1"
        conn.close()


def test_t22_ordered_migrations_stop_on_failure(seeded_db: Path) -> None:
    """T22: Repeated migrations run in order; earlier failure stops remaining files."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        mig1 = MigrationRecord(
            path=Path("001_good.sql"),
            name="001_good.sql",
            sha256="111",
            statements=[SqlStatement(1, 1, "ALTER TABLE profiles ADD COLUMN headline TEXT;")],
        )
        mig2 = MigrationRecord(
            path=Path("002_fail.sql"),
            name="002_fail.sql",
            sha256="222",
            statements=[SqlStatement(1, 1, "INVALID SQL STATEMENT;")],
        )
        mig3 = MigrationRecord(
            path=Path("003_unreached.sql"),
            name="003_unreached.sql",
            sha256="333",
            statements=[SqlStatement(1, 1, "CREATE TABLE unreached (id INT);")],
        )

        with pytest.raises(MigrationError):
            apply_migrations(conn, [mig1, mig2, mig3], deadline)

        assert mig1.execution == MigrationExecution.APPLIED
        assert mig2.execution == MigrationExecution.FAILED
        assert mig3.execution == MigrationExecution.NOT_RUN

        # mig1 committed
        cols = [c[1] for c in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        assert "headline" in cols

        # mig3 never ran
        tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall()]
        assert "unreached" not in tables
        conn.close()


def test_t25_deferred_foreign_keys_fail_at_commit(seeded_db: Path) -> None:
    """T25: defer_foreign_keys=ON allowed; unresolved FK violation fails at COMMIT."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("defer.sql"),
            name="defer.sql",
            sha256="def",
            statements=[
                SqlStatement(1, 1, "PRAGMA defer_foreign_keys = ON;"),
                SqlStatement(2, 2, "INSERT INTO work_samples (id, profile_id, title) VALUES (999, 88888, 'broken');"),
            ],
        )

        with pytest.raises(MigrationError) as exc_info:
            apply_migrations(conn, [mig], deadline)
        assert mig.execution == MigrationExecution.FAILED
        conn.close()


def test_good_sql_fixture_execution(seeded_db: Path) -> None:
    """Good migration really adds headline and an index."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("good.sql"),
            name="good.sql",
            sha256="good",
            statements=split_statements(GOOD_SQL, "good.sql"),
        )
        apply_migrations(conn, [mig], deadline)
        verify_after_integrity(conn, deadline)

        assert mig.execution == MigrationExecution.APPLIED

        # Check headline exists
        cols = [c[1] for c in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        assert "headline" in cols

        # Check index exists
        indices = [i[1] for i in conn.execute("PRAGMA index_list(profiles)").fetchall()]
        assert "idx_profiles_status" in indices
        conn.close()


def test_bad_sql_fixture_execution(seeded_db: Path) -> None:
    """Bad migration removes bio, replaces 3 profiles, cascades 6 work_samples deletions."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("bad.sql"),
            name="bad.sql",
            sha256="bad",
            statements=split_statements(BAD_SQL, "bad.sql"),
        )
        apply_migrations(conn, [mig], deadline)
        verify_after_integrity(conn, deadline)

        assert mig.execution == MigrationExecution.APPLIED

        # Check bio dropped
        cols = [c[1] for c in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        assert "bio" not in cols

        # Profiles row count is still 12 (12 - 3 + 3)
        prof_count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        assert prof_count == 12

        # Work samples: 24 - 6 = 18
        ws_count = conn.execute("SELECT COUNT(*) FROM work_samples").fetchone()[0]
        assert ws_count == 18
        conn.close()


def test_cascade_rebuild_fixture_execution(seeded_db: Path) -> None:
    """Cascade rebuild bad SQL leaves profiles at 12, but work_samples drops from 24 to 0."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        conn = open_working_connection(copies.working_path, limits, deadline)

        mig = MigrationRecord(
            path=Path("cascade_bad.sql"),
            name="cascade_bad.sql",
            sha256="cas",
            statements=split_statements(CASCADE_REBUILD_BAD_SQL, "cascade_bad.sql"),
        )
        apply_migrations(conn, [mig], deadline)
        verify_after_integrity(conn, deadline)

        assert mig.execution == MigrationExecution.APPLIED

        prof_count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        assert prof_count == 12

        # 24 work_samples cascade deleted!
        ws_count = conn.execute("SELECT COUNT(*) FROM work_samples").fetchone()[0]
        assert ws_count == 0
        conn.close()
