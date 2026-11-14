# 12.11.26
# ruff: noqa: E402

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
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from django.core.management import call_command
from django.test import Client

from searchapp import site_reachability
from searchapp.views import system


class _FakeResponse:
    def __init__(self, url, status_code):
        self.url = url
        self.status_code = status_code


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _serve(monkeypatch, outcome):
    monkeypatch.setattr(site_reachability, "create_client", lambda **kwargs: _FakeClient(outcome))


@pytest.mark.parametrize(
    "outcome, state",
    [
        (_FakeResponse("https://site.example/", 200), "up"),
        (_FakeResponse("https://www.site.example/home", 200), "up"),
        (_FakeResponse("https://consent.site.example/", 200), "up"),
        (_FakeResponse("https://site-new.example/", 200), "moved"),
        (_FakeResponse("https://site.example/", 503), "error"),
        (CurlConnectionError("Could not resolve host"), "down"),
    ],
)
def test_check_site_classifies_the_response(monkeypatch, outcome, state):
    _serve(monkeypatch, outcome)

    result = site_reachability.check_site("demo", "https://site.example/")

    assert result["state"] == state


def test_check_site_reports_the_new_domain_after_a_redirect(monkeypatch):
    _serve(monkeypatch, _FakeResponse("https://site-new.example/", 200))

    result = site_reachability.check_site("demo", "https://site.example/")

    assert result["final_url"] == "https://site-new.example/"
    assert result["final_host"] == "site-new.example"


def test_check_site_without_url_does_no_request(monkeypatch):
    monkeypatch.setattr(site_reachability, "create_client", lambda **kwargs: pytest.fail("no request expected"))

    assert site_reachability.check_site("demo", "")["state"] == "unknown"


def test_site_url_prefers_the_configured_domain(monkeypatch):
    monkeypatch.setattr(
        site_reachability.config_manager.domain,
        "get",
        lambda site, key, default="": "https://live.example/" if site == "raiplay" else default,
    )

    assert site_reachability.site_url("raiplay") == "https://live.example/"
    assert site_reachability.site_url("crunchyroll") == "https://www.crunchyroll.com/"
    assert site_reachability.site_url("not_a_site") == ""


def test_site_url_drops_a_non_http_domain(monkeypatch):
    monkeypatch.setattr(site_reachability.config_manager.domain, "get", lambda site, key, default="": "javascript:alert(1)")

    assert site_reachability.site_url("streamingcommunity") == ""


def test_check_sites_reuses_recent_results_until_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(site_reachability, "_cached_results", {"at": 0.0, "sites": None, "results": []})
    monkeypatch.setattr(site_reachability, "site_url", lambda site: "https://site.example/")
    monkeypatch.setattr(site_reachability, "check_site", lambda site, url: calls.append(site) or {"site": site})

    site_reachability.check_sites(["demo"])
    site_reachability.check_sites(["demo"])
    assert calls == ["demo"]

    site_reachability.check_sites(["demo"], refresh=True)
    assert calls == ["demo", "demo"]


def test_site_status_endpoint_lists_every_available_site(monkeypatch):
    call_command("migrate", verbosity=0)
    monkeypatch.setattr(system, "get_available_sites", lambda: ["b_site", "a_site"])
    monkeypatch.setattr(system, "check_sites", lambda sites, refresh: [{"site": s, "state": "up"} for s in sites])

    response = Client(HTTP_HOST="localhost").get("/api/site-status/")

    assert response.status_code == 200
    assert [s["site"] for s in response.json()["sites"]] == ["a_site", "b_site"]


def test_check_site_proposes_the_root_of_the_new_domain(monkeypatch):
    _serve(monkeypatch, _FakeResponse("https://site-new.example/home?ref=1", 200))

    result = site_reachability.check_site("demo", "https://site.example/")

    assert result["proposed_url"] == "https://site-new.example/"


def _post_domain(site):
    call_command("migrate", verbosity=0)
    return Client(HTTP_HOST="localhost").post("/api/site-domain/", data=f'{{"site": "{site}"}}', content_type="application/json")


def test_the_new_domain_is_applied_only_when_asked_and_only_if_the_site_still_redirects(monkeypatch):
    approved = []
    monkeypatch.setattr(system, "get_available_sites", lambda: ["demo"])
    monkeypatch.setattr(system, "site_url", lambda site: "https://site.example/")
    monkeypatch.setattr(system.config_manager, "approve_domain", lambda site, url: approved.append((site, url)))
    _serve(monkeypatch, _FakeResponse("https://site-new.example/home", 200))

    response = _post_domain("demo")

    assert response.status_code == 200
    assert response.json()["url"] == "https://site-new.example/"
    assert approved == [("demo", "https://site-new.example/")]

    _serve(monkeypatch, _FakeResponse("https://site.example/", 200))
    assert _post_domain("demo").status_code == 409
    assert len(approved) == 1


def test_checking_the_sites_never_replaces_a_domain(monkeypatch):
    monkeypatch.setattr(site_reachability, "_cached_results", {"at": 0.0, "sites": None, "results": []})
    monkeypatch.setattr(site_reachability, "site_url", lambda site: "https://site.example/")
    monkeypatch.setattr(site_reachability.config_manager, "approve_domain", lambda *a: pytest.fail("needs the user's choice"))
    _serve(monkeypatch, _FakeResponse("https://site-new.example/", 200))

    assert site_reachability.check_sites(["demo"], refresh=True)[0]["state"] == "moved"


def test_an_unknown_site_cannot_get_a_new_domain(monkeypatch):
    monkeypatch.setattr(system, "get_available_sites", lambda: ["demo"])

    assert _post_domain("other").status_code == 400
