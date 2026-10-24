# Build Status - Raxo Rehearse v0.1

Implementation tracking according to `04_BUILD_STEPS.md`.

## Summary
- **Current Phase**: Phase 0 — Installable package and fixtures
- **Environment**: Python 3.12.14, SQLite 3.40.1, Linux x86_64

## Phase Status

| Phase | Description | Status | Commands Run & Evidence |
|---|---|---|---|
| Phase 0 | Installable package and fixtures | Complete | `pip install -e ".[dev]"`, `raxorehearse --version`, `pytest -q`: 2 passed; T01 seed verified (15 users, 12 profiles, 24 work_samples, 0 FK errors). |
| Phase 1 | Input handling and isolated copies | Complete | `inputs.py`, `copies.py`, `sql_statements.py` implemented. Tests for sidecars (T27), source preservation (T28), output rejection (T36), corrupt/FK preflight (T26), statement parsing (T17-T20): 13 passed. |
| Phase 2 | Real SQL execution | Complete | `sql_guard.py`, `migrate.py` implemented. Transaction wrapper, authorizer, per-file rollback (T21), ordered sequence (T22), transaction escape denial (T23), external effects denial (T24), deferred FK handling (T25), good/bad/cascade fixtures verified: 23 passed. |
| Phase 3 | Observed before/after impact | Complete | `inspect_db.py`, `compare.py` implemented. Typed binary encoding (T13), good migration (T02), bad migration metrics (T03), cascade rebuild (T04), non-key update (T05), composite PK / WITHOUT ROWID (T09), NO_PRIMARY_KEY gap (T10), KEY_DEFINITION_CHANGED (T11), NULL_KEY (T12), KEY_SIZE_LIMIT (T14), GENERATED_COLUMN (T15): 34 passed. |
| Phase 4 | Aggregate checks and final outcomes | Complete | `checks.py` implemented. Strict JSON validation, duplicate-key rejection, unique ASCII IDs (T33), read-only authorizer and query contract (T31-T32), Fixture D evaluation with good (12->12, null->0) and bad (12->9 CHECK_FAILED, null->0): 38 passed. |
| Phase 5 | Public JSON and polished HTML | Complete | `report_json.py`, `report_html.py`, `service.py`, `demo.py` implemented. HTML escaping (T37), privacy/no secret leakage (T38), failure JSON (T39), deterministic report ordering (T40): 42 passed. |
| Phase 6 | Complete user workflow | Complete | Subprocess tests in `test_cli.py` (T41 demo exits 10 with exact metrics, check with good SQL exits 0, malformed migration exits 20, entry point verified). Total 46 passed. Manual demo run verified. |
| Phase 7 | Repository readiness | Complete | `docs/demo-report.html` generated from live engine run. `README.md`, `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/limitations.md`, `docs/prepared-d1-snapshot.md`, `.gitignore`, CI workflow created. `python -m build` built wheel and sdist in `dist/`. Fresh isolated virtualenv outside checkout successfully installed wheel and ran `raxorehearse --version`, `--help`, and `demo` (exit 10). |

## Final Status
All 8 phases (Phase 0 through Phase 7) are complete and validated. Zero failures remaining. Package distribution wheel and sdist are built in `dist/`. Ready for local review and deployment.
