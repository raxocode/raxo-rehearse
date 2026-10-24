"""Internal and public data models and exceptions for Raxo Rehearse."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from raxorehearse.limits import (
    DEFAULT_TIMEOUT_SECONDS,
    Limits,
)


class RunStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"

    @property
    def exit_code(self) -> int:
        if self == RunStatus.PASS:
            return 0
        elif self == RunStatus.REVIEW:
            return 10
        else:
            return 20


class FailOnThreshold(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class MigrationExecution(str, Enum):
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class CoverageStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NOT_RUN = "NOT_RUN"


class ComparisonKind(str, Enum):
    EXACT = "EXACT"
    UNAVAILABLE = "UNAVAILABLE"


class FindingSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Exceptions
class RehearseError(Exception):
    """Base exception for rehearsal errors."""


class InputError(RehearseError):
    """Raised when an input database, migration, or check specification is invalid."""


class UnsupportedSql(RehearseError):
    """Raised when migration SQL contains unsupported statements or features."""


class MigrationError(RehearseError):
    """Raised when migration execution fails."""

    def __init__(
        self,
        message: str,
        migration_name: str | None = None,
        statement_index: int | None = None,
        line: int | None = None,
        sqlite_errorname: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.migration_name = migration_name
        self.statement_index = statement_index
        self.line = line
        self.sqlite_errorname = sqlite_errorname


class CoverageGapError(RehearseError):
    """Raised when coverage cannot be completed due to limits or gaps."""


class CheckExecutionError(RehearseError):
    """Raised when an aggregate check fails execution or violates contract."""


class DeadlineExceeded(RehearseError):
    """Raised when execution time exceeds the cooperative deadline."""


class ReportWriteError(RehearseError):
    """Raised when report writing or directory creation fails."""


@dataclass
class Deadline:
    """Cooperative deadline tracking using time.monotonic()."""

    timeout_seconds: float
    start_time: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return (time.monotonic() - self.start_time) >= self.timeout_seconds

    def check(self) -> None:
        if self.is_expired():
            raise DeadlineExceeded("Cooperative deadline exceeded")

    def remaining(self) -> float:
        rem = self.timeout_seconds - (time.monotonic() - self.start_time)
        return max(0.0, rem)

    def sqlite_progress_handler(self) -> int:
        """Returns 1 to interrupt SQLite query if expired, 0 to continue."""
        return 1 if self.is_expired() else 0


@dataclass
class RunOptions:
    """Command-line options passed to the rehearsal service."""

    database: Path | None
    migrations: list[Path]
    out: Path
    checks: Path | None = None
    fail_on: str = "warning"
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    is_demo: bool = False
    limits: Limits = field(default_factory=Limits)


@dataclass
class SqlStatement:
    """A single parsed SQL statement."""

    index: int  # 1-indexed within file
    line: int  # 1-indexed start line
    sql: str


@dataclass
class MigrationRecord:
    """Internal migration file representation."""

    path: Path
    name: str  # basename
    sha256: str
    statements: list[SqlStatement]
    execution: MigrationExecution = MigrationExecution.NOT_RUN


@dataclass
class ColumnInfo:
    """Internal column schema representation."""

    cid: int
    name: str
    type: str
    notnull: bool
    dflt_value: str | None
    pk: int
    hidden: int  # 0: normal, 1: stored generated, 2: virtual generated, 3: hidden


@dataclass
class TableSchema:
    """Internal table schema representation."""

    name: str
    sql: str | None
    is_virtual: bool
    is_view: bool
    columns: list[ColumnInfo]
    pk_columns: list[str]


@dataclass
class SchemaObject:
    """Internal schema object representation (index, view, trigger)."""

    type: str  # 'index', 'view', 'trigger'
    name: str
    tbl_name: str
    sql: str | None


@dataclass
class DatabaseInventory:
    """Complete inventory of supported and excluded objects."""

    tables: dict[str, TableSchema]
    schema_objects: dict[tuple[str, str], SchemaObject]  # (type, name) -> SchemaObject
    excluded_engine_objects: set[tuple[str, str]]
    row_counts: dict[str, int | None]


@dataclass
class CoverageGapItem:
    """A coverage limitation or gap."""

    table: str | None
    code: str
    message: str


@dataclass
class TableComparison:
    """Per-table comparison outcome."""

    name: str
    before_rows: int | None
    after_rows: int | None
    before_columns: list[str]
    after_columns: list[str]
    before_key: list[str]
    after_key: list[str]
    shared_value_columns: list[str]
    comparison: str  # EXACT or UNAVAILABLE
    removed_keys: int | None
    added_keys: int | None
    changed_rows: int | None


@dataclass
class FindingObject:
    """Schema object context for a finding."""

    kind: str
    name: str


@dataclass
class Finding:
    """Rule finding."""

    code: str
    severity: str  # 'error', 'warning', 'info'
    message: str
    table: str | None = None
    column: str | None = None
    object: FindingObject | None = None
    check_id: str | None = None
    count: int | None = None


@dataclass
class CheckSpec:
    """Specification of an aggregate check."""

    id: str
    sql: str
    expect: dict[str, Any]


@dataclass
class CheckResult:
    """Outcome of an aggregate check."""

    id: str
    expect: dict[str, Any]
    before_value: int | None
    after_value: int | None
    passed: bool | None


@dataclass
class ReportError:
    """Execution or operational error."""

    code: str
    message: str
    migration: str | None = None
    statement_index: int | None = None
    line: int | None = None
    sqlite_errorname: str | None = None


@dataclass
class RunResult:
    """Complete internal outcome of a rehearsal run."""

    status: RunStatus
    exit_code: int
    fail_on: str
    database_name: str
    source_sha256: str | None
    source_unchanged: bool | None
    started_at: str  # UTC ISO 8601
    duration_ms: int
    python_version: str
    sqlite_version: str
    comparison_scope: str
    migrations: list[MigrationRecord]
    coverage_status: CoverageStatus
    tables_total: int | None
    tables_compared: int
    excluded_engine_objects: int
    coverage_gaps: list[CoverageGapItem]
    tables: list[TableComparison]
    findings: list[Finding]
    checks: list[CheckResult]
    errors: list[ReportError]
