"""Service orchestration for Raxo Rehearse."""

from __future__ import annotations

import datetime
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from raxorehearse.checks import evaluate_checks, parse_and_validate_checks
from raxorehearse.compare import compare_databases
from raxorehearse.copies import create_isolated_copies, open_working_connection
from raxorehearse.demo_data import (
    BAD_SQL,
    CHECKS_JSON,
    SEED_SQL,
)
from raxorehearse.inputs import (
    compute_file_sha256,
    validate_migration_files,
    validate_output_directory,
    validate_source_database,
)
from raxorehearse.inspect_db import inspect_database
from raxorehearse.limits import COMPARISON_SCOPE
from raxorehearse.migrate import apply_migrations, verify_after_integrity
from raxorehearse.models import (
    CheckResult,
    CheckSpec,
    ComparisonKind,
    CoverageGapItem,
    CoverageStatus,
    Deadline,
    DeadlineExceeded,
    Finding,
    FindingSeverity,
    InputError,
    MigrationError,
    MigrationRecord,
    RehearseError,
    ReportError,
    ReportWriteError,
    RunOptions,
    RunResult,
    RunStatus,
    TableComparison,
)
from raxorehearse.report_html import render_public_report_html
from raxorehearse.report_json import (
    build_public_report_model,
    serialize_public_report_json,
)


def write_reports(report_model: dict[str, Any], out_dir: Path) -> None:
    """Atomically write report.json and report.html to the reserved output directory."""
    try:
        json_content = serialize_public_report_json(report_model)
        html_content = render_public_report_html(report_model)

        json_tmp = out_dir / "report.json.tmp"
        html_tmp = out_dir / "report.html.tmp"
        json_target = out_dir / "report.json"
        html_target = out_dir / "report.html"

        json_tmp.write_text(json_content, encoding="utf-8")
        html_tmp.write_text(html_content, encoding="utf-8")

        # Atomic replacement
        json_tmp.replace(json_target)
        html_tmp.replace(html_target)
    except Exception as exc:
        raise ReportWriteError(f"Failed to write rehearsal reports to '{out_dir}': {exc}")


def print_terminal_summary(result: RunResult, out_dir: Path, is_demo: bool = False) -> None:
    """Print concise terminal summary."""
    sys.stdout.write("\n=== Raxo Rehearse Summary ===\n")
    sys.stdout.write(f"Database: {result.database_name}\n")
    sys.stdout.write(f"Status:   {result.status.value} (exit {result.exit_code})\n")
    sys.stdout.write(f"Coverage: {result.coverage_status.value} ({result.tables_compared}/{result.tables_total or 0} tables)\n")

    err_cnt = sum(1 for f in result.findings if f.severity == "error")
    warn_cnt = sum(1 for f in result.findings if f.severity == "warning")
    info_cnt = sum(1 for f in result.findings if f.severity == "info")
    sys.stdout.write(f"Findings: {err_cnt} error(s), {warn_cnt} warning(s), {info_cnt} info\n")

    # Attention line if any
    for t in result.tables:
        if (
            t.before_rows is not None
            and t.after_rows is not None
            and t.before_rows == t.after_rows
            and t.removed_keys
            and t.removed_keys > 0
        ):
            sys.stdout.write(f"Notice:   {t.name} still has {t.before_rows} rows; {t.removed_keys} original keys are missing.\n")

    if result.errors:
        sys.stdout.write("\nErrors:\n")
        for e in result.errors:
            ctx = f" ({e.migration}:{e.line})" if e.line else ""
            sys.stdout.write(f"  [{e.code}] {e.message}{ctx}\n")

    if is_demo:
        sys.stdout.write("\nNote: Exit 10 (REVIEW) is expected for demo fixtures (deliberate simulated data loss).\n")

    sys.stdout.write(f"\nReports written to:\n  {out_dir / 'report.html'}\n  {out_dir / 'report.json'}\n\n")


