"""Tests for json_query — jq-like JSON querying."""

import json

import pytest

from tools.json_query import query


class TestJsonQuery:
    @pytest.mark.parametrize("json_str,path,expected", [
        ('{"name": "alice", "age": 30}', "name", "alice"),
        ('{"user": {"name": "bob", "details": {"age": 25}}}', "user.name", "bob"),
        ('{"items": [10, 20, 30]}', "items[1]", 20),
        ('{"users": [{"name": "a"}, {"name": "b"}]}', "users[0].name", "a"),
        ('{"users": [{"n": "a"}, {"n": "b"}]}', "users[*].n", ["a", "b"]),
        ('{"nums": [1, 2, 3]}', "nums[-1]", 3),
        ('{"a": {"b": {"c": {"d": {"e": "deep"}}}}}', "a.b.c.d.e", "deep"),
        ('{"x": 1}', "", {"x": 1}),
    ])
    def test_query_success(self, json_str: str, path: str, expected) -> None:
        r = query(json_str, path)
        assert r["ok"] is True
        assert r["result"] == expected

    @pytest.mark.parametrize("json_str,path", [
        ("{bad json}", "key"),
        ('{"a": 1}', "b"),
        ('"just a string"', "key"),
        ("{}", "key"),
    ])
    def test_query_failure(self, json_str: str, path: str) -> None:
        r = query(json_str, path)
        assert r["ok"] is False

    # --- Boundary / edge cases ---

    def test_null_value(self) -> None:
        r = query('{"a": null}', "a")
        assert r["ok"] is True
        assert r["result"] is None

    def test_boolean_value(self) -> None:
        r = query('{"flag": true}', "flag")
        assert r["ok"] is True
        assert r["result"] is True

    def test_large_json_not_crashing(self) -> None:
        huge = {"data": [{"id": i, "value": "x" * 100} for i in range(5000)]}
        r = query(json.dumps(huge), "data[0].id")
        assert r["ok"] is True
        assert r["result"] == 0
