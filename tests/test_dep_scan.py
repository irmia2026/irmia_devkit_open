"""Tests for dep_scan — dependency scanning."""

from pathlib import Path
from tools.dep_scan import scan


class TestDepScan:
    def test_scan_simple_project(self, project_dir):
        """Scan a project with known imports."""
        r = scan(project_dir)
        assert r["ok"] is True
        # files_scanned counts files with non-empty deps
        assert r["files_scanned"] >= 1
        deps = r["dependencies"]
        # main.py imports from .utils
        assert r["has_cycles"] is False

    def test_invalid_directory(self):
        r = scan("/nonexistent_path_xyz")
        assert r["ok"] is False
        assert "error" in r

    def test_empty_dir(self, tmp_dir):
        """Empty directory — no .py files to scan."""
        r = scan(tmp_dir)
        assert r["ok"] is True
        assert r["files_scanned"] == 0
        assert r["dependencies"] == {}

    def test_no_python_files(self, tmp_dir):
        p = Path(tmp_dir)
        (p / "readme.txt").write_text("hello")
        r = scan(str(p))
        assert r["ok"] is True
        assert r["files_scanned"] == 0
        assert r["dependencies"] == {}

    def test_syntax_error_file(self, tmp_dir):
        """A file with syntax error should be skipped."""
        p = Path(tmp_dir)
        (p / "broken.py").write_text("this is not valid python @@")
        (p / "helper.py").write_text("def h(): return 1\n")
        (p / "good.py").write_text("import helper\n")
        r = scan(str(p))
        assert r["ok"] is True
        # good.py 有项目内依赖；broken.py 因 SyntaxError 跳过
        assert r["files_scanned"] == 1
        assert r["dependencies"] == {"good": ["helper"]}

    def test_cycle_detection(self, tmp_dir):
        """Create two files that import each other."""
        p = Path(tmp_dir)
        (p / "a.py").write_text("from b import bar\ndef foo(): pass\n")
        (p / "b.py").write_text("from a import foo\ndef bar(): pass\n")
        r = scan(str(p))
        assert r["ok"] is True
        # 图的键为项目内模块名（a/b），依赖只保留项目内模块，循环可被检出
        assert r["has_cycles"] is True
        cycle_modules = {m for c in r["cycles"] for m in c}
        assert {"a", "b"} <= cycle_modules

    def test_excluded_dirs_skipped(self, tmp_dir):
        """node_modules/.venv/__pycache__ 等目录不参与扫描。"""
        p = Path(tmp_dir)
        (p / "main.py").write_text("import os\n")
        for d in ("__pycache__", ".git", ".venv", "venv", "node_modules",
                  ".tox", "dist", "build", ".mypy_cache", ".pytest_cache"):
            sub = p / d
            sub.mkdir()
            (sub / "junk.py").write_text("import main\n")
        r = scan(str(p))
        assert r["ok"] is True
        # 排除目录里的 junk.py 不应出现在依赖图中
        assert all("junk" not in k for k in r["dependencies"])

    def test_package_module_names(self, tmp_dir):
        """包内模块以点分模块名为键，__init__.py 映射为包名。"""
        p = Path(tmp_dir)
        pkg = p / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg import core\n")
        (pkg / "core.py").write_text("import pkg\n")
        r = scan(str(p))
        assert r["ok"] is True
        assert "pkg" in r["dependencies"]
        assert "pkg.core" in r["dependencies"]
        assert r["has_cycles"] is True
