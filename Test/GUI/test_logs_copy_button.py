# 16.11.26

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "GUI"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

from django.core.management import call_command
from django.test import Client

from searchapp import i18n


@pytest.fixture(autouse=True)
def _db():
    call_command("migrate", verbosity=0, interactive=False)


def _logs_page() -> str:
    return Client().get("/logs/", HTTP_HOST="127.0.0.1", HTTP_ACCEPT_LANGUAGE="en").content.decode("utf-8")


def test_logs_page_has_a_copy_button_disabled_until_a_log_is_loaded():
    page = _logs_page()
    assert 'id="cn-logs-copy" disabled>Copy</button>' in page
    assert 'id="cn-logs-copy-status" role="status"' in page


def test_copy_falls_back_to_selection_when_the_clipboard_api_is_unavailable():
    page = _logs_page()
    assert "navigator.clipboard && window.isSecureContext" in page
    assert 'document.execCommand("copy")' in page


def test_copy_texts_are_translated_in_italian():
    catalog = i18n.load_catalog("it")
    for text in ("Copy", "Log copied to clipboard.", "Copy failed. The text is selected: press Ctrl+C."):
        assert catalog[text].strip()
