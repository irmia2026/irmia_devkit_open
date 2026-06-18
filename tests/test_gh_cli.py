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
