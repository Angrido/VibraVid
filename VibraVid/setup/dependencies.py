# 12.11.26

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .checker import (
    check_deno,
    check_dovi_tool,
    check_ffmpeg,
    check_flux,
    check_mkvmerge,
    check_mkvpropedit,
    check_velora,
    check_yt_dlp,
)

REQUIRED_DEPENDENCIES = frozenset({"FFmpeg", "FFprobe", "mkvmerge", "Velora"})

_VERSION_FLAGS = {
    "FFmpeg": ["-version"],
    "FFprobe": ["-version"],
    "dovi_tool": ["--version"],
    "mkvmerge": ["--version"],
    "mkvpropedit": ["--version"],
    "yt-dlp": ["--version"],
    "deno": ["--version"],
}


def extract_version(text: str) -> str:
    for line in text.splitlines():
        if "version" in line.lower():
            match = re.search(r"v?(\d+(?:\.\d+){1,3})", line)
            if match:
                return match.group(1)
    match = re.search(r"v?(\d+(?:\.\d+){1,3})", text)
    return match.group(1) if match else ""


def probe_binary_version(dep_name: str, path: str | None) -> str:
    if not path:
        return ""
    try:
        if dep_name == "Velora":
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
            raw = (out.stdout or out.stderr).strip()
            first = raw.splitlines()[0] if raw else ""
            try:
                return str(json.loads(first).get("version", "")) or extract_version(raw)
            except (ValueError, AttributeError):
                return extract_version(raw)
        flags = _VERSION_FLAGS.get(dep_name, ["--version"])
        out = subprocess.run([path, *flags], capture_output=True, text=True, timeout=5)
        return extract_version(f"{out.stdout}\n{out.stderr}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def external_dependencies() -> list[tuple[str, str | None]]:
    ffmpeg_path, ffprobe_path = check_ffmpeg(download=False)
    return [
        ("FFmpeg", ffmpeg_path),
        ("FFprobe", ffprobe_path),
        ("flux", check_flux(download=False)),
        ("dovi_tool", check_dovi_tool(download=False)),
        ("mkvmerge", check_mkvmerge(download=False)),
        ("mkvpropedit", check_mkvpropedit(download=False)),
        ("Velora", check_velora(download=False)),
        ("yt-dlp", check_yt_dlp(download=False)),
        ("deno", check_deno(download=False)),
    ]


def dependency_report() -> list[dict]:
    deps = external_dependencies()
    with ThreadPoolExecutor(max_workers=len(deps)) as pool:
        versions = list(pool.map(lambda dep: probe_binary_version(*dep), deps))
    return [
        {"name": name, "path": path, "version": version, "found": bool(path), "required": name in REQUIRED_DEPENDENCIES}
        for (name, path), version in zip(deps, versions, strict=True)
    ]
