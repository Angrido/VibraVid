# 12.11.26

import logging
import sys
import threading
import time
from collections import Counter, defaultdict
from typing import Any

import requests
from django.db import close_old_connections
from django.db.models import Max, Min

from VibraVid.core.utils.audio_selection import matches_audio_language

from . import manual_service
from .arr_service import _build_clients, _load_arr_config

logger = logging.getLogger("ARR")

TARGET_LANGUAGE = "it"
INTERVAL_HOURS = (0, 1, 3, 6, 12, 24, 48)
INTERVAL_KEY = "language_check_interval_hours"

_run_lock = threading.Lock()
_progress: dict[str, Any] = {"done": 0, "total": 0, "finished_at": None}
_interval_changed = threading.Event()
_loop_lock = threading.Lock()
_loop_started = False


def movie_key(movie_id: int) -> str:
    return f"movie:{movie_id}"


def serie_key(series_id: int) -> str:
    return f"serie:{series_id}"


def episode_key(episode_id: int) -> str:
    return f"episode:{episode_id}"


def verdict_for(match_name: str, audio_supported: bool, codes: list[str]) -> str:
    from ..models import ArrLanguageCheck

    if not audio_supported and "(ITA)" in match_name.upper():
        return ArrLanguageCheck.Verdict.AVAILABLE
    if not audio_supported or not codes:
        return ArrLanguageCheck.Verdict.UNKNOWN
    if any(code and matches_audio_language([code], TARGET_LANGUAGE) for code in codes):
        return ArrLanguageCheck.Verdict.AVAILABLE
    return ArrLanguageCheck.Verdict.ABSENT


def record(media_key: str, title_key: str, verdict: str, codes: list[str], provider: str) -> None:
    from ..models import ArrLanguageCheck

    ArrLanguageCheck.objects.update_or_create(
        media_key=media_key,
        defaults={"title_key": title_key, "verdict": verdict, "languages": codes, "provider": provider or ""},
    )


def _check(movie_id: int | None = None, episode_id: int | None = None) -> tuple[str, list[str], str]:
    from searchapp.api import get_api
    from searchapp.api.base import Entries

    from ..models import ArrLanguageCheck

    match = manual_service.find_on_provider(movie_id=movie_id, episode_id=episode_id)
    payload, provider = match["payload"], match["provider"] or ""
    if not payload:
        return ArrLanguageCheck.Verdict.NOT_FOUND, [], provider
    item = Entries(**{k: v for k, v in payload.items() if k in Entries.__dataclass_fields__})
    try:
        languages = get_api(provider).get_available_audio_languages(item, match["season"], match["episode"])
        supported = True
    except (NotImplementedError, AttributeError):
        languages, supported = [], False
    codes = [language.get("code", "") for language in languages]
    return verdict_for(item.name or "", supported, codes), codes, provider


def _targets(movie_ids: set[int] | None, series_ids: set[int] | None) -> list[tuple[str, str, dict]]:
    cfg = _load_arr_config()
    sonarr, radarr = _build_clients(cfg)
    if not sonarr and not radarr:
        raise manual_service.ArrNotConfigured
    items = manual_service._missing_items(
        cfg,
        sonarr if series_ids is None or series_ids else None,
        radarr if movie_ids is None or movie_ids else None,
    )
    targets = []
    for item in items:
        if item["content_type"] == "movie":
            if movie_ids is None or item["id"] in movie_ids:
                targets.append((movie_key(item["id"]), movie_key(item["id"]), {"movie_id": item["id"]}))
            continue
        if series_ids is not None and item["id"] not in series_ids:
            continue
        for season in item["seasons"]:
            for episode in season["episodes"]:
                targets.append((episode_key(episode["id"]), serie_key(item["id"]), {"episode_id": episode["id"]}))
    return targets


def _run(targets: list[tuple[str, str, dict]], prune_titles: set[str] | None) -> None:
    from ..models import ArrLanguageCheck

    close_old_connections()
    _progress.update(done=0, total=len(targets), finished_at=None)
    try:
        for media_key, title_key, ids in targets:
            try:
                verdict, codes, provider = _check(**ids)
            except Exception as exc:
                logger.warning("[language check] %s could not be checked: %s", media_key, exc)
                verdict, codes, provider = ArrLanguageCheck.Verdict.FAILED, [], ""
            record(media_key, title_key, verdict, codes, provider)
            _progress["done"] += 1
        stale = ArrLanguageCheck.objects.exclude(media_key__in=[target[0] for target in targets])
        if prune_titles is not None:
            stale = stale.filter(title_key__in=prune_titles)
        stale.delete()
        logger.info("[language check] %s missing item(s) checked for Italian audio", len(targets))
    finally:
        _progress["finished_at"] = time.time()
        close_old_connections()


