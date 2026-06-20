"""Tests for md_strip — Markdown stripping."""

import pytest

from tools.md_strip import strip


class TestMdStrip:
    @pytest.mark.parametrize("md,expected", [
        ("# Title\n\n## Subtitle\nContent", "Title\n\nSubtitle\nContent"),
        ("Text\n```python\nprint('hello')\n```\nMore", "Text\n\nMore"),
        ("Use `code` here", "Use code here"),
        ("- item1\n- item2\n- item3", "item1\nitem2\nitem3"),
        ("[Google](https://google.com) and [GitHub](https://github.com)", "Google and GitHub"),
        ("**bold** and *italic*", "bold and italic"),
        ("~~deleted~~ text", "deleted text"),
        ("> quoted text\n> more quoted", "quoted text\nmore quoted"),
        ("Above\n\n---\n\nBelow", "Above\n\nBelow"),
        ("![alt text](image.png) caption", "alt text caption"),
        ("Just plain text with no markdown", "Just plain text with no markdown"),
        ("", ""),
    ])
    def test_md_elements(self, md: str, expected: str) -> None:
        r = strip(md)
        assert r["ok"] is True
        assert r["result"] == expected

    def test_mixed_formatting(self) -> None:
        md = "# Title\n\n**bold** and *italic* with `code`\n\n- list item\n\n[link](url)"
        r = strip(md)
        assert r["ok"] is True
        assert r["result"] == "Title\n\nbold and italic with code\n\nlist item\n\nlink"

    def test_length_stats(self) -> None:
        r = strip("# Hello\nWorld")
        assert r["ok"] is True
        assert r["original_length"] > r["stripped_length"]
