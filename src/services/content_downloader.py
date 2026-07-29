"""
Content Downloader - downloads video/music candidates from free stock APIs.

Sources:
- Pexels (video) - https://www.pexels.com/api/
- Pixabay (video) - https://pixabay.com/api/docs/
- Jamendo (music) - https://developer.jamendo.com/

Note: Pixabay's public API only covers images/video, not audio, despite
older docs in this project claiming otherwise - there is no free official
"Pixabay music API". Jamendo is the real free-tier music API used here.

This module intentionally does NOT scrape YouTube/Reddit via yt-dlp. That
fallback used to exist for themes flagged "hazardous" (Pexels/Pixabay don't
carry violent/hunting footage), but scraping breaks constantly (site
changes, throttling, no SLA) and is a bad tradeoff for a background job that
needs to run unattended. If a theme's stock-footage pool is consistently
too thin, that's a signal to source a curated/paid library for it (see
FootageQC.check_pool_health), not to scrape.

Every candidate downloaded here is *unvetted* - callers must run it through
src.processors.footage_qc.FootageQC before treating it as usable.
"""

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"
JAMENDO_SEARCH_URL = "https://api.jamendo.com/v3.0/tracks/"


class ContentDownloader:
    """Downloads unvetted video/music candidates from free stock APIs."""

    def __init__(self):
        self.video_dir = Path("data/raw/videos")
        self.music_dir = Path("data/raw/music")
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.music_dir.mkdir(parents=True, exist_ok=True)

        self.pexels_api_key = os.getenv("PEXELS_API_KEY")
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY")
        self.jamendo_client_id = os.getenv("JAMENDO_CLIENT_ID")

        if not self._configured(self.pexels_api_key, "your_pexels_api_key_here"):
            logger.warning("PEXELS_API_KEY not set - get free key at https://www.pexels.com/api/")
        if not self._configured(self.pixabay_api_key, "your_pixabay_api_key_here"):
            logger.warning("PIXABAY_API_KEY not set - get free key at https://pixabay.com/api/docs/")
        if not self._configured(self.jamendo_client_id, "your_jamendo_client_id_here"):
            logger.warning("JAMENDO_CLIENT_ID not set - get free key at https://developer.jamendo.com/")

    @staticmethod
    def _configured(value: Optional[str], placeholder: str) -> bool:
        return bool(value) and value != placeholder

    # ------------------------------------------------------------------
    # Video candidates (over-fetched, unvetted - caller runs FootageQC)
    # ------------------------------------------------------------------
    def download_video_candidates(
        self,
        search_terms: List[str],
        theme: str,
        count: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Downloads up to `count` candidate clips across Pexels and Pixabay,
        spread across the given search terms for variety. Over-fetching
        instead of taking the first match is what lets FootageQC actually
        pick the best clip rather than whatever search happened to rank
        first.
        """
        candidates: List[Dict[str, Any]] = []

        per_source_target = max(1, count // 2)
        if self._configured(self.pexels_api_key, "your_pexels_api_key_here"):
            candidates.extend(self._fetch_pexels_videos(search_terms, theme, per_source_target))
        if self._configured(self.pixabay_api_key, "your_pixabay_api_key_here"):
            candidates.extend(self._fetch_pixabay_videos(search_terms, theme, count - len(candidates)))

        if not candidates:
            logger.error(
                f"No video candidates found for theme '{theme}' "
                f"(check PEXELS_API_KEY/PIXABAY_API_KEY are configured)"
            )
        return candidates[:count]

    def _fetch_pexels_videos(
        self, search_terms: List[str], theme: str, target_count: int
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        headers = {"Authorization": self.pexels_api_key}

        for search_term in search_terms:
            if len(results) >= target_count:
                break
            try:
                params = {
                    "query": search_term,
                    "orientation": "portrait",
                    "size": "large",
                    "per_page": 15,
                    "page": random.randint(1, 3),
                }
                response = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"Pexels API error {response.status_code} for '{search_term}'")
                    continue

                videos = response.json().get("videos", [])
                # Take several per search term (not just the top hit) so the
                # QC step has real options to choose between.
                per_term_needed = max(1, target_count - len(results))
                for video in videos[: per_term_needed * 2]:
                    video_file = self._best_portrait_file(video.get("video_files", []))
                    if not video_file:
                        continue
                    output_path = self.video_dir / f"pexels_{video['id']}_{theme}.mp4"
                    if not output_path.exists():
                        if not self._download_file(video_file["link"], output_path):
                            continue
                    results.append({
                        "path": output_path, "url": video_file["link"],
                        "source": "pexels", "source_id": str(video["id"]),
                    })
                    if len(results) >= target_count:
                        break
            except requests.RequestException as e:
                logger.warning(f"Pexels request failed for '{search_term}': {e}")
            time.sleep(0.5)  # stay well under Pexels' 200 req/hour default limit

        return results

    def _fetch_pixabay_videos(
        self, search_terms: List[str], theme: str, target_count: int
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for search_term in search_terms:
            if len(results) >= target_count:
                break
            try:
                params = {
                    "key": self.pixabay_api_key,
                    "q": search_term,
                    "video_type": "film",
                    "per_page": 15,
                }
                response = requests.get(PIXABAY_VIDEO_URL, params=params, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"Pixabay API error {response.status_code} for '{search_term}'")
                    continue

                hits = response.json().get("hits", [])
                per_term_needed = max(1, target_count - len(results))
                for hit in hits[: per_term_needed * 2]:
                    video_variant = hit.get("videos", {}).get("large") or hit.get("videos", {}).get("medium")
                    if not video_variant or not video_variant.get("url"):
                        continue
                    output_path = self.video_dir / f"pixabay_{hit['id']}_{theme}.mp4"
                    if not output_path.exists():
                        if not self._download_file(video_variant["url"], output_path):
                            continue
                    results.append({
                        "path": output_path, "url": video_variant["url"],
                        "source": "pixabay", "source_id": str(hit["id"]),
                    })
                    if len(results) >= target_count:
                        break
            except requests.RequestException as e:
                logger.warning(f"Pixabay request failed for '{search_term}': {e}")
            time.sleep(0.5)

        return results

    @staticmethod
    def _best_portrait_file(video_files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        best_hd = None
        for file in video_files:
            width, height = file.get("width", 0), file.get("height", 0)
            if width >= height:
                continue  # not portrait
            if height >= 1080:
                return file
            if height >= 720 and best_hd is None:
                best_hd = file
        return best_hd or (video_files[0] if video_files else None)

    @staticmethod
    def _download_file(url: str, output_path: Path) -> bool:
        try:
            response = requests.get(url, timeout=60)
            if response.status_code != 200:
                logger.warning(f"Download failed ({response.status_code}): {url}")
                return False
            output_path.write_bytes(response.content)
            return True
        except requests.RequestException as e:
            logger.warning(f"Download error for {url}: {e}")
            return False

    # ------------------------------------------------------------------
    # Music candidates (Jamendo)
    # ------------------------------------------------------------------
    def download_music_candidates(
        self,
        search_terms: List[str],
        theme: str,
        count: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Downloads up to `count` candidate tracks from Jamendo. Jamendo's
        catalog is independent-artist Creative Commons music; license terms
        vary per track, so this only keeps tracks whose `license_ccurl`
        Jamendo returns (i.e. it has a resolvable CC license) - still worth
        a manual spot-check before commercial use at scale.
        """
        if not self._configured(self.jamendo_client_id, "your_jamendo_client_id_here"):
            logger.error("Jamendo not configured - set JAMENDO_CLIENT_ID")
            return []

        results: List[Dict[str, Any]] = []
        for search_term in search_terms:
            if len(results) >= count:
                break
            try:
                params = {
                    "client_id": self.jamendo_client_id,
                    "format": "json",
                    "search": search_term,
                    "limit": max(5, count),
                    "include": "musicinfo",
                    "audioformat": "mp32",
                }
                response = requests.get(JAMENDO_SEARCH_URL, params=params, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"Jamendo API error {response.status_code} for '{search_term}'")
                    continue

                tracks = response.json().get("results", [])
                for track in tracks:
                    if len(results) >= count:
                        break
                    audio_url = track.get("audio")
                    license_url = track.get("license_ccurl")
                    if not audio_url or not license_url:
                        continue  # skip anything without a resolvable license

                    output_path = self.music_dir / f"jamendo_{track['id']}_{theme}.mp3"
                    if not output_path.exists():
                        if not self._download_file(audio_url, output_path):
                            continue
                    results.append({
                        "path": output_path, "url": audio_url,
                        "source": "jamendo", "source_id": str(track["id"]),
                        "license_url": license_url,
                    })
            except requests.RequestException as e:
                logger.warning(f"Jamendo request failed for '{search_term}': {e}")
            time.sleep(0.5)

        if not results:
            logger.error(f"No music candidates found for theme '{theme}'")
        return results

    # ------------------------------------------------------------------
    def download_content_for_idea(
        self,
        content_idea,
        video_count: int = 10,
        music_count: int = 5,
    ) -> Dict[str, Any]:
        """
        Downloads candidate video/music pools for a ContentSuggestion.
        Returns raw, unvetted candidate lists - the caller must run them
        through FootageQC (video) before use.
        """
        logger.info(f"Downloading content candidates for theme: {content_idea.theme}")

        video_candidates = self.download_video_candidates(
            search_terms=content_idea.video_search_terms,
            theme=content_idea.theme,
            count=video_count,
        )
        music_candidates = self.download_music_candidates(
            search_terms=content_idea.music_search_terms,
            theme=content_idea.theme,
            count=music_count,
        )

        return {
            "video_candidates": video_candidates,
            "music_candidates": music_candidates,
        }
