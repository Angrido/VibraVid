# 21.11.26

import json

from VibraVid.cli.command import queue
from VibraVid.utils import config_manager


def _write_queue(tmp_path, name, statuses):
    folder = tmp_path / ".cache" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    items = [{"id": f"{name}{i}", "argv": ["--help"], "status": status} for i, status in enumerate(statuses)]
    (folder / f"{name}.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return folder / f"{name}.json"


def test_clear_completed_removes_only_the_done_items(tmp_path, monkeypatch):
    monkeypatch.setattr(config_manager, "base_path", str(tmp_path))
    mixed = _write_queue(tmp_path, "queue_a", ["done", "pending", "failed", "running", "done"])
    all_done = _write_queue(tmp_path, "queue_b", ["done"])

    assert queue.clear_completed() == 3

    left = json.loads(mixed.read_text(encoding="utf-8"))["items"]
    assert [it["status"] for it in left] == ["pending", "failed", "running"]
    assert not all_done.exists()
