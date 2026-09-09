"""
Instagram Graph API service for uploading and publishing reels.

Handles:
- Media container creation
- Status polling
- Publishing to Instagram
- Metrics retrieval
- S3 integration for video hosting
- Read-only preflight credential/permission validation

Failures are always represented as typed exceptions (never silently
swallowed or converted into a fake success) so callers can persist durable,
distinguishable state.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import requests
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import subprocess

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance

logger = get_logger(__name__)

# The Graph API version pinned here MUST be a currently-supported version.
# v19.0 expired on 2026-05-21 and must never be used as the active default;
# override via config/env if Meta deprecates this one too.
DEFAULT_API_VERSION = "v22.0"
DEFAULT_GRAPH_BASE_URL = "https://graph.instagram.com"

_ACCESS_TOKEN_RE_PATTERNS = ("access_token",)


def sanitize_error_text(text: str) -> str:
    """Strip access tokens out of an error string before it is logged, sent
    to Telegram, or persisted to the database."""
    import re
    sanitized = text
    for key in _ACCESS_TOKEN_RE_PATTERNS:
        sanitized = re.sub(rf'{key}=[^&\s"\']+', f'{key}=***REDACTED***', sanitized)
        # JSON-ish "key": "value" or Python-repr-ish 'key': 'value'
        sanitized = re.sub(rf'([\'"]){key}\1\s*:\s*([\'"])[^\'"]*\2', rf'\1{key}\1: \g<2>***REDACTED***\2', sanitized)
    return sanitized


class InstagramPublishError(Exception):
    """Base class for all Instagram publishing failures. Always carries a
    sanitized (token-free) message safe to log/persist/send to Telegram."""

    def __init__(self, message: str):
        super().__init__(sanitize_error_text(message))


class InstagramAuthError(InstagramPublishError):
    """Authentication/authorization failure (bad/expired token, missing
    permissions, invalid app config)."""


class InstagramContainerError(InstagramPublishError):
    """Media container creation failed (bad video URL, invalid caption, etc.)."""


class InstagramProcessingTimeoutError(InstagramPublishError):
    """Container never reached FINISHED within the polling budget."""


class InstagramMediaPublishError(InstagramPublishError):
    """The media_publish call itself failed after a successfully processed container."""


@dataclass(frozen=True)
class PublishResult:
    """Structured success result for `publish_reel`. There is no "silent
    failure" representation - failures are always raised exceptions."""
    media_id: str
    container_id: str


def _is_auth_error(error_data: Any) -> bool:
    """Best-effort detection of Graph API auth/permission failures from an
    error response body, regardless of exact shape."""
    try:
        if isinstance(error_data, dict):
            err = error_data.get("error", error_data)
            err_type = str(err.get("type", "")).lower()
            err_code = err.get("code")
            err_subcode = err.get("error_subcode")
            if "oauth" in err_type or err_code in (190, 200, 10) or err_subcode in (458, 459, 460, 463, 467):
                return True
    except Exception:
        pass
    return False


