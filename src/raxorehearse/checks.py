"""Aggregate check parsing, strict validation, and read-only execution."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from raxorehearse.limits import Limits
from raxorehearse.models import (
    CheckExecutionError,
    CheckResult,
    CheckSpec,
    Deadline,
    Finding,
    FindingSeverity,
    InputError,
)
from raxorehearse.sql_guard import read_only_authorizer
from raxorehearse.sql_statements import split_statements

CHECK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _no_duplicate_keys_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys at any nesting level."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Duplicate key in JSON: '{key}'.")
        result[key] = value
    return result


def parse_and_validate_checks(
    checks_path: Path, limits: Limits
) -> list[CheckSpec]:
    """Parse and strictly validate aggregate checks JSON file."""
    if not checks_path.exists() or not checks_path.is_file():
        raise InputError(f"Checks file does not exist or is not a file: {checks_path}")

    size = checks_path.stat().st_size
    if size > limits.max_checks_json_bytes:
        raise InputError(
            f"Checks JSON file size ({size} bytes) exceeds limit of {limits.max_checks_json_bytes} bytes (256 KiB)."
        )

    try:
        raw_text = checks_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise InputError(f"Could not read checks file as UTF-8: {exc}")

    return parse_and_validate_checks_json(raw_text, limits)


def parse_and_validate_checks_json(
    raw_json: str, limits: Limits
) -> list[CheckSpec]:
    """Strictly validate aggregate checks JSON string."""
    try:
        data = json.loads(raw_json, object_pairs_hook=_no_duplicate_keys_hook)
    except Exception as exc:
        raise InputError(f"Invalid JSON in checks file: {exc}")

    if not isinstance(data, dict):
        raise InputError("Checks JSON root must be an object.")

    # Top-level keys must be exactly "version" and "checks"
    if set(data.keys()) != {"version", "checks"}:
        raise InputError(
            f"Checks JSON root must contain exactly 'version' and 'checks', got: {sorted(data.keys())}."
        )

    # version must be integer 1 (reject booleans)
    version = data["version"]
    if type(version) is not int or isinstance(version, bool) or version != 1:
        raise InputError("Checks JSON 'version' must be integer 1.")

    checks_list = data["checks"]
    if not isinstance(checks_list, list):
        raise InputError("Checks JSON 'checks' must be an array.")

    if len(checks_list) > limits.max_checks:
        raise InputError(
            f"Number of checks ({len(checks_list)}) exceeds limit of {limits.max_checks}."
        )

    seen_ids: set[str] = set()
    specs: list[CheckSpec] = []

    for idx, c in enumerate(checks_list):
        if not isinstance(c, dict):
            raise InputError(f"Check at index {idx} must be an object.")

        if set(c.keys()) != {"id", "sql", "expect"}:
            raise InputError(
                f"Check at index {idx} must contain exactly 'id', 'sql', and 'expect', got: {sorted(c.keys())}."
            )

        cid = c["id"]
        if not isinstance(cid, str) or not CHECK_ID_PATTERN.match(cid):
            raise InputError(
                f"Check id '{cid}' is invalid. Must match ASCII regex '^[a-z][a-z0-9_]{{0,63}}$'."
            )

        if cid in seen_ids:
            raise InputError(f"Duplicate check id: '{cid}'. Check IDs must be unique.")
        seen_ids.add(cid)

        csql = c["sql"]
        if not isinstance(csql, str) or not csql.strip():
            raise InputError(f"Check '{cid}' sql must be a non-empty string.")

        if len(csql.encode("utf-8")) > limits.max_check_sql_bytes:
            raise InputError(
                f"Check '{cid}' SQL exceeds limit of {limits.max_check_sql_bytes} bytes (16 KiB)."
            )

        # Validate that SQL parses into exactly one statement
        stmts = split_statements(csql, f"check:{cid}")
        if len(stmts) != 1:
            raise InputError(
                f"Check '{cid}' SQL must contain exactly one statement, found {len(stmts)}."
            )

        cexpect = c["expect"]
        if not isinstance(cexpect, dict):
            raise InputError(f"Check '{cid}' expect must be an object.")

        kind = cexpect.get("kind")
        if kind == "unchanged":
            if set(cexpect.keys()) != {"kind"}:
                raise InputError(f"Check '{cid}' expect for 'unchanged' must only contain 'kind'.")
        elif kind == "equals":
            if set(cexpect.keys()) != {"kind", "value"}:
                raise InputError(
                    f"Check '{cid}' expect for 'equals' must contain exactly 'kind' and 'value'."
                )
            val = cexpect["value"]
            if type(val) is not int or isinstance(val, bool):
                raise InputError(f"Check '{cid}' expect 'value' must be an integer (booleans excluded).")
        else:
            raise InputError(
                f"Check '{cid}' expect kind '{kind}' is unsupported. Must be 'unchanged' or 'equals'."
            )

        specs.append(CheckSpec(id=cid, sql=csql, expect=cexpect))

    return specs


def execute_check_query(
    conn: sqlite3.Connection, sql: str, check_id: str, deadline: Deadline
) -> int:
    """Execute a single check query on a read-only connection and return the integer result.

    Enforces exactly one row with one integer column.
    """
    deadline.check()
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(2)
    except Exception as exc:
        raise CheckExecutionError(
            f"Query execution failed for check '{check_id}': {type(exc).__name__}."
        )

    if not rows:
        raise CheckExecutionError(
            f"Query for check '{check_id}' returned 0 rows; exactly 1 row is required."
        )

    if len(rows) > 1:
        raise CheckExecutionError(
            f"Query for check '{check_id}' returned multiple rows; exactly 1 row is required."
        )

    row = rows[0]
    if len(row) != 1:
        raise CheckExecutionError(
            f"Query for check '{check_id}' returned {len(row)} columns; exactly 1 column is required."
        )

    val = row[0]
    if type(val) is not int or isinstance(val, bool):
        type_name = type(val).__name__ if val is not None else "null"
        raise CheckExecutionError(
            f"Query for check '{check_id}' returned non-integer value of type {type_name}."
        )

    return val


def evaluate_checks(
    checks: list[CheckSpec],
    before_path: Path,
    after_path: Path,
    deadline: Deadline,
) -> tuple[list[CheckResult], list[Finding]]:
    """Evaluate all aggregate checks on baseline and final databases."""
    results: list[CheckResult] = []
    findings: list[Finding] = []

    if not checks:
        return results, findings

    deadline.check()

    # Open dedicated read-only connections with query_only=ON and authorizer
    before_uri = before_path.resolve().as_uri() + "?mode=ro"
    after_uri = after_path.resolve().as_uri() + "?mode=ro"

    conn_b = sqlite3.connect(before_uri, uri=True)
    conn_a = sqlite3.connect(after_uri, uri=True)

    try:
        for c in (conn_b, conn_a):
            c.execute("PRAGMA query_only = ON")
            c.set_progress_handler(deadline.sqlite_progress_handler, 10000)
            c.set_authorizer(read_only_authorizer)

        for check in checks:
            deadline.check()
            kind = check.expect["kind"]

            if kind == "unchanged":
                before_val = execute_check_query(conn_b, check.sql, check.id, deadline)
                after_val = execute_check_query(conn_a, check.sql, check.id, deadline)
                passed = before_val == after_val

                results.append(
                    CheckResult(
                        id=check.id,
                        expect=check.expect,
                        before_value=before_val,
                        after_value=after_val,
                        passed=passed,
                    )
                )

                if not passed:
                    findings.append(
                        Finding(
                            code="CHECK_FAILED",
                            severity=FindingSeverity.ERROR.value,
                            message=f"Aggregate check '{check.id}' failed expectation: before={before_val}, after={after_val}.",
                            check_id=check.id,
                        )
                    )

            elif kind == "equals":
                before_val = None
                after_val = execute_check_query(conn_a, check.sql, check.id, deadline)
                expected_val = check.expect["value"]
                passed = after_val == expected_val

                results.append(
                    CheckResult(
                        id=check.id,
                        expect=check.expect,
                        before_value=None,
                        after_value=after_val,
                        passed=passed,
                    )
                )

                if not passed:
                    findings.append(
                        Finding(
                            code="CHECK_FAILED",
                            severity=FindingSeverity.ERROR.value,
                            message=f"Aggregate check '{check.id}' failed expectation: expected={expected_val}, actual={after_val}.",
                            check_id=check.id,
                        )
                    )

    finally:
        for c in (conn_b, conn_a):
            try:
                c.set_authorizer(None)
                c.set_progress_handler(None, 0)
                c.close()
            except Exception:
                pass

    return results, findings
