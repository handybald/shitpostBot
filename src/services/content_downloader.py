"""
Content Downloader - Automatically downloads videos and music from free sources.

Uses AI-generated search terms to find and download copyright-free content from:
- Pexels (videos - 100% free, no API limits)
- Pixabay (videos and music - 100% free)
"""

import os
import requests
from pathlib import Path
from typing import Optional, List
import random
import time

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ContentDownloader:
    """Download videos and music from free stock sites."""

    def __init__(self):
        """Initialize content downloader."""
        self.video_dir = Path("data/raw/videos")
        self.music_dir = Path("data/raw/music")

        # Create directories
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.music_dir.mkdir(parents=True, exist_ok=True)

        # Pexels API (get free key at https://www.pexels.com/api/)
        self.pexels_api_key = os.getenv("PEXELS_API_KEY")

        # Pixabay API (get free key at https://pixabay.com/api/docs/)
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY")

        if not self.pexels_api_key or self.pexels_api_key == "your_pexels_api_key_here":
            logger.warning("PEXELS_API_KEY not set - get free key at https://www.pexels.com/api/")
            logger.warning("Without API key, will use fallback stock content")
        else:
            logger.info("Pexels API configured for video downloads")

        if not self.pixabay_api_key or self.pixabay_api_key == "your_pixabay_api_key_here":
            logger.warning("PIXABAY_API_KEY not set - get free key at https://pixabay.com/api/docs/")
        else:
            logger.info("Pixabay API configured for music downloads")

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
            theme: Content theme for organizing
            filename_prefix: Optional prefix for filename

        Returns:
            Path to downloaded file, or None if failed
        """
        if not self.pexels_api_key or self.pexels_api_key == "your_pexels_api_key_here":
            logger.error("Pexels API key required - get free at https://www.pexels.com/api/")
            return None

        # Try each search term until one works
        for search_term in search_terms:
            try:
                # Generate filename
                if filename_prefix:
                    output_filename = f"{filename_prefix}_{theme}.mp4"
                else:
                    safe_term = search_term.replace(" ", "_").replace("/", "_")[:30]
                    output_filename = f"{safe_term}_{theme}.mp4"

                output_path = self.video_dir / output_filename

                # Skip if already exists
                if output_path.exists():
                    logger.info(f"Video already exists: {output_filename}")
                    return output_path

                logger.info(f"Searching Pexels for: '{search_term}'")

                # Search Pexels API
                url = "https://api.pexels.com/videos/search"
                headers = {"Authorization": self.pexels_api_key}
                params = {
                    "query": search_term,
                    "orientation": "portrait",  # Vertical for Instagram
                    "size": "medium",
                    "per_page": 10
                }

                response = requests.get(url, headers=headers, params=params, timeout=15)

                if response.status_code != 200:
                    logger.warning(f"Pexels API error: {response.status_code}")
                    time.sleep(2)
                    continue

                data = response.json()

                if not data.get("videos"):
                    logger.warning(f"No videos found for: {search_term}")
                    continue

                # Get random video from results
                video = random.choice(data["videos"][:5])  # Pick from top 5

                # Find best portrait video file (HD, vertical)
                video_file = None
                for file in video["video_files"]:
                    height = file.get("height", 0)
                    width = file.get("width", 0)
                    # Look for portrait orientation (height > width) and HD quality
                    if height >= 720 and width < height:
                        video_file = file
                        break

                if not video_file:
                    # Fallback to first available file
                    video_file = video["video_files"][0] if video["video_files"] else None

                if not video_file:
                    logger.warning(f"No suitable video file found for: {search_term}")
                    continue

                # Download video
                logger.info(f"Downloading video from Pexels (ID: {video['id']})...")
                video_response = requests.get(video_file["link"], timeout=60)

                if video_response.status_code == 200:
                    output_path.write_bytes(video_response.content)
                    size_mb = len(video_response.content) / 1024 / 1024
                    logger.info(f"✅ Downloaded video: {output_filename} ({size_mb:.1f} MB)")
                    return output_path
                else:
                    logger.warning(f"Failed to download video file: {video_response.status_code}")
                    continue

            except requests.Timeout:
                logger.warning(f"Download timeout for: {search_term}")
                continue
            except Exception as e:
                logger.error(f"Error downloading video with '{search_term}': {e}")
                continue

            # Rate limit (Pexels allows 200 requests/hour)
            time.sleep(1)

        logger.error("Failed to download video with any search term")
        return None

    def download_music(
        self,
        search_terms: List[str],
        theme: str,
        filename_prefix: Optional[str] = None
    ) -> Optional[Path]:
        """
        Download music from Pixabay using search terms.

        Args:
            search_terms: List of search terms to try
            theme: Content theme for organizing
            filename_prefix: Optional prefix for filename

        Returns:
            Path to downloaded file, or None if failed
        """
        if not self.pixabay_api_key or self.pixabay_api_key == "your_pixabay_api_key_here":
            logger.error("Pixabay API key required - get free at https://pixabay.com/api/docs/")
            return None

        # Try each search term until one works
        for search_term in search_terms:
            # Generate filename (will use m4a format to avoid conversion issues)
            if filename_prefix:
                output_filename = f"{filename_prefix}_{theme}.m4a"
            else:
                safe_term = search_term.replace(" ", "_").replace("/", "_")[:30]
                output_filename = f"{safe_term}_{theme}.m4a"

            output_path = self.music_dir / output_filename

            # Skip if already exists
            if output_path.exists():
                logger.info(f"Music already exists: {output_filename}")
                return output_path

            logger.info(f"Downloading music for: '{search_term}'")

            # Use yt-dlp to download copyright-free phonk music from YouTube
            try:
                import subprocess

                # Build search query
                yt_search = f"ytsearch1:{search_term} no copyright"

                # Download with yt-dlp (download best audio directly, no conversion needed)
                cmd = [
                    "yt-dlp",
                    "-f", "bestaudio[ext=m4a]/bestaudio",  # Download m4a directly (no conversion)
                    "-o", output_path.as_posix(),
                    "--no-playlist",
                    "--quiet",
                    "--no-warnings",
                    yt_search
                ]

                logger.info(f"Running yt-dlp: {yt_search}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                if result.returncode == 0 and output_path.exists():
                    size_mb = output_path.stat().st_size / 1024 / 1024
                    logger.info(f"✅ Downloaded music: {output_path.name} ({size_mb:.1f} MB)")
                    return output_path
                else:
                    logger.warning(f"yt-dlp failed for '{search_term}': {result.stderr}")
                    continue

            except subprocess.TimeoutExpired:
                logger.warning(f"Download timeout for: {search_term}")
                continue
            except FileNotFoundError:
                logger.error("yt-dlp not installed - install with: pip install yt-dlp")
                return None
            except Exception as e:
                logger.error(f"Error downloading music: {e}")
                continue
            finally:
                # Rate limit between searches
                time.sleep(1)

        logger.error("Failed to download music with any search term")
        return None

    def download_content_for_idea(
        self,
        content_idea
    ) -> dict:
        """
        Download both video and music for a ContentSuggestion.

        Args:
            content_idea: ContentSuggestion from Gemini

        Returns:
            Dict with video_path and music_path (or None if failed)
        """
        logger.info(f"Downloading content for theme: {content_idea.theme}")

        # Download video
        video_path = self.download_video(
            search_terms=content_idea.video_search_terms,
            theme=content_idea.theme
        )

        # Download music
        music_path = self.download_music(
            search_terms=content_idea.music_search_terms,
            theme=content_idea.theme
        )

        return {
            "video_path": video_path,
            "music_path": music_path
        }
