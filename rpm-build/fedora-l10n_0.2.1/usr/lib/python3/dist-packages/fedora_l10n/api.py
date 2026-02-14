"""Weblate API client with caching and rate limiting."""

import json
import os
import time
import hashlib
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://translate.fedoraproject.org/api"
CACHE_DIR = Path.home() / ".cache" / "fedora-l10n"
CACHE_TTL = 3600  # 1 hour
RATE_DELAY = 0.6  # seconds between requests
MAX_RETRIES = 5

_last_request_time = 0.0


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _read_cache(url: str):
    p = _cache_path(url)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if time.time() - data.get("_ts", 0) < CACHE_TTL:
                return data.get("_payload")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _write_cache(url: str, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(url)
    try:
        p.write_text(json.dumps({"_ts": time.time(), "_payload": payload}))
    except OSError:
        pass


def _fetch(url: str, use_cache: bool = True):
    global _last_request_time

    if use_cache:
        cached = _read_cache(url)
        if cached is not None:
            return cached

    for attempt in range(MAX_RETRIES):
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_DELAY:
            time.sleep(RATE_DELAY - elapsed)

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            _last_request_time = time.time()
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if use_cache:
                    _write_cache(url, data)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RATE_DELAY * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, OSError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(RATE_DELAY * (2 ** attempt))
                continue
            raise

    return None


def get_projects(callback=None):
    """Fetch all projects (paginated). callback(page, total_pages) for progress."""
    all_projects = []
    url = f"{BASE_URL}/projects/?page_size=50"
    page = 0
    while url:
        data = _fetch(url)
        if data is None:
            break
        results = data.get("results", [])
        all_projects.extend(results)
        url = data.get("next")
        page += 1
        total = data.get("count", 0)
        total_pages = (total + 49) // 50
        if callback:
            callback(page, total_pages)
    return all_projects


def get_project_statistics(slug: str):
    return _fetch(f"{BASE_URL}/projects/{slug}/statistics/")


def get_language_statistics(slug: str, lang: str):
    return _fetch(f"{BASE_URL}/projects/{slug}/statistics/{lang}/")


def get_components(slug: str):
    all_components = []
    url = f"{BASE_URL}/projects/{slug}/components/?page_size=50"
    while url:
        data = _fetch(url)
        if data is None:
            break
        all_components.extend(data.get("results", []))
        url = data.get("next")
    return all_components


def get_component_statistics(project: str, component: str, lang: str):
    return _fetch(f"{BASE_URL}/components/{project}/{component}/statistics/{lang}/")


def clear_cache():
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
