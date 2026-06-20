"""Tests for csv_utils — CSV/TSV parsing and generation."""

import pytest

from tools.csv_utils import parse, generate


class TestParse:
    @pytest.mark.parametrize("text,delimiter,headers,count", [
        ("name,age,city\nalice,30,nyc\nbob,25,sf\n", "comma", ["name", "age", "city"], 2),
        ("name\tage\tcity\nalice\t30\tnyc\n", "tab", ["name", "age", "city"], 1),
        ("value\na\nb\nc\n", "comma", ["value"], 3),
    ])
    def test_parse_basic(self, text: str, delimiter: str, headers: list, count: int) -> None:
        r = parse(text)
        assert r["ok"] is True
        assert r["delimiter"] == delimiter
        assert r["headers"] == headers
        assert r["count"] == count

    def test_explicit_delimiter(self) -> None:
        r = parse("name|age\nx|1\ny|2\n", delimiter="|")
        assert r["ok"] is True
        assert r["count"] == 2
        assert r["headers"] == ["name", "age"]

    def test_no_header(self) -> None:
        text = "alice,30\nbob,25\n"
        r = parse(text, has_header=False)
        assert r["ok"] is True
        assert r["headers"] == []
        assert r["count"] == 2
        assert "col_0" in r["rows"][0]

    def test_empty_text(self) -> None:
        r = parse("")
        assert r["ok"] is True
        assert r["count"] == 0
        assert r["rows"] == []

    def test_large_csv_truncated(self) -> None:
        lines = ["name,age"] + [f"user{i},{i}" for i in range(250)]
        r = parse("\n".join(lines))
        assert r["ok"] is True
        assert r["count"] == 250
        assert r["truncated"] is True
        assert len(r["rows"]) <= 200

    # --- Boundary / edge cases ---

    def test_bom_csv(self) -> None:
        text = "\ufeffname,age\nalice,30\n"
        r = parse(text)
        assert r["ok"] is True
        assert r["count"] >= 1

    def test_quoted_comma(self) -> None:
        text = 'name,desc\nalice,"loves, coding"\n'
        r = parse(text)
        assert r["ok"] is True
        assert r["count"] == 1
        assert r["rows"][0]["desc"] == "loves, coding"

    def test_crlf_newlines(self) -> None:
        text = "name,age\r\nalice,30\r\nbob,25\r\n"
        r = parse(text)
        assert r["ok"] is True
        assert r["count"] == 2


class TestGenerate:
    @pytest.mark.parametrize("rows,delimiter,expected_prefix", [
        ([{"name": "alice", "age": "30"}, {"name": "bob", "age": "25"}], ",", "name,age"),
        ([{"a": "1", "b": "2"}], "\t", "a\tb"),
    ])
    def test_generate_basic(self, rows: list, delimiter: str, expected_prefix: str) -> None:
        r = generate(rows, delimiter=delimiter) if delimiter != "," else generate(rows)
        assert r["ok"] is True
        assert r["result"].startswith(expected_prefix)
        assert r["row_count"] == len(rows)

    def test_empty_rows(self) -> None:
        r = generate([])
        assert r["ok"] is False
        assert "error" in r

    def test_single_row(self) -> None:
        rows = [{"x": "y"}]
        r = generate(rows)
        assert r["ok"] is True
        assert r["row_count"] == 1
