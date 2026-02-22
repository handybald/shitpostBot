"""
Content Downloader - Automatically downloads videos and music from free sources.

Uses AI-generated search terms to find and download copyright-free content from:
- Pexels (videos - 100% free, no API limits)
- Pixabay (videos and music - 100% free)
"""

import os
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
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
        filename_prefix: Optional[str] = None,
        excluded_urls: Optional[set] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Download a video from Pexels using search terms.

        Args:
            search_terms: List of search terms to try
            theme: Content theme for organizing
            filename_prefix: Optional prefix for filename
            excluded_urls: Set of URLs to skip (for uniqueness)

        Returns:
            Path to downloaded file, or None if failed
        """
        if not self.pexels_api_key or self.pexels_api_key == "your_pexels_api_key_here":
            logger.error("Pexels API key required - get free at https://www.pexels.com/api/")
            # Fallback to YouTube if Pexels key is missing
            return self._download_video_youtube(search_terms, theme, filename_prefix)

        # PRIORITIZE YouTube for HAZARDOUS content (Pexels doesn't allow violence/hunting)
        hazardous_themes = ["redpill_reality", "sigma_mindset", "brutal_truth", "sigma_gaming"]
        is_hazardous_search = any(x in " ".join(search_terms).lower() for x in ["hunt", "kill", "fight", "attack", "predator", "blood", "war"])
        
        if theme in hazardous_themes or is_hazardous_search:
            logger.info(f"Theme '{theme}' or search terms detected as hazardous - Preferring Reddit/YouTube source...")
            
            # 1. Try Reddit first (most raw/authentic)
            reddit_path = self._download_video_reddit(theme, filename_prefix, excluded_urls)
            if reddit_path:
                return reddit_path

            # 2. Fallback to YouTube
            logger.info("Reddit scrape failed or no content, falling back to YouTube...")
            yt_path = self._download_video_youtube(search_terms, theme, filename_prefix)
            if yt_path:
                return yt_path
            
            # If both fail, fall back to Pexels (though it might be soft)
            logger.warning("YouTube download failed, falling back to Pexels...")

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
                    return {
                        "path": output_path,
                        "url": "existing_file",
                        "source": "pexels",
                        "source_id": "unknown"
                    }

                logger.info(f"Searching Pexels for: '{search_term}'")

                # Search Pexels API
                url = "https://api.pexels.com/videos/search"
                headers = {"Authorization": self.pexels_api_key}
                params = {
                    "query": search_term,
                    "orientation": "portrait",  # Vertical for Instagram
                    "size": "large",  # Download large/HD resolution to avoid scaling artifacts
                    "per_page": 20,  # Get more results to ensure diversity
                    "page": random.randint(1, 3)  # Randomize which page of results we fetch from
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

                # Diversify video selection: take from middle of results for variety
                # Using top 10-20 range helps avoid always picking the top 1-2 results
                available_videos = data["videos"]
                if len(available_videos) > 15:
                    # Shuffle and pick from a diverse range, not always the top ranked
                    candidate_videos = available_videos[5:15]  # Skip top results, get middle range
                elif len(available_videos) > 5:
                    candidate_videos = available_videos[:10]
                else:
                    candidate_videos = available_videos

                if len(candidate_videos) > 1:
                    # Random selection from diverse pool
                    video = random.choice(candidate_videos)
                else:
                    video = candidate_videos[0]

                # Find best portrait video file - prioritize FULL HD (1080p+) vertical
                video_file = None
                best_video = None

                for file in video["video_files"]:
                    height = file.get("height", 0)
                    width = file.get("width", 0)
                    # Look for portrait orientation (height > width)
                    if width < height:
                        # Prioritize 1080p+ (for Instagram Reels)
                        if height >= 1080:
                            video_file = file
                            break
                        # Fallback to any HD video
                        elif height >= 720 and best_video is None:
                            best_video = file

                # Use best HD video if full HD not found
                if not video_file and best_video:
                    video_file = best_video

                if not video_file:
                    # Last resort fallback to first available file
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

                    # Re-encode to fix interlacing/corruption issues from source
                    logger.info(f"Normalizing video encoding to fix corruption...")
                    try:
                        import subprocess
                        import tempfile

                        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf:
                            temp_path = Path(tf.name)

                        # Re-encode with strong deinterlacing to fix Vimeo artifacts
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", output_path.as_posix(),
                            "-vf", "yadif=mode=send_frame:parity=auto",
                            "-c:v", "libx264",
                            "-crf", "18",
                            "-pix_fmt", "yuv420p",
                            "-c:a", "aac",
                            "-loglevel", "error",
                            temp_path.as_posix()
                        ]

                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)

                        # Replace original with cleaned version
                        import shutil
                        shutil.move(temp_path.as_posix(), output_path.as_posix())
                        logger.info(f"✅ Video normalized: {output_filename}")

                    except Exception as e:
                        logger.warning(f"Could not normalize video, using as-is: {e}")

                    return {
                        "path": output_path,
                        "url": video_file["link"],
                        "source": "pexels",
                        "source_id": str(video["id"])
                    }
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

        # If Pexels fails or returns nothing, try YouTube (better for specific/hazardous content)
        logger.info("Pexels failed, trying YouTube for video content...")
        youtube_path = self._download_video_youtube(search_terms, theme, filename_prefix)
        if youtube_path:
            return youtube_path

        logger.error("Failed to download video with any search term")
        return None

    def _download_video_reddit(
        self,
        theme: str,
        filename_prefix: Optional[str] = None,
        excluded_urls: Optional[set] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Download video from Reddit (r/NatureIsMetal, etc.) for hazardous content.
        Does not use search terms, but fetches 'Top of Week' from relevant subreddits.
        """
        import sys
        import subprocess
        
        # Subreddits for hazardous content
        subreddits = ["NatureIsMetal", "HardcoreNature"]
        if "fight" in theme or "sigma" in theme:
            subreddits.append("fightporn")
        
        for subreddit in subreddits:
            try:
                logger.info(f"Checking r/{subreddit} for top content...")
                headers = {"User-Agent": "ShitPostBot/1.0"}
                url = f"https://www.reddit.com/r/{subreddit}/top.json?limit=25&t=week"
                
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    logger.warning(f"Failed to access r/{subreddit}: {response.status_code}")
                    continue
                
                data = response.json()
                posts = data.get("data", {}).get("children", [])
                
                # Collect ALL valid video candidates first
                candidates = []
                for post in posts:
                    post_data = post["data"]
                    video_url = post_data.get("url")
                    
                    # Check uniqueness
                    if excluded_urls and video_url in excluded_urls:
                        logger.debug(f"Skipping duplicate Reddit video: {video_url}")
                        continue

                    # Check if it's a video
                    is_video = post_data.get("is_video") or \
                               video_url.endswith(".mp4") or \
                               "v.redd.it" in video_url or \
                               "imgur.com" in video_url
                               
                    if is_video:
                        candidates.append(post_data)
                
                if not candidates:
                    logger.info(f"No video candidates found in r/{subreddit}")
                    continue
                    
                # Pick a random video from candidates to ensure variety
                logger.info(f"Found {len(candidates)} candidates in r/{subreddit}. Picking random one...")
                selected_post = random.choice(candidates)
                
                video_url = selected_post.get("url")
                title = selected_post.get("title", "reddit_video")
                
                # Generate filename
                if filename_prefix:
                    output_filename = f"{filename_prefix}_{theme}_reddit.mp4"
                else:
                    safe_title = "".join(x for x in title if x.isalnum() or x in "_")[:30]
                    # Append random ID to filename to avoid overwrites and allow duplicates if needed
                    import uuid
                    rnd_id = str(uuid.uuid4())[:4]
                    output_filename = f"{safe_title}_{theme}_{rnd_id}_reddit.mp4"
                    
                output_path = self.video_dir / output_filename
                
                # Skip if EXACT file exists (unlikely with random ID now)
                if output_path.exists():
                    logger.info(f"Reddit video already exists: {output_filename}")
                    return {
                        "path": output_path,
                        "url": video_url,
                        "source": "reddit",
                        "source_id": selected_post.get("id")
                    }
                    
                logger.info(f"Downloading from Reddit: {title} ({video_url})")
                
                # Use yt-dlp to download
                cmd = [
                    sys.executable, "-m", "yt_dlp",
                    "-f", "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "-o", output_path.as_posix(),
                    "--no-playlist",
                    "--quiet",
                    "--no-warnings",
                    video_url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if result.returncode == 0 and output_path.exists():
                    size_mb = output_path.stat().st_size / 1024 / 1024
                    logger.info(f"✅ Downloaded Reddit video: {output_filename} ({size_mb:.1f} MB)")
                    return {
                        "path": output_path,
                        "url": video_url,
                        "source": "reddit",
                        "source_id": selected_post.get("id")
                    }
                else:
                    logger.warning(f"yt-dlp failed for Reddit URL {video_url}: {result.stderr}")
                    continue
                        
            except Exception as e:
                logger.error(f"Error scraping Reddit r/{subreddit}: {e}")
                continue
                
        return None

    def _download_video_youtube(
        self,
        search_terms: List[str],
        theme: str,
        filename_prefix: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Download video from YouTube using yt-dlp."""
        import sys
        import subprocess
        
        for search_term in search_terms:
            try:
                # Generate filename
                if filename_prefix:
                    output_filename = f"{filename_prefix}_{theme}_yt.mp4"
                else:
                    safe_term = search_term.replace(" ", "_").replace("/", "_")[:30]
                    output_filename = f"{safe_term}_{theme}_yt.mp4"

                output_path = self.video_dir / output_filename
                
                if output_path.exists():
                    return {
                        "path": output_path,
                        "url": f"https://www.youtube.com/results?search_query={search_term}", # Approx URL
                        "source": "youtube",
                        "source_id": output_filename
                    }

                logger.info(f"Searching YouTube for: '{search_term}'")
                
                # Check for "hazardous" or "viral" themes where we want raw content (not stock)
                is_viral_theme = any(x in theme for x in ["sigma", "redpill", "brutal", "motivation", "nature"])
                
                if is_viral_theme:
                    # Search for Shorts/Vertical content which is often raw/viral style
                    # We remove "stock footage" to get actual clips (e.g. nature, fights)
                    search_query = f"{search_term} #shorts"
                else:
                    # For generic background, look for nice stock footage
                    search_query = f"{search_term} stock footage no copyright"
                
                # Search for high quality video
                yt_search = f"ytsearch1:{search_query}"
                
                cmd = [
                    sys.executable, "-m", "yt_dlp",
                    # Enforce H.264 (AVC) to avoid AV1 decoding errors
                    "-S", "codec:h264",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "-o", output_path.as_posix(),
                    # Remove download-sections to avoid ffmpeg errors
                    # VideoGenerator will handle trimming later
                    "--no-playlist",
                    "--quiet",
                    "--no-warnings",
                    yt_search
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if result.returncode == 0 and output_path.exists():
                    size_mb = output_path.stat().st_size / 1024 / 1024
                    logger.info(f"✅ Downloaded YouTube video: {output_filename} ({size_mb:.1f} MB)")
                    return {
                        "path": output_path,
                        "url": f"https://www.youtube.com/results?search_query={search_term}",
                        "source": "youtube",
                        "source_id": output_filename
                    }
                else:
                    logger.warning(f"yt-dlp video download failed for '{search_term}': {result.stderr}")
                    
            except Exception as e:
                logger.error(f"Error downloading YouTube video: {e}")
                continue
                
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
                # Use sys.executable -m yt_dlp to ensure we use the installed package in venv
                import sys
                cmd = [
                    sys.executable, "-m", "yt_dlp",
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
        content_idea,
        excluded_urls: Optional[set] = None
    ) -> dict:
        """
        Download both video and music for a ContentSuggestion.

        Args:
            content_idea: ContentSuggestion from Gemini
            excluded_urls: Set of video URLs to skip

        Returns:
            Dict with video_path and music_path (or None if failed)
        """
        logger.info(f"Downloading content for theme: {content_idea.theme}")

        # Download video
        video_data = self.download_video(
            search_terms=content_idea.video_search_terms,
            theme=content_idea.theme,
            excluded_urls=excluded_urls
        )

        # Download music
        music_path = self.download_music(
            search_terms=content_idea.music_search_terms,
            theme=content_idea.theme
        )

        return {
            "video_path": video_data["path"] if video_data else None,
            "video_data": video_data,
            "music_path": music_path
        }
