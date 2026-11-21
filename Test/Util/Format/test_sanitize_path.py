# 21.11.26

"""Path sanitising keeps what the user configured verbatim and only rewrites the title-derived components."""

import os

import pytest

from VibraVid.core.ui.tracker import context_tracker
from VibraVid.utils import config_manager, os_manager


@pytest.fixture
def root_path(monkeypatch):
    """Point OUTPUT.root_path at a test value without touching the real config file."""
    original_get = config_manager.config.get

    def set_root(value, system):
        monkeypatch.setattr(os_manager, "system", system)

        def fake_get(section, key, *args, **kwargs):
            if (section, key) == ("OUTPUT", "root_path"):
                return value
            return original_get(section, key, *args, **kwargs)

        monkeypatch.setattr(config_manager.config, "get", fake_get)

    return set_root


def test_windows_configured_root_with_accents_is_kept(root_path):
    root_path("D:\\Vidéos\\Nicolò", "windows")
    assert os_manager.get_sanitize_path("D:\\Vidéos\\Nicolò\\Serie\\Série: Uno\\S01E01.mkv") == "D:\\Vidéos\\Nicolò\\Serie\\Serie Uno\\S01E01.mkv"


def test_posix_configured_root_with_colon_is_kept(root_path):
    root_path("/mnt/nas:1/Vidéo", "linux")
    assert os_manager.get_sanitize_path("/mnt/nas:1/Vidéo/Serie/Série: Uno/S01E01.mkv") == "/mnt/nas:1/Vidéo/Serie/Serie Uno/S01E01.mkv"


def test_relative_configured_root_is_kept(root_path):
    root_path("./Vidéo", "linux")
    assert os_manager.get_sanitize_path("./Vidéo/Film/Amélie.mkv") == "./Vidéo/Film/Amelie.mkv"


def test_forced_output_path_is_kept(root_path, monkeypatch):
    root_path("Video", "windows")
    monkeypatch.setattr(context_tracker, "output_path", "E:\\Téléchargements")
    assert os_manager.get_sanitize_path("E:\\Téléchargements\\Amélie?.mkv") == "E:\\Téléchargements\\Amelie.mkv"


def test_existing_absolute_directory_is_kept(root_path, tmp_path):
    root_path("Video", "windows" if os.name == "nt" else "linux")
    existing = tmp_path / "Nicolò"
    existing.mkdir()
    sep = "\\" if os.name == "nt" else "/"
    assert os_manager.get_sanitize_path(f"{existing}{sep}Série{sep}ep.mkv") == f"{existing}{sep}Serie{sep}ep.mkv"


def test_sanitising_twice_is_stable(root_path):
    root_path("D:\\Vidéos", "windows")
    once = os_manager.get_sanitize_path("D:\\Vidéos\\Serie\\Série: Uno\\" + "B" * 300 + ".mkv")
    assert once.endswith(".mkv")
    assert os_manager.get_sanitize_path(once) == once


def test_long_title_keeps_its_extension():
    result = os_manager.get_sanitize_file("A" * 300 + ".mkv")
    assert result.endswith(".mkv")
    assert len(result) <= 255


def test_emoji_only_titles_get_distinct_stable_placeholders():
    first = os_manager.get_sanitize_file("\U0001F3AC\U0001F525")
    second = os_manager.get_sanitize_file("\U0001F37F")
    assert first and second and first != second
    assert os_manager.get_sanitize_file("\U0001F3AC\U0001F525") == first
    assert os_manager.get_sanitize_file("\U0001F3AC.mkv").endswith(".mkv")
    assert os_manager.get_sanitize_file("\U0001F3AC.mkv") != ".mkv"
