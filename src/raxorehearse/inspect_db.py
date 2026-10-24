"""Database schema inventory and metadata inspection."""

from __future__ import annotations

import sqlite3
from typing import Any

from raxorehearse.models import (
    ColumnInfo,
    DatabaseInventory,
    Deadline,
    SchemaObject,
    TableSchema,
)


def quote_identifier(name: str) -> str:
    """Safely quote a SQLite identifier with doubled double-quotes."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def normalize_sql(sql: str | None) -> str | None:
    """Normalize SQL by replacing CRLF with LF and stripping exterior whitespace."""
    if sql is None:
        return None
    return sql.replace("\r\n", "\n").strip()


def inspect_database(
    connection: sqlite3.Connection, deadline: Deadline
) -> DatabaseInventory:
    """Inspect schema, tables, columns, objects, and row counts of a database."""
    deadline.check()

    tables: dict[str, TableSchema] = {}
    schema_objects: dict[tuple[str, str], SchemaObject] = {}
    excluded_engine_objects: set[tuple[str, str]] = set()
    row_counts: dict[str, int | None] = {}

    # Step 1: Use PRAGMA table_list to classify tables in schema 'main'
    # columns: schema, name, type, ncol, wr, strict
    cursor = connection.execute("PRAGMA table_list")
    table_list_rows = cursor.fetchall()

    for row in table_list_rows:
        deadline.check()
        schema_name, tbl_name, tbl_type = row[0], row[1], row[2]
        if schema_name != "main":
            continue

        # Ignore SQLite internal tables
        if tbl_name.startswith("sqlite_"):
            excluded_engine_objects.add(("table", tbl_name))
            continue

        is_view = tbl_type == "view"
        is_virtual = tbl_type == "virtual"
        is_shadow = tbl_type == "shadow"

        if is_shadow:
            excluded_engine_objects.add(("shadow", tbl_name))
            continue

        if is_view:
            # Views are schema objects, not application data tables
            continue

        # Inspect columns for this table
        columns = inspect_columns(connection, tbl_name, deadline)
        # Order PK columns by positive pk ordinal
        pk_cols = [
            c.name
            for c in sorted(
                [c for c in columns if c.pk > 0],
                key=lambda x: x.pk,
            )
        ]

        tables[tbl_name] = TableSchema(
            name=tbl_name,
            sql=None,  # Will be populated from sqlite_schema
            is_virtual=is_virtual,
            is_view=False,
            columns=columns,
            pk_columns=pk_cols,
        )

        if not is_virtual:
            try:
                cnt_row = connection.execute(
                    f"SELECT COUNT(*) FROM {quote_identifier(tbl_name)}"
                ).fetchone()
                row_counts[tbl_name] = cnt_row[0] if cnt_row else 0
            except Exception:
                row_counts[tbl_name] = None
        else:
            row_counts[tbl_name] = None

    # Step 2: Query sqlite_schema for definitions and explicit objects
    # columns: type, name, tbl_name, rootpage, sql
    schema_rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema"
    ).fetchall()

    for s_type, s_name, s_tbl_name, s_sql in schema_rows:
        deadline.check()
        norm_sql = normalize_sql(s_sql)

        if s_type == "table":
            if s_name.startswith("sqlite_"):
                excluded_engine_objects.add(("table", s_name))
                continue
            if s_name in tables:
                tables[s_name].sql = norm_sql

        elif s_type in ("index", "view", "trigger"):
            if s_name.startswith("sqlite_"):
                excluded_engine_objects.add((s_type, s_name))
                continue
            if norm_sql is None:
                # SQLite autoindex
                excluded_engine_objects.add((s_type, s_name))
                continue

            schema_objects[(s_type, s_name)] = SchemaObject(
                type=s_type,
                name=s_name,
                tbl_name=s_tbl_name,
                sql=norm_sql,
            )

    return DatabaseInventory(
        tables=tables,
        schema_objects=schema_objects,
        excluded_engine_objects=excluded_engine_objects,
        row_counts=row_counts,
    )


def inspect_columns(
    connection: sqlite3.Connection, table_name: str, deadline: Deadline
) -> list[ColumnInfo]:
    """Inspect columns of a table using PRAGMA table_xinfo."""
    deadline.check()
    # table_xinfo columns: cid, name, type, notnull, dflt_value, pk, hidden
    # Use quote_identifier for PRAGMA parameter
    quoted = quote_identifier(table_name)
    rows = connection.execute(f"PRAGMA table_xinfo({quoted})").fetchall()

    columns: list[ColumnInfo] = []
    for row in rows:
        cid = row[0]
        col_name = row[1]
        col_type = row[2] or ""
        notnull = bool(row[3])
        dflt_val = normalize_sql(row[4]) if row[4] is not None else None
        pk = row[5]
        hidden = row[6] if len(row) > 6 else 0

        columns.append(
            ColumnInfo(
                cid=cid,
                name=col_name,
                type=col_type.upper(),
                notnull=notnull,
                dflt_value=dflt_val,
                pk=pk,
                hidden=hidden,
            )
        )
    return columns
