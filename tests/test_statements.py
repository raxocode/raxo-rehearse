"""Tests for SQL statement splitting and scanner state tracking."""

import pytest
from raxorehearse.models import InputError
from raxorehearse.sql_statements import split_statements


def test_t17_semicolons_in_strings_and_comments() -> None:
    """T17: Semicolon inside text/comment does not split; two statements on one line both run."""
    sql = (
        "INSERT INTO t VALUES ('semi; colon', \"quoted; col\"); -- comment; here\n"
        "/* block; \n comment; */ SELECT 1; SELECT 2;"
    )
    stmts = split_statements(sql, "test.sql")
    assert len(stmts) == 3
    assert stmts[0].index == 1
    assert stmts[0].line == 1
    assert "INSERT INTO t VALUES" in stmts[0].sql
    assert stmts[1].index == 2
    assert stmts[1].line == 3
    assert stmts[1].sql == "SELECT 1;"
    assert stmts[2].index == 3
    assert stmts[2].line == 3
    assert stmts[2].sql == "SELECT 2;"


def test_t18_trigger_definition_with_semicolons() -> None:
    """T18: CREATE TRIGGER body with semicolons is one single statement."""
    sql = """
    CREATE TRIGGER tr_after_insert
    AFTER INSERT ON users
    BEGIN
        INSERT INTO audit_log (action) VALUES ('user_inserted');
        UPDATE stats SET count = count + 1 WHERE key = 'users';
    END;
    """
    stmts = split_statements(sql, "trigger.sql")
    assert len(stmts) == 1
    assert stmts[0].index == 1
    assert stmts[0].line == 2
    assert "CREATE TRIGGER" in stmts[0].sql
    assert "END;" in stmts[0].sql


def test_t19_tail_parsing_no_semicolon() -> None:
    """T19: Final statement without semicolon works; trailing comments ignored; empty/comment-only file rejected."""
    sql = "SELECT 1; SELECT 2 -- trailing comment"
    stmts = split_statements(sql, "tail.sql")
    assert len(stmts) == 2
    assert stmts[0].sql == "SELECT 1;"
    assert "SELECT 2" in stmts[1].sql

    empty_sql = "   -- only comment\n/* block */\n"
    stmts_empty = split_statements(empty_sql, "empty.sql")
    assert len(stmts_empty) == 0


def test_t20_parse_failure_unterminated() -> None:
    """T20: Unterminated string/block comment reports input error with useful line context."""
    unterminated_str = "SELECT 'hello\nworld"
    with pytest.raises(InputError) as exc_info:
        split_statements(unterminated_str, "bad_str.sql")
    assert "Unterminated string literal" in str(exc_info.value)
    assert "line 1" in str(exc_info.value)

    unterminated_comment = "SELECT 1; /* open block"
    with pytest.raises(InputError) as exc_info:
        split_statements(unterminated_comment, "bad_comment.sql")
    assert "Unterminated block comment" in str(exc_info.value)

    unterminated_bracket = "SELECT [col name from t"
    with pytest.raises(InputError) as exc_info:
        split_statements(unterminated_bracket, "bad_bracket.sql")
    assert "Unterminated bracket" in str(exc_info.value)


def test_dot_commands_rejected() -> None:
    """SQLite CLI dot commands are rejected."""
    sql = ".read other.sql\nSELECT 1;"
    with pytest.raises(InputError) as exc:
        split_statements(sql, "dot.sql")
    assert "dot command" in str(exc.value)