class InstagramService:
    """Wrapper around Instagram Graph API for reel uploading and publishing."""

    def __init__(
        self,
        user_id: str,
        access_token: str,
        api_version: str = DEFAULT_API_VERSION,
        graph_base_url: str = DEFAULT_GRAPH_BASE_URL,
    ):
        """
        Initialize Instagram service.

        Args:
            user_id: Instagram Business Account ID
            access_token: Instagram Graph API access token
            api_version: API version (configurable - default is NOT the
                expired v19.0)
            graph_base_url: Graph API host, configurable because it depends
                on the account/login integration (e.g. graph.instagram.com
                vs graph.facebook.com for some integrations)
        """
        self.user_id = user_id
        self.access_token = access_token
        self.api_version = api_version
        self.graph_base_url = graph_base_url.rstrip("/")
        self.base_url = f"{self.graph_base_url}/{api_version}"

    @classmethod
    def from_config(cls):
        """Create service from configuration."""
        config = get_config_instance()
        return cls(
            user_id=config.get("instagram.user_id"),
            access_token=config.get("instagram.access_token"),
            api_version=config.get("instagram.api_version", DEFAULT_API_VERSION),
            graph_base_url=config.get("instagram.graph_base_url", DEFAULT_GRAPH_BASE_URL),
        )

    def get_video_duration(self, video_path: Path) -> float:
        """Extract video duration using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1:nokey=1",
                video_path.as_posix()
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get video duration: {e}")
            return 0.0

    def s3_upload_and_presign(
        self,
        local_path: Path,
        bucket: str,
        region: str = "us-east-1",
        s3_key: Optional[str] = None,
        expires: int = 3600
    ) -> str:
        """
        Upload video to S3 and return presigned URL.

        Args:
            local_path: Path to local video file
            bucket: S3 bucket name
            region: AWS region
            s3_key: Custom S3 key (default: reels/{filename})
            expires: URL expiration in seconds

        Returns:
            Presigned S3 URL
        """
        s3 = boto3.client("s3", region_name=region)

        # Use custom key or default to reels/ directory
        if s3_key is None:
            s3_key = f"reels/{local_path.name}"

        logger.info(f"Uploading {local_path.name} to S3 bucket {bucket} as {s3_key}")

        try:
            s3.upload_file(
                local_path.as_posix(),
                bucket,
                s3_key,
                ExtraArgs={"ContentType": "video/mp4"}
            )
            logger.info(f"S3 upload complete: {s3_key}")
        except (BotoCoreError, ClientError) as e:
            logger.error(f"S3 upload failed: {e}")
            raise

        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=expires,
        )
        return url

    def preflight_check(self) -> Dict[str, Any]:
        """Read-only validation that credentials and permissions are usable,
        WITHOUT creating any media or publishing anything.

        Returns:
            Dict with account info (id, username if available) on success.

        Raises:
            InstagramAuthError: if credentials/permissions are invalid.
            InstagramPublishError: for any other failure reaching the API.
        """
        if not self.user_id or not self.access_token:
            raise InstagramAuthError("Instagram user_id/access_token not configured")

        url = f"{self.base_url}/{self.user_id}"
        params = {"fields": "id,username", "access_token": self.access_token}

        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            raise InstagramPublishError(f"Preflight request error: {e}")

        if not r.ok:
            error_data = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
            if _is_auth_error(error_data):
                raise InstagramAuthError(f"Preflight auth check failed ({r.status_code}): {error_data}")
            raise InstagramPublishError(f"Preflight check failed ({r.status_code}): {error_data}")

        logger.info("Instagram preflight check passed")
        return r.json()

    def create_container(
        self,
        video_url: str,
        caption: str,
        video_path: Optional[Path] = None
    ) -> str:
        """
        Create a media container on Instagram.

        Args:
            video_url: URL to the video (S3 or other)
            caption: Post caption
            video_path: Optional local path to extract duration

        Returns:
            Container ID for polling

        Raises:
            InstagramAuthError: if the failure is an auth/permission failure.
            InstagramContainerError: for any other container-creation failure.
        """
        url = f"{self.base_url}/{self.user_id}/media"

        data = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token,
        }

        # Add video duration if available
        if video_path:
            duration = self.get_video_duration(video_path)
            if duration > 0:
                data["video_duration"] = int(duration)

        logger.info("Creating media container...")

        try:
            r = requests.post(url, data=data, timeout=120)
        except requests.RequestException as e:
            raise InstagramContainerError(f"Request error during container creation: {e}")

        if not r.ok:
            error_data = (
                r.json() if r.headers.get("content-type", "").startswith("application/json")
                else r.text
            )
            logger.error(f"Container creation failed: {error_data}")
            if _is_auth_error(error_data):
                raise InstagramAuthError(f"Container creation auth failure ({r.status_code}): {error_data}")
            raise InstagramContainerError(f"Container creation failed ({r.status_code}): {error_data}")

        response = r.json()
        if "id" not in response:
            raise InstagramContainerError(f"No container ID in response: {response}")

        logger.info(f"Container created: {response['id']}")
        return response["id"]

    def get_status(self, creation_id: str) -> Dict[str, Any]:
        """
        Poll the status of a media container.

        Args:
            creation_id: Container ID returned from create_container()

        Returns:
            Status response dict with 'status' and 'status_code'

        Raises:
            InstagramAuthError: if the failure is an auth/permission failure.
            InstagramContainerError: for any other status-check failure.
        """
        url = f"{self.base_url}/{creation_id}"

        params = {
            "fields": "status,status_code",
            "access_token": self.access_token
        }

        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            raise InstagramContainerError(f"Request error during status check: {e}")

        if not r.ok:
            error_data = (
                r.json() if r.headers.get("content-type", "").startswith("application/json")
                else r.text
            )
            logger.error(f"Status check failed: {error_data}")
            if _is_auth_error(error_data):
                raise InstagramAuthError(f"Status check auth failure ({r.status_code}): {error_data}")
            raise InstagramContainerError(f"Status check failed ({r.status_code}): {error_data}")

        return r.json()

    def publish_container(self, creation_id: str) -> str:
        """
        Publish a finished media container to Instagram.

        Args:
            creation_id: Container ID (must have status=FINISHED)

        Returns:
            Published media ID

        Raises:
            InstagramAuthError: if the failure is an auth/permission failure.
            InstagramMediaPublishError: for any other media_publish failure.
        """
        url = f"{self.base_url}/{self.user_id}/media_publish"

        data = {
            "creation_id": creation_id,
            "access_token": self.access_token
        }

        logger.info("Publishing media...")

        try:
            r = requests.post(url, data=data, timeout=60)
        except requests.RequestException as e:
            raise InstagramMediaPublishError(f"Request error during publish: {e}")

        if not r.ok:
            error_data = (
                r.json() if r.headers.get("content-type", "").startswith("application/json")
                else r.text
            )
            logger.error(f"Publish failed: {error_data}")
            if _is_auth_error(error_data):
                raise InstagramAuthError(f"Publish auth failure ({r.status_code}): {error_data}")
            raise InstagramMediaPublishError(f"Publish failed ({r.status_code}): {error_data}")

        response = r.json()
        if "id" not in response:
            raise InstagramMediaPublishError(f"No media ID in publish response: {response}")

        logger.info(f"Published successfully: {response['id']}")
        return response["id"]

    def publish_reel(
        self,
        video_url: str,
        caption: str,
        video_path: Optional[Path] = None,
        poll_seconds: int = 5,
        max_polls: int = 60
    ) -> PublishResult:
        """
        Full workflow: create container -> poll -> publish.

        Args:
            video_url: URL to video
            caption: Post caption
            video_path: Optional local path for duration extraction
            poll_seconds: Poll interval
            max_polls: Maximum poll attempts

        Returns:
            PublishResult on success.

        Raises:
            InstagramAuthError, InstagramContainerError,
            InstagramProcessingTimeoutError, InstagramMediaPublishError:
            distinguishing exactly which stage failed. Never returns a fake
            success - a failure always raises.
        """
        creation_id = self.create_container(video_url, caption, video_path)

        logger.info(f"Polling status (max {max_polls} attempts, {poll_seconds}s interval)...")

        finished = False
        for attempt in range(max_polls):
            time.sleep(poll_seconds)

            status_data = self.get_status(creation_id)
            status = status_data.get("status")

            logger.info(f"[{attempt + 1}/{max_polls}] status: {status}")

            if status == "FINISHED":
                logger.info("Container finished, proceeding to publish")
                finished = True
                break
            elif status in ("ERROR", "FAILED"):
                raise InstagramContainerError(f"Processing failed: {status_data}")

        if not finished:
            raise InstagramProcessingTimeoutError(
                f"Container did not finish within {max_polls} polls ({max_polls * poll_seconds}s)"
            )

        media_id = self.publish_container(creation_id)
        return PublishResult(media_id=media_id, container_id=creation_id)

    def get_metrics(self, media_id: str, fields: Optional[list] = None) -> Dict[str, Any]:
        """
        Get metrics for a published post.

        Args:
            media_id: Instagram media ID
            fields: Metrics to retrieve (default: likes, comments, shares)

        Returns:
            Metrics dict

        Raises:
            Exception: If retrieval fails
        """
        if fields is None:
            fields = ["like_count", "comments_count", "ig_media_product_type"]

        url = f"{self.base_url}/{media_id}"

        params = {
            "fields": ",".join(fields),
            "access_token": self.access_token
        }

        try:
            r = requests.get(url, params=params, timeout=30)

            if not r.ok:
                error_data = (
                    r.json() if r.headers.get("content-type") == "application/json"
                    else r.text
                )
                logger.error(f"Metrics retrieval failed: {error_data}")
                raise Exception(f"Metrics retrieval failed ({r.status_code}): {error_data}")

            return r.json()

        except requests.RequestException as e:
            logger.error(f"Request error during metrics retrieval: {e}")
            raise
