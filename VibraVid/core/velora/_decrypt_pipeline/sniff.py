# 01.04.25

from pathlib import Path

from VibraVid.core.ui.tracker import context_tracker


def _reads_as_self_initializing_mp4(path: Path) -> bool:
    """True if *path* starts with its own `ftyp` box — a complete, independently decryptable MP4 document — rather than a bare `moof`/`mdat` fragment meant to share a separate init segment."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return False
    return len(head) == 8 and head[4:8] == b"ftyp"


def _reads_as_plaintext_ts(path: Path) -> bool:
    """True if *path* reads as MPEG-TS (sync byte 0x47 at offsets 0, 188 and 376, as far as the file goes) -- already decrypted or never encrypted, so decrypting it again would corrupt it. One 0x47 byte is not enough: CBC ciphertext starts with it about once in 256 segments."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(377)
    except OSError:
        return False
    return bool(head) and all(head[offset] == 0x47 for offset in (0, 188, 376) if offset < len(head))


def _skip_post_decrypt() -> bool:
    """Debug switch (--no-decrypt CLI flag): leave segments encrypted, no decrypt at all."""
    return context_tracker.skip_decrypt


def _streaming_mux_enabled(site: str | None = None) -> bool:
    """Fast path runs when process.live_mux (login.toml) or PROCESS.use_live_mux (config.toml) is true, or --livemux; --no-livemux always disables it."""
    from VibraVid.core.downloader.util.live_switches import live_mux_allowed

    return live_mux_allowed(site)[0]
