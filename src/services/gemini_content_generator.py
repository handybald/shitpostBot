"""
Gemini-powered content generator for high-quality post creation.

Generates:
- Redpill/motivational prompts
- Phonk music recommendations
- Background video suggestions
- Engaging captions

Uses Google's Gemini API (free tier available).
"""

import os
import json
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ContentSuggestion:
    """AI-generated content suggestion."""
    prompt: str
    caption: str
    theme: str
    music_vibe: str
    video_style: str
    hashtags: List[str]
    music_search_terms: List[str]  # Search terms for finding phonk music
    video_search_terms: List[str]  # Search terms for finding background videos

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "caption": self.caption,
            "theme": self.theme,
            "music_vibe": self.music_vibe,
            "video_style": self.video_style,
            "hashtags": self.hashtags,
            "music_search_terms": self.music_search_terms,
            "video_search_terms": self.video_search_terms
        }


class GeminiContentGenerator:
    """Generate high-quality content using Google Gemini AI."""

    CONTENT_THEMES = [
        "redpill_reality",
        "sigma_mindset",
        "financial_freedom",
        "self_improvement",
        "brutal_truth",
        "stoic_philosophy",
        "monk_mode",
        "high_value_mindset"
    ]

    PHONK_VIBES = [
        "aggressive_bass_heavy",
        "dark_atmospheric",
        "memphis_phonk",
        "drift_phonk",
        "cowbell_heavy",
        "distorted_808s"
    ]

    VIDEO_STYLES = [
        "luxury_lifestyle",
        "urban_night_drive",
        "gym_motivation",
        "nature_solitude",
        "city_lights",
        "abstract_geometric",
        "sports_car_footage",
        "rain_aesthetic"
    ]

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini content generator.

        Args:
            api_key: Google Gemini API key (or uses GEMINI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            logger.warning("Gemini API key not configured, using fallback generation")
            self.client = None
        else:
            try:
                from google import genai
                self.genai_client = genai.Client(api_key=self.api_key)
                # Use gemini-2.5-flash (latest free tier model)
                self.model_name = 'gemini-2.5-flash'
                self.client = self.genai_client  # For compatibility checks
                logger.info("Gemini content generator initialized with gemini-2.5-flash (new API)")
            except ImportError:
                logger.error("google-genai package not installed. Install with: pip install google-genai")
                self.client = None
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.client = None

    def generate_content_idea(
        self,
        theme: Optional[str] = None,
        style: str = "redpill_motivational"
    ) -> ContentSuggestion:
        """
        Generate a complete content idea with prompt, caption, and suggestions.

        Args:
            theme: Optional specific theme to use
            style: Content style (redpill_motivational, stoic, sigma, etc.)

        Returns:
            ContentSuggestion with all generated elements
        """
        if not self.client:
            return self._fallback_content_idea(theme, style)

        try:
            prompt = self._build_generation_prompt(theme, style)

            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            content = self._parse_gemini_response(response.text)

            logger.info(f"Generated content idea: {content.theme}")
            return content

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            return self._fallback_content_idea(theme, style)

    def generate_redpill_prompt(self) -> str:
        """Generate a powerful redpill/truth bomb prompt."""
        if not self.client:
            return self._fallback_redpill_prompt()

        try:
            prompt = """Generate a powerful, thought-provoking "redpill" quote about reality, success, or self-improvement.

Requirements:
- 10-20 words maximum
- Hard truth or brutal reality
- Motivational but realistic
- No fluff or generic platitudes
- Should make people think differently
- Sigma/high-value mindset

Examples:
- "Most people die at 25 but aren't buried until 75"
- "Comfort is the enemy of progress"
- "Your competition is working while you're sleeping"

Generate ONE powerful quote, nothing else:"""

            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            quote = response.text.strip().strip('"').strip("'")
            logger.info(f"Generated redpill prompt: {quote[:50]}...")
            return quote

        except Exception as e:
            logger.error(f"Failed to generate redpill prompt: {e}")
            return self._fallback_redpill_prompt()

    def suggest_phonk_music_vibe(self, theme: str) -> Dict[str, Any]:
        """
        Suggest phonk music characteristics for the theme.

        Args:
            theme: Content theme

        Returns:
            Dict with music vibe suggestions
        """
        vibe_map = {
            "redpill_reality": {
                "style": "aggressive_bass_heavy",
                "bpm_range": "140-160",
                "characteristics": ["heavy 808s", "distorted bass", "dark atmosphere"],
                "example_keywords": ["drift phonk", "brazilian phonk", "aggressive"]
            },
            "sigma_mindset": {
                "style": "dark_atmospheric",
                "bpm_range": "130-150",
                "characteristics": ["cowbell", "memphis samples", "hypnotic"],
                "example_keywords": ["sigma phonk", "memphis", "underground"]
            },
            "stoic_philosophy": {
                "style": "ambient_phonk",
                "bpm_range": "100-120",
                "characteristics": ["reverb heavy", "atmospheric", "slow trap"],
                "example_keywords": ["chill phonk", "ambient", "meditation"]
            },
            "monk_mode": {
                "style": "minimal_phonk",
                "bpm_range": "90-110",
                "characteristics": ["sparse", "deep bass", "focused"],
                "example_keywords": ["minimal phonk", "lo-fi phonk", "focus"]
            }
        }

        return vibe_map.get(theme, vibe_map["redpill_reality"])

    def suggest_video_style(self, theme: str, music_vibe: str) -> str:
        """Suggest appropriate video background style."""
        suggestions = {
            "aggressive_bass_heavy": ["sports_car_footage", "urban_night_drive", "gym_motivation"],
            "dark_atmospheric": ["city_lights", "rain_aesthetic", "urban_night_drive"],
            "ambient_phonk": ["nature_solitude", "abstract_geometric", "rain_aesthetic"],
            "minimal_phonk": ["nature_solitude", "city_lights", "abstract_geometric"]
        }

        options = suggestions.get(music_vibe, self.VIDEO_STYLES)
        return random.choice(options)

    def _build_generation_prompt(self, theme: Optional[str], style: str) -> str:
        """Build comprehensive generation prompt for Gemini."""
        theme = theme or random.choice(self.CONTENT_THEMES)

        return f"""Generate a complete Instagram Reel content package for a {style} post.

Theme: {theme}
Style: {style}

Generate a JSON response with:
1. "prompt": A powerful 10-15 word quote/truth bomb (redpill style, no fluff)
2. "caption": Instagram caption under 150 chars with 2-3 hashtags
3. "theme": The theme category
4. "music_vibe": Phonk music style description
5. "video_style": Background video description
6. "hashtags": Array of 3-5 relevant hashtags
7. "music_search_terms": Array of 3-5 search terms to find the perfect phonk music (e.g., ["aggressive phonk", "drift phonk bass boosted", "brazilian phonk 808"])
8. "video_search_terms": Array of 3-5 search terms to find the perfect background video (e.g., ["night city drive 4k", "tokyo drift aesthetic", "urban cyberpunk"])

Requirements:
- Quote must be POWERFUL and thought-provoking
- Caption should be authentic and engaging
- Focus on hard truths, not generic motivation
- Sigma/high-value mindset
- No cringe or corporate speak
- Music search terms should be specific phonk subgenres or popular track styles
- Video search terms should be specific, searchable on YouTube/stock sites

Output ONLY valid JSON, no explanations:"""

    def _parse_gemini_response(self, response_text: str) -> ContentSuggestion:
        """Parse Gemini JSON response into ContentSuggestion."""
        try:
            # Extract JSON from response (Gemini sometimes adds markdown)
            text = response_text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)

            return ContentSuggestion(
                prompt=data.get("prompt", ""),
                caption=data.get("caption", ""),
                theme=data.get("theme", "general"),
                music_vibe=data.get("music_vibe", "aggressive_bass_heavy"),
                video_style=data.get("video_style", "urban_night_drive"),
                hashtags=data.get("hashtags", []),
                music_search_terms=data.get("music_search_terms", ["phonk music", "bass boosted phonk"]),
                video_search_terms=data.get("video_search_terms", ["aesthetic video", "urban night"])
            )

        except Exception as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            return self._fallback_content_idea()

    def _fallback_redpill_prompt(self) -> str:
        """Fallback redpill prompts when API is unavailable."""
        prompts = [
            "Most people die at 25 but aren't buried until 75",
            "Comfort is the enemy of progress",
            "Your competition is working while you're sleeping",
            "Discipline is choosing between what you want now and what you want most",
            "The hardest choices require the strongest wills",
            "Excellence is not an act but a habit",
            "Pain is temporary, regret is forever",
            "Success is lonely, failure is crowded",
            "The grind never stops, neither should you",
            "Weak men create hard times, hard times create strong men",
            "Your excuses are not valid, only your results matter",
            "The lion doesn't concern himself with the opinions of sheep",
            "Mediocrity is a choice, excellence is earned",
            "Comfort zones are where dreams go to die",
            "The successful do what the unsuccessful won't"
        ]
        return random.choice(prompts)

    def _fallback_content_idea(
        self,
        theme: Optional[str] = None,
        style: str = "redpill_motivational"
    ) -> ContentSuggestion:
        """Fallback content generation without API."""
        theme = theme or random.choice(self.CONTENT_THEMES)
        prompt = self._fallback_redpill_prompt()

        captions = [
            f"{prompt} 💪 #Motivation #Mindset #Success",
            f"Real talk: {prompt} 🔥 #RedPill #Truth #Growth",
            f"{prompt} ⚡ Time to level up. #Hustle #Grind #Win",
            f"Facts: {prompt} 🎯 #SigmaMindset #HighValue #Boss"
        ]

        # Fallback music and video search terms
        music_searches = {
            "redpill_reality": ["aggressive phonk", "drift phonk bass", "brazilian phonk"],
            "sigma_mindset": ["dark phonk", "memphis phonk", "sigma phonk"],
            "stoic_philosophy": ["ambient phonk", "chill phonk beats", "lo-fi phonk"],
            "monk_mode": ["minimal phonk", "deep phonk", "focus phonk"]
        }

        video_searches = {
            "redpill_reality": ["night city drive 4k", "urban aesthetic", "cyberpunk city"],
            "sigma_mindset": ["luxury lifestyle", "supercar driving", "business success"],
            "stoic_philosophy": ["nature solitude 4k", "meditation visuals", "ancient architecture"],
            "monk_mode": ["minimal aesthetic", "focus visuals", "monochrome abstract"]
        }

        return ContentSuggestion(
            prompt=prompt,
            caption=random.choice(captions),
            theme=theme,
            music_vibe=random.choice(self.PHONK_VIBES),
            video_style=random.choice(self.VIDEO_STYLES),
            hashtags=["#Motivation", "#Mindset", "#Success"],
            music_search_terms=music_searches.get(theme, ["phonk music", "bass boosted"]),
            video_search_terms=video_searches.get(theme, ["aesthetic video", "4k background"])
        )


def create_gemini_generator() -> GeminiContentGenerator:
    """Factory function to create Gemini generator."""
    return GeminiContentGenerator()
