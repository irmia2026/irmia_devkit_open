"""Tests for html_extract — HTML content extraction."""

import pytest

from tools.html_extract import extract


class TestHtmlExtract:
    @pytest.mark.parametrize("html,what,expected_text,expected_count", [
        (
            "<html><body><p>Hello World</p></body></html>",
            "text", "Hello World", 1,
        ),
        (
            "<html><body><script>alert('x')</script><p>content</p></body></html>",
            "text", "content", 1,
        ),
        (
            "<html><head><style>body{color:red}</style></head><body><p>visible</p></body></html>",
            "text", "visible", 1,
        ),
        (
            "", "text", "", 0,
        ),
    ])
    def test_text_extraction(self, html: str, what: str, expected_text: str, expected_count: int) -> None:
        r = extract(html, what=what)
        assert r["ok"] is True
        assert r["data"]["text"].strip() == expected_text

    @pytest.mark.parametrize("html,expected_count,expected_hrefs", [
        (
            '<a href="https://example.com">Ex</a><a href="/local">Lo</a>',
            2, ["https://example.com", "/local"],
        ),
        (
            "<body><p>no links</p></body>",
            0, [],
        ),
    ])
    def test_links(self, html: str, expected_count: int, expected_hrefs: list) -> None:
        r = extract(html, what="links")
        assert r["ok"] is True
        assert r["data"]["count"] == expected_count
        if expected_hrefs:
            assert [l["href"] for l in r["data"]["links"]] == expected_hrefs

    @pytest.mark.parametrize("html,expected_count", [
        (
            "<table><tr><th>Name</th><th>Age</th></tr><tr><td>Alice</td><td>30</td></tr></table>",
            1,
        ),
        (
            "<table><tr><td>1</td></tr></table><table><tr><td>2</td></tr></table>",
            2,
        ),
    ])
    def test_tables(self, html: str, expected_count: int) -> None:
        r = extract(html, what="tables")
        assert r["ok"] is True
        assert r["data"]["count"] == expected_count

    def test_css_query(self) -> None:
        html = '<div class="content"><p>para1</p><p>para2</p></div>'
        r = extract(html, what="query", selector=".content p")
        assert r["ok"] is True
        assert r["data"]["count"] == 2

    @pytest.mark.parametrize("html,what,selector", [
        ("<p>test</p>", "query", ""),
        ("<p>test</p>", "invalid", "ignored"),
    ])
    def test_extract_errors(self, html: str, what: str, selector: str) -> None:
        kwargs = {"html": html, "what": what}
        if selector != "ignored":
            kwargs["selector"] = selector
        r = extract(**kwargs)
        assert r["ok"] is False
        assert "error" in r
