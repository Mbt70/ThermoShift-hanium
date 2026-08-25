"""백엔드 API 클라이언트.

store 모듈들이 공통으로 쓰는 얇은 HTTP 래퍼다.

동작 원칙
  - API 주소가 설정돼 있으면 API를 쓴다.
  - API가 꺼져 있거나 오류면 None 을 돌려주고, 호출한 store가
    기존 로컬 JSON 목데이터로 폴백한다.

실행 환경이 두 가지라 전송 계층을 분리했다.
  - 일반 Python(라즈베리파이 등): requests
  - 브라우저(stlite/Pyodide): requests는 소켓을 못 써서 동작하지 않는다.
    대신 동기 XMLHttpRequest 를 쓴다(stlite는 워커에서 돌아 동기 XHR 허용).

주소 설정
  1. THERMOSHIFT_API_BASE 환경변수 (서버 실행)
  2. app/api_config.json 의 api_base (Vercel/stlite 빌드 시 생성)
"""

import json as jsonlib
import logging
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

TIMEOUT_SEC = float(os.environ.get("THERMOSHIFT_API_TIMEOUT", "3"))

# 연달아 실패하면 매 rerun마다 타임아웃을 기다리지 않도록 잠시 꺼 둔다.
_FAILURE_LIMIT = 3
_failures = 0

# 로그인 후 발급받은 세션 토큰. auth_store 가 채운다.
# 프로세스 전역이 아니라 Streamlit 세션에 두는 편이 맞지만, stlite 는
# 브라우저 탭 하나가 곧 한 세션이라 이 방식으로 충분하다.
_token: Optional[str] = None


def set_token(token: Optional[str]) -> None:
    global _token
    _token = token


def get_token() -> Optional[str]:
    return _token


# 서버가 401을 돌려준 적이 있는지. 토큰 만료를 감지하는 신호로 쓴다.
# 이게 없으면 만료된 세션이 조용히 목데이터로 폴백해, 사용자가 가짜 수치를
# 실제 값으로 오해하게 된다.
_unauthorized = False


def unauthorized_seen() -> bool:
    return _unauthorized


def clear_unauthorized() -> None:
    global _unauthorized
    _unauthorized = False


# --------------------------------------------------------------------------
# 전송 계층 선택
# --------------------------------------------------------------------------

def _load_requests():
    try:
        import requests  # noqa: PLC0415
        return requests
    except ImportError:
        return None


def _load_xhr():
    """브라우저(Pyodide) 환경이면 XMLHttpRequest 를 돌려준다."""
    try:
        from js import XMLHttpRequest  # noqa: PLC0415
        return XMLHttpRequest
    except ImportError:
        return None


_requests = _load_requests()
_XHR = None if _requests else _load_xhr()


def _resolve_api_base() -> str:
    from_env = os.environ.get("THERMOSHIFT_API_BASE")
    if from_env:
        return from_env.rstrip("/")

    # stlite 빌드는 환경변수를 쓸 수 없으므로 빌드 시 생성한 설정 파일을 읽는다.
    config_path = Path(__file__).resolve().parent.parent / "api_config.json"
    try:
        config = jsonlib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(config.get("api_base") or "").rstrip("/")


API_BASE = _resolve_api_base()


def transport_name() -> str:
    """현재 어떤 전송 계층을 쓰는지. 설정 화면 진단용."""
    if _requests is not None:
        return "requests"
    if _XHR is not None:
        return "xhr"
    return "none"


def api_enabled() -> bool:
    return bool(API_BASE) and transport_name() != "none" and _failures < _FAILURE_LIMIT


def reset_failures() -> None:
    """설정 화면 등에서 연결을 다시 시도할 때 쓴다."""
    global _failures
    _failures = 0


# --------------------------------------------------------------------------
# 요청
# --------------------------------------------------------------------------

def _build_url(path: str, params: Optional[dict]) -> str:
    url = f"{API_BASE}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urlencode(clean)}"
    return url


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_token}"} if _token else {}


def _send(method: str, path: str, params: Optional[dict] = None,
          body: Optional[dict] = None) -> Optional[tuple[int, str]]:
    """(상태코드, 본문) 을 돌려준다. 연결 자체가 실패하면 None."""
    url = _build_url(path, params)

    if _requests is not None:
        try:
            response = _requests.request(
                method, url, json=body, headers=_auth_headers(), timeout=TIMEOUT_SEC
            )
        except _requests.RequestException as exc:
            logger.warning("API 연결 실패 (%s %s): %s", method, path, exc)
            return None
        return response.status_code, response.text

    if _XHR is not None:
        try:
            xhr = _XHR.new()
            xhr.open(method, url, False)  # 세 번째 인자 False = 동기 요청
            for name, value in _auth_headers().items():
                xhr.setRequestHeader(name, value)
            payload = None
            if body is not None:
                xhr.setRequestHeader("Content-Type", "application/json")
                payload = jsonlib.dumps(body, ensure_ascii=False)
            xhr.send(payload)
        except Exception as exc:  # js 예외는 파이썬 예외 계층 밖이라 넓게 잡는다
            logger.warning("API 연결 실패 (%s %s): %s", method, path, exc)
            return None
        return int(xhr.status), str(xhr.responseText or "")

    return None


def _request(method: str, path: str, params: Optional[dict] = None,
             body: Optional[dict] = None) -> Optional[Any]:
    global _failures
    if not api_enabled():
        return None

    result = _send(method, path, params, body)
    if result is None:
        _failures += 1
        return None

    _failures = 0
    status, text = result
    if status == 401:
        global _unauthorized
        _unauthorized = True
        return None
    if status == 204:
        return {}
    if not 200 <= status < 300:
        # 4xx는 서버가 살아 있다는 뜻이므로 폴백 카운터를 올리지 않는다.
        logger.info("API %s %s -> %s %s", method, path, status, text[:200])
        return None
    try:
        return jsonlib.loads(text)
    except ValueError:
        return None


def get(path: str, params: Optional[dict] = None) -> Optional[Any]:
    return _request("GET", path, params=params)


def post(path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Optional[Any]:
    return _request("POST", path, params=params, body=json)


def patch(path: str, json: Optional[dict] = None) -> Optional[Any]:
    return _request("PATCH", path, body=json)


def put(path: str, json: Optional[dict] = None) -> Optional[Any]:
    return _request("PUT", path, body=json)


def delete(path: str) -> Optional[Any]:
    return _request("DELETE", path)


def send(method: str, path: str, json: Optional[dict] = None,
         params: Optional[dict] = None) -> Optional[tuple[int, Any]]:
    """(상태코드, 파싱된 본문) 을 돌려준다. 연결 실패면 None.

    로그인처럼 성공/실패를 구분하면서 본문도 필요한 경우에 쓴다.
    """
    if not api_enabled():
        return None
    result = _send(method, path, params, json)
    if result is None:
        return None
    status, text = result
    try:
        data = jsonlib.loads(text) if text else None
    except ValueError:
        data = None
    return status, data


def status_code(method: str, path: str, json: Optional[dict] = None,
                params: Optional[dict] = None) -> Optional[int]:
    """응답 본문 대신 상태 코드만 필요할 때(로그인 성공/실패 구분 등).

    None 은 '연결 실패' 를 뜻하고, 이때만 호출부가 로컬 저장소로 폴백한다.
    """
    if not api_enabled():
        return None
    result = _send(method, path, params, json)
    return None if result is None else result[0]