def run_rehearsal(options: RunOptions) -> RunResult:
    """Execute complete migration rehearsal workflow."""
    if options.is_demo and options.database is None:
        from raxorehearse.demo import execute_demo
        return execute_demo(options)

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_monotonic = time.monotonic()
    deadline = Deadline(timeout_seconds=float(options.timeout), start_time=start_monotonic)

    # Validate output directory first
    validate_output_directory(options.out)

    # Create output directory
    try:
        options.out.mkdir(parents=False, exist_ok=False)
    except Exception as exc:
        raise ReportWriteError(f"Could not create output directory '{options.out}': {exc}")

    database_path = options.database
    if not database_path:
        raise InputError("Database path is required.")

    # Validate database and compute initial hash
    db_name, source_sha256 = validate_source_database(
        database_path, options.limits, deadline
    )

    # Validate migrations
    migrations = validate_migration_files(options.migrations, options.limits)

    # Validate checks if supplied
    checks_specs: list[CheckSpec] = []
    if options.checks:
        checks_specs = parse_and_validate_checks(options.checks, options.limits)

    # Execution containers
    tables: list[TableComparison] = []
    findings: list[Finding] = []
    coverage_gaps: list[CoverageGapItem] = []
    checks_results: list[CheckResult] = []
    errors: list[ReportError] = []
    coverage_status = CoverageStatus.NOT_RUN
    tables_total: int | None = None
    tables_compared = 0
    excluded_objects_count = 0
    source_unchanged: bool | None = None

    # Step 3: Run isolated execution inside private TemporaryDirectory
    try:
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)

            # Create isolated copies
            copies = create_isolated_copies(
                database_path, temp_dir, options.limits, deadline
            )

            # Open working connection
            conn_w = open_working_connection(
                copies.working_path, options.limits, deadline
            )

            # Apply migrations
            migration_failed = False
            try:
                apply_migrations(conn_w, migrations, deadline)
                verify_after_integrity(conn_w, deadline)
            except MigrationError as m_err:
                migration_failed = True
                errors.append(
                    ReportError(
                        code="MIGRATION_FAILED",
                        message=m_err.message,
                        migration=m_err.migration_name,
                        statement_index=m_err.statement_index,
                        line=m_err.line,
                        sqlite_errorname=m_err.sqlite_errorname,
                    )
                )
            except Exception as exc:
                migration_failed = True
                errors.append(
                    ReportError(
                        code="MIGRATION_FAILED",
                        message=f"Migration failed unexpectedly: {type(exc).__name__}",
                    )
                )
            finally:
                conn_w.close()

            # Open read-only connections for before and working copies
            before_uri = copies.before_path.resolve().as_uri() + "?mode=ro"
            conn_before = sqlite3.connect(before_uri, uri=True)

            try:
                before_inv = inspect_database(conn_before, deadline)
                tables_total = len(before_inv.tables)

                if migration_failed:
                    # Do not compare partially migrated database
                    coverage_status = CoverageStatus.NOT_RUN
                    for tname, tschema in sorted(before_inv.tables.items()):
                        tables.append(
                            TableComparison(
                                name=tname,
                                before_rows=before_inv.row_counts.get(tname),
                                after_rows=None,
                                before_columns=[c.name for c in tschema.columns],
                                after_columns=[],
                                before_key=tschema.pk_columns,
                                after_key=[],
                                shared_value_columns=[],
                                comparison=ComparisonKind.UNAVAILABLE.value,
                                removed_keys=None,
                                added_keys=None,
                                changed_rows=None,
                            )
                        )
                else:
                    # Migrations succeeded, inspect working database and compare
                    working_uri = copies.working_path.resolve().as_uri() + "?mode=ro"
                    conn_after = sqlite3.connect(working_uri, uri=True)
                    try:
                        after_inv = inspect_database(conn_after, deadline)
                        all_table_names = set(before_inv.tables.keys()) | set(after_inv.tables.keys())
                        tables_total = len(all_table_names)

                        # Union of excluded engine objects identities (type, name)
                        all_excluded = before_inv.excluded_engine_objects | after_inv.excluded_engine_objects
                        excluded_objects_count = len(all_excluded)

                        (
                            tables,
                            findings,
                            coverage_gaps,
                            coverage_status,
                        ) = compare_databases(
                            conn_before,
                            conn_after,
                            before_inv,
                            after_inv,
                            options.limits,
                            deadline,
                        )
                        tables_compared = sum(
                            1 for t in tables if t.comparison == ComparisonKind.EXACT.value
                        )

                        # Evaluate aggregate checks
                        if checks_specs:
                            try:
                                ch_results, ch_findings = evaluate_checks(
                                    checks_specs,
                                    copies.before_path,
                                    copies.working_path,
                                    deadline,
                                )
                                checks_results = ch_results
                                findings.extend(ch_findings)
                            except CheckExecutionError as c_err:
                                errors.append(
                                    ReportError(
                                        code="CHECK_EXECUTION_FAILED",
                                        message=str(c_err),
                                    )
                                )
                    finally:
                        conn_after.close()

            finally:
                conn_before.close()

    except DeadlineExceeded:
        errors.append(
            ReportError(
                code="DEADLINE_EXCEEDED",
                message="Execution exceeded cooperative deadline budget.",
            )
        )
        coverage_status = CoverageStatus.PARTIAL
    except Exception as exc:
        errors.append(
            ReportError(
                code="INTERNAL_ERROR",
                message=f"Rehearsal failed with internal error: {exc}",
            )
        )

    # Step 4: Rehash source file to ensure it was not modified
    try:
        post_sha256 = compute_file_sha256(database_path, deadline)
        if post_sha256 != source_sha256:
            errors.append(
                ReportError(
                    code="SOURCE_CHANGED",
                    message="Source database was modified during rehearsal execution.",
                )
            )
            source_unchanged = False
        else:
            source_unchanged = True
    except Exception as exc:
        errors.append(
            ReportError(
                code="SOURCE_CHANGED",
                message=f"Failed to verify source database integrity: {exc}",
            )
        )
        source_unchanged = None

    # Step 5: Determine status and exit code
    if errors:
        final_status = RunStatus.ERROR
        final_exit = 20
    elif coverage_status != CoverageStatus.COMPLETE:
        final_status = RunStatus.INCOMPLETE
        final_exit = 20
    else:
        # Check findings against fail_on threshold
        if options.fail_on == "error":
            blocking = [f for f in findings if f.severity == FindingSeverity.ERROR.value]
        else:  # default "warning"
            blocking = [
                f
                for f in findings
                if f.severity in (FindingSeverity.ERROR.value, FindingSeverity.WARNING.value)
            ]

        if blocking:
            final_status = RunStatus.REVIEW
            final_exit = 10
        else:
            final_status = RunStatus.PASS
            final_exit = 0

    duration_ms = int((time.monotonic() - start_monotonic) * 1000)

    import sqlite3 as sq

    result = RunResult(
        status=final_status,
        exit_code=final_exit,
        fail_on=options.fail_on,
        database_name=db_name,
        source_sha256=source_sha256,
        source_unchanged=source_unchanged,
        started_at=started_at,
        duration_ms=duration_ms,
        python_version=sys.version,
        sqlite_version=sq.sqlite_version,
        comparison_scope=COMPARISON_SCOPE,
        migrations=migrations,
        coverage_status=coverage_status,
        tables_total=tables_total,
        tables_compared=tables_compared,
        excluded_engine_objects=excluded_objects_count,
        coverage_gaps=coverage_gaps,
        tables=tables,
        findings=findings,
        checks=checks_results,
        errors=errors,
    )

    # Step 6: Build report model and write reports
    report_model = build_public_report_model(result)
    write_reports(report_model, options.out)

    # Step 7: Print terminal summary
    print_terminal_summary(result, options.out, is_demo=options.is_demo)

    return result
