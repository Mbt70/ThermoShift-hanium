import os

import requests

# 127.0.0.1, not localhost: on Windows, requests/urllib3 resolving
# "localhost" through the system resolver can take ~2 seconds per call
# (IPv6-then-IPv4 fallback) - with several sequential API calls per page
# render, that alone was the entire source of the every-click lag.
API_BASE_URL = os.getenv("THERMOSHIFT_API_URL", "http://127.0.0.1:8000")
_TIMEOUT = 5

# A shared Session reuses the underlying TCP connection across calls
# (HTTP keep-alive) instead of paying a fresh handshake every time.
_session = requests.Session()


def _request(method: str, path: str, *, ignore_404: bool = False, **kwargs):
    response = _session.request(method, f"{API_BASE_URL}{path}", timeout=_TIMEOUT, **kwargs)
    if ignore_404 and response.status_code == 404:
        return None
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def api_get(path: str, *, params: dict | None = None, ignore_404: bool = False):
    return _request("GET", path, params=params, ignore_404=ignore_404)


def api_post(path: str, *, json: dict | None = None):
    return _request("POST", path, json=json)


def api_patch(path: str, *, json: dict | None = None, ignore_404: bool = False):
    return _request("PATCH", path, json=json, ignore_404=ignore_404)


def api_delete(path: str, *, ignore_404: bool = False):
    return _request("DELETE", path, ignore_404=ignore_404)
