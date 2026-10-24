"""Self-contained HTML report renderer from public report model."""

from __future__ import annotations

import html
from typing import Any


def esc(val: Any) -> str:
    """Safely escape text for HTML output."""
    if val is None:
        return "—"
    return html.escape(str(val), quote=True)


def esc_num(val: int | None) -> str:
    """Format numeric value or em dash for null."""
    if val is None:
        return '<span class="na" title="Unavailable or not applicable">—</span>'
    return f"<code>{val:,}</code>"


def render_public_report_html(report: dict[str, Any]) -> str:
    """Render the public report model into a complete, standalone HTML document."""
    run = report["run"]
    status = run["status"]
    exit_code = run["exit_code"]
    fail_on = run["fail_on"]
    coverage = report["coverage"]
    tables = report["tables"]
    findings = report["findings"]
    checks = report["checks"]
    errors = report["errors"]
    migrations = report["migrations"]

    # Status theme classes
    status_class_map = {
        "PASS": "status-pass",
        "REVIEW": "status-review",
        "INCOMPLETE": "status-incomplete",
        "ERROR": "status-error",
    }
    status_class = status_class_map.get(status, "status-error")

    # Counts by severity
    err_findings = [f for f in findings if f["severity"] == "error"]
    warn_findings = [f for f in findings if f["severity"] == "warning"]
    info_findings = [f for f in findings if f["severity"] == "info"]

    # Blocking findings based on fail_on
    if fail_on == "error":
        blocking_findings = err_findings
        remaining_findings = warn_findings + info_findings
    else:  # default "warning"
        blocking_findings = err_findings + warn_findings
        remaining_findings = info_findings

    # Check for attention lines: before_rows == after_rows, but removed_keys > 0
    attention_lines: list[str] = []
    for t in tables:
        b_rows = t.get("before_rows")
        a_rows = t.get("after_rows")
        rem_keys = t.get("removed_keys")
        if b_rows is not None and a_rows is not None and b_rows == a_rows and rem_keys and rem_keys > 0:
            attention_lines.append(
                f"<strong>{esc(t['name'])}</strong> still has {esc(b_rows)} rows; "
                f"<strong>{esc(rem_keys)} original keys are missing</strong>."
            )

    # CSS styles
    css = """
        :root {
            --bg: #F4F5F7;
            --panel: #FFFFFF;
            --ink: #142334;
            --ink-muted: #64748B;
            --border: #E2E8F0;
            --teal-bg: #E6FFFA;
            --teal-text: #0F766E;
            --teal-border: #319795;
            --amber-bg: #FFFBEB;
            --amber-text: #B45309;
            --amber-border: #D97706;
            --red-bg: #FEF2F2;
            --red-text: #B91C1C;
            --red-border: #DC2626;
            --mono: ui-monospace, SFMono-Regular, "Roboto Mono", Menlo, Consolas, monospace;
            --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            color: var(--ink);
            font-family: var(--sans);
            font-size: 15px;
            line-height: 1.5;
            padding: 2.5rem 1.5rem;
        }
        .container {
            max-width: 1100px;
            margin: 0 auto;
        }
        header {
            margin-bottom: 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .brand {
            font-weight: 700;
            font-size: 1.25rem;
            color: var(--ink);
            letter-spacing: -0.01em;
        }
        .brand span {
            color: var(--ink-muted);
            font-weight: 400;
        }
        .subtitle {
            font-size: 0.9rem;
            color: var(--ink-muted);
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.75rem;
            margin-bottom: 1.75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        h2 {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--ink);
            border-bottom: 1px solid var(--border);
            padding-bottom: 0.5rem;
        }
        h3 {
            font-size: 1rem;
            font-weight: 600;
            margin: 1rem 0 0.5rem 0;
            color: var(--ink);
        }
        /* Outcome panel */
        .outcome-panel {
            border-left: 6px solid var(--border);
        }
        .status-pass {
            border-left-color: var(--teal-border);
            background: linear-gradient(to right, #F0FDF4 0%, #FFFFFF 150px);
        }
        .status-review {
            border-left-color: var(--amber-border);
            background: linear-gradient(to right, #FFFBEB 0%, #FFFFFF 150px);
        }
        .status-incomplete, .status-error {
            border-left-color: var(--red-border);
            background: linear-gradient(to right, #FEF2F2 0%, #FFFFFF 150px);
        }
        .status-badge {
            display: inline-block;
            font-weight: 700;
            font-size: 1.1rem;
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }
        .status-pass .status-badge { background: var(--teal-bg); color: var(--teal-text); }
        .status-review .status-badge { background: var(--amber-bg); color: var(--amber-text); }
        .status-incomplete .status-badge, .status-error .status-badge { background: var(--red-bg); color: var(--red-text); }

        .meta-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
            padding-top: 1rem;
            border-top: 1px dashed var(--border);
        }
        .meta-item { font-size: 0.85rem; }
        .meta-label { color: var(--ink-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; margin-bottom: 0.2rem; }
        .meta-value { font-weight: 600; font-family: var(--mono); }

        .attention-box {
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 6px;
            padding: 1rem 1.25rem;
            margin: 1.25rem 0;
            color: #92400E;
            font-size: 0.95rem;
        }
        .attention-box p + p { margin-top: 0.5rem; }

        .explanation {
            margin-top: 0.75rem;
            font-size: 0.9rem;
            color: var(--ink-muted);
            line-height: 1.6;
        }

        /* Tables */
        .table-wrap {
            overflow-x: auto;
            margin-top: 0.75rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            text-align: left;
        }
        th, td {
            padding: 0.65rem 0.85rem;
            border-bottom: 1px solid var(--border);
        }
        th {
            background: #F8FAFC;
            color: var(--ink-muted);
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        tr:last-child td { border-bottom: none; }
        code {
            font-family: var(--mono);
            font-size: 0.85em;
            background: #F1F5F9;
            padding: 0.15rem 0.35rem;
            border-radius: 3px;
        }
        .num-col { text-align: right; }
        th.num-col { text-align: right; }
        .badge-exact { color: var(--teal-text); font-weight: 600; }
        .badge-unavail { color: var(--red-text); font-weight: 600; }
        .na { color: var(--ink-muted); }

        /* Findings list */
        .finding-list { list-style: none; margin-top: 0.75rem; }
        .finding-item {
            padding: 0.75rem 1rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 0.5rem;
            background: #FAFAFA;
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
        }
        .finding-error { border-left: 4px solid var(--red-border); background: #FFF5F5; }
        .finding-warning { border-left: 4px solid var(--amber-border); background: #FFFDF5; }
        .finding-info { border-left: 4px solid #3B82F6; background: #F8FAFC; }

        .finding-badge {
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            padding: 0.15rem 0.4rem;
            border-radius: 3px;
            font-family: var(--mono);
        }
        .finding-error .finding-badge { background: #FEE2E2; color: #991B1B; }
        .finding-warning .finding-badge { background: #FEF3C7; color: #92400E; }
        .finding-info .finding-badge { background: #E0E7FF; color: #3730A3; }

        .finding-content { flex: 1; }
        .finding-title { font-weight: 600; font-size: 0.9rem; }
        .finding-desc { color: var(--ink-muted); font-size: 0.85rem; margin-top: 0.2rem; }

        .empty-state {
            padding: 1rem;
            text-align: center;
            color: var(--ink-muted);
            font-style: italic;
            background: #F8FAFC;
            border-radius: 6px;
            border: 1px dashed var(--border);
        }

        /* Limitations */
        .limitations-list {
            padding-left: 1.25rem;
            color: var(--ink-muted);
            font-size: 0.85rem;
            line-height: 1.6;
        }
        .limitations-list li { margin-bottom: 0.4rem; }

        @media print {
            body { background: white; padding: 0; }
            .panel { box-shadow: none; border: 1px solid #ccc; break-inside: avoid; }
        }
    """

    out: list[str] = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en">')
    out.append("<head>")
    out.append('  <meta charset="UTF-8">')
    out.append('  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    out.append("  <title>Migration impact</title>")
    out.append(f"  <style>{css}</style>")
    out.append("</head>")
    out.append("<body>")
    out.append('  <div class="container">')

    # Header
    out.append("    <header>")
    out.append('      <div>')
    out.append('        <div class="brand">RaxoCode <span>/ Rehearse</span></div>')
    out.append('        <div class="subtitle">SQLite Migration Rehearsal Report</div>')
    out.append("      </div>")
    out.append(f'      <div><code>{esc(run["started_at"])}</code></div>')
    out.append("    </header>")

    # Section 1: Outcome & Coverage Panel
    out.append(f'    <section class="panel outcome-panel {status_class}">')
    out.append(f'      <div class="status-badge">{esc(status)} (Exit {exit_code})</div>')
    out.append('      <p class="explanation">')
    if status == "PASS":
        out.append(
            "No blocking findings in this rehearsal. All declared tables compared with exact key verification, "
            "and all aggregate checks succeeded."
        )
    elif status == "REVIEW":
        out.append(
            "One or more findings require review before applying migrations. "
            "Rehearsal completed with complete coverage, but detected potential record loss or schema drift."
        )
    elif status == "INCOMPLETE":
        out.append(
            "Rehearsal could not complete full comparison coverage within declared v0.1 scope. "
            "Some tables may lack explicit keys, use unsupported features, or exceeded limits."
        )
    else:  # ERROR
        out.append(
            "Rehearsal encountered an operational error, migration syntax error, or integrity check failure."
        )
    out.append("</p>")

    # Attention line if applicable
    if attention_lines:
        out.append('      <div class="attention-box">')
        for att in attention_lines:
            out.append(f"        <p>{att}</p>")
        out.append("      </div>")

    # Meta grid
    out.append('      <div class="meta-grid">')
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Coverage Status</div>')
    out.append(f'          <div class="meta-value">{esc(coverage["status"])}</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Tables Compared</div>')
    out.append(
        f'          <div class="meta-value">{esc(coverage["tables_compared"])} / {esc(coverage["tables_total"])}</div>'
    )
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Findings</div>')
    out.append(
        f'          <div class="meta-value">{len(err_findings)} err · {len(warn_findings)} warn · {len(info_findings)} info</div>'
    )
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Duration</div>')
    out.append(f'          <div class="meta-value">{esc(run["duration_ms"])} ms</div>')
    out.append("        </div>")
    out.append("      </div>")
    out.append("    </section>")

    # Section 2: Table Impact
    out.append('    <section class="panel">')
    out.append("      <h2>1. Table impact</h2>")
    out.append('      <div class="table-wrap">')
    out.append("        <table>")
    out.append("          <thead>")
    out.append("            <tr>")
    out.append("              <th>Table</th>")
    out.append('              <th class="num-col">Before Rows</th>')
    out.append('              <th class="num-col">After Rows</th>')
    out.append('              <th class="num-col">Removed Keys</th>')
    out.append('              <th class="num-col">Added Keys</th>')
    out.append('              <th class="num-col">Changed Rows</th>')
    out.append("              <th>Comparison</th>")
    out.append("            </tr>")
    out.append("          </thead>")
    out.append("          <tbody>")
    for t in tables:
        comp_badge = (
            '<span class="badge-exact">EXACT</span>'
            if t["comparison"] == "EXACT"
            else '<span class="badge-unavail">UNAVAILABLE</span>'
        )
        out.append("            <tr>")
        out.append(f"              <td><code>{esc(t['name'])}</code></td>")
        out.append(f'              <td class="num-col">{esc_num(t["before_rows"])}</td>')
        out.append(f'              <td class="num-col">{esc_num(t["after_rows"])}</td>')
        out.append(f'              <td class="num-col">{esc_num(t["removed_keys"])}</td>')
        out.append(f'              <td class="num-col">{esc_num(t["added_keys"])}</td>')
        out.append(f'              <td class="num-col">{esc_num(t["changed_rows"])}</td>')
        out.append(f"              <td>{comp_badge}</td>")
        out.append("            </tr>")
    out.append("          </tbody>")
    out.append("        </table>")
    out.append("      </div>")
    out.append("    </section>")

    # Section 3: Findings
    out.append('    <section class="panel">')
    out.append("      <h2>2. Findings</h2>")

    out.append("      <h3>Blocking findings</h3>")
    if blocking_findings:
        out.append('      <ul class="finding-list">')
        for f in blocking_findings:
            sev = f["severity"]
            out.append(f'        <li class="finding-item finding-{sev}">')
            out.append(f'          <div class="finding-badge">{esc(f["code"])}</div>')
            out.append('          <div class="finding-content">')
            out.append(f'            <div class="finding-title">{esc(f["message"])}</div>')
            if f.get("count") is not None:
                out.append(f'            <div class="finding-desc">Affected count: {f["count"]}</div>')
            out.append("          </div>")
            out.append("        </li>")
        out.append("      </ul>")
    else:
        out.append('      <div class="empty-state">No blocking findings for chosen threshold.</div>')

    out.append("      <h3>Remaining findings</h3>")
    if remaining_findings:
        out.append('      <ul class="finding-list">')
        for f in remaining_findings:
            sev = f["severity"]
            out.append(f'        <li class="finding-item finding-{sev}">')
            out.append(f'          <div class="finding-badge">{esc(f["code"])}</div>')
            out.append('          <div class="finding-content">')
            out.append(f'            <div class="finding-title">{esc(f["message"])}</div>')
            out.append("          </div>")
            out.append("        </li>")
        out.append("      </ul>")
    else:
        out.append('      <div class="empty-state">No remaining informational findings.</div>')
    out.append("    </section>")

    # Section 4: Aggregate Checks
    out.append('    <section class="panel">')
    out.append("      <h2>3. Aggregate checks</h2>")
    if checks:
        out.append('      <div class="table-wrap">')
        out.append("        <table>")
        out.append("          <thead>")
        out.append("            <tr>")
        out.append("              <th>Check ID</th>")
        out.append("              <th>Expectation</th>")
        out.append('              <th class="num-col">Baseline</th>')
        out.append('              <th class="num-col">Final</th>')
        out.append("              <th>Outcome</th>")
        out.append("            </tr>")
        out.append("          </thead>")
        out.append("          <tbody>")
        for c in checks:
            kind = c["expect"].get("kind")
            exp_text = f"unchanged" if kind == "unchanged" else f"equals {c['expect'].get('value')}"
            if c["passed"] is True:
                out_badge = '<span class="badge-exact">PASS</span>'
            elif c["passed"] is False:
                out_badge = '<span class="badge-unavail">FAIL</span>'
            else:
                out_badge = '<span class="na">NOT RUN</span>'

            out.append("            <tr>")
            out.append(f"              <td><code>{esc(c['id'])}</code></td>")
            out.append(f"              <td><code>{esc(exp_text)}</code></td>")
            out.append(f'              <td class="num-col">{esc_num(c["before_value"])}</td>')
            out.append(f'              <td class="num-col">{esc_num(c["after_value"])}</td>')
            out.append(f"              <td>{out_badge}</td>")
            out.append("            </tr>")
        out.append("          </tbody>")
        out.append("        </table>")
        out.append("      </div>")
    else:
        out.append('      <div class="empty-state">No aggregate checks configured for this run.</div>')
    out.append("    </section>")

    # Section 5: Coverage Gaps and Errors
    gaps = coverage.get("gaps", [])
    if gaps or errors:
        out.append('    <section class="panel">')
        out.append("      <h2>4. Coverage gaps and errors</h2>")
        if gaps:
            out.append("        <h3>Coverage gaps</h3>")
            out.append('        <ul class="finding-list">')
            for g in gaps:
                tbl_txt = f"[{esc(g['table'])}] " if g.get("table") else ""
                out.append('          <li class="finding-item finding-warning">')
                out.append(f'            <div class="finding-badge">{esc(g["code"])}</div>')
                out.append('            <div class="finding-content">')
                out.append(f'              <div class="finding-title">{tbl_txt}{esc(g["message"])}</div>')
                out.append("            </div>")
                out.append("          </li>")
            out.append("        </ul>")

        if errors:
            out.append("        <h3>Execution errors</h3>")
            out.append('        <ul class="finding-list">')
            for e in errors:
                ctx_parts = []
                if e.get("migration"):
                    ctx_parts.append(f"migration: {e['migration']}")
                if e.get("line"):
                    ctx_parts.append(f"line: {e['line']}")
                ctx_txt = f" ({', '.join(ctx_parts)})" if ctx_parts else ""
                out.append('          <li class="finding-item finding-error">')
                out.append(f'            <div class="finding-badge">{esc(e["code"])}</div>')
                out.append('            <div class="finding-content">')
                out.append(f'              <div class="finding-title">{esc(e["message"])}{esc(ctx_txt)}</div>')
                out.append("            </div>")
                out.append("          </li>")
            out.append("        </ul>")
        out.append("    </section>")

    # Section 6: Reproducibility Metadata
    out.append('    <section class="panel">')
    out.append("      <h2>5. Reproducibility metadata</h2>")
    out.append('      <div class="meta-grid">')
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Input Database</div>')
    out.append(f'          <div class="meta-value">{esc(run["database_name"])}</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Source SHA-256</div>')
    out.append(f'          <div class="meta-value">{esc(run["source_sha256"][:16])}…</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Source Unchanged</div>')
    out.append(f'          <div class="meta-value">{esc(run["source_unchanged"])}</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Python Version</div>')
    out.append(f'          <div class="meta-value">{esc(run["python_version"].split()[0])}</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">SQLite Version</div>')
    out.append(f'          <div class="meta-value">{esc(run["sqlite_version"])}</div>')
    out.append("        </div>")
    out.append('        <div class="meta-item">')
    out.append('          <div class="meta-label">Comparison Scope</div>')
    out.append(f'          <div class="meta-value">{esc(run["comparison_scope"])}</div>')
    out.append("        </div>")
    out.append("      </div>")

    out.append('      <h3 style="margin-top: 1.5rem;">Migration sequence</h3>')
    out.append('      <div class="table-wrap">')
    out.append("        <table>")
    out.append("          <thead>")
    out.append("            <tr>")
    out.append("              <th>#</th>")
    out.append("              <th>Migration File</th>")
    out.append("              <th>SHA-256</th>")
    out.append('              <th class="num-col">Statements</th>')
    out.append("              <th>Execution</th>")
    out.append("            </tr>")
    out.append("          </thead>")
    out.append("          <tbody>")
    for idx, m in enumerate(migrations, 1):
        out.append("            <tr>")
        out.append(f"              <td>{idx}</td>")
        out.append(f"              <td><code>{esc(m['name'])}</code></td>")
        out.append(f"              <td><code>{esc(m['sha256'][:16])}…</code></td>")
        out.append(f'              <td class="num-col">{esc_num(m["statement_count"])}</td>')
        out.append(f"              <td><code>{esc(m['execution'])}</code></td>")
        out.append("            </tr>")
    out.append("          </tbody>")
    out.append("        </table>")
    out.append("      </div>")
    out.append("    </section>")

    # Section 7: Limitations
    out.append('    <section class="panel">')
    out.append("      <h2>6. Limitations & scope</h2>")
    out.append('      <ul class="limitations-list">')
    out.append(
        "        <li><strong>Final-state comparison:</strong> Measures the state difference before and after migrations. Intermediate states or delete-reinserts of identical keys/values are not tracked as distinct events.</li>"
    )
    out.append(
        "        <li><strong>Untested application code:</strong> Rehearsal executes SQL against disposable copies; it does not exercise application queries, ORM mapping hooks, or runtime transactions.</li>"
    )
    out.append(
        "        <li><strong>Declared scope:</strong> Tables without explicit primary keys, virtual tables, generated columns, and tables exceeding resource ceilings yield visible coverage gaps.</li>"
    )
    out.append(
        "        <li><strong>SQLite runtime:</strong> Rehearsal uses the local SQLite engine. It does not provide Cloudflare D1 or cloud runtime parity guarantees.</li>"
    )
    out.append("      </ul>")
    out.append("    </section>")

    out.append("  </div>")
    out.append("</body>")
    out.append("</html>\n")

    return "\n".join(out)
