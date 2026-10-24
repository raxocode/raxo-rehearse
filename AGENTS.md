# Raxo Rehearse implementation rules

This repository builds Raxo Rehearse, a local SQLite migration rehearsal CLI. Read the complete build specification before implementing. If the documents are at the root, read them there; if moved, read `docs/build/`. Keep this file at the repository root.

## Required reading

1. `00_START_HERE.md`
2. `01_PRODUCT_CONTRACT.md`
3. `02_ENGINE_DESIGN.md`
4. `03_REPORT_CONTRACT.md`
5. `04_BUILD_STEPS.md`
6. `05_FIXTURES_AND_TESTS.md`
7. `06_GITHUB_RELEASE.md`
8. `07_WORKFLOWS_AND_SOURCES.md`

The product contract owns behavior; the report contract owns serialization; the engine design owns module/algorithm choices. The build plan is implementation order. Do not invent conflicting CLI flags, exit codes, schema fields, or fallback modes.

## Execution

- Build the real tool through all phases; do not stop at a plan, scaffold, or frontend mockup.
- Use Python 3.11-compatible standard-library runtime code. Runtime dependencies are empty.
- Keep CLI parsing, copying, migration execution, comparison, checks, and reports in focused modules.
- Only disposable working databases may be migrated. The source connection is read-only and all temporary files are cleaned up.
- Do not use `executescript` in the migration runner or split scripts on semicolons naively.
- Guard migration SQL and read-only checks; never advertise the process as a hostile-code sandbox.
- Compare actual stable keys and shared-field hashes; no row-count-only success or silent sampling.
- Treat unavailable measurements as null and missing coverage as incomplete. Never turn operational failures into success.
- Keep SQL text, row values, keys, full paths, copied databases, and per-row hashes out of public reports.
- Use fictional fixtures for all public examples. Do not request or retrieve production credentials or customer databases to complete this repository.
- The demo must call the same engine and produce actual measured results. Its expected exit is 10.
- No hosted service, React frontend, cloud deployment, LLM, telemetry, remote apply command, or extra database adapter in v0.1.

## Verification

Run the meaningful behavioral tests and distribution checks required by the pack. Do not weaken an assertion, skip a requirement, or hard-code a fixture result to obtain a green run. If the environment prevents a required check, record the precise limitation without claiming it passed.

Update `BUILD_STATUS.md` at phase boundaries. Include completed behavior, commands/results, remaining failures, and the next task. Keep actual implementation and documentation aligned.

When the work is complete, report the finished behavior, the tests actually executed, how to run the demo, and any material limitations. Prepare a local repository; do not publish packages, create a remote repository, or push releases without a separate user instruction.
