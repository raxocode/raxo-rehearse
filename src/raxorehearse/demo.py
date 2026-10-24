"""Demo orchestration using authoritative synthetic fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path

from raxorehearse.demo_data import (
    BAD_SQL,
    CHECKS_JSON,
    SEED_SQL,
)
from raxorehearse.models import RunOptions, RunResult


def execute_demo(options: RunOptions) -> RunResult:
    """Run rehearsal against synthetic demo fixtures.

    Creates temporary seed database, bad migration, and checks file, then calls the standard rehearsal service.
    Expected outcome: REVIEW, exit 10.
    """
    from raxorehearse.service import run_rehearsal

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        seed_path = temp_dir / "seed.sqlite"

        # Create seed database using executescript (trusted fixture creation)
        import sqlite3

        conn = sqlite3.connect(str(seed_path))
        try:
            conn.executescript(SEED_SQL)
            conn.commit()
        finally:
            conn.close()

        # Create migration and checks files
        mig_path = temp_dir / "bad.sql"
        mig_path.write_text(BAD_SQL, encoding="utf-8")

        checks_path = temp_dir / "checks.json"
        checks_path.write_text(CHECKS_JSON, encoding="utf-8")

        demo_options = RunOptions(
            database=seed_path,
            migrations=[mig_path],
            out=options.out,
            checks=checks_path,
            fail_on="warning",
            timeout=options.timeout,
            is_demo=True,
            limits=options.limits,
        )

        return run_rehearsal(demo_options)
