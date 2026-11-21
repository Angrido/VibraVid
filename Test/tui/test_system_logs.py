# 21.11.26

from pathlib import Path
from types import SimpleNamespace

from VibraVid.tui.screens.system import SystemScreen


class _Viewer:
    def __init__(self):
        self.written: list[str] = []

    def clear(self):
        self.written.clear()

    def write(self, text):
        self.written.append(str(text))


def test_log_viewer_reads_only_the_tail_of_a_big_log(tmp_path, monkeypatch):
    """Highlighting a log runs on the UI thread: a log of hundreds of MB must not be read whole."""
    log = tmp_path / "big.log"
    log.write_text("".join(f"line {n} {'x' * 200}\n" for n in range(20_000)), encoding="utf-8")

    def whole_file_read(self, *args, **kwargs):
        raise AssertionError("the whole log was read")

    monkeypatch.setattr(Path, "read_text", whole_file_read)
    viewer = _Viewer()

    SystemScreen._display_log(SimpleNamespace(query_one=lambda *args: viewer), log)

    body = [line for line in viewer.written if line.startswith("line ")]
    assert not any("Error reading" in line for line in viewer.written)
    assert len(body) == 1000
    assert body[-1].startswith("line 19999 ") and body[0].startswith("line 19000 ")


def test_log_viewer_shows_a_short_log_whole(tmp_path):
    log = tmp_path / "small.log"
    log.write_text("first\nsecond\n", encoding="utf-8")
    viewer = _Viewer()

    SystemScreen._display_log(SimpleNamespace(query_one=lambda *args: viewer), log)

    assert viewer.written[1:] == ["first", "second"]
