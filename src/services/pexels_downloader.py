"""
Pexels API Content Downloader - Downloads videos and music from Pexels (100% free, no copyright).

Better alternative to YouTube for automated content generation.
"""

import os
import requests
from pathlib import Path
from typing import Optional, List
import random
import time

from src.utils.logger import get_logger

logger = get_logger(__name__)


class PexelsDownloader:
    """Download videos from Pexels using their API."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Pexels downloader.

        Args:
            api_key: Pexels API key (get free at https://www.pexels.com/api/)
        """
        self.api_key = api_key or os.getenv("PEXELS_API_KEY")
        self.video_dir = Path("data/raw/videos")
        self.music_dir = Path("data/raw/music")

        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.music_dir.mkdir(parents=True, exist_ok=True)

        self.has_api_key = bool(self.api_key and self.api_key != "your_pexels_api_key_here")

        if self.has_api_key:
            logger.info("Pexels API initialized")
        else:
            logger.warning("Pexels API key not configured - set PEXELS_API_KEY in .env")

    def download_video(
        self,
        search_terms: List[str],
        theme: str,
        filename_prefix: Optional[str] = None
    ) -> Optional[Path]:
        """
        Download a video from Pexels using search terms.

        Args:
            search_terms: List of search terms to try
            theme: Content theme
            filename_prefix: Optional filename prefix

        Returns:
            Path to downloaded file or None
        """
        if not self.has_api_key:
            logger.error("Pexels API key required")
            return self._use_placeholder_video(theme)

        # Try each search term
        for search_term in search_terms:
            try:
                # Search for videos
                url = "https://api.pexels.com/videos/search"
                headers = {"Authorization": self.api_key}
                params = {
                    "query": search_term,
                    "orientation": "portrait",  # Vertical for Instagram
                    "size": "medium",
                    "per_page": 5
                }

                logger.info(f"Searching Pexels for: '{search_term}'")
                response = requests.get(url, headers=headers, params=params, timeout=10)

                if response.status_code != 200:
                    logger.warning(f"Pexels API error: {response.status_code}")
                    continue

                data = response.json()

                if not data.get("videos"):
                    logger.warning(f"No videos found for: {search_term}")
                    continue

                # Get random video from results
                video = random.choice(data["videos"])

                # Find HD portrait video file
                video_file = None
                for file in video["video_files"]:
                    if file.get("height", 0) >= 1080 and file.get("width", 0) < file.get("height", 0):
                        video_file = file
                        break

                if not video_file:
                    # Fallback to any file
                    video_file = video["video_files"][0]

                # Download video
                if filename_prefix:
                    output_filename = f"{filename_prefix}_{theme}.mp4"
                else:
                    safe_term = search_term.replace(" ", "_")[:30]
                    output_filename = f"{safe_term}_{theme}_{video['id']}.mp4"

                output_path = self.video_dir / output_filename

                if output_path.exists():
                    logger.info(f"Video already exists: {output_filename}")
                    return output_path

                logger.info(f"Downloading video from Pexels: {video_file['link']}")

                video_response = requests.get(video_file["link"], timeout=60)
                if video_response.status_code == 200:
                    output_path.write_bytes(video_response.content)
                    logger.info(f"✅ Downloaded video: {output_filename} ({len(video_response.content) / 1024 / 1024:.1f} MB)")
                    return output_path

            except Exception as e:
                logger.error(f"Error downloading from Pexels: {e}")
                continue

            # Rate limit
            time.sleep(1)

        logger.error("Failed to download video from Pexels")
        return self._use_placeholder_video(theme)

    def _use_placeholder_video(self, theme: str) -> Optional[Path]:
        """
        Create or use a placeholder video when downloads fail.

        Args:
            theme: Content theme

        Returns:
            Path to placeholder or None
        """
        # For now, just log and return None
        # In production, you could generate a simple colored background video
        logger.warning(f"No video available for theme: {theme}")
        return None

    def download_music_placeholder(self, theme: str) -> Optional[Path]:
        """
        Music downloads aren't supported by Pexels API.
        For music, recommend using:
        - Pixabay Music API
        - YouTube Audio Library
        - Manual downloads from free sites

        Args:
            theme: Content theme

        Returns:
            None (music requires different source)
        """
        logger.warning("Music downloads require different API (Pixabay, Freesound, etc.)")
        logger.info("For phonk music, manually download from:")
        logger.info("  - Pixabay Music: https://pixabay.com/music/")
        logger.info("  - YouTube Audio Library: https://studio.youtube.com")
        logger.info("  - Free Music Archive: https://freemusicarchive.org")
        return None


def create_pexels_downloader() -> PexelsDownloader:
    """Factory function."""
    return PexelsDownloader()
