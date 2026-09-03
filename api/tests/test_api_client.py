import pytest

from shared import api_client


class FailingSession:
    def request(self, *_args, **_kwargs):
        raise OSError("private transport detail")


def test_transport_failure_becomes_sanitized_503(monkeypatch):
    monkeypatch.setattr(api_client, "_session", FailingSession())
    monkeypatch.setattr(api_client, "_current_access_token", lambda: None)

    status, body = api_client._send("GET", "https://example.test", None, 1)

    assert status == 503
    assert "API connection unavailable" in body
    assert "private transport detail" not in body


def test_503_is_not_silently_treated_as_empty_data(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "_send",
        lambda *_args, **_kwargs: (503, '{"detail":"unavailable"}'),
    )

    with pytest.raises(api_client.ApiError) as exc:
        api_client._request("GET", "/rooms")

    assert exc.value.status_code == 503
