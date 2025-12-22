"""
LLM provider service for generating engaging captions.

Supports:
- Google Gemini API (Free tier, recommended)
- OpenAI API (GPT-4o-mini, GPT-4, etc.)
- Anthropic API (Claude, etc.)
- Fallback template-based captions

Generates captions tailored to:
- Content theme (motivation, philosophy, hustle)
- Quote and music vibe
- Instagram engagement best practices
"""

import os
import json
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance

logger = get_logger(__name__)


class CaptionGenerator(ABC):
    """Abstract base for caption generation."""

    @abstractmethod
    def generate(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Generate caption for reel."""
        pass


class OpenAIGenerator(CaptionGenerator):
    """Generate captions using OpenAI API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.8):
        """
        Initialize OpenAI generator.

        Args:
            api_key: OpenAI API key
            model: Model name (default: gpt-4o-mini for cost)
            temperature: Creativity level 0-1
        """
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai")

        self.model = model
        self.temperature = temperature
        logger.info(f"Initialized OpenAI generator with model: {model}")

    def generate(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Generate caption using OpenAI."""
        prompt = self._build_prompt(quote, theme, music_energy)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert Instagram content creator who writes engaging, authentic captions for motivational reels. Keep captions under 200 characters. Use relevant hashtags. Be concise and impactful."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=200,
            )

            caption = response.choices[0].message.content.strip()
            logger.info(f"OpenAI caption generated ({len(caption)} chars)")
            return caption

        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            raise

    def _build_prompt(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Build prompt for caption generation."""
        energy_desc = f" with {music_energy} energy" if music_energy else ""

        return f"""Generate an engaging Instagram reel caption for a {theme} themed reel{energy_desc}.

The reel features this quote: "{quote}"

Requirements:
- Under 200 characters
- Authentic and conversational
- Include 2-3 relevant hashtags
- Call to action (optional but encouraged)
- Match the {theme} theme vibe

Generate ONLY the caption, no explanations."""


class GeminiGenerator(CaptionGenerator):
    """Generate captions using Google Gemini API (free tier available)."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        """
        Initialize Gemini generator.

        Args:
            api_key: Google Gemini API key
            model: Model name (default: gemini-2.5-flash for free tier)
        """
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.model = model
        except ImportError:
            raise ImportError("google-genai package required. Install with: pip install google-genai")

        logger.info(f"Initialized Gemini generator with model: {model}")

    def generate(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Generate caption using Gemini."""
        prompt = self._build_prompt(quote, theme, music_energy)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            caption = response.text.strip()
            logger.info(f"Gemini caption generated ({len(caption)} chars)")
            return caption

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise

    def _build_prompt(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Build prompt for caption generation."""
        import random

        energy_desc = f" with {music_energy} energy phonk music" if music_energy else ""

        # Random caption style rotation
        caption_styles = [
            "Use a QUESTION style: 'Does this happen to you?', 'Who can relate?', 'Are you ready?'",
            "Use a CALL-TO-ACTION style: 'Send this to someone who needs it', 'Tag a friend', 'Share if you agree'",
            "Use a STATEMENT style with hashtags: Motivational message + #sigmamindset #redpillreality #motivation"
        ]
        selected_style = random.choice(caption_styles)

        return f"""Generate an engaging Instagram reel caption for a {theme} themed reel{energy_desc}.

The reel features this quote: "{quote}"

Requirements:
- Under 150 characters total
- Authentic, bold, and direct tone
- Include MAXIMUM 3 relevant hashtags (redpill/sigma/motivation style)
- No fluff or corporate speak
- Match the {theme} vibe (redpill, sigma mindset, brutal truth)
- {selected_style}

Generate ONLY the caption, no explanations or quotation marks."""


class AnthropicGenerator(CaptionGenerator):
    """Generate captions using Anthropic (Claude) API."""

    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        """
        Initialize Anthropic generator.

        Args:
            api_key: Anthropic API key
            model: Model name (default: claude-3-haiku for cost)
        """
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")

        self.model = model
        logger.info(f"Initialized Anthropic generator with model: {model}")

    def generate(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Generate caption using Anthropic."""
        prompt = self._build_prompt(quote, theme, music_energy)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            )

            caption = response.content[0].text.strip()
            logger.info(f"Anthropic caption generated ({len(caption)} chars)")
            return caption

        except Exception as e:
            logger.error(f"Anthropic generation failed: {e}")
            raise

    def _build_prompt(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Build prompt for caption generation."""
        energy_desc = f" with {music_energy} energy" if music_energy else ""

        return f"""Generate an engaging Instagram reel caption for a {theme} themed reel{energy_desc}.

The reel features this quote: "{quote}"

Requirements:
- Under 200 characters
- Authentic and conversational
- Include 2-3 relevant hashtags
- Call to action (optional but encouraged)
- Match the {theme} theme vibe

Generate ONLY the caption, no explanations."""


class TemplateGenerator(CaptionGenerator):
    """Fallback template-based caption generation."""

    TEMPLATES = {
        "motivation": [
            "{quote} 💪 #Motivation #Mindset #Success",
            "Real talk: {quote} 🔥 #RedPill #Truth #Growth",
            "{quote} ⚡ #SigmaMindset #Hustle #Win",
            "Does this resonate with you? {quote} #Motivation #Reality",
            "Tag someone who needs to hear this: {quote} 💎",
            "Who's ready? {quote} #Success #NeverGiveUp",
        ],
        "redpill_reality": [
            "{quote} 💊 #RedPill #Truth #RealityCheck",
            "Facts: {quote} 🎯 #HardTruth #NoBS #Mindset",
            "{quote} ⚡ #RedPilled #Woke #Success",
            "They don't want you to know: {quote} 🚨",
            "Tag someone who sees the truth #RedPill",
            "This is what they don't teach: {quote} 💊 #Reality",
        ],
        "sigma_mindset": [
            "{quote} 🐺 #SigmaMale #HighValue #Grindset",
            "{quote} ⚡ #SigmaMindset #LonePath #Success",
            "{quote} 💎 #Sigma #IndependentMindset #Boss",
            "Who's built different? Share this 🐺 #SigmaGrind",
            "Only sigma males understand: {quote} 💯",
            "Real ones know: {quote} #SigmaMindset #NoCompromise",
        ],
        "philosophy": [
            "{quote} 🧠 #Philosophy #Wisdom #Truth",
            "{quote} 💭 #Stoic #DeepThoughts #Mindset",
            "{quote} 📖 #Philosophy #AncientWisdom #Growth",
            "Ancient wisdom: {quote} 🏛️ #Philosophy",
            "Can you relate to this? {quote} #WisdomShare",
        ],
        "stoic_philosophy": [
            "{quote} 🏛️ #Stoicism #MarcusAurelius #Wisdom",
            "{quote} ⚔️ #StoicMindset #InnerPeace #Strength",
            "{quote} 🗿 #Stoic #Philosophy #Resilience",
            "Share this with someone struggling #Stoicism",
            "Marcus Aurelius knew: {quote} 💪 #StoicLife",
        ],
        "brutal_truth": [
            "{quote} 🔥 #HardTruth #BrutalReality #FaceIt",
            "Someone needs to hear: {quote} 💯 #Truth",
            "Most won't accept: {quote} 🚨 #RealTalk",
            "Tag a friend who needs this wake-up call #BrutalTruth",
            "The uncomfortable truth: {quote} 🎯 #Reality",
        ],
        "hustle": [
            "{quote} 🔥 #Hustle #Grind #NoExcuses",
            "{quote} 💼 #Entrepreneur #HustleHard #Success",
            "{quote} 💪 #GrindMode #Results #Dedication",
            "This is for hustlers only: {quote} 💯",
            "Share to someone on the grind #NeverStop",
        ],
        "monk_mode": [
            "{quote} 🧘 #MonkMode #Focus #SelfDiscipline",
            "{quote} 🎯 #DeepWork #NoDistractions #Growth",
            "{quote} 🔇 #MonkMode #Isolation #Building",
            "Are you ready to go monk mode? {quote} 🧘",
            "Spread this to those serious about growth #Focus",
        ],
        "financial_freedom": [
            "{quote} 💰 #FinancialFreedom #Wealth #Money",
            "{quote} 📈 #Investing #WealthBuilding #Freedom",
            "{quote} 💵 #Finance #Entrepreneur #Rich",
            "Who wants financial freedom? {quote} 🚀 #Wealth",
            "Share with someone building empire #Money #Success",
        ],
        "self_improvement": [
            "{quote} 📈 #SelfImprovement #Growth #BetterEveryDay",
            "{quote} 🎯 #PersonalDevelopment #LevelUp #Success",
            "{quote} 💎 #SelfGrowth #Transformation #Mindset",
            "Tag someone on their growth journey {quote} 📈",
            "You needed to read this: {quote} #GrowthMindset",
        ],
        "sigma_gaming": [
            "Strategic thinking wins: {quote} ♟️ #SigmaGaming #Strategy",
            "Every move matters. {quote} 🎮 #CompetitiveEdge #Gaming",
            "Only sigma gamers know: {quote} 💯 #StrategyWins",
            "Who's built to compete? {quote} 🐺 #GamingMindset",
            "The game rewards strategy: {quote} ♟️ #SigmaMindset #Gaming",
        ],
    }

    def generate(
        self,
        quote: str,
        theme: str,
        music_energy: Optional[str] = None,
    ) -> str:
        """Generate caption from templates."""
        import random

        templates = self.TEMPLATES.get(theme, self.TEMPLATES["motivation"])
        template = random.choice(templates)

        # Extract just the quote text without attribution
        quote_text = quote.split("—")[0].strip() if "—" in quote else quote

        caption = template.format(quote=quote_text)
        logger.info(f"Template caption generated for theme: {theme}")
        return caption


class LLMProvider:
    """Factory for caption generation with fallback support."""

    def __init__(self, generator: CaptionGenerator, fallback: Optional[CaptionGenerator] = None):
        """
        Initialize LLM provider.

        Args:
            generator: Primary generator
            fallback: Optional fallback generator
        """
        self.generator = generator
        self.fallback = fallback or TemplateGenerator()
        logger.info("LLM provider initialized")

    def _sanitize_caption(self, caption: str) -> str:
        """
        Ensure caption has 2-3 hashtags and is under 150 chars.

        Args:
            caption: Raw caption from generator

        Returns:
            Cleaned caption with 2-3 hashtags
        """
        import re

        # Find all hashtags
        hashtags = re.findall(r'#\w+', caption)

        # Track if we had hashtags originally
        had_hashtags = len(hashtags) > 0

        # If more than 3 hashtags, keep only the first 3
        if len(hashtags) > 3:
            # Remove extra hashtags from the caption
            caption_text = caption
            for ht in hashtags[3:]:
                caption_text = caption_text.replace(ht, "").strip()
            caption = caption_text

        # If NO hashtags, add default ones
        if not had_hashtags:
            caption = caption + " #Motivation #Mindset #Success"

        # Ensure caption is under 150 chars
        if len(caption) > 150:
            caption = caption[:150].rsplit(' ', 1)[0].rstrip('#').strip() + '...'

        return caption.strip()

    @classmethod
    def from_config(cls):
        """Create provider from configuration."""
        config = get_config_instance()
        llm_config = config.get("llm", {})

        provider = llm_config.get("provider", "gemini").lower()
        api_key = llm_config.get("api_key") or ""
        model = llm_config.get("model", "gpt-4o-mini")
        temperature = llm_config.get("caption_temperature", 0.8)

        generator = None

        # Try Gemini first (free tier recommended)
        if provider == "gemini":
            gemini_key = os.getenv("GEMINI_API_KEY") or api_key
            if gemini_key and gemini_key != "your_gemini_api_key_here":
                try:
                    generator = GeminiGenerator(
                        api_key=gemini_key,
                        model="gemini-2.5-flash"
                    )
                    logger.info("Using Gemini as primary generator")
                except ImportError:
                    logger.warning("Gemini not available (install: pip install google-generativeai)")
                except Exception as e:
                    logger.warning(f"Gemini initialization failed: {e}")

        # OpenAI fallback
        elif provider == "openai":
            try:
                generator = OpenAIGenerator(
                    api_key=api_key or "",
                    model=model,
                    temperature=temperature
                )
                logger.info("Using OpenAI as primary generator")
            except ImportError:
                logger.warning("OpenAI not available, will use fallback")

        # Anthropic option
        elif provider == "anthropic":
            try:
                generator = AnthropicGenerator(
                    api_key=api_key or "",
                    model=model
                )
                logger.info("Using Anthropic as primary generator")
            except ImportError:
                logger.warning("Anthropic not available, will use fallback")

        # Auto-detect: try Gemini -> OpenAI -> Templates
        if generator is None:
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key and gemini_key != "your_gemini_api_key_here":
                try:
                    generator = GeminiGenerator(api_key=gemini_key)
                    logger.info("Auto-selected Gemini as primary generator")
                except:
                    pass

        if generator is None:
            generator = TemplateGenerator()
            logger.info("Using template generator as primary")

        # Always use template as fallback
        fallback = TemplateGenerator()

        return cls(generator=generator, fallback=fallback)

    def generate(
        self,
        quote: str,
        theme: str = "motivation",
        music_energy: Optional[str] = None,
    ) -> str:
        """
        Generate caption with fallback support.

        Args:
            quote: Quote text
            theme: Content theme (motivation, philosophy, hustle)
            music_energy: Music energy level (high, medium, low)

        Returns:
            Generated caption
        """
        try:
            caption = self.generator.generate(
                quote=quote,
                theme=theme,
                music_energy=music_energy
            )
            return self._sanitize_caption(caption)
        except Exception as e:
            logger.warning(f"Primary generator failed, using fallback: {e}")
            try:
                caption = self.fallback.generate(
                    quote=quote,
                    theme=theme,
                    music_energy=music_energy
                )
                return self._sanitize_caption(caption)
            except Exception as e2:
                logger.error(f"Fallback generator also failed: {e2}")
                # Last resort: quote + minimal caption (already sanitized - 2 hashtags)
                return f'"{quote}"\n\n#ReelQuote #Motivation'
