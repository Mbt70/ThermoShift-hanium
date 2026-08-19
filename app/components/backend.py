"""백엔드 API 클라이언트.

store 모듈들이 공통으로 쓰는 얇은 HTTP 래퍼다.

동작 원칙
  - THERMOSHIFT_API_BASE 가 설정되어 있으면 API를 쓴다.
  - API가 꺼져 있거나 오류면 None 을 돌려주고, 호출한 store가
    기존 로컬 JSON 목데이터로 폴백한다.

덕분에 파이(실증 환경)에서는 실데이터로, 팀원 노트북에서는 백엔드 없이도
프론트를 그대로 띄울 수 있다.
"""

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

API_BASE = os.environ.get("THERMOSHIFT_API_BASE", "").rstrip("/")
TIMEOUT_SEC = float(os.environ.get("THERMOSHIFT_API_TIMEOUT", "3"))

# 연달아 실패하면 매 rerun마다 타임아웃을 기다리지 않도록 잠시 꺼 둔다.
_FAILURE_LIMIT = 3
_failures = 0


def api_enabled() -> bool:
    return bool(API_BASE) and _failures < _FAILURE_LIMIT


def reset_failures() -> None:
    """설정 화면 등에서 연결을 다시 시도할 때 쓴다."""
    global _failures
    _failures = 0


def _request(method: str, path: str, **kwargs) -> Optional[Any]:
    global _failures
    if not api_enabled():
        return None
    try:
        response = requests.request(
            method, f"{API_BASE}{path}", timeout=TIMEOUT_SEC, **kwargs
        )
    except requests.RequestException as exc:
        _failures += 1
        logger.warning("API 연결 실패 (%s %s): %s", method, path, exc)
        return None

    _failures = 0
    if response.status_code == 204:
        return {}
    if not response.ok:
        # 4xx는 서버가 살아 있다는 뜻이므로 폴백 카운터를 올리지 않는다.
        logger.info("API %s %s -> %s %s", method, path, response.status_code, response.text[:200])
        return None
    try:
        return response.json()
    except ValueError:
        return None


def get(path: str, params: Optional[dict] = None) -> Optional[Any]:
    return _request("GET", path, params=params)


def post(path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Optional[Any]:
    return _request("POST", path, json=json, params=params)


def patch(path: str, json: Optional[dict] = None) -> Optional[Any]:
    return _request("PATCH", path, json=json)


def put(path: str, json: Optional[dict] = None) -> Optional[Any]:
    return _request("PUT", path, json=json)


def delete(path: str) -> Optional[Any]:
    return _request("DELETE", path)


def status_code(method: str, path: str, **kwargs) -> Optional[int]:
    """응답 본문 대신 상태 코드만 필요할 때(중복 가입 확인 등)."""
    if not api_enabled():
        return None
    try:
        response = requests.request(
            method, f"{API_BASE}{path}", timeout=TIMEOUT_SEC, **kwargs
        )
    except requests.RequestException:
        return None
    return response.status_code
