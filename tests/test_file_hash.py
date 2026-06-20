"""Tests for file_hash."""

import hashlib
from pathlib import Path

from tools import file_hash as fh


class TestCompute:
    def test_sha256(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        content = b"hello world"
        p.write_bytes(content)
        r = fh.compute(str(p), algo="sha256")
        assert r["ok"] is True
        assert r["algo"] == "sha256"
        assert r["hash"] == hashlib.sha256(content).hexdigest()
        assert r["size"] == len(content)
        assert r["file"] == str(p.resolve())

    def test_md5(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        content = b"hello"
        p.write_bytes(content)
        r = fh.compute(str(p), algo="md5")
        assert r["ok"] is True
        assert r["hash"] == hashlib.md5(content).hexdigest()

    def test_sha1(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        content = b"hello"
        p.write_bytes(content)
        r = fh.compute(str(p), algo="sha1")
        assert r["ok"] is True
        assert r["hash"] == hashlib.sha1(content).hexdigest()

    def test_default_algorithm(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        p.write_bytes(b"x")
        r = fh.compute(str(p))
        assert r["algo"] == "sha256"

    def test_large_file(self, tmp_dir):
        p = Path(tmp_dir) / "big.bin"
        content = b"a" * (1024 * 1024 + 123)
        p.write_bytes(content)
        r = fh.compute(str(p), algo="sha256")
        assert r["ok"] is True
        assert r["hash"] == hashlib.sha256(content).hexdigest()

    def test_missing_file(self, tmp_dir):
        r = fh.compute(str(Path(tmp_dir) / "missing.txt"))
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_unsupported_algorithm(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        p.write_bytes(b"x")
        r = fh.compute(str(p), algo="crc32")
        assert r["ok"] is False
        assert "不支持的算法" in r["error"]
