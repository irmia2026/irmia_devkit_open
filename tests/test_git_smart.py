"""Tests for git_smart — commit guards and structured output."""

import os
import tempfile
import subprocess
import pytest
from tools import git_smart
from tools.git_smart import commit, status, diff


@pytest.fixture
def git_repo():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init"], cwd=d, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
    # Create initial commit
    with open(os.path.join(d, "README.md"), "w") as f:
        f.write("# test\n")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


class TestGitSmart:
    def test_status_clean(self, git_repo):
        s = status(git_repo)
        assert s["ok"] is True
        assert s["clean"] is True

    def test_commit_success(self, git_repo):
        with open(os.path.join(git_repo, "main.py"), "w") as f:
            f.write("print('hello')\n")
        result = commit(git_repo, "feat: add main.py")
        assert result["ok"] is True
        assert result["files_committed"] == 1

    def test_commit_no_changes(self, git_repo):
        result = commit(git_repo, "should fail")
        assert result["ok"] is False
        assert "没有可提交" in result["error"]

    def test_commit_many_files_blocked(self, git_repo):
        for i in range(15):
            with open(os.path.join(git_repo, f"file_{i}.py"), "w") as f:
                f.write(f"# file {i}\n")
        result = commit(git_repo, "too many")
        assert result["ok"] is False
        assert "过多" in result["error"] or "文件" in result.get("proposal", "")


def _mock_git(monkeypatch, captured, porcelain):
    """Mock _run_git：按子命令返回固定结果，并记录调用参数。"""
    def fake(cwd, args, timeout=15):
        captured.append(args)
        if args[:2] == ["status", "--porcelain"]:
            return {"ok": True, "stdout": porcelain, "stderr": ""}
        if args[:1] == ["add"]:
            return {"ok": True, "stdout": "", "stderr": ""}
        if args[:1] == ["commit"]:
            return {"ok": True, "stdout": "committed", "stderr": ""}
        if args[:2] == ["log", "-1"]:
            return {"ok": True, "stdout": "abc123", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}
    monkeypatch.setattr(git_smart, "_run_git", fake)


class TestCommitFilesForce:
    def test_commit_specific_files_adds_only_those(self, monkeypatch):
        captured = []
        _mock_git(monkeypatch, captured, " M main.py\n M README.md")
        result = commit(".", "feat: only main", files=["main.py"])
        assert result["ok"] is True
        add_calls = [a for a in captured if a[:1] == ["add"]]
        assert add_calls == [["add", "--", "main.py"]]
        assert result["files_staged"] == ["main.py"]

    def test_commit_files_rejects_absolute_and_escape(self, monkeypatch):
        captured = []
        _mock_git(monkeypatch, captured, " M main.py")
        assert commit(".", "msg", files=["../evil.py"])["ok"] is False
        assert commit(".", "msg", files=["a/../../evil.py"])["ok"] is False
        assert commit(".", "msg", files=["C:/abs.py"])["ok"] is False
        assert commit(".", "msg", files=["/abs.py"])["ok"] is False
        # 校验失败不应触发任何 git add
        assert not [a for a in captured if a[:1] == ["add"]]

    def test_commit_empty_files_falls_back_to_add_all(self, monkeypatch):
        captured = []
        _mock_git(monkeypatch, captured, " M main.py")
        result = commit(".", "msg", files=[])
        assert result["ok"] is True
        add_calls = [a for a in captured if a[:1] == ["add"]]
        assert add_calls == [["add", "-A"]]

    def test_commit_blocked_options_are_executable(self, monkeypatch):
        captured = []
        porcelain = "\n".join(f" M file_{i}.py" for i in range(12))
        _mock_git(monkeypatch, captured, porcelain)
        result = commit(".", "too many")
        assert result["ok"] is False
        assert result.get("reason") == "too_many_files"
        assert "Code:12" in result["proposal"]
        force_opt = result["options"][0]
        assert force_opt == {
            "tool": "git_commit",
            "params": {"cwd": ".", "message": "too many", "force": True},
        }
        code_opt = result["options"][1]
        assert code_opt["tool"] == "git_commit"
        assert code_opt["params"]["files"] == [f"file_{i}.py" for i in range(12)]
        assert result["evidence"]["file_groups"]["Code"][0] == "file_0.py"

    def test_commit_force_bypasses_block(self, monkeypatch):
        captured = []
        porcelain = "\n".join(f" M file_{i}.py" for i in range(12))
        _mock_git(monkeypatch, captured, porcelain)
        result = commit(".", "force it", force=True)
        assert result["ok"] is True
        assert ["commit", "-m", "force it"] in captured


class TestTruncation:
    def test_diff_truncates_over_max_lines(self, monkeypatch):
        big = "\n".join(f"line {i}" for i in range(600))

        def fake(cwd, args, timeout=15):
            if args[:1] == ["diff"] and "--stat" in args:
                return {"ok": True, "stdout": "1 file changed, 600 insertions(+)", "stderr": ""}
            if args[:1] == ["diff"]:
                return {"ok": True, "stdout": big, "stderr": ""}
            return {"ok": True, "stdout": "", "stderr": ""}
        monkeypatch.setattr(git_smart, "_run_git", fake)

        result = diff(".", max_lines=500)
        assert result["ok"] is True
        assert result["diff_truncated"] is True
        assert result["diff_total_lines"] == 600
        assert len(result["diff"].split("\n")) == 500
        assert result["diff"].split("\n")[-1] == "line 499"

    def test_diff_under_limit_unchanged(self, monkeypatch):
        small = "\n".join(f"line {i}" for i in range(10))

        def fake(cwd, args, timeout=15):
            return {"ok": True, "stdout": small, "stderr": ""}
        monkeypatch.setattr(git_smart, "_run_git", fake)

        result = diff(".")
        assert result["ok"] is True
        assert "diff_truncated" not in result
        assert result["diff"] == small

    def test_status_changes_capped_at_200(self, monkeypatch):
        porcelain = "\n".join(f" M file_{i}.py" for i in range(250))

        def fake(cwd, args, timeout=15):
            return {"ok": True, "stdout": porcelain, "stderr": ""}
        monkeypatch.setattr(git_smart, "_run_git", fake)

        s = status(".")
        assert s["ok"] is True
        assert len(s["changes"]) == 200
        assert s["changed_count"] == 250
        assert s["changes_truncated"] is True
        assert s["changes_total"] == 250
