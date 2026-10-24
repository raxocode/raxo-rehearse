"""Public JSON report construction and serialization."""

from __future__ import annotations

import json
from typing import Any

from raxorehearse import __version__
from raxorehearse.limits import COMPARISON_SCOPE, FORMAT_VERSION
from raxorehearse.models import RunResult


def build_public_report_model(result: RunResult) -> dict[str, Any]:
    """Construct the authoritative public report model from internal RunResult.

    Strictly separates sensitive internal data (raw SQL, connection paths, row contents).
    """
    # 1. Tool metadata
    tool = {
        "name": "raxorehearse",
        "version": __version__,
    }

    # 2. Run metadata
    run = {
        "status": result.status.value,
        "exit_code": result.exit_code,
        "fail_on": result.fail_on,
        "database_name": result.database_name,
        "source_sha256": result.source_sha256,
        "source_unchanged": result.source_unchanged,
        "started_at": result.started_at,
        "duration_ms": result.duration_ms,
        "python_version": result.python_version,
        "sqlite_version": result.sqlite_version,
        "comparison_scope": COMPARISON_SCOPE,
    }

    # 3. Migrations array in supplied execution order
    migrations = [
        {
            "name": m.name,
            "sha256": m.sha256,
            "statement_count": len(m.statements),
            "execution": m.execution.value,
        }
        for m in result.migrations
    ]

    # 4. Coverage object
    sorted_gaps = sorted(
        result.coverage_gaps,
        key=lambda g: (g.table or "", g.code),
    )
    coverage = {
        "status": result.coverage_status.value,
        "tables_total": result.tables_total,
        "tables_compared": result.tables_compared,
        "excluded_engine_objects": result.excluded_engine_objects,
        "gaps": [
            {
                "table": g.table,
                "code": g.code,
                "message": g.message,
            }
            for g in sorted_gaps
        ],
    }

    # 5. Tables array sorted by exact table name
    sorted_tables = sorted(result.tables, key=lambda t: t.name)
    tables = [
        {
            "name": t.name,
            "before_rows": t.before_rows,
            "after_rows": t.after_rows,
            "before_columns": t.before_columns,
            "after_columns": t.after_columns,
            "before_key": t.before_key,
            "after_key": t.after_key,
            "shared_value_columns": t.shared_value_columns,
            "comparison": t.comparison,
            "removed_keys": t.removed_keys,
            "added_keys": t.added_keys,
            "changed_rows": t.changed_rows,
        }
        for t in sorted_tables
    ]

    # 6. Findings array
    findings = [
        {
            "code": f.code,
            "severity": f.severity,
            "message": f.message,
            "table": f.table,
            "column": f.column,
            "object": (
                {"kind": f.object.kind, "name": f.object.name}
                if f.object is not None
                else None
            ),
            "check_id": f.check_id,
            "count": f.count,
        }
        for f in result.findings
    ]

    # 7. Checks array in configuration order
    checks = [
        {
            "id": c.id,
            "expect": c.expect,
            "before_value": c.before_value,
            "after_value": c.after_value,
            "passed": c.passed,
        }
        for c in result.checks
    ]

    # 8. Errors array
    errors = [
        {
            "code": e.code,
            "message": e.message,
            "migration": e.migration,
            "statement_index": e.statement_index,
            "line": e.line,
            "sqlite_errorname": e.sqlite_errorname,
        }
        for e in result.errors
    ]

    return {
        "format_version": FORMAT_VERSION,
        "tool": tool,
        "run": run,
        "migrations": migrations,
        "coverage": coverage,
        "tables": tables,
        "findings": findings,
        "checks": checks,
        "errors": errors,
    }


def serialize_public_report_json(report: dict[str, Any]) -> str:
    """Serialize the public report model to UTF-8 formatted JSON."""
    return json.dumps(report, indent=2, allow_nan=False) + "\n"
