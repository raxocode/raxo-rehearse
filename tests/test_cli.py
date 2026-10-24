"""Subprocess end-to-end CLI acceptance tests."""

import json
import subprocess
import sys
from pathlib import Path
import pytest

from conftest import create_seed_db
from raxorehearse.demo_data import (
    BAD_SQL,
    CHECKS_JSON,
    GOOD_SQL,
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run CLI command via python -m raxorehearse."""
    cmd = [sys.executable, "-m", "raxorehearse", *args]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_t41_demo_cli(tmp_path: Path) -> None:
    """T41: demo command exits 10 and produces report.json and report.html with fixture metrics."""
    out_dir = tmp_path / "demo_out"
    res = run_cli("demo", "--out", str(out_dir))

    # Assert deliberate REVIEW exit code 10
    assert res.returncode == 10, f"Expected exit code 10, got {res.returncode}. Stderr: {res.stderr}"

    report_json_path = out_dir / "report.json"
    report_html_path = out_dir / "report.html"

    assert report_json_path.exists()
    assert report_html_path.exists()

    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert report_data["run"]["status"] == "REVIEW"
    assert report_data["run"]["exit_code"] == 10
    assert report_data["run"]["database_name"] == "seed.sqlite"

    # Verify fixture metrics in profiles
    prof_table = next(t for t in report_data["tables"] if t["name"] == "profiles")
    assert prof_table["before_rows"] == 12
    assert prof_table["after_rows"] == 12
    assert prof_table["removed_keys"] == 3
    assert prof_table["added_keys"] == 3
    assert prof_table["changed_rows"] == 0

    # Verify work_samples metrics
    ws_table = next(t for t in report_data["tables"] if t["name"] == "work_samples")
    assert ws_table["before_rows"] == 24
    assert ws_table["after_rows"] == 18
    assert ws_table["removed_keys"] == 6

    # Verify checks
    ch1 = next(c for c in report_data["checks"] if c["id"] == "published_profiles_preserved")
    assert ch1["before_value"] == 12
    assert ch1["after_value"] == 9
    assert ch1["passed"] is False

    ch2 = next(c for c in report_data["checks"] if c["id"] == "no_empty_handles")
    assert ch2["before_value"] is None
    assert ch2["after_value"] == 0
    assert ch2["passed"] is True


def test_check_good_migration(tmp_path: Path) -> None:
    """check command with good.sql exits 0 (PASS)."""
    db_path = tmp_path / "seed.sqlite"
    create_seed_db(db_path)

    mig_path = tmp_path / "good.sql"
    mig_path.write_text(GOOD_SQL, encoding="utf-8")

    out_dir = tmp_path / "good_out"
    res = run_cli(
        "check",
        "--database",
        str(db_path),
        "--migration",
        str(mig_path),
        "--out",
        str(out_dir),
    )

    assert res.returncode == 0, f"Expected exit code 0, got {res.returncode}. Stderr: {res.stderr}"
    report_json_path = out_dir / "report.json"
    assert report_json_path.exists()
    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert report_data["run"]["status"] == "PASS"


def test_check_with_malformed_migration_exits_20(tmp_path: Path) -> None:
    """check command with syntax error in migration exits 20 (ERROR)."""
    db_path = tmp_path / "seed.sqlite"
    create_seed_db(db_path)

    bad_sql_file = tmp_path / "syntax_error.sql"
    bad_sql_file.write_text("THIS IS INVALID SQL;", encoding="utf-8")

    out_dir = tmp_path / "err_out"
    res = run_cli(
        "check",
        "--database",
        str(db_path),
        "--migration",
        str(bad_sql_file),
        "--out",
        str(out_dir),
    )

    assert res.returncode == 20
    report_json_path = out_dir / "report.json"
    assert report_json_path.exists()
    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert report_data["run"]["status"] == "ERROR"
    assert report_data["run"]["exit_code"] == 20


def test_console_script_entrypoint() -> None:
    """Console entry point 'raxorehearse' works."""
    res = subprocess.run(
        ["raxorehearse", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "raxorehearse 0.1.0" in res.stdout
