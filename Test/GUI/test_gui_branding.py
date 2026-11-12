# 12.11.26

from pathlib import Path

SEARCHAPP = Path(__file__).resolve().parents[2] / "GUI" / "searchapp"


def _branded_files():
    yield from (SEARCHAPP / "templates").rglob("*.html")
    yield from (SEARCHAPP / "i18n").glob("*.json")
    yield from (SEARCHAPP / "static").rglob("*.css")


def test_gui_has_no_leftover_previous_brand():
    leftovers = [str(p) for p in _branded_files() if "arrowar" in p.read_text(encoding="utf-8").lower()]
    assert leftovers == []


def test_shell_and_login_use_vibravid_wordmark_and_logo():
    for name in ("cinema_base.html", "cinema_login.html"):
        html = (SEARCHAPP / "templates" / "searchapp" / name).read_text(encoding="utf-8")
        assert "Vibra<i>Vid</i>" in html
        assert "searchapp/img/logo.svg" in html
    assert (SEARCHAPP / "static" / "searchapp" / "img" / "logo.svg").is_file()
