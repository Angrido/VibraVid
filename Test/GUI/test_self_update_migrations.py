# 21.11.26
# ruff: noqa: E402

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
for p in (str(repo_root), str(repo_root / "GUI")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

from searchapp import self_update


def _manage_module():
    spec = importlib.util.spec_from_file_location("vibravid_manage", repo_root / "GUI" / "manage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_source_update_leaves_the_migrate_marker(monkeypatch, tmp_path):
    (tmp_path / "GUI").mkdir()
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "git")
    monkeypatch.setattr(self_update, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(self_update.subprocess, "check_output", lambda *a, **k: "origin")
    monkeypatch.setattr(self_update.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "Updating", ""))
    monkeypatch.setattr(self_update.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())

    assert self_update._update_source()["success"] is True
    assert (tmp_path / "GUI" / ".migrate-pending").exists()


def test_the_reloader_child_migrates_when_the_marker_is_there(monkeypatch, tmp_path):
    """The autoreloader's child has RUN_MAIN=true and skipped migrate, so new code ran on the old schema after an update."""
    import django.core.management as management

    manage = _manage_module()
    marker = tmp_path / ".migrate-pending"
    marker.write_text("")
    calls = []
    monkeypatch.setattr(manage, "MIGRATE_MARKER", str(marker))
    monkeypatch.setattr(manage.subprocess, "run", lambda cmd, **k: calls.append(cmd[2:]))
    monkeypatch.setattr(management, "execute_from_command_line", lambda argv: None)
    monkeypatch.setattr(sys, "argv", ["manage.py", "runserver"])
    monkeypatch.setenv("RUN_MAIN", "true")

    manage.main()
    assert calls == [["migrate", "--noinput"]] and not marker.exists()

    manage.main()  # an ordinary reload: no marker, no migrate
    assert calls == [["migrate", "--noinput"]]
