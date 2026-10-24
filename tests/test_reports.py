"""Tests for public JSON and HTML reports, privacy, and determinism."""

import json
from pathlib import Path
import pytest

from raxorehearse.models import (
    CheckResult,
    ComparisonKind,
    CoverageStatus,
    Finding,
    FindingSeverity,
    MigrationExecution,
    MigrationRecord,
    ReportError,
    RunResult,
    RunStatus,
    SqlStatement,
    TableComparison,
)
from raxorehearse.report_html import render_public_report_html
from raxorehearse.report_json import (
    build_public_report_model,
    serialize_public_report_json,
)


def make_dummy_result(
    table_name: str = "profiles",
    with_error: bool = False,
) -> RunResult:
    """Helper to build a sample RunResult."""
    tables = [
        TableComparison(
            name=table_name,
            before_rows=12,
            after_rows=12,
            before_columns=["id", "handle", "bio"],
            after_columns=["id", "handle"],
            before_key=["id"],
            after_key=["id"],
            shared_value_columns=["handle"],
            comparison=ComparisonKind.EXACT.value,
            removed_keys=3,
            added_keys=3,
            changed_rows=0,
        )
    ]
    findings = [
        Finding(
            code="COLUMN_REMOVED",
            severity=FindingSeverity.ERROR.value,
            message="Column 'profiles.bio' was removed.",
            table=table_name,
            column="bio",
        ),
        Finding(
            code="ROWS_REMOVED",
            severity=FindingSeverity.ERROR.value,
            message=f"Table '{table_name}' had 3 keys removed.",
            table=table_name,
            count=3,
        ),
    ]
    migrations = [
        MigrationRecord(
            path=Path("001_bad.sql"),
            name="001_bad.sql",
            sha256="abcdef1234567890" * 4,
            statements=[SqlStatement(1, 1, "ALTER TABLE profiles DROP COLUMN bio;")],
            execution=MigrationExecution.APPLIED,
        )
    ]
    errors = []
    if with_error:
        errors.append(
            ReportError(
                code="MIGRATION_FAILED",
                message="SQLite rejected statement 1 in 001_bad.sql; inspect that statement locally.",
                migration="001_bad.sql",
                statement_index=1,
                line=1,
                sqlite_errorname="OperationalError",
            )
        )

    return RunResult(
        status=RunStatus.REVIEW if not with_error else RunStatus.ERROR,
        exit_code=10 if not with_error else 20,
        fail_on="warning",
        database_name="test.sqlite",
        source_sha256="1234567890abcdef" * 4,
        source_unchanged=True,
        started_at="2026-10-24T06:00:00Z",
        duration_ms=42,
        python_version="3.12.14",
        sqlite_version="3.40.1",
        comparison_scope="sqlite_final_state_v1",
        migrations=migrations,
        coverage_status=CoverageStatus.COMPLETE if not with_error else CoverageStatus.NOT_RUN,
        tables_total=1,
        tables_compared=1 if not with_error else 0,
        excluded_engine_objects=2,
        coverage_gaps=[],
        tables=tables,
        findings=findings if not with_error else [],
        checks=[],
        errors=errors,
    )


def test_t37_html_escaping_malicious_inputs() -> None:
    """T37: Malicious table name with XSS payload is strictly escaped in HTML."""
    xss_table_name = '<img src=x onerror=alert("hacked")></script>'
    result = make_dummy_result(table_name=xss_table_name)
    report_model = build_public_report_model(result)
    html_text = render_public_report_html(report_model)

    # Raw script or img tag must NOT be present unescaped
    assert '<img src=x onerror=alert("hacked")>' not in html_text
    assert "</script>" not in html_text

    # Escaped versions MUST be present
    assert "&lt;img src=x onerror=alert(&quot;hacked&quot;)&gt;&lt;/script&gt;" in html_text
    # No <script> tags at all in the document
    assert "<script" not in html_text


def test_t38_output_contents_privacy() -> None:
    """T38: No row values, full paths, query SQL, migration SQL appear in public JSON/HTML."""
    secret_sentinel = "DEMO_PRIVATE_BIO_7"
    secret_sql = "DROP COLUMN secret_classified"

    result = make_dummy_result()
    report_model = build_public_report_model(result)
    json_text = serialize_public_report_json(report_model)
    html_text = render_public_report_html(report_model)

    for text in (json_text, html_text):
        assert secret_sentinel not in text
        assert secret_sql not in text
        # Full filesystem paths must not appear
        assert "/workspace" not in text
        assert "/home" not in text
        assert "/tmp" not in text


def test_t39_failure_json() -> None:
    """T39: Failed migration has after-state unavailable, no bogus deletion findings, correct ERROR/20."""
    result = make_dummy_result(with_error=True)
    report_model = build_public_report_model(result)

    assert report_model["run"]["status"] == "ERROR"
    assert report_model["run"]["exit_code"] == 20
    assert report_model["coverage"]["status"] == "NOT_RUN"
    assert len(report_model["findings"]) == 0
    assert len(report_model["errors"]) == 1
    assert report_model["errors"][0]["code"] == "MIGRATION_FAILED"


def test_t40_deterministic_report() -> None:
    """T40: Stable ordering in JSON report output."""
    res1 = make_dummy_result()
    res2 = make_dummy_result()

    model1 = build_public_report_model(res1)
    model2 = build_public_report_model(res2)

    json1 = serialize_public_report_json(model1)
    json2 = serialize_public_report_json(model2)

    assert json1 == json2
