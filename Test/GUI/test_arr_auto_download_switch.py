# 12.11.26
# ruff: noqa: E402

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "GUI"
for path in (ROOT, GUI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

import pytest

from searchapp import arr_auto
from searchapp.arr import arr_service


class LoopStopped(Exception):
    pass


def _run_one_loop_iteration(monkeypatch, config):
    syncs = []
    monkeypatch.setattr(arr_service, "_load_arr_config", lambda: config)
    monkeypatch.setattr(arr_service, "_reconcile_orphaned_downloads", lambda *a, **k: 0)
    monkeypatch.setattr(arr_service, "trigger_polling_sync", lambda **kwargs: syncs.append(kwargs) or 0)

    def stop(_seconds):
        raise LoopStopped

    monkeypatch.setattr(arr_auto.time, "sleep", stop)
    with pytest.raises(LoopStopped):
        arr_auto._arr_loop()
    return syncs


def test_polling_loop_downloads_nothing_when_automatic_downloads_are_off(monkeypatch):
    syncs = _run_one_loop_iteration(monkeypatch, {"enabled": True, "enable_polling": True, "auto_download": False})

    assert syncs == []


def test_polling_loop_still_polls_when_automatic_downloads_are_on(monkeypatch):
    syncs = _run_one_loop_iteration(monkeypatch, {"enabled": True, "enable_polling": True, "auto_download": True})

    assert syncs == [{"full_resync": True}]


def test_existing_configs_without_the_switch_keep_automatic_downloads():
    assert arr_service.automatic_downloads_enabled({"enabled": True}) is True


@pytest.mark.parametrize("value, expected", [("false", False), ("0", False), ("true", True)])
def test_auto_download_can_be_set_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ARR_AUTO_DOWNLOAD", value)

    assert arr_service.automatic_downloads_enabled(arr_service._load_arr_config()) is expected
