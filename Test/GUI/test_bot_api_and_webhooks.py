# 05.10.26
# ruff: noqa: E402

"""``/api/bot/*`` (the bridge used by the Telegram bot) and the ARR webhooks: shared-secret handling and input validation."""

import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "GUI"
for path in (ROOT, GUI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

import pytest
from django.core.management import call_command
from django.test import Client

from searchapp import api_bot
from searchapp.arr import arr_service

SECRET = "s3cret-token"
HEADER = api_bot.BOT_TOKEN_HEADER


@pytest.fixture(scope="module")
def client():
    call_command("migrate", verbosity=0)
    return Client(HTTP_HOST="localhost")


def _post(client, url, body, **headers):
    return client.post(url, data=json.dumps(body), content_type="application/json", **headers)


# --- /api/bot/*: shared secret --------------------------------------------------------------------------------------------
BOT_GET = ["/api/bot/sites/", "/api/bot/status/", "/api/bot/logs/"]
BOT_POST = ["/api/bot/search/", "/api/bot/seasons/", "/api/bot/download/", "/api/bot/cancel/"]


@pytest.mark.parametrize("url", BOT_GET)
def test_bot_get_endpoints_are_open_when_no_secret_is_configured(client, monkeypatch, url):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)

    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url", BOT_GET)
def test_bot_get_endpoints_need_the_secret_when_one_is_configured(client, monkeypatch, url):
    monkeypatch.setenv("VIBRAVID_BOT_SECRET", SECRET)

    assert client.get(url).status_code == 403
    assert client.get(url, headers={HEADER: "wrong"}).status_code == 403
    assert client.get(url, headers={HEADER: SECRET}).status_code == 200


@pytest.mark.parametrize("url", BOT_POST)
def test_bot_post_endpoints_need_the_secret_when_one_is_configured(client, monkeypatch, url):
    monkeypatch.setenv("VIBRAVID_BOT_SECRET", SECRET)

    assert _post(client, url, {}).status_code == 403
    assert _post(client, url, {}, headers={HEADER: "wrong"}).status_code == 403
    assert _post(client, url, {}, headers={HEADER: SECRET}).status_code == 400  # authorized, but the body is empty


@pytest.mark.parametrize(
    "url, message",
    [
        ("/api/bot/search/", "query mancante"),
        ("/api/bot/seasons/", "parametri mancanti"),
        ("/api/bot/download/", "parametri mancanti"),
        ("/api/bot/cancel/", "download_id o series_name mancante"),
    ],
)
def test_bot_post_endpoints_validate_their_input(client, monkeypatch, url, message):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)
    response = _post(client, url, {})

    assert response.status_code == 400
    assert response.json() == {"error": message}


@pytest.mark.parametrize("url", BOT_POST)
def test_bot_post_endpoints_treat_a_body_that_is_not_json_as_empty(client, monkeypatch, url):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)
    response = client.post(url, data="not json", content_type="application/json")

    assert response.status_code == 400


@pytest.mark.parametrize("url", BOT_POST)
@pytest.mark.parametrize("body", [[], "text", 3, {"site": "x", "payload": ["not", "a", "dict"]}])
def test_bot_post_endpoints_reject_json_that_is_not_an_object(client, monkeypatch, url, body):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)

    assert _post(client, url, body).status_code == 400


