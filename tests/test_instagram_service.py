"""Unit tests for the Instagram service's typed exceptions, configurable
API version/base URL, and read-only preflight check. `requests` is fully
mocked - no real network request is ever made (see conftest.py's autouse
`no_real_network` fixture, which would fail the test if one slipped through).
"""

import pytest

from src.services.instagram import (
    InstagramService, InstagramAuthError, InstagramContainerError,
    InstagramMediaPublishError, DEFAULT_API_VERSION, sanitize_error_text,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text_data=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text_data
        self.headers = {"content-type": "application/json"}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._json


class TestConfigurableVersionAndBaseUrl:
    def test_default_version_is_not_the_expired_v19(self):
        assert DEFAULT_API_VERSION != "v19.0"

    def test_base_url_uses_configured_version_and_host(self):
        svc = InstagramService(
            user_id="123", access_token="secret-token",
            api_version="v99.0", graph_base_url="https://custom.graph.example.com"
        )
        assert svc.base_url == "https://custom.graph.example.com/v99.0"


class TestSanitization:
    def test_sanitize_error_text_strips_access_token(self):
        raw = "Publish failed (400): {'error': {'access_token': 'EAABsecret123'}}"
        cleaned = sanitize_error_text(raw)
        assert "EAABsecret123" not in cleaned
        assert "REDACTED" in cleaned

    def test_sanitize_error_text_strips_query_string_token(self):
        raw = "GET https://graph.instagram.com/v22.0/123?access_token=EAAB_secret&fields=id failed"
        cleaned = sanitize_error_text(raw)
        assert "EAAB_secret" not in cleaned


class TestPreflightCheck:
    def test_preflight_success_returns_account_info(self, monkeypatch):
        svc = InstagramService(user_id="123", access_token="tok")

        def fake_get(url, params=None, timeout=None):
            assert "access_token" not in url  # never leaked into the URL path itself
            return FakeResponse(200, json_data={"id": "123", "username": "shitpostbot"})

        monkeypatch.setattr("src.services.instagram.requests.get", fake_get)

        result = svc.preflight_check()
        assert result["username"] == "shitpostbot"

    def test_preflight_auth_failure_raises_typed_auth_error(self, monkeypatch):
        svc = InstagramService(user_id="123", access_token="bad-token")

        def fake_get(url, params=None, timeout=None):
            return FakeResponse(400, json_data={"error": {"type": "OAuthException", "code": 190, "message": "bad token"}})

        monkeypatch.setattr("src.services.instagram.requests.get", fake_get)

        with pytest.raises(InstagramAuthError):
            svc.preflight_check()

    def test_preflight_missing_credentials_raises_auth_error_without_calling_api(self, monkeypatch):
        svc = InstagramService(user_id="", access_token="")

        def fake_get(*args, **kwargs):
            raise AssertionError("must not call the API with no credentials configured")

        monkeypatch.setattr("src.services.instagram.requests.get", fake_get)

        with pytest.raises(InstagramAuthError):
            svc.preflight_check()


class TestPublishReelDistinguishesFailureStages:
    def test_container_error_is_typed_and_never_silently_succeeds(self, monkeypatch):
        svc = InstagramService(user_id="123", access_token="tok")

        def fake_post(url, data=None, timeout=None):
            if "/media_publish" in url:
                raise AssertionError("must not reach media_publish if container creation failed")
            return FakeResponse(500, json_data={"error": {"message": "internal error"}})

        monkeypatch.setattr("src.services.instagram.requests.post", fake_post)

        with pytest.raises(InstagramContainerError):
            svc.create_container(video_url="https://example.com/video.mp4", caption="hello")

    def test_media_publish_error_is_typed(self, monkeypatch):
        svc = InstagramService(user_id="123", access_token="tok")

        def fake_post(url, data=None, timeout=None):
            return FakeResponse(500, json_data={"error": {"message": "publish failed"}})

        monkeypatch.setattr("src.services.instagram.requests.post", fake_post)

        with pytest.raises(InstagramMediaPublishError):
            svc.publish_container("container-123")

    def test_auth_error_detected_across_stages(self, monkeypatch):
        svc = InstagramService(user_id="123", access_token="expired-tok")

        def fake_post(url, data=None, timeout=None):
            return FakeResponse(401, json_data={"error": {"type": "OAuthException", "code": 190}})

        monkeypatch.setattr("src.services.instagram.requests.post", fake_post)

        with pytest.raises(InstagramAuthError):
            svc.create_container(video_url="https://example.com/video.mp4", caption="hello")
