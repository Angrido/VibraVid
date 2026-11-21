# 16.04.24

import logging
import os
import subprocess
from pathlib import Path

from VibraVid.core.ui.bar_manager import console
from VibraVid.setup import get_ffmpeg_path, get_flux_path

from .detect import detect_subtitle_format, fix_subtitle_extension
from .sanitize import sanitize_vtt_file
from .ttml import convert_ttml_to_format

logger = logging.getLogger(__name__)
_SUPPORTED_TARGET_FORMATS = ("vtt", "srt", "ass")
_warned_force_values: set[str] = set()


def convert_subtitle(
    subtitle_path: str, target_format: str, chunk_offsets: list[float] | None = None, media_duration: float | None = None
) -> str | None:
    """Converts a subtitle file to the target format using FFmpeg.

    Args:
      - 'vtt', 'srt', 'ass': convert to specified container format
      - 'auto': detect format and either rename or convert as needed
      - 'copy': leave the file untouched (no conversion or sanitization)
      - 'chunk_offsets': optional list of chunk offsets for TTML conversion (if applicable)
      - 'media_duration': optional duration (s) of the media, so a late first TTML cue is not rebased to 0
    """
    # no-op when user requests copy
    if target_format == "copy":
        return subtitle_path

    # Any other value was used as a file extension ("on" -> "sub.on") and the subtitle was lost: fall back to auto.
    if target_format not in ("auto", *_SUPPORTED_TARGET_FORMATS):
        if target_format not in _warned_force_values:
            _warned_force_values.add(target_format)
            logger.warning(f"force_subtitle = {target_format!r} is not supported (use auto, copy, srt, vtt or ass): using auto")
        target_format = "auto"

    if target_format == "auto":
        detected_format = detect_subtitle_format(subtitle_path)

        # If it's TTML, we MUST convert it because most players/containers don't support raw TTML
        if detected_format == "ttml":
            output_path = f"{os.path.splitext(subtitle_path)[0]}.srt"
            if convert_ttml_to_format(subtitle_path, output_path, "srt", chunk_offsets=chunk_offsets, media_duration=media_duration):
                return output_path
            return None

        # Otherwise, just ensure extension is correct
        return fix_subtitle_extension(subtitle_path)

    current_format = detect_subtitle_format(subtitle_path)
    if current_format == target_format:
        return subtitle_path

    output_path = f"{os.path.splitext(subtitle_path)[0]}.{target_format}"

    # Special high-fidelity converter for TTML -> (SRT, VTT)
    if current_format == "ttml":
        if target_format in ["srt", "vtt"]:
            if convert_ttml_to_format(subtitle_path, output_path, target_format, chunk_offsets=chunk_offsets, media_duration=media_duration):
                return output_path
        elif target_format == "ass":
            tmp_srt = f"{os.path.splitext(subtitle_path)[0]}_tmp.srt"
            if convert_ttml_to_format(subtitle_path, tmp_srt, "srt", chunk_offsets=chunk_offsets, media_duration=media_duration):
                res = convert_subtitle(tmp_srt, "ass")
                try:
                    os.remove(tmp_srt)
                except OSError as exc:
                    logger.debug("Could not remove a temporary path: %s", exc)
                return res

        return None

    # Already named for the target (e.g. VTT content in a .srt): ffmpeg cannot write a file onto itself, and a
    # failed conversion would drop the subtitle, so keep it as it is.
    if os.path.normcase(os.path.abspath(output_path)) == os.path.normcase(os.path.abspath(subtitle_path)):
        logger.info(f"convert_subtitle: {os.path.basename(subtitle_path)} already has the .{target_format} extension, keeping it")
        return subtitle_path

    try:
        cmd = [get_ffmpeg_path(), "-v", "error", "-i", subtitle_path, output_path, "-y"]
        logger.info(f"Running convert_subtitle for {os.path.basename(subtitle_path)} with cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            logger.info(f"convert_subtitle OK -> {os.path.basename(output_path)}")
            return output_path
        else:
            console.print(f"[red]    Failed to convert subtitle to {target_format}: {result.stderr}")
            return None

    except Exception as e:
        console.print(f"[red]    Error converting subtitle: {str(e)}")
        return None


def extract_vtt_from_wvtt_mp4(wvtt_path: str, output_vtt_path: str | None = None) -> str | None:
    """Extract a plain WebVTT (.vtt) file from a fragmented MP4 container that carries a WVTT (WebVTT-in-MP4) subtitle track."""
    if not os.path.exists(wvtt_path):
        logger.error(f"extract_vtt_from_wvtt_mp4: input not found: {wvtt_path}")
        return None

    if output_vtt_path is None:
        output_vtt_path = str(Path(wvtt_path).with_suffix(".vtt"))

    try:
        flux = get_flux_path()
        cmd = [flux, "--extract-text", "-i", wvtt_path, "-o", output_vtt_path]
        logger.info(f"Running extract_vtt_from_wvtt_mp4 [flux] for {os.path.basename(wvtt_path)} with cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0 and os.path.exists(output_vtt_path) and os.path.getsize(output_vtt_path) > 0:
            logger.info(f"extract_vtt_from_wvtt_mp4 [flux] OK -> {os.path.basename(output_vtt_path)}")
            sanitize_vtt_file(output_vtt_path)
            return output_vtt_path
        else:
            logger.warning(f"extract_vtt_from_wvtt_mp4 [flux] failed (rc={result.returncode}): {result.stderr.strip()[:200]}")

    except Exception as exc:
        logger.warning(f"extract_vtt_from_wvtt_mp4 [flux] exception: {exc}")

    return None
