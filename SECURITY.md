# Security Policy

## Trusted Input Assumption

Raxo Rehearse is a local developer tool and CI utility designed to run in developer workstations and trusted build pipelines.

- **No Hostile Code Sandbox:** Rehearse's SQL authorizers and transaction wrappers protect against accidental external operations (such as `ATTACH`, `VACUUM INTO`, or dangerous extension functions). However, it is not an operating system sandbox and must not be used to execute untrusted or adversarial SQL or database files.
- **Trusted Snapshots:** Run rehearsals only on snapshots and migration files originating from trusted projects.

## Data Privacy in Reports

`report.json` and `report.html` are engineered to prevent unintentional data leakage:
- Raw SQL definitions and queries are omitted.
- Database records, individual cell values, primary keys, and per-row hashes are omitted.
- Absolute filesystem paths are stripped.

## Reporting Security Issues

If you discover a security vulnerability in Raxo Rehearse, please report it privately via GitHub Security Advisories on the repository rather than filing a public issue.

Do not include real application database files, confidential credentials, or customer data in any issue report or reproduction.
