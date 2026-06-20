"""Tests for project_init — project scanning and context generation."""

from pathlib import Path

from tools.project_init import scan


class TestProjectInit:
    def test_scan_current_project(self):
        """Scan the actual project directory."""
        r = scan(".")
        assert r["ok"] is True
        ctx = r["context"]
        assert "project_name" in ctx
        assert "language" in ctx
        assert "dependencies" in ctx
        assert "directories" in ctx
        # This project has Python files
        assert ctx["language"] == "python"
        assert "tools" in ctx["directories"]
        assert "tests" in ctx["directories"]

    def test_invalid_directory(self):
        r = scan("/nonexistent_dir_xyz")
        assert r["ok"] is False
        assert "error" in r

    def test_empty_directory(self, tmp_dir):
        r = scan(tmp_dir)
        assert r["ok"] is True
        ctx = r["context"]
        assert ctx["language"] == "unknown"
        assert ctx["dependencies"]["runtime"] == []
        assert ctx["entry"] is None

    def test_minimal_python_project(self, tmp_dir):
        p = Path(tmp_dir)
        (p / "main.py").write_text("print('hello')\n")
        (p / "requirements.txt").write_text("requests\nflask\n")
        r = scan(str(p))
        assert r["ok"] is True
        ctx = r["context"]
        assert ctx["language"] == "python"
        assert ctx["entry"] == "main.py"
        assert "requests" in ctx["dependencies"]["runtime"]
        assert "flask" in ctx["dependencies"]["runtime"]

    def test_project_with_git(self, tmp_dir):
        import subprocess
        p = Path(tmp_dir)
        (p / "app.py").write_text("x = 1\n")
        subprocess.run(["git", "init"], cwd=str(p), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(p), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(p), capture_output=True, timeout=10)
        subprocess.run(["git", "add", "."], cwd=str(p), capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(p), capture_output=True, timeout=10)
        r = scan(str(p))
        assert r["ok"] is True
        assert "git" in r["context"]
