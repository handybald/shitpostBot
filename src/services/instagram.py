"""
Instagram Graph API service for uploading and publishing reels.

Handles:
- Media container creation
- Status polling
- Publishing to Instagram
- Metrics retrieval
- S3 integration for video hosting
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

import requests
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import subprocess

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance

logger = get_logger(__name__)


class InstagramService:
    """Wrapper around Instagram Graph API for reel uploading and publishing."""

    def __init__(self, user_id: str, access_token: str, api_version: str = "v19.0"):
        """
        Initialize Instagram service.

        Args:
            user_id: Instagram Business Account ID
            access_token: Instagram Graph API access token
            api_version: API version (default: v19.0)
        """
        self.user_id = user_id
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.instagram.com/{api_version}"

    @classmethod
    def from_config(cls):
        """Create service from configuration."""
        config = get_config_instance()
        return cls(
            user_id=config.get("instagram.user_id"),
            access_token=config.get("instagram.access_token"),
            api_version=config.get("instagram.api_version", "v19.0")
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
        expires: int = 3600
    ) -> str:
        """
        Upload video to S3 and return presigned URL.

        Args:
            local_path: Path to local video file
            bucket: S3 bucket name
            region: AWS region
            expires: URL expiration in seconds

        Returns:
            Presigned S3 URL
        """
        s3 = boto3.client("s3", region_name=region)
        key = f"reels/{local_path.name}"

        logger.info(f"Uploading {local_path.name} to S3 bucket {bucket}")

        try:
            s3.upload_file(
                local_path.as_posix(),
                bucket,
                key,
                ExtraArgs={"ContentType": "video/mp4"}
            )
            logger.info(f"S3 upload complete: {key}")
        except (BotoCoreError, ClientError) as e:
            logger.error(f"S3 upload failed: {e}")
            raise

        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url

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
            Exception: If container creation fails
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

            if not r.ok:
                error_data = (
                    r.json() if r.headers.get("content-type") == "application/json"
                    else r.text
                )
                logger.error(f"Container creation failed: {error_data}")
                raise Exception(f"Container creation failed ({r.status_code}): {error_data}")

            response = r.json()
            if "id" not in response:
                logger.error(f"No container ID in response: {response}")
                raise Exception(f"No container ID in response: {response}")

            logger.info(f"Container created: {response['id']}")
            return response["id"]

        except requests.RequestException as e:
            logger.error(f"Request error during container creation: {e}")
            raise

    def get_status(self, creation_id: str) -> Dict[str, Any]:
        """
        Poll the status of a media container.

        Args:
            creation_id: Container ID returned from create_container()

        Returns:
            Status response dict with 'status' and 'status_code'

        Raises:
            Exception: If status check fails
        """
        url = f"{self.base_url}/{creation_id}"

        params = {
            "fields": "status,status_code",
            "access_token": self.access_token
        }

        try:
            r = requests.get(url, params=params, timeout=30)

            if not r.ok:
                error_data = (
                    r.json() if r.headers.get("content-type") == "application/json"
                    else r.text
                )
                logger.error(f"Status check failed: {error_data}")
                raise Exception(f"Status check failed ({r.status_code}): {error_data}")

            return r.json()

        except requests.RequestException as e:
            logger.error(f"Request error during status check: {e}")
            raise

    def publish_container(self, creation_id: str) -> str:
        """
        Publish a finished media container to Instagram.

        Args:
            creation_id: Container ID (must have status=FINISHED)

        Returns:
            Published media ID

        Raises:
            Exception: If publish fails
        """
        url = f"{self.base_url}/{self.user_id}/media_publish"

        data = {
            "creation_id": creation_id,
            "access_token": self.access_token
        }

        logger.info("Publishing media...")

        try:
            r = requests.post(url, data=data, timeout=60)

            if not r.ok:
                error_data = (
                    r.json() if r.headers.get("content-type") == "application/json"
                    else r.text
                )
                logger.error(f"Publish failed: {error_data}")
                raise Exception(f"Publish failed ({r.status_code}): {error_data}")

            response = r.json()
            if "id" not in response:
                logger.error(f"No media ID in publish response: {response}")
                raise Exception(f"No media ID in publish response: {response}")

            logger.info(f"Published successfully: {response['id']}")
            return response["id"]

        except requests.RequestException as e:
            logger.error(f"Request error during publish: {e}")
            raise

    def publish_reel(
        self,
        video_url: str,
        caption: str,
        video_path: Optional[Path] = None,
        poll_seconds: int = 5,
        max_polls: int = 60
    ) -> str:
        """
        Full workflow: create container → poll → publish.

        Args:
            video_url: URL to video
            caption: Post caption
            video_path: Optional local path for duration extraction
            poll_seconds: Poll interval
            max_polls: Maximum poll attempts

        Returns:
            Published media ID

        Raises:
            Exception: If any step fails
        """
        # Create container
        creation_id = self.create_container(video_url, caption, video_path)

        # Poll until finished
        logger.info(f"Polling status (max {max_polls} attempts, {poll_seconds}s interval)...")

        for attempt in range(max_polls):
            time.sleep(poll_seconds)

            try:
                status_data = self.get_status(creation_id)
                status = status_data.get("status")

                logger.info(f"[{attempt + 1}/{max_polls}] status: {status}")

                if status == "FINISHED":
                    logger.info("Container finished, proceeding to publish")
                    break
                elif status in ("ERROR", "FAILED"):
                    error_msg = f"Processing failed: {status_data}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

            except Exception as e:
                if "Processing failed" in str(e):
                    raise
                logger.warning(f"Status check error (attempt {attempt + 1}): {e}")
                continue
        else:
            error_msg = f"Container did not finish within {max_polls} polls"
            logger.error(error_msg)
            raise Exception(error_msg)

        # Publish
        media_id = self.publish_container(creation_id)
        return media_id

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
