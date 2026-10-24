"""Exact keyed data comparison, typed binary encoding, schema diffing, and findings."""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from typing import Any

from raxorehearse.inspect_db import quote_identifier
from raxorehearse.limits import Limits
from raxorehearse.models import (
    ComparisonKind,
    CoverageGapItem,
    CoverageStatus,
    DatabaseInventory,
    Deadline,
    Finding,
    FindingObject,
    FindingSeverity,
    TableComparison,
    TableSchema,
)


def encode_cell(val: Any) -> bytes:
    """Unambiguously encode a SQLite value with 1-byte tag and 8-byte big-endian length.

    - None: tag 'N', empty payload
    - Integer: tag 'I', base-10 ASCII payload
    - Real: tag 'R', struct.pack('>d', val) payload
    - Text: tag 'T', UTF-8 payload
    - BLOB: tag 'B', raw bytes payload
    """
    if val is None:
        return b"N\x00\x00\x00\x00\x00\x00\x00\x00"

    if isinstance(val, bool):
        payload = b"1" if val else b"0"
        return b"I" + struct.pack(">Q", len(payload)) + payload

    if isinstance(val, int):
        payload = str(val).encode("ascii")
        return b"I" + struct.pack(">Q", len(payload)) + payload

    if isinstance(val, float):
        payload = struct.pack(">d", val)
        return b"R" + struct.pack(">Q", len(payload)) + payload

    if isinstance(val, str):
        payload = val.encode("utf-8")
        return b"T" + struct.pack(">Q", len(payload)) + payload

    if isinstance(val, (bytes, bytearray, memoryview)):
        payload = bytes(val)
        return b"B" + struct.pack(">Q", len(payload)) + payload

    raise TypeError(f"Unsupported value type for encoding: {type(val)}")


