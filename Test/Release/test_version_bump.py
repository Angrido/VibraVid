# 12.11.26

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "version_bump.py"
spec = importlib.util.spec_from_file_location("version_bump", SCRIPT)
version_bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_bump)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("[GUI] Fix the ARR retry button", "patch"),
        ("[Muxing] Log the errors that best-effort steps used to swallow", "patch"),
        ("[GUI] Address review findings on retry", "patch"),
        ("[GUI] Add a Retry button to failed downloads", "minor"),
        ("[Service] Support a new site", "minor"),
        ("[CLI] Rename flags\n\nBREAKING CHANGE: --old is gone", "major"),
        ("[Docs] Add a page about hooks", None),
        ("[Test] Add muxing coverage", None),
        ("[Docs] [GUI] Add a settings tab", "minor"),
        ("[RELEASE] Version 1.5.0", None),
        ("Merge pull request #13 from Angrido/branch\n\n[GUI] Add something", None),
        ("", None),
    ],
)
def test_commit_message_maps_to_bump_level(message, expected):
    assert version_bump.classify_commit(message) == expected


def test_highest_level_among_commits_wins():
    assert version_bump.bump_level(["[GUI] Fix a label", "[GUI] Add a page", "[HLS] Fix a crash"]) == "minor"


def test_no_releasable_commits_means_no_bump():
    assert version_bump.bump_level(["[Docs] Fix a typo", "[RELEASE] Version 1.5.0"]) is None


@pytest.mark.parametrize(
    ("level", "expected"),
    [("patch", "1.5.1"), ("minor", "1.6.0"), ("major", "2.0.0")],
)
def test_next_version_resets_lower_parts(level, expected):
    assert version_bump.next_version("1.5.0", level) == expected


def test_write_version_updates_package_and_pyproject(tmp_path):
    version_file = tmp_path / "version.py"
    version_file.write_text('__title__ = "VibraVid"\n__version__ = "1.5.0"\n', encoding="utf-8")
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text(
        '[project]\nname = "VibraVid"\nversion = "1.5.0"\n\n[tool.x]\nversion = "9.9.9"\n', encoding="utf-8"
    )

    version_bump.write_version("1.6.0", version_file, pyproject_file)

    assert version_bump.read_version(version_file) == "1.6.0"
    assert 'version = "1.6.0"' in pyproject_file.read_text(encoding="utf-8")
    assert 'version = "9.9.9"' in pyproject_file.read_text(encoding="utf-8")


def test_package_and_pyproject_versions_match():
    pyproject_text = (SCRIPT.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version_bump.read_version()}"' in pyproject_text
