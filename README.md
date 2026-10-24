# Raxo Rehearse

See what your SQLite migration changes before you apply it.

Rehearse runs your SQL against disposable copies of a closed database snapshot, compares the before/after records, and produces an HTML report plus JSON for CI. Your input snapshot is opened read-only.

The demo finishes with twelve profile rows—just like it started—but detects three missing original profiles, three new profiles, six missing work samples, and a removed column.

An interactive sample of the generated output is available at [docs/demo-report.html](docs/demo-report.html).

---

## Quickstart

Clone the repository and install in development mode:

```bash
git clone https://github.com/raxocode/raxo-rehearse.git
cd raxo-rehearse
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m pip install -e .
```

Run the built-in synthetic demo:

```bash
raxorehearse demo --out demo-run
```

**Exit 10 is expected:** the demo intentionally contains data loss to demonstrate detection. Open `demo-run/report.html` in your browser to inspect the visual report.

---

## Rehearsing Your Own Migrations

To rehearse your own pending migrations against a closed standalone snapshot:

```bash
raxorehearse check \
  --database snapshot.sqlite \
  --migration migrations/001_next.sql \
  --out rehearsal-run
```

You can pass multiple migration files in execution order, configure custom aggregate checks, and adjust the failure threshold:

```bash
raxorehearse check \
  --database snapshot.sqlite \
  --migration migrations/001.sql \
  --migration migrations/002.sql \
  --checks checks.json \
  --fail-on warning \
  --timeout 60 \
  --out rehearsal-run
```

> **Important:** The `--database` option requires a closed, standalone snapshot. Never run rehearsals against a live application database or a file with adjacent `-wal`, `-shm`, or `-journal` files.

---

## What Rehearse Measures

For every table, Rehearse inventories schema structure and row counts before and after migration execution. For eligible tables with explicit primary keys:

- **Removed keys (`removed_keys`):** Keys present in the baseline snapshot but absent after migration.
- **Added keys (`added_keys`):** Keys absent in baseline but present after migration.
- **Changed surviving rows (`changed_rows`):** Surviving keys whose shared, ordinary non-key column values were modified.

### Supported & Unsupported Tables
- **Supported:** Regular SQLite tables (including `WITHOUT ROWID` tables) with explicit primary keys.
- **Unsupported (partial coverage):**
  - Tables without explicit primary keys (`NO_PRIMARY_KEY`).
  - Tables with generated or hidden columns (`GENERATED_COLUMN`).
  - Tables whose primary key definition changed (`KEY_DEFINITION_CHANGED`).
  - Tables with NULL or duplicate key data (`NULL_KEY`, `AMBIGUOUS_KEY`).
  - Virtual tables and shadow objects (`VIRTUAL_TABLE`).

When unsupported tables are encountered, their row counts and schema changes remain visible, but keyed row comparisons are marked `UNAVAILABLE` with an explicit coverage gap code.

---

## Exit Codes

Rehearse produces deterministic, CI-friendly exit codes:

| Status | Exit Code | Meaning |
|---|---|---|
| `PASS` | `0` | Rehearsal completed, coverage is complete within declared scope, and no findings reach the blocking threshold (`--fail-on`). |
| `REVIEW` | `10` | Rehearsal completed with complete coverage, but at least one blocking finding was detected (e.g. lost keys, dropped column, failed check). |
| `INCOMPLETE` | `20` | Rehearsal could not complete full comparison coverage (e.g. table without primary key, deadline budget exceeded). |
| `ERROR` | `20` | Operational failure, invalid input, syntax error in migration SQL, foreign key violation, or source snapshot modified during run. |

---

## Aggregate Checks

You can provide an optional JSON configuration file specifying assertion queries that run against the snapshot:

```json
{
  "version": 1,
  "checks": [
    {
      "id": "published_profiles_preserved",
      "sql": "SELECT COUNT(*) FROM profiles WHERE status = 'published'",
      "expect": {"kind": "unchanged"}
    },
    {
      "id": "no_empty_handles",
      "sql": "SELECT COUNT(*) FROM profiles WHERE handle IS NULL OR trim(handle) = ''",
      "expect": {"kind": "equals", "value": 0}
    }
  ]
}
```

- `unchanged`: Evaluates on baseline and final databases; expects identical integer results.
- `equals`: Evaluates on the final database; expects exact match with the specified integer `value`.

See [examples/profile-app/checks.json](examples/profile-app/checks.json) for a complete example.

---

## Data Privacy & Report Contents

All reports (`report.json` and `report.html`) are designed for safe sharing and CI artifact publishing:
- **Never included:** Raw SQL text, record data values, primary key values, absolute filesystem paths, per-row hashes, or database connection strings.
- **Included metadata:** Table names, column names, record counts, check IDs, execution durations, migration basenames, and file SHA-256 fingerprints.

---

## Limits & Runtime Boundaries

- **Input database size:** Up to 256 MiB.
- **Working database size cap:** Up to 512 MiB enforced via SQLite page limits.
- **Application tables:** Up to 100 tables per snapshot.
- **Rows:** Up to 100,000 rows per table; 1,000,000 rows total across tables.
- **Key size:** Encoded composite keys up to 1,024 bytes.
- **Migrations:** Up to 20 files, 2 MiB combined UTF-8 text, 2,000 statements total.
- **Checks:** Up to 50 queries, 256 KiB file size, 16 KiB per SQL statement.

### Final-State Comparison Semantics
Rehearse performs final-state diffing. It compares records before and after the complete migration sequence. A DELETE followed by an INSERT of an identical key and identical column values within the same migration sequence produces no net change and is not distinguished from an unchanged record.

### Cloudflare D1 Boundary
Rehearse executes on standard SQLite. It is not an authenticated Cloudflare D1 runner or cloud emulator. A separate workflow for preparing snapshots from exported D1 databases is documented in [docs/prepared-d1-snapshot.md](docs/prepared-d1-snapshot.md).

For full details, see [docs/limitations.md](docs/limitations.md).

---

## Alternatives

- **[Atlas migration lint](https://atlasgo.io/versioned/lint):** Static schema analysis and migration linting across multiple database engines. Use Atlas for declarative schema management and pre-run syntax validation.
- **[migration-validator](https://github.com/CheesyChicken/migration-validator):** Validates schema drift, checksums, and row samples.
- **[Litescope](https://github.com/croc100/Litescope):** Broad administrative console for SQLite and D1 dry runs and inspection.

Raxo Rehearse focuses specifically on exact, keyed data preservation on local SQLite snapshots with zero runtime dependencies.

---

## Contributing & License

Contributions are welcome! Please review [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Licensed under the [MIT License](LICENSE). Copyright © 2026 RaxoCode.
