"""Tests for database copies, isolation, and integrity checks."""

import os
import sqlite3
import tempfile
from pathlib import Path
import pytest

from raxorehearse.copies import create_isolated_copies, open_working_connection
from raxorehearse.demo_data import SEED_SQL
from raxorehearse.inputs import (
    compute_file_sha256,
    validate_output_directory,
    validate_source_database,
)
from raxorehearse.limits import Limits
from raxorehearse.models import (
    Deadline,
    InputError,
    MigrationError,
)


def test_t26_integrity_preflight_corrupt(tmp_path: Path) -> None:
    """T26: Corrupt input and baseline FK inconsistency produce ERROR."""
    corrupt_db = tmp_path / "corrupt.sqlite"
    # Write garbage into database file after sqlite header
    corrupt_db.write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(Exception):
            create_isolated_copies(corrupt_db, Path(td), limits, deadline)


def test_t26_fk_inconsistency(tmp_path: Path) -> None:
    """T26: Baseline FK inconsistency produces ERROR."""
    fk_db = tmp_path / "fk_broken.sqlite"
    conn = sqlite3.connect(str(fk_db))
    # Create tables with FK turned off, then insert violation
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, p_id INTEGER REFERENCES parent(id))")
    conn.execute("INSERT INTO child VALUES (1, 999)")
    conn.commit()
    conn.close()

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(MigrationError) as exc_info:
            create_isolated_copies(fk_db, Path(td), limits, deadline)
        assert "foreign key" in str(exc_info.value).lower()


def test_t27_source_sidecars_rejected(tmp_path: Path, seeded_db: Path) -> None:
    """T27: Any -wal/-shm/-journal adjacent file rejected without deleting it."""
    wal_file = seeded_db.parent / f"{seeded_db.name}-wal"
    wal_file.write_text("dummy wal content")

    deadline = Deadline(timeout_seconds=5)
    limits = Limits()

    with pytest.raises(InputError) as exc_info:
        validate_source_database(seeded_db, limits, deadline)
    assert "adjacent sidecar" in str(exc_info.value)
    # Ensure sidecar was NOT deleted
    assert wal_file.exists()


def test_t28_source_preservation(tmp_path: Path, seeded_db: Path) -> None:
    """T28: Source hash unchanged, read-only opening, no source-adjacent files created."""
    deadline = Deadline(timeout_seconds=5)
    limits = Limits()

    # Pre-hash
    pre_hash = compute_file_sha256(seeded_db, deadline)
    dir_files_before = set(seeded_db.parent.iterdir())

    with tempfile.TemporaryDirectory() as td:
        copies = create_isolated_copies(seeded_db, Path(td), limits, deadline)
        assert copies.before_path.exists()
        assert copies.working_path.exists()

        # Both copies should have identical logical records
        conn_b = sqlite3.connect(str(copies.before_path))
        conn_w = sqlite3.connect(str(copies.working_path))
        try:
            assert conn_b.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 12
            assert conn_w.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 12
        finally:
            conn_b.close()
            conn_w.close()

    # Verify source hash unchanged and no sidecars created beside source
    post_hash = compute_file_sha256(seeded_db, deadline)
    assert post_hash == pre_hash
    dir_files_after = set(seeded_db.parent.iterdir())
    assert dir_files_before == dir_files_after


def test_t36_existing_output_rejected(tmp_path: Path) -> None:
    """T36: Reject ordinary directory/file/symlink without modifying existing contents."""
    existing_dir = tmp_path / "already_exists"
    existing_dir.mkdir()
    sentinel = existing_dir / "keep_me.txt"
    sentinel.write_text("do not touch")

    with pytest.raises(InputError) as exc:
        validate_output_directory(existing_dir)
    assert "already exists" in str(exc.value)
    assert sentinel.read_text() == "do not touch"


def test_input_size_limit(tmp_path: Path, seeded_db: Path) -> None:
    """Input database exceeding limits raises InputError."""
    deadline = Deadline(timeout_seconds=5)
    small_limits = Limits(max_input_db_bytes=100)  # Very small limit

    with pytest.raises(InputError) as exc:
        validate_source_database(seeded_db, small_limits, deadline)
    assert "exceeds limit" in str(exc.value)
