from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from api import security


class FakeCursor:
    def __init__(self, row=(1,)):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query, _params):
        return self

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=(1,)):
        self.row = row

    def cursor(self):
        return FakeCursor(self.row)


@contextmanager
def fake_conn(row=(1,)):
    yield FakeConnection(row)


def credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def request(method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": "/"})


def test_signed_session_round_trip(monkeypatch):
    monkeypatch.setattr(security, "get_conn", lambda: fake_conn())
    token = security.create_access_token(7)
    assert security.get_current_user_id(request(), credentials(token)) == 7


def test_tampered_session_is_rejected(monkeypatch):
    monkeypatch.setattr(security, "get_conn", lambda: fake_conn())
    token = security.create_access_token(7) + "tampered"
    with pytest.raises(HTTPException) as exc:
        security.get_current_user_id(request(), credentials(token))
    assert exc.value.status_code == 401


def test_inactive_user_session_is_rejected(monkeypatch):
    monkeypatch.setattr(security, "get_conn", lambda: fake_conn(None))
    with pytest.raises(HTTPException) as exc:
        security.get_current_user_id(
            request(), credentials(security.create_access_token(7))
        )
    assert exc.value.status_code == 401


def test_cross_user_self_access_is_rejected():
    with pytest.raises(HTTPException) as exc:
        security.require_self(user_id=2, current_user_id=1)
    assert exc.value.status_code == 403


def test_demo_session_can_read_but_cannot_change_state(monkeypatch):
    monkeypatch.setattr(security, "get_conn", lambda: fake_conn())
    token = security.create_access_token(7, scope="demo")
    assert security.get_current_user_id(request("GET"), credentials(token)) == 7
    with pytest.raises(HTTPException) as exc:
        security.get_current_user_id(request("PATCH"), credentials(token))
    assert exc.value.status_code == 403
