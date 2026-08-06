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

    def test_extended_categories(self, git_repo: str) -> None:
        """九类分类 + other 兜底；fixture 中的 chore commit 应归入 chore。"""
        r = changelog(cwd=git_repo, count=30)
        assert r["ok"] is True
        for key in ("features", "fixes", "perf", "refactors", "docs",
                    "tests", "chore", "build", "ci", "other"):
            assert key in r["categories"]
        assert len(r["categories"]["chore"]) == 1
        assert "bump version" in r["categories"]["chore"][0]
        assert r["counts"]["chore"] == 1
