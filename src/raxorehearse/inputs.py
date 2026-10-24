"""Input validation, hashing, and sidecar checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from raxorehearse.limits import Limits
from raxorehearse.models import (
    CheckSpec,
    Deadline,
    InputError,
    MigrationRecord,
    RunOptions,
)
from raxorehearse.sql_statements import split_statements

SQLITE_HEADER = b"SQLite format 3\x00"


def compute_file_sha256(path: Path, deadline: Deadline | None = None) -> str:
    """Compute SHA-256 hash of a file in 64 KiB chunks with deadline checking."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if deadline:
                deadline.check()
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


@dataclass
class ValidatedInputs:
    """Container for validated inputs ready for rehearsal execution."""

    database_path: Path
    database_name: str
    source_sha256: str
    migrations: list[MigrationRecord]
    checks: list[CheckSpec]
    out_dir: Path
    fail_on: str
    timeout: int
    limits: Limits
    is_demo: bool


def validate_source_database(
    db_path: Path, limits: Limits, deadline: Deadline
) -> tuple[str, str]:
    """Validate closed standalone SQLite snapshot and compute its hash."""
    if not db_path.exists() or not db_path.is_file():
        raise InputError(f"Database file does not exist or is not a file: {db_path}")

    # Check sidecars
    parent = db_path.parent
    name = db_path.name
    sidecars = [
        parent / f"{name}-wal",
        parent / f"{name}-shm",
        parent / f"{name}-journal",
    ]
    present_sidecars = [str(s.name) for s in sidecars if s.exists()]
    if present_sidecars:
        raise InputError(
            f"Input database has adjacent sidecar files ({', '.join(present_sidecars)}). "
            "Raxo Rehearse requires a closed standalone snapshot, never a live application database. "
            "Please prepare a fresh standalone backup rather than deleting sidecars from a live database."
        )

    # Size check
    size = db_path.stat().st_size
    if size > limits.max_input_db_bytes:
        raise InputError(
            f"Database size ({size} bytes) exceeds limit of {limits.max_input_db_bytes} bytes (256 MiB)."
        )

    # SQLite header check
    with open(db_path, "rb") as f:
        header = f.read(16)
        if header != SQLITE_HEADER:
            raise InputError(
                f"Input file '{db_path.name}' is not a valid SQLite database (missing SQLite header)."
            )

    sha256 = compute_file_sha256(db_path, deadline)
    return db_path.name, sha256


def validate_migration_files(
    migration_paths: list[Path], limits: Limits
) -> list[MigrationRecord]:
    """Validate and parse migration files."""
    if not migration_paths:
        raise InputError("At least one migration file must be supplied.")

    if len(migration_paths) > limits.max_migration_files:
        raise InputError(
            f"Too many migration files ({len(migration_paths)} > {limits.max_migration_files})."
        )

    records: list[MigrationRecord] = []
    total_bytes = 0
    total_statements = 0

    for path in migration_paths:
        if not path.exists() or not path.is_file():
            raise InputError(f"Migration file does not exist or is not a file: {path}")

        try:
            raw_bytes = path.read_bytes()
        except Exception as exc:
            raise InputError(f"Could not read migration file '{path}': {exc}")

        total_bytes += len(raw_bytes)
        if total_bytes > limits.max_combined_migration_bytes:
            raise InputError(
                f"Combined migration files size exceeds limit of {limits.max_combined_migration_bytes} bytes (2 MiB)."
            )

        try:
            sql_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"Migration file '{path.name}' is not valid UTF-8: {exc}")

        hasher = hashlib.sha256(raw_bytes)
        sha256 = hasher.hexdigest().lower()

        statements = split_statements(sql_text, filename=path.name)
        if not statements:
            raise InputError(
                f"Migration file '{path.name}' is empty or contains only comments/whitespace."
            )

        total_statements += len(statements)
        if total_statements > limits.max_statements:
            raise InputError(
                f"Total statement count ({total_statements}) exceeds limit of {limits.max_statements}."
            )

        records.append(
            MigrationRecord(
                path=path,
                name=path.name,
                sha256=sha256,
                statements=statements,
            )
        )

    return records


def validate_output_directory(out_dir: Path) -> None:
    """Validate that output directory does not exist."""
    if out_dir.exists() or out_dir.is_symlink():
        raise InputError(
            f"Output directory already exists: '{out_dir}'. Raxo Rehearse requires a new, nonexistent output directory."
        )
