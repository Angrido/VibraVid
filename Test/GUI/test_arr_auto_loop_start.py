# 21.11.26
# ruff: noqa: E402

import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
for p in (str(repo_root), str(repo_root / "GUI")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

from searchapp import arr_auto
from searchapp.arr import arr_service


def test_the_loop_starts_even_when_arr_is_off_at_boot(monkeypatch):
    """Enabling ARR in Settings after boot found no loop running until the next restart: the loop idles while ARR is off."""
    started = []

    class _Thread:
        def __init__(self, target, daemon, name):
            self.name = name

        def start(self):
            started.append(self.name)

    monkeypatch.setattr(arr_auto, "_should_start_loop", lambda: True)
    monkeypatch.setattr(arr_auto, "_loop_started", False)
    monkeypatch.setattr(arr_auto.threading, "Thread", _Thread)
    monkeypatch.setattr(arr_service, "_load_arr_config", lambda: {"enabled": False})

    arr_auto.start_arr_auto_loop()
    arr_auto.start_arr_auto_loop()  # a second call never starts a second loop

    assert started == ["ArrAutoLoop"]
