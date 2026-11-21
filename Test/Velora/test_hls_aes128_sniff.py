# 21.11.26

"""HLS AES-128: a fresh segment is always decrypted; only a resumed one that really reads as MPEG-TS is left alone.

CBC ciphertext starts with a random byte, so a first byte of 0x47 alone happens on about 1 segment in 256.
"""

import threading
from types import SimpleNamespace

import pytest

from VibraVid.core.velora._decrypt_pipeline import hls as hls_module
from VibraVid.core.velora._decrypt_pipeline.hls import HlsDecryptMixin
from VibraVid.core.velora._decrypt_pipeline.segment_io import SegmentIOMixin
from VibraVid.core.velora._decrypt_pipeline.sniff import _reads_as_plaintext_ts


class _Host(HlsDecryptMixin, SegmentIOMixin):
    pass


def _ts_bytes(packets: int = 3) -> bytes:
    return b"".join(b"\x47" + bytes(187) for _ in range(packets))


def _cipher_starting_with_sync_byte() -> bytes:
    return b"\x47" + bytes(range(1, 256)) + bytes(range(256)) * 2


@pytest.fixture
def decrypted(monkeypatch):
    calls = []

    def fake_decrypt(src, dst, key, iv, number):
        calls.append(src.name)
        dst.write_bytes(_ts_bytes())

    monkeypatch.setattr(hls_module, "decrypt_aes128_file", fake_decrypt)
    return calls


def _ctx():
    return SimpleNamespace(live_merger=None, key_cache={}, key_cache_lock=threading.Lock(), all_headers={})


def _seg():
    return {"number": 3, "enc": {"method": "AES-128", "key_bytes": b"k" * 16, "iv": None}}


def test_sniff_needs_the_ts_packet_cadence(tmp_path):
    ts, cipher = tmp_path / "ts.ts", tmp_path / "cipher.ts"
    ts.write_bytes(_ts_bytes())
    cipher.write_bytes(_cipher_starting_with_sync_byte())

    assert _reads_as_plaintext_ts(ts) is True
    assert _reads_as_plaintext_ts(cipher) is False


def test_fresh_segment_starting_with_0x47_is_still_decrypted(tmp_path, decrypted):
    fp = tmp_path / "seg_00003.ts"
    fp.write_bytes(_ts_bytes())

    _Host()._decrypt_hls_segment(_ctx(), fp, _seg())

    assert decrypted == ["seg_00003.ts"]


def test_resumed_plaintext_segment_is_not_decrypted_again(tmp_path, decrypted):
    fp = tmp_path / "seg_00003.ts"
    fp.write_bytes(_ts_bytes())

    _Host()._decrypt_hls_segment(_ctx(), fp, _seg(), skipped=True)

    assert decrypted == []


def test_resumed_ciphertext_that_starts_with_0x47_is_decrypted(tmp_path, decrypted):
    fp = tmp_path / "seg_00003.ts"
    fp.write_bytes(_cipher_starting_with_sync_byte())

    _Host()._decrypt_hls_segment(_ctx(), fp, _seg(), skipped=True)

    assert decrypted == ["seg_00003.ts"]
