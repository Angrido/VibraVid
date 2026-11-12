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

from django.test import Client

from VibraVid.setup import dependencies


def test_dependencies_endpoint_reports_missing_required_tools_without_downloading(monkeypatch):
    monkeypatch.setattr(dependencies, "external_dependencies", lambda: [("FFmpeg", "/opt/ffmpeg"), ("mkvmerge", None), ("flux", None)])
    monkeypatch.setattr(dependencies, "probe_binary_version", lambda name, path: "7.1" if path else "")

    response = Client().get("/api/dependencies/", HTTP_HOST="127.0.0.1")

    assert response.status_code == 200
    assert response.json()["dependencies"] == [
        {"name": "FFmpeg", "path": "/opt/ffmpeg", "version": "7.1", "found": True, "required": True},
        {"name": "mkvmerge", "path": None, "version": "", "found": False, "required": True},
        {"name": "flux", "path": None, "version": "", "found": False, "required": False},
    ]


def test_external_dependencies_never_ask_the_checkers_to_download(monkeypatch):
    calls = []

    def fake_check(name):
        def check(download=True):
            calls.append((name, download))
            return ("/x", "/y") if name == "ffmpeg" else None
        return check

    for name in ("ffmpeg", "flux", "dovi_tool", "mkvmerge", "mkvpropedit", "velora", "yt_dlp", "deno"):
        monkeypatch.setattr(dependencies, f"check_{name}", fake_check(name))

    names = [name for name, _ in dependencies.external_dependencies()]

    assert "FFmpeg" in names and "mkvmerge" in names
    assert calls and all(download is False for _, download in calls)


def test_extract_version_reads_common_outputs():
    assert dependencies.extract_version("ffmpeg version 7.1.1 Copyright (c) 2000-2025") == "7.1.1"
    assert dependencies.extract_version("mkvmerge v80.0 ('Roundabout') 64-bit") == "80.0"
    assert dependencies.extract_version("no digits here") == ""
