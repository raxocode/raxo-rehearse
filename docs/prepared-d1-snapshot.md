# Optional Prepared Snapshot from Cloudflare D1

> **Status:** Documented workflow; not exercised or integrated in v0.1 automated test suite.

Raxo Rehearse executes locally against standalone SQLite databases. It does not connect directly to Cloudflare D1 or invoke Wrangler commands.

If you use Cloudflare D1, you can export a staging or snapshot database and convert it to a standalone SQLite database prior to running Rehearse.

## Export and Preparation Steps

1. **Export D1 Database to SQL:**
   Using the Cloudflare Wrangler CLI, export your staging database to a SQL dump:
   ```bash
   npx wrangler d1 export STAGING_DB --remote --output=database.sql
   ```
   *(Replace `STAGING_DB` with your configured database binding).*

2. **Import SQL into a Fresh SQLite Database:**
   Using the official SQLite command-line tool, import the export into a fresh, closed SQLite database:
   ```bash
   sqlite3 prepared-snapshot.sqlite ".read database.sql"
   ```

3. **Validate and Rehearse:**
   Ensure the database is closed and has no remaining `-wal` or `-shm` sidecar files:
   ```bash
   raxorehearse check \
     --database prepared-snapshot.sqlite \
     --migration migrations/pending.sql \
     --out prepared-d1-review
   ```

## Runtime Considerations & Differences

- **No Parity Guarantee:** D1 provides its own execution limits, transaction batching semantics, and cloud machinery. A successful rehearsal on a local SQLite snapshot does not guarantee identical execution in D1.
- **Separate Staging Validation:** Always validate critical database migrations in a dedicated disposable Wrangler/D1 staging environment before applying to production.
- **Sensitive Data:** Never commit raw production exports or customer database snapshots to version control or public CI artifacts.
