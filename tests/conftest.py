"""Pytest configuration and shared fixtures for Raxo Rehearse."""

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


@pytest.fixture
def seed_sql() -> str:
    return SEED_SQL


@pytest.fixture
def good_sql() -> str:
    return GOOD_SQL


@pytest.fixture
def bad_sql() -> str:
    return BAD_SQL


@pytest.fixture
def checks_json() -> str:
    return CHECKS_JSON


@pytest.fixture
def cascade_bad_sql() -> str:
    return CASCADE_REBUILD_BAD_SQL


def create_seed_db(db_path: Path) -> Path:
    """Create a standalone seeded SQLite database file from Fixture A."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SEED_SQL)
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "snapshot.sqlite"
    return create_seed_db(db_path)