@pytest.mark.parametrize("url", BOT_POST)
def test_bot_post_endpoints_refuse_what_another_site_could_send_when_no_secret_is_set(client, monkeypatch, url):
    """The views are csrf_exempt: without a secret, a page on another site could POST a text/plain form whose body parses as JSON."""
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)
    smuggled = '{"site": "x", "payload": {"name": "x", "type": "film"}, "a": "="}'

    assert client.post(url, data=smuggled, content_type="text/plain").status_code == 403
    assert _post(client, url, {}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert _post(client, url, {}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 400  # allowed, body empty


@pytest.mark.parametrize("url", BOT_GET)
def test_bot_get_endpoints_refuse_post(client, monkeypatch, url):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)

    assert _post(client, url, {}).status_code == 405


# --- ARR webhooks ------------------------------------------------------------------------------------------------------------

WEBHOOKS = [
    ("/api/arr/webhook/seerr/", "seerr", "enable_seerr_webhook"),
    ("/api/arr/webhook/sonarr/", "sonarr_webhook", "enable_sonarr_webhook"),
    ("/api/arr/webhook/radarr/", "radarr_webhook", "enable_radarr_webhook"),
]


def _arr_config(monkeypatch, **overrides):
    config = {"enabled": True, "enable_seerr_webhook": True, "enable_sonarr_webhook": True, "enable_radarr_webhook": True}
    config.update(overrides)
    monkeypatch.setattr(arr_service, "_load_arr_config", lambda: config)


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_is_ignored_when_arr_is_disabled(client, monkeypatch, url, section, flag):
    _arr_config(monkeypatch, enabled=False)
    response = _post(client, url, {})

    assert response.status_code == 200 and response.json()["status"] == "disabled"


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_is_ignored_when_its_own_switch_is_off(client, monkeypatch, url, section, flag):
    _arr_config(monkeypatch, **{flag: False})
    response = _post(client, url, {})

    assert response.status_code == 200 and response.json()["status"] == "disabled"


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_rejects_a_missing_or_wrong_token(client, monkeypatch, url, section, flag):
    _arr_config(monkeypatch, **{section: {"webhook_secret": SECRET}})

    assert _post(client, url, {}).status_code == 403
    assert _post(client, url, {}, headers={"X-Webhook-Token": "wrong"}).status_code == 403


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_with_the_right_token_still_validates_the_body(client, monkeypatch, url, section, flag):
    _arr_config(monkeypatch, **{section: {"webhook_secret": SECRET}})
    response = client.post(url, data="not json", content_type="application/json", headers={"X-Webhook-Token": SECRET})

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid JSON"


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
@pytest.mark.parametrize("body", [[], "text", 3, {"eventType": None, "notification_type": None}])
def test_webhook_answers_a_body_that_is_not_an_object_with_a_400_and_no_exception_text(client, monkeypatch, url, section, flag, body):
    """`[]` reached payload.get() and the 500 carried "'list' object has no attribute 'get'" back to the caller."""
    _arr_config(monkeypatch, **{section: {"webhook_secret": SECRET}})
    monkeypatch.setattr(arr_service, "trigger_webhook_sync", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(arr_service, "trigger_sonarr_webhook_sync", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(arr_service, "trigger_radarr_webhook_sync", lambda *a, **k: None, raising=False)
    response = _post(client, url, body, headers={"X-Webhook-Token": SECRET})

    assert response.status_code in (200, 400)
    assert "attribute" not in response.content.decode()


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
@pytest.mark.parametrize("valid_token", [False, True])
def test_webhook_does_not_log_auth_headers_or_raw_body(client, monkeypatch, caplog, url, section, flag, valid_token):
    secret = "webhook-secret-should-not-be-logged"
    supplied_token = secret if valid_token else "incorrect-token-should-not-be-logged"
    _arr_config(monkeypatch, **{section: {"webhook_secret": secret}})

    with caplog.at_level(logging.INFO, logger="searchapp.views.arr"):
        response = client.post(
            url,
            data="invalid-json-with-sensitive-body-value",
            content_type="application/json",
            headers={
                "X-Webhook-Token": supplied_token,
                "Authorization": "Bearer sensitive-authorization-value",
            },
        )

    assert response.status_code == (400 if valid_token else 403)
    for sensitive in (
        secret,
        supplied_token,
        "sensitive-authorization-value",
        "sensitive-body-value",
    ):
        assert sensitive not in caplog.text


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_does_not_log_parsed_test_payload(client, monkeypatch, caplog, url, section, flag):
    secret = "webhook-secret-should-not-be-logged"
    _arr_config(monkeypatch, **{section: {"webhook_secret": secret}})
    payload = {
        "notification_type": "TEST_NOTIFICATION",
        "eventType": "Test",
        "media": {"media_type": "movie"},
        "series": {"id": 1},
        "movie": {"id": 1},
        "private": "sensitive-json-payload-value",
    }

    with caplog.at_level(logging.INFO, logger="searchapp.views.arr"):
        response = _post(client, url, payload, headers={"X-Webhook-Token": secret})

    assert response.status_code == 200
    assert secret not in caplog.text
    assert "sensitive-json-payload-value" not in caplog.text


@pytest.mark.parametrize("url, section, flag", WEBHOOKS)
def test_webhook_downloads_nothing_when_automatic_downloads_are_off(client, monkeypatch, url, section, flag):
    def must_not_sync(*args, **kwargs):
        raise AssertionError("a webhook started a download in manual mode")

    for name in ("trigger_webhook_sync", "trigger_sonarr_webhook_sync", "trigger_radarr_webhook_sync"):
        monkeypatch.setattr(arr_service, name, must_not_sync)
    _arr_config(monkeypatch, auto_download=False)
    payload = {"notification_type": "MEDIA_APPROVED", "eventType": "Download", "media": {"tmdbId": 1, "media_type": "movie"}}

    response = _post(client, url, payload)

    assert response.status_code == 200 and response.json()["status"] == "manual"


# --- /api/bot/download/ -----------------------------------------------------------------------------------------------------
def _fake_jobs(monkeypatch):
    calls = []

    def fake_run(site, payload, season=None, episodes=None, media_type="Film", **_kw):
        calls.append(site)
        return type("Job", (), {"download_id": f"{site}_job{len(calls)}"})()

    monkeypatch.setattr(api_bot, "_run_download_in_thread", fake_run)
    return calls


def test_bot_download_rejects_an_unknown_site_before_queuing(client, monkeypatch):
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)
    calls = _fake_jobs(monkeypatch)

    response = _post(client, "/api/bot/download/", {"site": "nosuchsite", "payload": {"name": "X", "is_movie": True}})

    assert response.status_code == 400
    assert response.json() == {"error": "sito non disponibile"}
    assert calls == []


def test_bot_download_returns_the_id_of_the_job_it_queued(client, monkeypatch):
    """Two identical requests must not share an id: a cancel from one chat would stop the other."""
    monkeypatch.delenv("VIBRAVID_BOT_SECRET", raising=False)
    monkeypatch.setattr(api_bot, "is_site_available", lambda site: site == "streamingcommunity")
    _fake_jobs(monkeypatch)
    body = {"site": "streamingcommunity", "payload": {"name": "Film1", "is_movie": True}}

    first = _post(client, "/api/bot/download/", body).json()
    second = _post(client, "/api/bot/download/", body).json()

    assert first == {"queued": True, "download_id": "streamingcommunity_job1", "title": "Film1"}
    assert second["download_id"] == "streamingcommunity_job2"


# --- Sonarr "On Episode File Delete" (documented trigger in arr.md) ----------------------------------------------------------
def test_sonarr_episode_file_delete_starts_a_sync(client, monkeypatch):
    synced = []
    monkeypatch.setattr(arr_service, "trigger_sonarr_webhook_sync", lambda payload: synced.append(payload) or 0)
    _arr_config(monkeypatch, auto_download=True)
    payload = {"eventType": "EpisodeFileDelete", "series": {"id": 1, "title": "Show", "tmdbId": 1001}, "episodes": []}

    response = _post(client, "/api/arr/webhook/sonarr/", payload)

    assert response.status_code == 200
    assert response.json()["message"] == "Processing Sonarr event EPISODEFILEDELETE"
