"""백엔드 API 클라이언트. 웹·앱 프론트가 공용으로 쓴다.

실행 환경이 두 가지라 전송 계층을 분리했다.
  - 일반 Python(라즈베리파이·로컬 개발): requests
  - 브라우저(stlite/Pyodide): requests 는 소켓을 쓸 수 없어 아예 동작하지
    않는다. 대신 동기 XMLHttpRequest 를 쓴다 (stlite 는 워커 스레드에서
    돌기 때문에 동기 XHR 이 허용된다).

호출부는 어느 쪽인지 알 필요가 없다. api_get/api_post/... 인터페이스와
ApiError 는 두 환경에서 동일하게 동작한다.
"""

import json as jsonlib
import os
from pathlib import Path
from urllib.parse import urlencode

_TIMEOUT = 5


class ApiError(Exception):
    """HTTP 오류 응답. 전송 계층이 무엇이든 이 예외로 통일한다.

    requests.HTTPError 를 그대로 노출하면 Pyodide 환경에서 requests 자체가
    없어 except 절이 NameError 로 깨진다.
    """

    def __init__(self, status_code: int, message: str = ""):
        super().__init__(f"HTTP {status_code}: {message}"[:200])
        self.status_code = status_code
        self.message = message


def _resolve_base_url() -> str:
    # 127.0.0.1, not localhost: on Windows, resolving "localhost" through the
    # system resolver can take ~2 seconds per call (IPv6-then-IPv4 fallback) -
    # with several sequential API calls per page render, that alone was the
    # entire source of the every-click lag.
    from_env = os.getenv("THERMOSHIFT_API_URL")
    if from_env:
        return from_env.rstrip("/")

    # stlite 빌드는 환경변수를 쓸 수 없다. 빌드 스크립트가 만들어 둔 설정
    # 파일을 읽는다 (scripts/build-pwa.mjs).
    config_path = Path(__file__).resolve().parent.parent / "app" / "api_config.json"
    try:
        config = jsonlib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "http://127.0.0.1:8000"
    return str(config.get("api_base") or "http://127.0.0.1:8000").rstrip("/")


API_BASE_URL = _resolve_base_url()


# --------------------------------------------------------------------------
# 전송 계층
# --------------------------------------------------------------------------

def _load_requests():
    try:
        import requests  # noqa: PLC0415

        return requests
    except ImportError:
        return None


def _load_xhr():
    try:
        from js import XMLHttpRequest  # noqa: PLC0415

        return XMLHttpRequest
    except ImportError:
        return None


_requests = _load_requests()
_XHR = None if _requests else _load_xhr()

# A shared Session reuses the underlying TCP connection across calls
# (HTTP keep-alive) instead of paying a fresh handshake every time.
_session = _requests.Session() if _requests else None


def transport_name() -> str:
    """현재 쓰는 전송 계층. 설정 화면 진단용."""
    if _requests is not None:
        return "requests"
    if _XHR is not None:
        return "xhr"
    return "none"


def _build_url(path: str, params: dict | None) -> str:
    url = f"{API_BASE_URL}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urlencode(clean)}"
    return url


def _send(method: str, url: str, body: dict | None) -> tuple[int, str]:
    """(상태코드, 본문 문자열). 연결 자체가 실패하면 예외를 그대로 올린다."""
    if _session is not None:
        response = _session.request(method, url, json=body, timeout=_TIMEOUT)
        return response.status_code, response.text

    if _XHR is not None:
        xhr = _XHR.new()
        xhr.open(method, url, False)  # 세 번째 인자 False = 동기 요청
        payload = None
        if body is not None:
            xhr.setRequestHeader("Content-Type", "application/json")
            payload = jsonlib.dumps(body, ensure_ascii=False)
        xhr.send(payload)
        return int(xhr.status), str(xhr.responseText or "")

    raise RuntimeError(
        "사용 가능한 HTTP 전송 계층이 없습니다 (requests 도 XMLHttpRequest 도 없음)"
    )


def _request(method: str, path: str, *, params: dict | None = None,
             json: dict | None = None, ignore_404: bool = False):
    status, text = _send(method, _build_url(path, params), json)

    if ignore_404 and status == 404:
        return None
    if status >= 400:
        raise ApiError(status, text)
    if status == 204 or not text:
        return None
    return jsonlib.loads(text)


def api_get(path: str, *, params: dict | None = None, ignore_404: bool = False):
    return _request("GET", path, params=params, ignore_404=ignore_404)


def api_post(path: str, *, json: dict | None = None, params: dict | None = None):
    return _request("POST", path, json=json, params=params)


def api_patch(path: str, *, json: dict | None = None, ignore_404: bool = False):
    return _request("PATCH", path, json=json, ignore_404=ignore_404)


def api_delete(path: str, *, ignore_404: bool = False):
    return _request("DELETE", path, ignore_404=ignore_404)
