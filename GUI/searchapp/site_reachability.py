# 12.11.26

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from curl_cffi import CurlError

from VibraVid.utils.config import config_manager
from VibraVid.utils.http_client import create_client

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 8
RESULTS_TTL_SECONDS = 300

_cached_results: dict = {"at": 0.0, "sites": None, "results": []}
_cache_lock = threading.Lock()

FIXED_HOMEPAGES = {
    "aurora": "https://public.aurora.enhanced.live/site/page/homepage/",
    "chili": "https://www.chili.com/",
    "crunchyroll": "https://www.crunchyroll.com/",
    "discoveryplus": "https://www.discoveryplus.com/",
    "la7": "https://www.la7.it/",
    "mediasetinfinity": "https://mediasetinfinity.mediaset.it/",
    "plutotv": "https://pluto.tv/",
    "raiplay": "https://www.raiplay.it/",
    "rakutentv": "https://www.rakuten.tv/",
    "timvision": "https://www.timvision.it/",
    "tubitv": "https://tubitv.com/",
    "youtube": "https://www.youtube.com/",
    "youtube_music": "https://music.youtube.com/",
}


def site_url(site: str) -> str:
    url = str(config_manager.domain.get(site, "full_url", default="") or FIXED_HOMEPAGES.get(site, ""))
    return url if urlsplit(url).scheme in ("http", "https") else ""


def site_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _same_site(host_a: str, host_b: str) -> bool:
    return host_a == host_b or host_a.endswith("." + host_b) or host_b.endswith("." + host_a)


def check_site(site: str, url: str) -> dict:
    result = {"site": site, "url": url, "state": "unknown", "final_url": "", "final_host": "", "http_status": None}
    if not url:
        return result

    try:
        with create_client(timeout=CHECK_TIMEOUT_SECONDS) as client:
            response = client.get(url)
    except (CurlError, ValueError) as exc:
        logger.info("Site %s unreachable at %s: %s", site, url, type(exc).__name__)
        result["state"] = "down"
        return result

    final_url = str(response.url or url)
    result["final_url"] = final_url
    result["final_host"] = site_host(final_url)
    result["http_status"] = response.status_code
    if not _same_site(result["final_host"], site_host(url)):
        result["state"] = "moved"
    elif response.status_code >= 400:
        result["state"] = "error"
    else:
        result["state"] = "up"
    return result


def check_sites(sites: list[str], refresh: bool = False) -> list[dict]:
    if not sites:
        return []
    with _cache_lock:
        fresh = time.monotonic() - _cached_results["at"] < RESULTS_TTL_SECONDS
        if not refresh and fresh and _cached_results["sites"] == sites:
            return _cached_results["results"]

        targets = [(site, site_url(site)) for site in sites]
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            results = list(pool.map(lambda target: check_site(*target), targets))
        _cached_results.update(at=time.monotonic(), sites=sites, results=results)
        return results