def encode_tuple(values: tuple[Any, ...]) -> bytes:
    """Encode a tuple of values by concatenating cell encodings."""
    return b"".join(encode_cell(v) for v in values)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings by severity (error, warning, info), then code, table, column, object, check_id."""
    severity_rank = {
        FindingSeverity.ERROR.value: 0,
        FindingSeverity.WARNING.value: 1,
        FindingSeverity.INFO.value: 2,
    }
    return sorted(
        findings,
        key=lambda f: (
            severity_rank.get(f.severity, 99),
            f.code,
            f.table or "",
            f.column or "",
            f.object.kind if f.object else "",
            f.object.name if f.object else "",
            f.check_id or "",
        ),
    )


class DatabaseComparator:
    """Compares baseline and migrated databases."""

    def __init__(
        self,
        before_conn: sqlite3.Connection,
        after_conn: sqlite3.Connection,
        before_inv: DatabaseInventory,
        after_inv: DatabaseInventory,
        limits: Limits,
        deadline: Deadline,
    ):
        self.before_conn = before_conn
        self.after_conn = after_conn
        self.before_inv = before_inv
        self.after_inv = after_inv
        self.limits = limits
        self.deadline = deadline

        self.findings: list[Finding] = []
        self.coverage_gaps: list[CoverageGapItem] = []
        self.table_comparisons: list[TableComparison] = []

    def compare(self) -> tuple[list[TableComparison], list[Finding], list[CoverageGapItem], CoverageStatus]:
        self.deadline.check()

        all_table_names = sorted(set(self.before_inv.tables.keys()) | set(self.after_inv.tables.keys()))

        # Check total tables limit
        if len(all_table_names) > self.limits.max_tables:
            self.coverage_gaps.append(
                CoverageGapItem(
                    table=None,
                    code="TABLE_LIMIT",
                    message=f"Total application tables ({len(all_table_names)}) exceeds limit of {self.limits.max_tables}.",
                )
            )

        # Check total row count limit across tables
        total_rows_before = sum(r for r in self.before_inv.row_counts.values() if r is not None)
        total_rows_after = sum(r for r in self.after_inv.row_counts.values() if r is not None)
        if total_rows_before > self.limits.max_rows_total or total_rows_after > self.limits.max_rows_total:
            self.coverage_gaps.append(
                CoverageGapItem(
                    table=None,
                    code="ROW_LIMIT",
                    message="Total database rows across tables exceeds limit of 1,000,000.",
                )
            )

        for tbl_name in all_table_names:
            self.deadline.check()
            self._compare_table(tbl_name)

        # Compare schema objects (indexes, views, triggers)
        self._compare_schema_objects()

        # Determine coverage status
        has_gaps = len(self.coverage_gaps) > 0
        any_unavailable = any(tc.comparison == ComparisonKind.UNAVAILABLE.value for tc in self.table_comparisons)
        if has_gaps or any_unavailable:
            coverage_status = CoverageStatus.PARTIAL
        else:
            coverage_status = CoverageStatus.COMPLETE

        sorted_findings = sort_findings(self.findings)
        return self.table_comparisons, sorted_findings, self.coverage_gaps, coverage_status

    def _compare_table(self, tbl_name: str) -> None:
        in_before = tbl_name in self.before_inv.tables
        in_after = tbl_name in self.after_inv.tables

        # Case 1: Wholly removed table
        if in_before and not in_after:
            b_schema = self.before_inv.tables[tbl_name]
            b_rows = self.before_inv.row_counts.get(tbl_name)

            self.findings.append(
                Finding(
                    code="TABLE_REMOVED",
                    severity=FindingSeverity.ERROR.value,
                    message=f"Table '{tbl_name}' was removed.",
                    table=tbl_name,
                )
            )

            is_eligible, gap = self._check_eligibility(b_schema, b_rows, side="before")
            if not is_eligible:
                if gap:
                    self.coverage_gaps.append(gap)
                self.table_comparisons.append(
                    TableComparison(
                        name=tbl_name,
                        before_rows=b_rows,
                        after_rows=None,
                        before_columns=[c.name for c in b_schema.columns],
                        after_columns=[],
                        before_key=b_schema.pk_columns,
                        after_key=[],
                        shared_value_columns=[],
                        comparison=ComparisonKind.UNAVAILABLE.value,
                        removed_keys=None,
                        added_keys=None,
                        changed_rows=None,
                    )
                )
                return

            # Scan rows to validate keys
            scan_gap = self._validate_keys_scan(self.before_conn, b_schema)
            if scan_gap:
                self.coverage_gaps.append(scan_gap)
                self.table_comparisons.append(
                    TableComparison(
                        name=tbl_name,
                        before_rows=b_rows,
                        after_rows=None,
                        before_columns=[c.name for c in b_schema.columns],
                        after_columns=[],
                        before_key=b_schema.pk_columns,
                        after_key=[],
                        shared_value_columns=[],
                        comparison=ComparisonKind.UNAVAILABLE.value,
                        removed_keys=None,
                        added_keys=None,
                        changed_rows=None,
                    )
                )
                return

            removed_keys_count = b_rows if b_rows is not None else 0
            if removed_keys_count > 0:
                self.findings.append(
                    Finding(
                        code="ROWS_REMOVED",
                        severity=FindingSeverity.ERROR.value,
                        message=f"Table '{tbl_name}' had {removed_keys_count} keys removed.",
                        table=tbl_name,
                        count=removed_keys_count,
                    )
                )

            self.table_comparisons.append(
                TableComparison(
                    name=tbl_name,
                    before_rows=b_rows,
                    after_rows=None,
                    before_columns=[c.name for c in b_schema.columns],
                    after_columns=[],
                    before_key=b_schema.pk_columns,
                    after_key=[],
                    shared_value_columns=[],
                    comparison=ComparisonKind.EXACT.value,
                    removed_keys=removed_keys_count,
                    added_keys=0,
                    changed_rows=0,
                )
            )
            return

        # Case 2: Wholly added table
        if not in_before and in_after:
            a_schema = self.after_inv.tables[tbl_name]
            a_rows = self.after_inv.row_counts.get(tbl_name)

            self.findings.append(
                Finding(
                    code="TABLE_ADDED",
                    severity=FindingSeverity.INFO.value,
                    message=f"Table '{tbl_name}' was added.",
                    table=tbl_name,
                )
            )

            is_eligible, gap = self._check_eligibility(a_schema, a_rows, side="after")
            if not is_eligible:
                if gap:
                    self.coverage_gaps.append(gap)
                self.table_comparisons.append(
                    TableComparison(
                        name=tbl_name,
                        before_rows=None,
                        after_rows=a_rows,
                        before_columns=[],
                        after_columns=[c.name for c in a_schema.columns],
                        before_key=[],
                        after_key=a_schema.pk_columns,
                        shared_value_columns=[],
                        comparison=ComparisonKind.UNAVAILABLE.value,
                        removed_keys=None,
                        added_keys=None,
                        changed_rows=None,
                    )
                )
                return

            scan_gap = self._validate_keys_scan(self.after_conn, a_schema)
            if scan_gap:
                self.coverage_gaps.append(scan_gap)
                self.table_comparisons.append(
                    TableComparison(
                        name=tbl_name,
                        before_rows=None,
                        after_rows=a_rows,
                        before_columns=[],
                        after_columns=[c.name for c in a_schema.columns],
                        before_key=[],
                        after_key=a_schema.pk_columns,
                        shared_value_columns=[],
                        comparison=ComparisonKind.UNAVAILABLE.value,
                        removed_keys=None,
                        added_keys=None,
                        changed_rows=None,
                    )
                )
                return

            added_keys_count = a_rows if a_rows is not None else 0
            if added_keys_count > 0:
                self.findings.append(
                    Finding(
                        code="ROWS_ADDED",
                        severity=FindingSeverity.INFO.value,
                        message=f"Table '{tbl_name}' had {added_keys_count} keys added.",
                        table=tbl_name,
                        count=added_keys_count,
                    )
                )

            self.table_comparisons.append(
                TableComparison(
                    name=tbl_name,
                    before_rows=None,
                    after_rows=a_rows,
                    before_columns=[],
                    after_columns=[c.name for c in a_schema.columns],
                    before_key=[],
                    after_key=a_schema.pk_columns,
                    shared_value_columns=[],
                    comparison=ComparisonKind.EXACT.value,
                    removed_keys=0,
                    added_keys=added_keys_count,
                    changed_rows=0,
                )
            )
            return

        # Case 3: Surviving table on both sides
        b_schema = self.before_inv.tables[tbl_name]
        a_schema = self.after_inv.tables[tbl_name]
        b_rows = self.before_inv.row_counts.get(tbl_name)
        a_rows = self.after_inv.row_counts.get(tbl_name)

        b_cols_dict = {c.name: c for c in b_schema.columns}
        a_cols_dict = {c.name: c for c in a_schema.columns}

        # Check schema changes
        # 1. Removed columns
        for cname in b_cols_dict:
            if cname not in a_cols_dict:
                self.findings.append(
                    Finding(
                        code="COLUMN_REMOVED",
                        severity=FindingSeverity.ERROR.value,
                        message=f"Column '{tbl_name}.{cname}' was removed.",
                        table=tbl_name,
                        column=cname,
                    )
                )

        # 2. Added columns
        for cname in a_cols_dict:
            if cname not in b_cols_dict:
                self.findings.append(
                    Finding(
                        code="COLUMN_ADDED",
                        severity=FindingSeverity.INFO.value,
                        message=f"Column '{tbl_name}.{cname}' was added.",
                        table=tbl_name,
                        column=cname,
                    )
                )

        # 3. Changed column definitions
        for cname, b_col in b_cols_dict.items():
            if cname in a_cols_dict:
                a_col = a_cols_dict[cname]
                if (
                    b_col.type != a_col.type
                    or b_col.notnull != a_col.notnull
                    or b_col.dflt_value != a_col.dflt_value
                    or b_col.pk != a_col.pk
                ):
                    self.findings.append(
                        Finding(
                            code="COLUMN_DEFINITION_CHANGED",
                            severity=FindingSeverity.WARNING.value,
                            message=f"Column definition for '{tbl_name}.{cname}' was modified.",
                            table=tbl_name,
                            column=cname,
                        )
                    )

        # 4. Key definition changed
        b_key_def = [(c.name, c.type) for c in b_schema.columns if c.pk > 0]
        a_key_def = [(c.name, c.type) for c in a_schema.columns if c.pk > 0]
        key_def_changed = b_key_def != a_key_def
        if key_def_changed:
            self.findings.append(
                Finding(
                    code="KEY_DEFINITION_CHANGED",
                    severity=FindingSeverity.WARNING.value,
                    message=f"Primary key definition changed on table '{tbl_name}'.",
                    table=tbl_name,
                )
            )

        # 5. Table definition changed
        if b_schema.sql and a_schema.sql and b_schema.sql != a_schema.sql:
            self.findings.append(
                Finding(
                    code="TABLE_DEFINITION_CHANGED",
                    severity=FindingSeverity.INFO.value,
                    message=f"Table definition SQL changed for '{tbl_name}'.",
                    table=tbl_name,
                )
            )

        # Check eligibility for exact comparison
        b_eligible, b_gap = self._check_eligibility(b_schema, b_rows, side="before")
        a_eligible, a_gap = self._check_eligibility(a_schema, a_rows, side="after")

        if not b_eligible or not a_eligible or key_def_changed:
            gap = b_gap or a_gap
            if key_def_changed:
                gap = CoverageGapItem(
                    table=tbl_name,
                    code="KEY_DEFINITION_CHANGED",
                    message=f"Primary key definition changed on table '{tbl_name}'.",
                )
            if gap:
                self.coverage_gaps.append(gap)

            self.table_comparisons.append(
                TableComparison(
                    name=tbl_name,
                    before_rows=b_rows,
                    after_rows=a_rows,
                    before_columns=[c.name for c in b_schema.columns],
                    after_columns=[c.name for c in a_schema.columns],
                    before_key=b_schema.pk_columns,
                    after_key=a_schema.pk_columns,
                    shared_value_columns=[],
                    comparison=ComparisonKind.UNAVAILABLE.value,
                    removed_keys=None,
                    added_keys=None,
                    changed_rows=None,
                )
            )
            return

        # Perform exact comparison on surviving eligible table
        self._exact_keyed_compare(tbl_name, b_schema, a_schema, b_rows, a_rows)

    def _exact_keyed_compare(
        self,
        tbl_name: str,
        b_schema: TableSchema,
        a_schema: TableSchema,
        b_rows: int | None,
        a_rows: int | None,
    ) -> None:
        # Determine shared ordinary non-key columns, sorted alphabetically
        b_pk_set = set(b_schema.pk_columns)
        a_pk_set = set(a_schema.pk_columns)

        b_ordinary_non_keys = {c.name for c in b_schema.columns if c.hidden == 0 and c.name not in b_pk_set}
        a_ordinary_non_keys = {c.name for c in a_schema.columns if c.hidden == 0 and c.name not in a_pk_set}

        shared_non_keys = sorted(b_ordinary_non_keys & a_ordinary_non_keys)

        pk_cols = b_schema.pk_columns
        pk_cols_sql = ", ".join(quote_identifier(c) for c in pk_cols)
        shared_cols_sql = ", ".join(quote_identifier(c) for c in shared_non_keys)

        select_cols_sql = f"{pk_cols_sql}, {shared_cols_sql}" if shared_non_keys else pk_cols_sql
        quoted_table = quote_identifier(tbl_name)
        pk_count = len(pk_cols)

        # 1. Stream baseline rows
        before_map: dict[bytes, str] = {}
        try:
            cursor_b = self.before_conn.execute(f"SELECT {select_cols_sql} FROM {quoted_table}")
            while True:
                self.deadline.check()
                rows = cursor_b.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    pk_vals = row[:pk_count]
                    if any(v is None for v in pk_vals):
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "NULL_KEY", f"Table '{tbl_name}' contains NULL primary key values."),
                        )
                        return

                    encoded_pk = encode_tuple(pk_vals)
                    if len(encoded_pk) > self.limits.max_encoded_key_bytes:
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "KEY_SIZE_LIMIT", f"Table '{tbl_name}' composite key exceeds 1,024 bytes."),
                        )
                        return

                    if encoded_pk in before_map:
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "AMBIGUOUS_KEY", f"Table '{tbl_name}' contains duplicate primary keys."),
                        )
                        return

                    non_key_vals = row[pk_count:]
                    val_hash = hashlib.sha256(encode_tuple(non_key_vals)).hexdigest()
                    before_map[encoded_pk] = val_hash
        except Exception as exc:
            self._mark_unavailable_with_gap(
                tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                CoverageGapItem(tbl_name, "UNSUPPORTED_VALUE", f"Error scanning baseline rows: {exc}"),
            )
            return

        # 2. Stream after rows
        after_keys: set[bytes] = set()
        added_keys = 0
        changed_rows = 0

        try:
            cursor_a = self.after_conn.execute(f"SELECT {select_cols_sql} FROM {quoted_table}")
            while True:
                self.deadline.check()
                rows = cursor_a.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    pk_vals = row[:pk_count]
                    if any(v is None for v in pk_vals):
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "NULL_KEY", f"Table '{tbl_name}' contains NULL primary key values in after-state."),
                        )
                        return

                    encoded_pk = encode_tuple(pk_vals)
                    if len(encoded_pk) > self.limits.max_encoded_key_bytes:
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "KEY_SIZE_LIMIT", f"Table '{tbl_name}' composite key exceeds 1,024 bytes in after-state."),
                        )
                        return

                    if encoded_pk in after_keys:
                        self._mark_unavailable_with_gap(
                            tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                            CoverageGapItem(tbl_name, "AMBIGUOUS_KEY", f"Table '{tbl_name}' contains duplicate primary keys in after-state."),
                        )
                        return
                    after_keys.add(encoded_pk)

                    non_key_vals = row[pk_count:]
                    val_hash = hashlib.sha256(encode_tuple(non_key_vals)).hexdigest()

                    if encoded_pk not in before_map:
                        added_keys += 1
                    else:
                        before_hash = before_map.pop(encoded_pk)
                        if before_hash != val_hash:
                            changed_rows += 1
        except Exception as exc:
            self._mark_unavailable_with_gap(
                tbl_name, b_schema, a_schema, b_rows, a_rows, shared_non_keys,
                CoverageGapItem(tbl_name, "UNSUPPORTED_VALUE", f"Error scanning after rows: {exc}"),
            )
            return

        removed_keys = len(before_map)

        # Clear maps
        before_map.clear()
        after_keys.clear()

        # Emit findings
        if removed_keys > 0:
            self.findings.append(
                Finding(
                    code="ROWS_REMOVED",
                    severity=FindingSeverity.ERROR.value,
                    message=f"Table '{tbl_name}' had {removed_keys} keys removed.",
                    table=tbl_name,
                    count=removed_keys,
                )
            )

        if changed_rows > 0:
            self.findings.append(
                Finding(
                    code="ROWS_CHANGED",
                    severity=FindingSeverity.WARNING.value,
                    message=f"Table '{tbl_name}' had {changed_rows} surviving rows with modified values.",
                    table=tbl_name,
                    count=changed_rows,
                )
            )

        if added_keys > 0:
            self.findings.append(
                Finding(
                    code="ROWS_ADDED",
                    severity=FindingSeverity.INFO.value,
                    message=f"Table '{tbl_name}' had {added_keys} keys added.",
                    table=tbl_name,
                    count=added_keys,
                )
            )

        self.table_comparisons.append(
            TableComparison(
                name=tbl_name,
                before_rows=b_rows,
                after_rows=a_rows,
                before_columns=[c.name for c in b_schema.columns],
                after_columns=[c.name for c in a_schema.columns],
                before_key=b_schema.pk_columns,
                after_key=a_schema.pk_columns,
                shared_value_columns=shared_non_keys,
                comparison=ComparisonKind.EXACT.value,
                removed_keys=removed_keys,
                added_keys=added_keys,
                changed_rows=changed_rows,
            )
        )

    def _mark_unavailable_with_gap(
        self,
        tbl_name: str,
        b_schema: TableSchema,
        a_schema: TableSchema,
        b_rows: int | None,
        a_rows: int | None,
        shared_non_keys: list[str],
        gap: CoverageGapItem,
    ) -> None:
        self.coverage_gaps.append(gap)
        self.table_comparisons.append(
            TableComparison(
                name=tbl_name,
                before_rows=b_rows,
                after_rows=a_rows,
                before_columns=[c.name for c in b_schema.columns],
                after_columns=[c.name for c in a_schema.columns],
                before_key=b_schema.pk_columns,
                after_key=a_schema.pk_columns,
                shared_value_columns=shared_non_keys,
                comparison=ComparisonKind.UNAVAILABLE.value,
                removed_keys=None,
                added_keys=None,
                changed_rows=None,
            )
        )

    def _check_eligibility(
        self, schema: TableSchema, row_count: int | None, side: str
    ) -> tuple[bool, CoverageGapItem | None]:
        tbl_name = schema.name
        if schema.is_virtual:
            return False, CoverageGapItem(
                table=tbl_name,
                code="VIRTUAL_TABLE",
                message=f"Table '{tbl_name}' is a virtual table, which is unsupported for exact comparison.",
            )

        for col in schema.columns:
            if col.hidden != 0:
                return False, CoverageGapItem(
                    table=tbl_name,
                    code="GENERATED_COLUMN",
                    message=f"Table '{tbl_name}' contains generated or hidden columns.",
                )

        if not schema.pk_columns:
            return False, CoverageGapItem(
                table=tbl_name,
                code="NO_PRIMARY_KEY",
                message=f"Table '{tbl_name}' has no explicit primary key.",
            )

        if row_count is not None and row_count > self.limits.max_rows_per_table:
            return False, CoverageGapItem(
                table=tbl_name,
                code="ROW_LIMIT",
                message=f"Table '{tbl_name}' row count ({row_count}) exceeds limit of {self.limits.max_rows_per_table}.",
            )

        return True, None

    def _validate_keys_scan(
        self, conn: sqlite3.Connection, schema: TableSchema
    ) -> CoverageGapItem | None:
        tbl_name = schema.name
        pk_cols = schema.pk_columns
        pk_cols_sql = ", ".join(quote_identifier(c) for c in pk_cols)
        quoted_table = quote_identifier(tbl_name)

        seen_keys: set[bytes] = set()
        cursor = conn.execute(f"SELECT {pk_cols_sql} FROM {quoted_table}")
        while True:
            self.deadline.check()
            rows = cursor.fetchmany(500)
            if not rows:
                break
            for row in rows:
                if any(v is None for v in row):
                    return CoverageGapItem(
                        tbl_name, "NULL_KEY", f"Table '{tbl_name}' contains NULL primary key values."
                    )
                enc = encode_tuple(row)
                if len(enc) > self.limits.max_encoded_key_bytes:
                    return CoverageGapItem(
                        tbl_name, "KEY_SIZE_LIMIT", f"Table '{tbl_name}' key exceeds 1,024 bytes."
                    )
                if enc in seen_keys:
                    return CoverageGapItem(
                        tbl_name, "AMBIGUOUS_KEY", f"Table '{tbl_name}' contains duplicate keys."
                    )
                seen_keys.add(enc)
        return None

    def _compare_schema_objects(self) -> None:
        all_objects = set(self.before_inv.schema_objects.keys()) | set(self.after_inv.schema_objects.keys())

        for obj_key in sorted(all_objects):
            self.deadline.check()
            obj_type, obj_name = obj_key

            in_b = obj_key in self.before_inv.schema_objects
            in_a = obj_key in self.after_inv.schema_objects

            if in_b and not in_a:
                self.findings.append(
                    Finding(
                        code="SCHEMA_OBJECT_REMOVED",
                        severity=FindingSeverity.WARNING.value,
                        message=f"{obj_type.capitalize()} '{obj_name}' was removed.",
                        object=FindingObject(kind=obj_type, name=obj_name),
                    )
                )
            elif not in_b and in_a:
                self.findings.append(
                    Finding(
                        code="SCHEMA_OBJECT_ADDED",
                        severity=FindingSeverity.INFO.value,
                        message=f"{obj_type.capitalize()} '{obj_name}' was added.",
                        object=FindingObject(kind=obj_type, name=obj_name),
                    )
                )
            else:
                b_obj = self.before_inv.schema_objects[obj_key]
                a_obj = self.after_inv.schema_objects[obj_key]
                if b_obj.sql != a_obj.sql:
                    self.findings.append(
                        Finding(
                            code="SCHEMA_OBJECT_CHANGED",
                            severity=FindingSeverity.WARNING.value,
                            message=f"{obj_type.capitalize()} '{obj_name}' definition SQL changed.",
                            object=FindingObject(kind=obj_type, name=obj_name),
                        )
                    )


def compare_databases(
    before_conn: sqlite3.Connection,
    after_conn: sqlite3.Connection,
    before_inv: DatabaseInventory,
    after_inv: DatabaseInventory,
    limits: Limits,
    deadline: Deadline,
) -> tuple[list[TableComparison], list[Finding], list[CoverageGapItem], CoverageStatus]:
    """Run database comparison and generate metrics, findings, and coverage gaps."""
    comparator = DatabaseComparator(
        before_conn, after_conn, before_inv, after_inv, limits, deadline
    )
    return comparator.compare()
