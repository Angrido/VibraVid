# 12.11.26

import logging
import threading
from typing import Any

from django.db import close_old_connections

from .arr_service import (
    _build_clients,
    _dedup_key,
    _enqueue_if_new,
    _extract_provider_from_tags,
    _load_arr_config,
    download_episode,
    download_movie,
)
from .processor_service import ArrProcessorService

logger = logging.getLogger("ARR")

MANUAL_SOURCE = "manual_resync"


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


def _queue_states(keys: list[str]) -> dict[str, str]:
    from searchapp.models import ArrProcessingQueue

    entries = ArrProcessingQueue.objects.filter(dedup_key__in=keys).select_related("media_request")
    return {entry.dedup_key: entry.media_request.status for entry in entries}


def scan_missing() -> dict[str, Any]:
    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    clients = [client for client in (sonarr, radarr) if client]
    reachable = {client.label for client in clients if client.is_available()}
    items = (
        _missing_items(
            cfg,
            sonarr if sonarr and sonarr.label in reachable else None,
            radarr if radarr and radarr.label in reachable else None,
        )
        if reachable
        else []
    )

    series = sorted((i for i in items if i["content_type"] == "serie"), key=lambda i: i["title"].lower())
    movies = sorted((i for i in items if i["content_type"] == "movie"), key=lambda i: i["title"].lower())

    keys = [_dedup_key(movie) for movie in movies]
    for serie in series:
        for season in serie["seasons"]:
            keys.extend(_dedup_key(serie, season["number"], ep["episodeNumber"]) for ep in season["episodes"])
    states = _queue_states(keys)

    for movie in movies:
        movie["state"] = states.get(_dedup_key(movie), "")
    for serie in series:
        serie["episode_count"] = 0
        for season in serie["seasons"]:
            for episode in season["episodes"]:
                episode["state"] = states.get(_dedup_key(serie, season["number"], episode["episodeNumber"]), "")
            serie["episode_count"] += len(season["episodes"])

    return {
        "configured": bool(clients),
        "unreachable": [client.label for client in clients if client.label not in reachable],
        "polling_active": bool(cfg.get("enabled") and cfg.get("enable_polling")),
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
        return {"payload": payload, "provider": provider, "season": None, "episode": None}

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
        "season": season_num,
        "episode": local_episode if local_episode is not None else ep_num,
    }
