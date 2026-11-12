# 12.11.26

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "VibraVid" / "utils" / "upload" / "version.py"
PYPROJECT_FILE = ROOT / "pyproject.toml"
LEVELS = ("patch", "minor", "major")
RELEASE_SUBJECT = re.compile(r"^\[RELEASE\]\s*Version\s+\d+\.\d+\.\d+", re.IGNORECASE)
AREA_TAGS = re.compile(r"^(\[[^\]]+\]\s*)+")
FEATURE_VERBS = {"add", "adds", "added", "introduce", "implement", "support", "allow", "enable", "new"}
AREAS_WITHOUT_RELEASE = {"docs", "test", "tests", "ci"}


def classify_commit(message: str) -> str | None:
    lines = message.strip().splitlines()
    if not lines:
        return None
    subject = lines[0].strip()
    if subject.startswith("Merge ") or RELEASE_SUBJECT.match(subject):
        return None
    if "BREAKING" in message:
        return "major"
    tags = AREA_TAGS.match(subject)
    areas = {area.strip().lower() for area in re.findall(r"\[([^\]]+)\]", tags[0])} if tags else set()
    if areas and areas <= AREAS_WITHOUT_RELEASE:
        return None
    words = AREA_TAGS.sub("", subject).split()
    if words and words[0].lower().rstrip(":") in FEATURE_VERBS:
        return "minor"
    return "patch"


def bump_level(messages: list[str]) -> str | None:
    levels = [level for level in map(classify_commit, messages) if level]
    return max(levels, key=LEVELS.index) if levels else None


def next_version(current: str, level: str) -> str:
    major, minor, patch = (int(part) for part in current.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def read_version(version_file: Path = VERSION_FILE) -> str:
    return re.search(r'__version__ = "([^"]+)"', version_file.read_text(encoding="utf-8"))[1]


def write_version(version: str, version_file: Path = VERSION_FILE, pyproject_file: Path = PYPROJECT_FILE) -> None:
    version_text = version_file.read_text(encoding="utf-8")
    version_file.write_text(
        re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', version_text), encoding="utf-8"
    )
    pyproject_text = pyproject_file.read_text(encoding="utf-8")
    pyproject_file.write_text(
        re.sub(r'^version = "[^"]+"', f'version = "{version}"', pyproject_text, count=1, flags=re.MULTILINE),
        encoding="utf-8",
    )


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def commits_since_last_release() -> list[str]:
    last_release = _git("log", "-1", "--format=%H", "-E", r"--grep=^\[RELEASE\] Version").strip()
    revision_range = [f"{last_release}..HEAD"] if last_release else ["HEAD"]
    return [message for message in _git("log", "--format=%B%x1e", *revision_range).split("\x1e") if message.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("auto", *LEVELS), default="auto")
    level = parser.parse_args().level
    if level == "auto":
        level = bump_level(commits_since_last_release())
    if not level:
        return
    version = next_version(read_version(), level)
    write_version(version)
    print(version)


if __name__ == "__main__":
    main()
