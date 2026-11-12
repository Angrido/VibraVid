# 12.11.26

import logging
import os

from VibraVid.core.downloader.util import _post_decrypt
from VibraVid.core.downloader.util._post_decrypt import PostDownloadDecryptor


def test_failed_temporary_file_removal_is_logged_not_swallowed(tmp_path, monkeypatch, caplog):
    leftover = tmp_path / "segment.dec"
    leftover.write_bytes(b"x")

    def refuse(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(os, "remove", refuse)
    with caplog.at_level(logging.DEBUG, logger=_post_decrypt.logger.name):
        PostDownloadDecryptor._remove(str(leftover))

    assert leftover.exists()
    assert "Could not remove a temporary path" in caplog.text
    assert "segment.dec" in caplog.text


def test_corrupt_gzip_looking_segment_falls_back_to_raw_bytes(tmp_path, monkeypatch):
    from VibraVid.core.decryptor import _segment_crypto

    raw = b"\x1f\x8b\x08\x00" + b"\xff" * 28
    seen = []
    monkeypatch.setattr(_segment_crypto, "decrypt_aes128", lambda data, *args: seen.append(data) or data)
    source = tmp_path / "seg.ts"
    source.write_bytes(raw)

    _segment_crypto.decrypt_aes128_file(source, tmp_path / "seg.dec", b"k" * 16, None, 0)

    assert seen == [raw]
