# Contributing to Raxo Rehearse

Thank you for your interest in contributing to Raxo Rehearse.

## Development Setup

Requirements:
- Python 3.11 or newer.
- SQLite 3.37.0 or newer.

```bash
git clone https://github.com/raxocode/raxo-rehearse.git
cd raxo-rehearse
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Running Tests

Run the full pytest suite:

```bash
python -m pytest -q
```

Build the distribution wheel and compile bytecode:

```bash
python -m build
python -m compileall -q src
```

## Design Principles

1. **Zero Runtime Dependencies:** `raxorehearse` relies exclusively on the Python standard library (`sqlite3`, `argparse`, `dataclasses`, `pathlib`, `hashlib`, `json`, `html`, `struct`, `tempfile`).
2. **Read-Only Source Guarantee:** The input database is opened exclusively with `?mode=ro&immutable=1`. All migrations execute only on disposable working copies.
3. **No Mocks in Core Testing:** Core engine and integration tests run against real temporary SQLite databases and actual migration SQL.
4. **Data Privacy:** Sensitive values, raw SQL text, filesystem paths, and per-row hashes must never be serialized to public reports.
5. **Deterministic Statuses & Exits:** Results must follow strict precedence: `ERROR` (20) > `INCOMPLETE` (20) > `REVIEW` (10) > `PASS` (0).

## Submitting Issues and Reproductions

When reporting a bug, please include:
- Operating system and Python / SQLite versions.
- A minimal, reproducible SQL fixture with fictional data.
- Expected versus actual findings and exit codes.
- Do not upload real or confidential application snapshots.
