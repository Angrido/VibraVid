# 06.06.25

import json
import logging
import secrets
import time

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from searchapp.api import get_api
from searchapp.api.base import Entries

from VibraVid.core.utils.audio_selection import normalize_audio_language
from VibraVid.provider.tmdb import tmdb_client

from ..library_index import owned_episodes
from ._shared import _handle_series_download, _is_anime_source
from .cinema import _duotone

logger = logging.getLogger(__name__)

# The opened title's raw provider payload is kept in the session under a short random key, so the page has a
# plain GET URL (Back, Reload and the language switch never resubmit a form) without the payload in the URL.
_PAGES_SESSION_KEY = "series_pages"
_PAGE_TTL_SECONDS = 6 * 3600
_PAGES_KEPT = 30


def _remember_page(request: HttpRequest, source_alias: str, item_payload_raw: str, audio_language: str | None) -> str:
    now = time.time()
    pages = {
        key: page for key, page in request.session.get(_PAGES_SESSION_KEY, {}).items()
        if now - page.get("at", 0) < _PAGE_TTL_SECONDS
    }
    key = secrets.token_urlsafe(9)
    pages[key] = {"source_alias": source_alias, "item_payload": item_payload_raw,
                  "audio_language": audio_language or "", "at": now}
    request.session[_PAGES_SESSION_KEY] = dict(sorted(pages.items(), key=lambda kv: kv[1]["at"])[-_PAGES_KEPT:])
    return key


def _recall_page(request: HttpRequest, key: str) -> dict | None:
    page = request.session.get(_PAGES_SESSION_KEY, {}).get(key)
    if not isinstance(page, dict) or time.time() - page.get("at", 0) >= _PAGE_TTL_SECONDS:
        return None
    return page


@require_http_methods(["GET", "POST"])
def series_detail(request: HttpRequest) -> HttpResponse:
    """Show series detail page with seasons and episodes."""
    # --- POST with a download_type: handle download requests ---
    if request.method == "POST" and request.POST.get("download_type"):
        return _handle_series_download(request)

    # --- POST without download_type: store the title, then redirect to its GET page ---
    if request.method == "POST":
        source_alias = request.POST.get("source_alias")
        item_payload_raw = request.POST.get("item_payload")
        if not source_alias or not item_payload_raw:
            messages.error(request, "Unable to open this title. Select it again from the search results.")
            return redirect("search_home")
        key = _remember_page(request, source_alias, item_payload_raw, request.POST.get("audio_language"))
        return redirect(f"{reverse('series_detail')}?page={key}")

    # --- GET: show series detail page ---
    page_key = request.GET.get("page")
    if page_key:
        page = _recall_page(request, page_key)
        if page is None:
            messages.error(request, "This page has expired. Open the title again from the search results.")
            return redirect("search_home")
        source_alias, item_payload_raw = page["source_alias"], page["item_payload"]
        requested_audio = page["audio_language"]
    else:
        source_alias = request.GET.get("source_alias")
        item_payload_raw = request.GET.get("item_payload")
        requested_audio = request.GET.get("audio_language")

    if not source_alias or not item_payload_raw:
        return redirect("search_home")

    try:
        item_payload = json.loads(item_payload_raw)
        audio_language = normalize_audio_language(requested_audio or item_payload.get("_audio_language"))
        if audio_language:
            item_payload["_audio_language"] = audio_language
            item_payload_raw = json.dumps(item_payload)
        api = get_api(source_alias)
        entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
        media_item = Entries(**entries_fields)

        # Try to get TMDB backdrop for better background image.
        backdrop_url = media_item.poster  # fallback to original poster
        series_tmdb_id = None
        if not media_item.is_movie:
            try:
                try:
                    series_tmdb_id = int(media_item.tmdb_id) if media_item.tmdb_id else None
                except (TypeError, ValueError):
                    series_tmdb_id = None

                if series_tmdb_id:
                    backdrop = tmdb_client.get_backdrop_url('tv', series_tmdb_id, size="w1920")
                    if backdrop:
                        backdrop_url = backdrop

                else:
                    # Fallback to search by slug/year.
                    year_str = str(media_item.year) if media_item.year else None
                    prefer_anim = _is_anime_source(source_alias)
                    candidates = [media_item.slug, tmdb_client._slugify(media_item.name)]

                    for candidate in dict.fromkeys(c for c in candidates if c):
                        tmdb_result = tmdb_client.get_type_and_id_by_slug_year(
                            candidate, year_str, "tv", prefer_animation=prefer_anim,
                        )
                        if tmdb_result and tmdb_result.get('type') == 'tv':
                            series_tmdb_id = tmdb_result['id']
                            backdrop = tmdb_client.get_backdrop_url('tv', series_tmdb_id, size="w1920")
                            if backdrop:
                                backdrop_url = backdrop
                            break

            except Exception:
                # If TMDB fails, keep original poster
                pass

        # L'id risolto qui sopra non passa dal filtro per provider (_TV_MATCH_SITES): 
        if series_tmdb_id and not item_payload.get("tmdb_id"):
            item_payload = {**item_payload, "tmdb_id": series_tmdb_id}
            item_payload_raw = json.dumps(item_payload)

        seasons = None
        for attempt in range(3):
            try:
                seasons = api.get_series_metadata(media_item)
                break
            except Exception as e:
                logger.warning(f"get_series_metadata failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)

        if not seasons:
            messages.warning(request, "Unable to load season details right now. This may be due to active downloads. Try again in a few minutes.")
            seasons = []  # Allow page to load with empty seasons

        p1, p2 = _duotone(media_item.name)
        series_info = {
            "name": media_item.name,
            "poster": media_item.poster,        # original source poster
            "backdrop": backdrop_url,           # TMDB backdrop or fallback to poster
            "year": media_item.year,
            "source_alias": source_alias,
            "item_payload": item_payload_raw,
            "tmdb_id": series_tmdb_id or media_item.tmdb_id,
            "slug": media_item.slug,
            "p1": p1, "p2": p2,
            "is_album": media_item.is_album,
        }


        owned = owned_episodes(media_item.name)
        seasons_data = []
        for season in seasons:
            episodes_data = []
            owned_here = 0

            # Enrich episodes with language list for better display
            for ep in season.episodes:
                ep_dict = ep.__dict__.copy()
                lang = ep_dict.get("language") or ""
                ep_dict["language_list"] = [language.strip() for language in lang.split(",") if language.strip()] if lang else []

                try:
                    ep_dict["owned"] = (int(season.number), int(ep.number)) in owned
                except (TypeError, ValueError):
                    ep_dict["owned"] = False
                owned_here += 1 if ep_dict["owned"] else 0

                episodes_data.append(ep_dict)

            seasons_data.append({
                "number": season.number,
                "name": season.name,
                "image": season.image,
                "episode_count": season.episode_count,
                "episodes": episodes_data,
                "owned_count": owned_here,
                "missing_count": len(episodes_data) - owned_here,
            })

        return render(
            request,
            "searchapp/cinema_series.html",
            {
                "series": series_info,
                "seasons": seasons_data,
                "tmdb_available": bool(tmdb_client.api_key),
                "nav_active": "search",
            }
        )

    except Exception:
        logger.exception("Could not load the title details")  # the text can carry the provider's host name
        messages.error(request, "Could not load the details. Try again, or open the logs for details.")
        return redirect("search_home")

__all__ = ['series_detail']
