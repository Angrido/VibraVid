# 12.11.26

import logging
import threading
from collections import defaultdict
from typing import Any

import requests
from django.db import close_old_connections

from .arr_service import (
    _build_clients,
    _dedup_key,
    _enqueue_if_new,
    _extract_provider_from_tags,
    _load_arr_config,
    automatic_downloads_enabled,
    download_episode,
    download_movie,
)
from .processor_service import ArrProcessorService

logger = logging.getLogger("ARR")

MANUAL_SOURCE = "manual_resync"
AWAITING_IMPORT_STATES = ("completed", "import_pending")
NOT_QUEUED = {"state": "", "reason": ""}


class ArrNotConfigured(Exception):
    pass


def _missing_items(cfg: dict, sonarr, radarr) -> list[dict]:
    processor = ArrProcessorService(
        sonarr=sonarr,
        radarr=radarr,
        tags_mode=cfg.get("tags_mode", "BLACKLIST"),
        active_tag_ids=cfg.get("active_tag_ids", []),
    )
    return processor.get_missing_items()


def _queue_states(keys: list[str]) -> dict[str, dict[str, str]]:
    from searchapp.models import ArrProcessingQueue

    entries = ArrProcessingQueue.objects.filter(dedup_key__in=keys).select_related("media_request")
    queued = {
        entry.dedup_key: {"state": entry.media_request.status, "reason": entry.media_request.failure_reason}
        for entry in entries
    }
    return {key: queued.get(key, NOT_QUEUED) for key in keys}


def _keys_with_file(keys: list[str]) -> set[str]:
    sonarr, radarr = _build_clients(_load_arr_config())
    found: set[str] = set()
    series_keys: dict[int, set[str]] = defaultdict(set)
    for key in keys:
        source, arr_id = key.split("_")[:2]
        if source == "sonarr":
            series_keys[int(arr_id)].add(key)
        elif radarr and radarr.get_movie_by_id(int(arr_id)).get("hasFile"):
            found.add(key)
    for series_id, wanted in series_keys.items():
        if not sonarr:
            break
        episodes = sonarr.get_episodes_for_series(series_id)
        found |= wanted & {
            f"sonarr_{series_id}_s{e['seasonNumber']}_e{e['episodeNumber']}" for e in episodes if e.get("hasFile")
        }
    return found


def live_queue_states(keys: list[str]) -> dict[str, dict[str, str]]:
    states = _queue_states(keys)
    awaiting = [key for key, entry in states.items() if entry["state"] in AWAITING_IMPORT_STATES]
    if not awaiting:
        return states
    try:
        imported = _keys_with_file(awaiting)
    except requests.RequestException as exc:
        logger.warning(f"Could not ask Sonarr/Radarr whether downloads were imported: {exc}")
        return states
    return {key: {**entry, "state": "imported"} if key in imported else entry for key, entry in states.items()}


def scan_missing() -> dict[str, Any]:
    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    clients = [client for client in (sonarr, radarr) if client]
    problems = {client.label: client.connection_problem() for client in clients}
    usable = [client if client and not problems[client.label] else None for client in (sonarr, radarr)]
    items = _missing_items(cfg, *usable) if any(usable) else []

    series = sorted((i for i in items if i["content_type"] == "serie"), key=lambda i: i["title"].lower())
    movies = sorted((i for i in items if i["content_type"] == "movie"), key=lambda i: i["title"].lower())

    rows = list(movies)
    for movie in movies:
        movie["queue_key"] = _dedup_key(movie)
    for serie in series:
        serie["episode_count"] = 0
        for season in serie["seasons"]:
            for episode in season["episodes"]:
                episode["queue_key"] = _dedup_key(serie, season["number"], episode["episodeNumber"])
                rows.append(episode)
            serie["episode_count"] += len(season["episodes"])
    states = _queue_states([row["queue_key"] for row in rows])
    for row in rows:
        row.update(states[row["queue_key"]])

    return {
        "configured": bool(clients),
        "problems": {label: problem for label, problem in problems.items() if problem},
        "polling_active": bool(cfg.get("enabled") and cfg.get("enable_polling") and automatic_downloads_enabled(cfg)),
        "series": series,
        "movies": movies,
        "episode_total": sum(serie["episode_count"] for serie in series),
    }


