"""Complete SQL statement splitting with quoting state and line tracking."""

from __future__ import annotations

import sqlite3
from raxorehearse.models import InputError, SqlStatement


def split_statements(sql: str, filename: str = "<migration>") -> list[SqlStatement]:
    """Split SQL text into complete statements.

    Maintains lexical states for:
    - single-quoted strings ('...', with '' escaping)
    - double-quoted identifiers ("...", with "" escaping)
    - backtick identifiers (`...`)
    - bracket identifiers ([...])
    - line comments (-- to newline/EOF)
    - block comments (/* ... */)

    Validates statement completeness with sqlite3.complete_statement().
    Tracks physical 1-indexed line numbers of the first non-comment/non-whitespace token.
    Permits the final statement to lack a trailing semicolon if valid with synthetic ';'.
    Rejects SQLite CLI dot commands and unterminated strings/comments.
    """
    statements: list[SqlStatement] = []
    n = len(sql)
    i = 0
    current_line = 1

    stmt_start_idx = 0
    first_token_line: int | None = None
    first_token_char_idx: int | None = None
    has_non_comment_tokens = False

    while i < n:
        ch = sql[i]

        # Check for dot commands at start of a line
        if ch == "." and (i == 0 or sql[i - 1] == "\n"):
            # Look ahead to see if it's a CLI dot command (e.g. .read, .mode)
            rest_of_line = sql[i:].split("\n", 1)[0].strip()
            # If it starts with .letter (e.g. .read), reject it
            if len(rest_of_line) > 1 and rest_of_line[1].isalpha():
                raise InputError(
                    f"SQLite CLI dot command '{rest_of_line}' in {filename}:{current_line} is not supported."
                )

        # Handle whitespace
        if ch == "\n":
            current_line += 1
            i += 1
            continue
        elif ch.isspace():
            i += 1
            continue

        # Line comment: --
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            continue

        # Block comment: /* ... */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            comment_start_line = current_line
            i += 2
            closed = False
            while i < n:
                if sql[i] == "\n":
                    current_line += 1
                elif sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    i += 2
                    closed = True
                    break
                i += 1
            if not closed:
                raise InputError(
                    f"Unterminated block comment starting at line {comment_start_line} in {filename}."
                )
            continue

        # If we reach here, we found a non-comment, non-whitespace token
        if first_token_line is None:
            first_token_line = current_line
            first_token_char_idx = i
        has_non_comment_tokens = True

        # Single-quoted string: '...'
        if ch == "'":
            str_start_line = current_line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    current_line += 1
                elif sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        # Doubled quote
                        i += 2
                        continue
                    else:
                        i += 1
                        closed = True
                        break
                i += 1
            if not closed:
                raise InputError(
                    f"Unterminated string literal starting at line {str_start_line} in {filename}."
                )
            continue

        # Double-quoted identifier: "..."
        if ch == '"':
            id_start_line = current_line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    current_line += 1
                elif sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    else:
                        i += 1
                        closed = True
                        break
                i += 1
            if not closed:
                raise InputError(
                    f"Unterminated double-quoted identifier starting at line {id_start_line} in {filename}."
                )
            continue

        # Backtick identifier: `...`
        if ch == "`":
            bt_start_line = current_line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    current_line += 1
                elif sql[i] == "`":
                    if i + 1 < n and sql[i + 1] == "`":
                        i += 2
                        continue
                    else:
                        i += 1
                        closed = True
                        break
                i += 1
            if not closed:
                raise InputError(
                    f"Unterminated backtick identifier starting at line {bt_start_line} in {filename}."
                )
            continue

        # Bracket identifier: [...]
        if ch == "[":
            bk_start_line = current_line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    current_line += 1
                elif sql[i] == "]":
                    if i + 1 < n and sql[i + 1] == "]":
                        i += 2
                        continue
                    else:
                        i += 1
                        closed = True
                        break
                i += 1
            if not closed:
                raise InputError(
                    f"Unterminated bracket identifier starting at line {bk_start_line} in {filename}."
                )
            continue

        # Semicolon in normal code
        if ch == ";":
            start_pos = first_token_char_idx if first_token_char_idx is not None else stmt_start_idx
            candidate = sql[start_pos : i + 1]
            if sqlite3.complete_statement(candidate):
                clean_sql = candidate.strip()
                # Ensure it's not just a bare semicolon
                if clean_sql != ";" and has_non_comment_tokens:
                    statements.append(
                        SqlStatement(
                            index=len(statements) + 1,
                            line=first_token_line if first_token_line is not None else current_line,
                            sql=clean_sql,
                        )
                    )
                stmt_start_idx = i + 1
                first_token_line = None
                first_token_char_idx = None
                has_non_comment_tokens = False
            i += 1
            continue

        # Other normal characters
        i += 1

    # End of file reached. Check if remaining text has a statement
    start_pos = first_token_char_idx if first_token_char_idx is not None else stmt_start_idx
    remaining = sql[start_pos:].strip()
    if remaining and has_non_comment_tokens:
        # Check if complete with synthetic trailing semicolon
        synthetic = remaining + "\n;"
        if sqlite3.complete_statement(synthetic):
            statements.append(
                SqlStatement(
                    index=len(statements) + 1,
                    line=first_token_line if first_token_line is not None else current_line,
                    sql=remaining,
                )
            )
        else:
            raise InputError(
                f"Incomplete SQL statement at end of {filename} (line {first_token_line or current_line})."
            )

    return statements
