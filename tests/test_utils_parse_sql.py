import pytest

from datajoint.utils import parse_sql


def test_parse_sql_with_trailing_delimiter(tmp_path):
    sql_file = tmp_path / "script.sql"
    sql_file.write_text(
        """
        -- comment should be ignored
        CREATE TABLE t (id INT);
        INSERT INTO t VALUES (1);
        """
    )
    statements = list(parse_sql(sql_file))
    assert statements == [
        "CREATE TABLE t (id INT);",
        "INSERT INTO t VALUES (1);",
    ]


def test_parse_sql_without_trailing_delimiter(tmp_path):
    sql_file = tmp_path / "script.sql"
    sql_file.write_text(
        """
        CREATE TABLE t (id INT);
        INSERT INTO t VALUES (1)
        """
    )
    statements = list(parse_sql(sql_file))
    assert statements == [
        "CREATE TABLE t (id INT);",
        "INSERT INTO t VALUES (1)",
    ]
