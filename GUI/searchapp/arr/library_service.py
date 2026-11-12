# 12.11.26

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests
from django.db.models import Count

from .arr_service import _build_clients, _load_arr_config
from .clients._base import connection_problem
from .language_check import movie_key, serie_key
from .manual_service import NOT_QUEUED, ArrNotConfigured, _queue_states
from .processor_service import poster_url

logger = logging.getLogger("ARR")

BUSY_QUEUE_STATES = ("pending", "downloading")
ACTIVITY_BY_STATUS = {"downloading": "downloading", "pending": "queued", "failed": "failed"}


def _percent(have: int, total: int) -> int:
    return round(have * 100 / total) if total else 0


def _series_card(series: dict) -> dict[str, Any]:
    stats = series.get("statistics") or {}
    aired = stats.get("episodeCount", 0)
    have = stats.get("episodeFileCount", 0)
    missing = max(aired - have, 0) if series.get("monitored", True) else 0
    if not series.get("monitored", True):
        state = "unmonitored"
    elif missing:
        state = "missing"
    elif not aired:
        state = "unaired"
    else:
        state = "complete"
    return {
        "kind": "serie",
        "id": series["id"],
        "title": series["title"],
        "year": series.get("year"),
        "added": series.get("added") or "",
        "poster": poster_url(series.get("images")),
        "network": series.get("network") or "",
        "status": series.get("status") or "",
        "season_count": stats.get("seasonCount", 0),
        "have": have,
        "aired": aired,
        "missing": missing,
        "percent": _percent(have, aired),
        "size": stats.get("sizeOnDisk", 0),
        "state": state,
    }


def _movie_card(movie: dict) -> dict[str, Any]:
    if movie.get("hasFile"):
        state = "complete"
    elif not movie.get("monitored", True):
        state = "unmonitored"
    elif movie.get("isAvailable", True):
        state = "missing"
    else:
        state = "unaired"
    return {
        "kind": "movie",
        "id": movie["id"],
        "title": movie["title"],
        "year": movie.get("year"),
        "added": movie.get("added") or "",
        "poster": poster_url(movie.get("images")),
        "studio": movie.get("studio") or "",
        "runtime": movie.get("runtime") or 0,
        "size": movie.get("sizeOnDisk", 0),
        "missing": int(state == "missing"),
        "state": state,
    }


def _by_title(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda card: card["title"].lower())


def _cards(client, fetch: str, card, problems: dict[str, str]) -> list[dict]:
    if not client:
        return []
    try:
        return _by_title(card(item) for item in getattr(client, fetch)())
    except requests.RequestException as exc:
        problems[client.label] = connection_problem(exc)
        return []


def scan_library() -> dict[str, Any]:
    sonarr, radarr = _build_clients(_load_arr_config())
    problems: dict[str, str] = {}
    series = _cards(sonarr, "get_series", _series_card, problems)
    movies = _cards(radarr, "get_movies", _movie_card, problems)
    return {
        "configured": bool(sonarr or radarr),
        "problems": problems,
        "series": series,
        "movies": movies,
        "missing_episodes": sum(card["missing"] for card in series),
        "missing_movies": sum(card["missing"] for card in movies),
    }


def title_activity() -> dict[str, dict[str, int]]:
    from searchapp.models import ArrMediaRequest

    activity: dict[str, dict[str, int]] = defaultdict(dict)
    counted = (
        ArrMediaRequest.objects.filter(status__in=ACTIVITY_BY_STATUS)
        .order_by()
        .values_list("arr_source", "arr_id", "status")
        .annotate(total=Count("pk"))
    )
    for source, arr_id, status, total in counted:
        title_key = movie_key(arr_id) if source == "radarr" else serie_key(arr_id)
        activity[title_key][ACTIVITY_BY_STATUS[status]] = total
    return dict(activity)


def _air_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _episode_state(episode: dict, series_monitored: bool, now: datetime) -> str:
    if episode.get("hasFile"):
        return "complete"
    if not (series_monitored and episode.get("monitored", True)):
        return "unmonitored"
    aired = _air_date(episode.get("airDateUtc"))
    if aired is None or aired > now:
        return "unaired"
    return "missing"


def _details(item: dict) -> dict[str, Any]:
    return {
        "overview": item.get("overview") or "",
        "fanart": poster_url(item.get("images"), "fanart"),
        "genres": item.get("genres") or [],
    }


def series_detail(series_id: int) -> dict[str, Any]:
    sonarr, _ = _build_clients(_load_arr_config())
    if not sonarr:
        raise ArrNotConfigured
    series = sonarr.get_series_by_id(series_id)
    episodes = sonarr.get_episodes_for_series(series_id)
    keys = {e["id"]: f"sonarr_{series_id}_s{e['seasonNumber']}_e{e['episodeNumber']}" for e in episodes}
    queue = _queue_states(list(keys.values()))
    monitored = series.get("monitored", True)
    now = datetime.now(timezone.utc)

    seasons: dict[int, dict] = {}
    for episode in sorted(episodes, key=lambda e: (e["seasonNumber"], e["episodeNumber"])):
        number = episode["seasonNumber"]
        season = seasons.setdefault(number, {"number": number, "episodes": [], "have": 0, "missing": 0})
        state = _episode_state(episode, monitored, now)
        queued = NOT_QUEUED if state == "complete" else queue[keys[episode["id"]]]
        pickable = state == "missing" and number > 0
        season["episodes"].append(
            {
                "id": episode["id"],
                "number": episode["episodeNumber"],
                "title": episode.get("title") or "",
                "air_date": _air_date(episode.get("airDateUtc")),
                "state": state,
                "queue": queued["state"],
                "reason": queued["reason"],
                "queue_key": keys[episode["id"]],
                "pickable": pickable,
                "selectable": pickable and queued["state"] not in BUSY_QUEUE_STATES,
            }
        )
        season["have"] += state == "complete"
        season["missing"] += state == "missing"

    ordered = sorted(seasons.values(), key=lambda s: (s["number"] == 0, -s["number"]))
    for season in ordered:
        season["total"] = len(season["episodes"])
        season["percent"] = _percent(season["have"], season["total"])
        season["selectable"] = sum(e["selectable"] for e in season["episodes"])
        season["open"] = bool(season["missing"])
    if ordered and not any(season["open"] for season in ordered):
        ordered[0]["open"] = True

    return {
        "item": {**_series_card(series), **_details(series)},
        "seasons": ordered,
        "selectable": sum(season["selectable"] for season in ordered),
    }


def movie_detail(movie_id: int) -> dict[str, Any]:
    _, radarr = _build_clients(_load_arr_config())
    if not radarr:
        raise ArrNotConfigured
    movie = radarr.get_movie_by_id(movie_id)
    card = _movie_card(movie)
    key = f"radarr_{movie_id}"
    queued = NOT_QUEUED if card["state"] == "complete" else _queue_states([key])[key]
    return {
        "item": {**card, **_details(movie), "queue": queued["state"], "reason": queued["reason"], "queue_key": key},
        "selectable": card["state"] == "missing" and queued["state"] not in BUSY_QUEUE_STATES,
    }
