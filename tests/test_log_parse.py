"""Tests for log_parse — Log file parsing."""

import pytest

from tools.log_parse import parse


class TestLogParse:
    @pytest.mark.parametrize("log_text,log_format,expected_parsed", [
        (
            '192.168.1.1 - - [10/Jan/2025:12:00:00 +0000] "GET /index.html HTTP/1.1" 200 1234 "-" "Mozilla/5.0"',
            "nginx", 1,
        ),
        (
            '{"timestamp": "2025-01-10", "level": "info", "msg": "hello"}',
            "jsonl", 1,
        ),
        (
            "Jan 10 12:00:00 myhost myservice[123]: something happened",
            "syslog", 1,
        ),
    ])
    def test_single_line(self, log_text: str, log_format: str, expected_parsed: int) -> None:
        r = parse(log_text)
        assert r["ok"] is True
        assert r["format"] == log_format
        assert r["parsed"] == expected_parsed

    def test_apache_explicit(self) -> None:
        r = parse(
            '192.168.1.1 - - [10/Jan/2025:12:00:00 +0000] "GET /index.html HTTP/1.1" 200 1234',
            format="apache",
        )
        assert r["ok"] is True
        assert r["format"] == "apache"

    def test_auto_detect_jsonl(self) -> None:
        r = parse('{"event": "start", "severity": 1}')
        assert r["ok"] is True
        assert r["format"] == "jsonl"

    def test_mixed_good_and_bad_lines(self) -> None:
        text = (
            '192.168.1.1 - - [10/Jan/2025:12:00:00 +0000] "GET / HTTP/1.1" 200 123 "-" "-"\n'
            "bad line that doesn't match any format\n"
            '10.0.0.1 - - [10/Jan/2025:12:01:00 +0000] "POST /api HTTP/1.1" 201 456 "-" "-"'
        )
        r = parse(text)
        assert r["ok"] is True
        assert r["parsed"] == 2
        assert r["errors"] == 1

    @pytest.mark.parametrize("log_text,format_type", [
        ("test", "unsupported"),
    ])
    def test_unsupported_format(self, log_text: str, format_type: str) -> None:
        r = parse(log_text, format=format_type)
        assert r["ok"] is False
        assert "error" in r

    def test_empty_text(self) -> None:
        r = parse("")
        assert r["ok"] is True
        assert r["parsed"] == 0

    def test_multiline(self) -> None:
        lines = [
            '1.1.1.1 - - [01/Jan/2025:00:00:00 +0000] "GET / HTTP/1.1" 200 100 "-" "-"',
            '2.2.2.2 - - [01/Jan/2025:00:01:00 +0000] "POST /api HTTP/1.1" 201 200 "-" "-"',
        ]
        r = parse("\n".join(lines))
        assert r["ok"] is True
        assert r["parsed"] == 2

    def test_max_lines_limit(self) -> None:
        lines = [f'1.1.1.1 - - [01/Jan/2025:00:00:00 +0000] "GET /{i}.html HTTP/1.1" 200 100 "-" "-"' for i in range(300)]
        r = parse("\n".join(lines), max_lines=50)
        assert r["ok"] is True
        assert r["parsed"] <= 50
        assert r["total_lines"] == 50

    def test_truncated_input(self) -> None:
        r = parse("x" * 60000)
        assert r["ok"] is True
        assert "truncated_input" in r
