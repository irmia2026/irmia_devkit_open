"""Tests for git_changelog — Git changelog generation.

Uses the shared git_repo fixture from conftest.py."""

from tools.git_changelog import changelog


class TestGitChangelog:
    def test_basic_changelog(self, git_repo: str) -> None:
        r = changelog(cwd=git_repo, count=30)
        assert r["ok"] is True
        assert r["total"] == 5
        assert len(r["categories"]["features"]) >= 1
        assert len(r["categories"]["fixes"]) >= 1

    def test_invalid_directory(self) -> None:
        r = changelog(cwd="/nonexistent/path", count=10)
        assert r["ok"] is False
        assert "error" in r

    def test_non_git_directory(self, tmp_path) -> None:
        p = tmp_path / "not_a_repo"
        p.mkdir()
        r = changelog(cwd=str(p), count=10)
        assert r["ok"] is False

    def test_empty_repo(self, tmp_path) -> None:
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True, timeout=10)
        r = changelog(cwd=str(tmp_path), count=10)
        assert "ok" in r

    def test_single_commit(self, git_repo: str) -> None:
        r = changelog(cwd=git_repo, count=1)
        assert r["ok"] is True
        assert r["total"] == 1
