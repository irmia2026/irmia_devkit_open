from pathlib import Path

from tools import gh_cli


def test_pr_review_uses_body_file_for_multiline_body(monkeypatch):
    captured = {}

    def fake_run_gh(args, cwd=None, timeout=20):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        body_file = Path(args[args.index("--body-file") + 1])
        captured["body"] = body_file.read_text(encoding="utf-8")
        return {"ok": True, "stdout": "review submitted", "stderr": ""}

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)

    body = "line 1\nline 2\nline 3"
    result = gh_cli.pr_review("repo", 12, body, "comment")

    assert result["ok"] is True
    assert captured["args"][:4] == ["pr", "review", "12", "--comment"]
    assert "--body" not in captured["args"]
    assert "--body-file" in captured["args"]
    assert captured["body"] == body


def test_pr_review_rejects_unknown_event():
    result = gh_cli.pr_review("repo", 12, "body", "invalid")

    assert result["ok"] is False
    assert "review_event" in result["error"]


def test_run_view_flattens_json(monkeypatch):
    captured = {}

    def fake_run_gh(args, cwd=None, timeout=20):
        captured["args"] = args
        return {
            "ok": True,
            "stdout": '{"name":"CI","status":"completed","conclusion":"success",'
                      '"headBranch":"main","createdAt":"2026-01-01","jobs":[{"name":"test"}]}',
            "stderr": "",
        }

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)
    result = gh_cli.run_view(123, cwd="repo")

    assert result["ok"] is True
    assert result["name"] == "CI"
    assert result["conclusion"] == "success"
    assert result["jobs"] == [{"name": "test"}]
    assert captured["args"][:3] == ["run", "view", "123"]
    assert "--json" in captured["args"]


def test_run_view_error_passthrough(monkeypatch):
    def fake_run_gh(args, cwd=None, timeout=20):
        return {"ok": False, "error": "gh 未安装或不在 PATH 中"}

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)
    result = gh_cli.run_view(123)

    assert result["ok"] is False
    assert "error" in result


def test_run_logs_truncates_to_tail(monkeypatch):
    logs = "".join(f"log line {i}\n" for i in range(1000))

    def fake_run_gh(args, cwd=None, timeout=20):
        return {"ok": True, "stdout": logs, "stderr": ""}

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)
    result = gh_cli.run_logs(123, cwd="repo", max_chars=8000)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["logs"]) == 8000
    assert result["logs"] == logs[-8000:]
    assert result["logs"].endswith("log line 999\n")
    assert result["total_chars"] == len(logs)


def test_run_logs_short_output_not_truncated(monkeypatch):
    def fake_run_gh(args, cwd=None, timeout=20):
        return {"ok": True, "stdout": "short log", "stderr": ""}

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)
    result = gh_cli.run_logs(123)

    assert result["ok"] is True
    assert "truncated" not in result
    assert result["logs"] == "short log"


def test_run_logs_error_passthrough(monkeypatch):
    def fake_run_gh(args, cwd=None, timeout=20):
        return {"ok": False, "error": "no log found", "stderr": "no log"}

    monkeypatch.setattr(gh_cli, "_run_gh", fake_run_gh)
    result = gh_cli.run_logs(123)

    assert result["ok"] is False
    assert "error" in result or "stderr" in result
