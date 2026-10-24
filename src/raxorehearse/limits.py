"""Resource limits and constants for Raxo Rehearse v0.1."""

from dataclasses import dataclass

MIN_SQLITE_VERSION = (3, 37, 0)
MIN_SQLITE_VERSION_STR = "3.37.0"

MAX_INPUT_DB_BYTES = 256 * 1024 * 1024  # 256 MiB
MAX_WORKING_DB_BYTES = 512 * 1024 * 1024  # 512 MiB
MAX_TABLES = 100
MAX_ROWS_PER_TABLE = 100_000
MAX_ROWS_TOTAL = 1_000_000
MAX_ENCODED_KEY_BYTES = 1024  # 1 KiB
MAX_MIGRATION_FILES = 20
MAX_COMBINED_MIGRATION_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_CHECKS = 50
MAX_CHECKS_JSON_BYTES = 256 * 1024  # 256 KiB
MAX_CHECK_SQL_BYTES = 16 * 1024  # 16 KiB
MAX_STATEMENTS = 2000

DEFAULT_TIMEOUT_SECONDS = 60
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600

COMPARISON_SCOPE = "sqlite_final_state_v1"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class Limits:
    """Configurable limits container for tests and execution."""

    max_input_db_bytes: int = MAX_INPUT_DB_BYTES
    max_working_db_bytes: int = MAX_WORKING_DB_BYTES
    max_tables: int = MAX_TABLES
    max_rows_per_table: int = MAX_ROWS_PER_TABLE
    max_rows_total: int = MAX_ROWS_TOTAL
    max_encoded_key_bytes: int = MAX_ENCODED_KEY_BYTES
    max_migration_files: int = MAX_MIGRATION_FILES
    max_combined_migration_bytes: int = MAX_COMBINED_MIGRATION_BYTES
    max_checks: int = MAX_CHECKS
    max_checks_json_bytes: int = MAX_CHECKS_JSON_BYTES
    max_check_sql_bytes: int = MAX_CHECK_SQL_BYTES
    max_statements: int = MAX_STATEMENTS
