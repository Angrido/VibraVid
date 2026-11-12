# 12.11.26

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .arr_service import _build_clients, _load_arr_config
from .manual_service import ArrNotConfigured, _queue_states
from .processor_service import poster_url

logger = logging.getLogger("ARR")

BUSY_QUEUE_STATES = ("pending", "downloading")


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
        "poster": poster_url(movie.get("images")),
        "studio": movie.get("studio") or "",
        "runtime": movie.get("runtime") or 0,
        "size": movie.get("sizeOnDisk", 0),
        "missing": int(state == "missing"),
        "state": state,
    }


def _by_title(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda card: card["title"].lower())


def scan_library() -> dict[str, Any]:
    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    unreachable: list[str] = []
    series: list[dict] = []
    movies: list[dict] = []
    if sonarr:
        try:
            series = _by_title(_series_card(item) for item in sonarr.get_series())
        except requests.RequestException:
            unreachable.append(sonarr.label)
    if radarr:
        try:
            movies = _by_title(_movie_card(item) for item in radarr.get_movies())
        except requests.RequestException:
            unreachable.append(radarr.label)
    return {
        "configured": bool(sonarr or radarr),
        "unreachable": unreachable,
        "series": series,
        "movies": movies,
        "missing_episodes": sum(card["missing"] for card in series),
        "missing_movies": sum(card["missing"] for card in movies),
    }


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
    queue = _queue_states([f"sonarr_{series_id}_s{e['seasonNumber']}_e{e['episodeNumber']}" for e in episodes])
    monitored = series.get("monitored", True)
    now = datetime.now(timezone.utc)

    seasons: dict[int, dict] = {}
    for episode in sorted(episodes, key=lambda e: (e["seasonNumber"], e["episodeNumber"])):
        number = episode["seasonNumber"]
        season = seasons.setdefault(number, {"number": number, "episodes": [], "have": 0, "missing": 0})
        state = _episode_state(episode, monitored, now)
        queued = "" if state == "complete" else queue.get(f"sonarr_{series_id}_s{number}_e{episode['episodeNumber']}", "")
        season["episodes"].append(
            {
                "id": episode["id"],
                "number": episode["episodeNumber"],
                "title": episode.get("title") or "",
                "air_date": _air_date(episode.get("airDateUtc")),
                "state": state,
                "queue": queued,
                "selectable": state == "missing" and number > 0 and queued not in BUSY_QUEUE_STATES,
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
    queued = "" if card["state"] == "complete" else _queue_states([f"radarr_{movie_id}"]).get(f"radarr_{movie_id}", "")
    return {
        "item": {**card, **_details(movie), "queue": queued},
        "selectable": card["state"] == "missing" and queued not in BUSY_QUEUE_STATES,
    }