def _run_jobs(sonarr, radarr, jobs: list[tuple[dict, dict | None, dict | None]]) -> None:
    from .downloader_service import ArrDownloaderService

    close_old_connections()
    downloader = ArrDownloaderService(sonarr, radarr)
    for item, season, episode in jobs:
        if episode is None:
            download_movie(downloader, item)
        else:
            download_episode(downloader, item, season, episode)
    close_old_connections()


def start_selected_downloads(movie_ids: set[int], episode_ids: set[int]) -> dict[str, int]:
    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    if not sonarr and not radarr:
        raise ArrNotConfigured

    items = _missing_items(cfg, sonarr if episode_ids else None, radarr if movie_ids else None)
    jobs: list[tuple[dict, dict | None, dict | None]] = []
    selected = 0
    for item in items:
        if item["content_type"] == "movie":
            if item["id"] not in movie_ids:
                continue
            selected += 1
            if _enqueue_if_new(item, MANUAL_SOURCE):
                jobs.append((item, None, None))
            continue
        for season in item["seasons"]:
            for episode in season["episodes"]:
                if episode["id"] not in episode_ids:
                    continue
                selected += 1
                if _enqueue_if_new(
                    item,
                    MANUAL_SOURCE,
                    season_num=season["number"],
                    ep_num=episode["episodeNumber"],
                    episode_id=episode["id"],
                ):
                    jobs.append((item, season, episode))

    if jobs:
        threading.Thread(target=_run_jobs, args=(sonarr, radarr, jobs), daemon=True).start()
    logger.info(f"[manual] {len(jobs)} of {selected} selected missing item(s) queued for download")
    return {"queued": len(jobs), "skipped": selected - len(jobs), "gone": len(movie_ids) + len(episode_ids) - selected}


def provider_page_url(provider: str, payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    from VibraVid.utils import config_manager

    try:
        base = (config_manager.domain.get(provider, "full_url") or "").rstrip("/")
    except (KeyError, AttributeError):
        base = ""
    slug = f"{payload.get('id')}-{payload.get('slug')}"
    if provider == "streamingcommunity" and base and payload.get("id") and payload.get("slug"):
        return f"{base}/{payload.get('provider_language') or 'it'}/titles/{slug}"
    if provider == "animeunity" and base and payload.get("id") and payload.get("slug"):
        return f"{base}/anime/{slug}"
    url = str(payload.get("url") or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def find_on_provider(movie_id: int | None = None, episode_id: int | None = None) -> dict[str, Any]:
    from .downloader_service import ArrDownloaderService

    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    downloader = ArrDownloaderService(sonarr, radarr)

    if movie_id is not None:
        if not radarr:
            raise ArrNotConfigured
        movie = radarr.get_movie_by_id(movie_id)
        item = {
            "content_type": "movie",
            "id": movie["id"],
            "title": movie["title"],
            "year": movie.get("year"),
            "tmdbId": movie.get("tmdbId"),
            "imdbId": movie.get("imdbId"),
            "provider": _extract_provider_from_tags(radarr, movie.get("tags", [])),
        }
        payload, provider = downloader.locate(item)
        return {
            "payload": payload,
            "provider": provider,
            "url": provider_page_url(provider, payload),
            "season": None,
            "episode": None,
            "series_only": None if payload else downloader.series_only_match,
            "searched": downloader.searched_providers,
        }

    if not sonarr:
        raise ArrNotConfigured
    episode = sonarr.get_episode(episode_id)
    series = sonarr.get_series_by_id(episode["seriesId"])
    item = {
        "content_type": "serie",
        "id": series["id"],
        "title": series["title"],
        "year": series.get("year"),
        "tmdbId": series.get("tmdbId"),
        "tvdbId": series.get("tvdbId"),
        "imdbId": series.get("imdbId"),
        "provider": _extract_provider_from_tags(sonarr, series.get("tags", [])),
    }
    season_num, ep_num = episode["seasonNumber"], episode["episodeNumber"]
    payload, provider = downloader.locate(item, season_num, ep_num)
    local_episode = payload.pop("_provider_local_episode", None) if payload else None
    return {
        "payload": payload,
        "provider": provider,
        "url": provider_page_url(provider, payload),
        "season": season_num,
        "episode": local_episode if local_episode is not None else ep_num,
        "series_only": None,
        "searched": downloader.searched_providers,
        "series_id": series["id"],
    }