def _run_and_release(targets: list[tuple[str, str, dict]], prune_titles: set[str] | None) -> None:
    try:
        _run(targets, prune_titles)
    finally:
        _run_lock.release()


def start_check(movie_ids: set[int] | None = None, series_ids: set[int] | None = None) -> bool:
    if not _run_lock.acquire(blocking=False):
        return False
    try:
        targets = _targets(movie_ids, series_ids)
        prune = None
        if movie_ids is not None or series_ids is not None:
            prune = {movie_key(i) for i in movie_ids or ()} | {serie_key(i) for i in series_ids or ()}
        threading.Thread(target=_run_and_release, args=(targets, prune), daemon=True, name="ArrLanguageCheck").start()
    except BaseException:
        _run_lock.release()
        raise
    return True


def _summary(counts: Counter) -> dict[str, Any]:
    from ..models import ArrLanguageCheck

    total = sum(counts.values())
    available = counts[ArrLanguageCheck.Verdict.AVAILABLE]
    if available == total:
        tone, label = "good", "Italian audio"
    elif available:
        tone, label = "warn", "Italian audio"
    elif counts[ArrLanguageCheck.Verdict.ABSENT]:
        tone, label = "bad", "No Italian audio"
    elif counts[ArrLanguageCheck.Verdict.NOT_FOUND] == total:
        tone, label = "muted", "Not on any provider"
    else:
        tone, label = "muted", "Audio not verified"
    return {"tone": tone, "label": label, "count": f"{available}/{total}" if tone == "warn" else ""}


def title_summaries() -> dict[str, dict[str, Any]]:
    from ..models import ArrLanguageCheck

    counts: dict[str, Counter] = defaultdict(Counter)
    for title_key, verdict in ArrLanguageCheck.objects.values_list("title_key", "verdict"):
        counts[title_key][verdict] += 1
    return {title_key: _summary(verdicts) for title_key, verdicts in counts.items()}


def interval_hours() -> int:
    try:
        value = int(_load_arr_config().get(INTERVAL_KEY) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value in INTERVAL_HOURS else 0


def set_interval_hours(value: int) -> None:
    from VibraVid.utils import config_manager

    config_manager.config.set_key("ARR", INTERVAL_KEY, value)
    config_manager.save_config()
    _interval_changed.set()


def _checked_at(aggregate) -> float | None:
    from ..models import ArrLanguageCheck

    value = ArrLanguageCheck.objects.aggregate(value=aggregate("checked_at"))["value"]
    return value.timestamp() if value else None


def check_status() -> dict[str, Any]:
    finished = _progress["finished_at"] or _checked_at(Max)
    return {
        "running": _run_lock.locked(),
        "done": _progress["done"],
        "total": _progress["total"],
        "last_checked": int(finished) if finished else None,
        "interval_hours": interval_hours(),
        "titles": title_summaries(),
    }


def run_scheduled_check() -> None:
    if not _run_lock.acquire(blocking=False):
        return
    try:
        targets = _targets(None, None)
    except manual_service.ArrNotConfigured:
        _run_lock.release()
        return
    except requests.RequestException as exc:
        logger.warning("[language check] Sonarr or Radarr did not answer: %s", exc)
        _run_lock.release()
        return
    _run_and_release(targets, None)


def _loop() -> None:
    last_attempt = 0.0
    while True:
        wait = None
        try:
            hours = interval_hours()
            if hours:
                close_old_connections()
                wait = max(last_attempt, _checked_at(Min) or 0) + hours * 3600 - time.time()
                if wait <= 0:
                    last_attempt = time.time()
                    run_scheduled_check()
                    continue
        except Exception:
            logger.exception("[language check] Scheduled check failed")
            last_attempt = time.time()
        _interval_changed.clear()
        _interval_changed.wait(3600 if wait is None else min(max(wait, 60), 3600))


def start_language_check_loop() -> None:
    global _loop_started
    if not any(cmd in sys.argv for cmd in ("runserver", "runserver_plus")):
        return
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True
    threading.Thread(target=_loop, daemon=True, name="ArrLanguageCheckLoop").start()
