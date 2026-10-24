# Limitations and Scope — Raxo Rehearse v0.1

This document outlines the architectural and operational boundaries of Raxo Rehearse v0.1.

## 1. Explicit Keys Required for Row-Level Diffing
Rehearse compares records using explicit, stable primary keys (single-column or composite).
- Tables without explicit primary keys are inventoried for schema and row count changes, but their record diff is marked `UNAVAILABLE` with coverage gap `NO_PRIMARY_KEY`.
- If a migration alters the column composition or declared types of a primary key, Rehearse marks row comparison as `UNAVAILABLE` with code `KEY_DEFINITION_CHANGED`. Rehearse does not guess key rename mappings.

## 2. Final-State Comparison Semantics
Rehearse is a state comparison engine, not an event-sourced audit log.
- It observes the final state of the database after all migration files have completed compared against the initial snapshot.
- An intermediate DELETE followed by an INSERT of the same primary key with identical column values results in 0 net removed and 0 net added keys.

## 3. Generated Columns and Virtual Tables
- **Generated Columns:** Tables containing stored or virtual generated columns are inventoried, but exact row comparison is marked `UNAVAILABLE` (`GENERATED_COLUMN`).
- **Virtual Tables:** Virtual tables (such as FTS5 or RTree) and their underlying SQLite shadow tables cannot be safely diffed with standard table semantics and are classified as `VIRTUAL_TABLE` gaps.

## 4. Constraint Interpretation
Rehearse verifies constraint consistency through `PRAGMA quick_check` and `PRAGMA foreign_key_check`.
- It validates that the observed snapshot data is valid under SQLite constraint rules.
- It does not semantically diff SQL expressions in `CHECK`, `COLLATE`, or complex table options beyond reporting normalized SQL definition changes via `TABLE_DEFINITION_CHANGED`.

## 5. Resource Ceilings
Rehearse operates with bounded memory and execution limits:
- Maximum input snapshot size: 256 MiB.
- Maximum working database size: 512 MiB (capped via `PRAGMA max_page_count`).
- Maximum tables per snapshot: 100.
- Maximum rows per table: 100,000; total database rows: 1,000,000.
- Maximum encoded composite key length: 1,024 bytes.
- Maximum migration sequence: 20 files, 2 MiB combined, 2,000 statements.
- Maximum aggregate checks: 50 checks, 256 KiB file size, 16 KiB per query.

Exceeding a limit produces an explicit `INCOMPLETE` or `ERROR` exit without silent sampling.

## 6. Cooperative Execution Timeout
The `--timeout` flag (1–600 seconds, default 60) establishes a cooperative execution budget. Rehearse checks this deadline using SQLite VM progress callbacks and Python batch loops. It is not an operating-system hard interrupt for blocking system calls.

## 7. Cloudflare D1 and Alternative Runtimes
Rehearse runs on standard SQLite. It does not emulate Cloudflare D1's worker environment, HTTP batch API, or distributed storage behavior. See [prepared-d1-snapshot.md](prepared-d1-snapshot.md) for details on working with exported D1 data.
