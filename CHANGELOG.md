# Changelog

All notable changes to Raxo Rehearse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-24

### Added
- Core rehearsal CLI with `demo` and `check` subcommands (`raxorehearse` and `python -m raxorehearse`).
- Read-only source snapshot isolation using SQLite Backup API and `?mode=ro&immutable=1`.
- Per-file transaction wrapper with migration authorizer denying `ATTACH`, `DETACH`, `SAVEPOINT`, explicit `BEGIN`/`COMMIT`, and dangerous functions.
- Exact keyed before/after comparison tracking `removed_keys`, `added_keys`, and `changed_rows` on shared columns.
- Binary typed value encoding (`N`, `I`, `R`, `T`, `B`) preventing delimiter collisions and false equality.
- Visible coverage gaps for unkeyed tables (`NO_PRIMARY_KEY`), altered keys (`KEY_DEFINITION_CHANGED`), generated columns (`GENERATED_COLUMN`), and virtual tables (`VIRTUAL_TABLE`).
- Aggregate checks with `unchanged` and `equals` expectations executed on dedicated read-only connections with `PRAGMA query_only=ON`.
- Dual reporting: machine-readable `report.json` and standalone visual `report.html` with zero external assets and full HTML escaping.
- Comprehensive test suite covering 46+ behavioral scenarios including schema drift, cascade rebuilds, and resource ceilings.
