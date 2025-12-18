"""
Smart content selection system with weighted random selection and theme matching
"""

import random
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from src.database.repositories import (
    VideoRepository, MusicRepository, QuoteRepository
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ContentCombination:
    """Represents a selected combination of video, music, and quote"""
    def __init__(self, video, music, quote, theme: str = "general"):
        self.video = video
        self.music = music
        self.quote = quote
        self.theme = theme

    def __repr__(self):
        return f"<Combination {self.theme}: {self.video.filename} + {self.music.filename} + {self.quote.text[:30]}>"


class ContentSelector:
    """Intelligent content selection with weighted random + theme matching"""

    def __init__(self, session: Session, config: dict = None):
        self.session = session
        self.config = config or {}
        self.video_repo = VideoRepository(session)
        self.music_repo = MusicRepository(session)
        self.quote_repo = QuoteRepository(session)

        # Theme configuration
        self.themes = self.config.get("themes", {})
        self.avoid_recent = self.config.get("avoid_recent_assets", 10)
        self.prefer_less_used = self.config.get("prefer_less_used", True)

    def calculate_weight(self, asset, asset_type: str = "video") -> float:
        """
        Calculate selection weight based on usage count and recency.
        Less used assets get higher weights.

        Weight formula: base_weight * recency_factor
        where:
            base_weight = 1.0 / (1 + usage_count)
            recency_factor = 1.0 if last_used > 7 days else 0.5 (recently used = lower weight)
        """
        base_weight = 1.0 / (1.0 + asset.usage_count)

        # Penalize recently used assets
        if asset.last_used_at:
            days_since_use = (datetime.utcnow() - asset.last_used_at).days
            recency_factor = 0.2 if days_since_use < 7 else 1.0
        else:
            recency_factor = 1.0  # Never used = full weight

        final_weight = base_weight * recency_factor
        return max(final_weight, 0.1)  # Never let weight go to zero

    def select_by_weighted_random(self, assets: List, asset_type: str = "video") -> Optional:
        """Select asset using weighted random selection"""
        if not assets:
            return None

        # Calculate weights
        weights = [self.calculate_weight(asset, asset_type) for asset in assets]

        # Weighted random selection
        try:
            return random.choices(assets, weights=weights, k=1)[0]
        except Exception as e:
            logger.error(f"Error in weighted selection: {e}, falling back to random")
            return random.choice(assets)

    def select_video(self, theme: str = None) -> Optional:
        """Select a video, optionally filtered by theme"""
        try:
            if theme and theme in self.themes:
                theme_config = self.themes[theme]
                keywords = theme_config.get("video_keywords", [])
                # Filter videos by theme keywords (basic implementation)
                all_videos = self.video_repo.get_least_used(theme, limit=50)
            else:
                all_videos = self.video_repo.get_all()

            if not all_videos:
                logger.warning("No videos available")
                return None

            video = self.select_by_weighted_random(all_videos, "video")
            if video:
                logger.info(f"Selected video: {video.filename}")
            return video

        except Exception as e:
            logger.error(f"Error selecting video: {e}")
            return None

    def select_music(self, energy_level: str = None) -> Optional:
        """Select music, optionally filtered by energy level"""
        try:
            if energy_level:
                all_music = self.music_repo.get_by_energy(energy_level)
            else:
                # Prefer bass-heavy tracks
                all_music = self.music_repo.get_bass_heavy(min_bass_score=0.10)
                if not all_music:
                    all_music = self.music_repo.get_all()

            if not all_music:
                logger.warning("No music available")
                return None

            music = self.select_by_weighted_random(all_music, "music")
            if music:
                logger.info(f"Selected music: {music.filename}")
            return music

        except Exception as e:
            logger.error(f"Error selecting music: {e}")
            return None

    def select_quote(self, category: str = None, max_length: int = 100) -> Optional:
        """Select a quote, optionally filtered by category and length"""
        try:
            if category:
                all_quotes = self.quote_repo.get_by_category(category)
            else:
                all_quotes = self.quote_repo.get_short_quotes(max_length)

            if not all_quotes:
                logger.warning("No quotes available")
                return None

            quote = self.select_by_weighted_random(all_quotes, "quote")
            if quote:
                logger.info(f"Selected quote: {quote.text[:50]}...")
            return quote

        except Exception as e:
            logger.error(f"Error selecting quote: {e}")
            return None

    def is_valid_combination(self, video, music, quote) -> bool:
        """
        Check if combination is valid (not used recently, duration match, etc)
        """
        if not all([video, music, quote]):
            return False

        # Duration check: video should be shorter or similar to music
        if video.duration and music.duration:
            if video.duration > music.duration * 1.2:
                logger.warning(f"Video {video.duration}s longer than music {music.duration}s")
                return False

        return True

    def find_matching_combination(self, theme: str = None) -> Optional[ContentCombination]:
        """
        Find a complete valid combination of video, music, and quote.
        Attempts theme matching if theme is provided.
        """
        logger.info(f"Selecting content combination for theme: {theme or 'general'}")

        theme_config = {}
        if theme and theme in self.themes:
            theme_config = self.themes[theme]
            video_energy = None
            music_energy = theme_config.get("music_energy", "medium")
            quote_category = theme
        else:
            music_energy = None
            quote_category = None

        # Try up to 5 times to find valid combination
        for attempt in range(5):
            video = self.select_video(theme)
            music = self.select_music(music_energy)
            quote = self.select_quote(quote_category)

            if self.is_valid_combination(video, music, quote):
                combo = ContentCombination(video, music, quote, theme or "general")
                logger.info(f"Found valid combination on attempt {attempt + 1}: {combo}")
                return combo

        logger.error(f"Could not find valid combination after 5 attempts")
        return None

    def get_random_combination(self) -> Optional[ContentCombination]:
        """Get any valid combination without theme matching"""
        return self.find_matching_combination(theme=None)

    def get_themed_combination(self, theme: str) -> Optional[ContentCombination]:
        """Get combination matching specific theme"""
        if theme not in self.themes:
            logger.warning(f"Theme '{theme}' not configured, using random")
            return self.get_random_combination()
        return self.find_matching_combination(theme=theme)

    def get_next_theme(self) -> str:
        """Get next theme in rotation"""
        available_themes = list(self.themes.keys())
        if not available_themes:
            return None
        return random.choice(available_themes)

    def update_usage_counts(self, combo: ContentCombination):
        """Update usage counts after content selection"""
        try:
            self.video_repo.increment_usage(combo.video.id)
            self.music_repo.increment_usage(combo.music.id)
            self.quote_repo.increment_usage(combo.quote.id)
            logger.info(f"Updated usage counts for {combo}")
        except Exception as e:
            logger.error(f"Error updating usage counts: {e}")
