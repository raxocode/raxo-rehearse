"""Tests for input validation, fixtures, and source handling."""

import sqlite3
from pathlib import Path
import pytest

from raxorehearse.demo_data import (
    SEED_SQL,
    GOOD_SQL,
    BAD_SQL,
    CHECKS_JSON,
    CASCADE_REBUILD_BAD_SQL,
)


def test_t01_seed_setup(seeded_db: Path) -> None:
    """T01: Seed setup has exactly 15 users, 12 profiles, 24 work_samples, 0 FK violations."""
    conn = sqlite3.connect(str(seeded_db))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_errors) == 0, f"Expected 0 foreign key violations, got: {fk_errors}"

        qc = conn.execute("PRAGMA quick_check").fetchall()
        assert qc == [("ok",)], f"Expected quick_check ok, got: {qc}"

        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        profile_count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        sample_count = conn.execute("SELECT COUNT(*) FROM work_samples").fetchone()[0]

        assert user_count == 15, f"Expected 15 users, got {user_count}"
        assert profile_count == 12, f"Expected 12 profiles, got {profile_count}"
        assert sample_count == 24, f"Expected 24 work samples, got {sample_count}"
    finally:
        conn.close()


def test_fixtures_sync_with_examples() -> None:
    """Verify that examples/ files exactly match demo_data constants."""
    repo_root = Path(__file__).parent.parent
    examples_dir = repo_root / "examples"

    seed_file = examples_dir / "profile-app" / "seed.sql"
    good_file = examples_dir / "profile-app" / "good.sql"
    bad_file = examples_dir / "profile-app" / "bad.sql"
    checks_file = examples_dir / "profile-app" / "checks.json"
    cascade_file = examples_dir / "cascade-rebuild" / "bad.sql"

    assert seed_file.read_text(encoding="utf-8") == SEED_SQL
    assert good_file.read_text(encoding="utf-8") == GOOD_SQL
    assert bad_file.read_text(encoding="utf-8") == BAD_SQL
    assert checks_file.read_text(encoding="utf-8") == CHECKS_JSON
    assert cascade_file.read_text(encoding="utf-8") == CASCADE_REBUILD_BAD_SQL
