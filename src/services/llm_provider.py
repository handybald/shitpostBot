"""
LLM provider service for generating engaging captions.

Supports:
- OpenAI API (GPT-4o-mini, GPT-4, etc.)
- Anthropic API (Claude, etc.)
- Fallback template-based captions

Generates captions tailored to:
- Content theme (motivation, philosophy, hustle)
- Quote and music vibe
- Instagram engagement best practices
"""

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
            "🔥 {quote}\n\n💪 Your mindset determines your reality. What will you do today to level up?\n\n#Motivation #Mindset #Growth",
            "✨ Remember: {quote}\n\n🚀 The only limit is the one you accept. Time to break through.\n\n#Inspiration #Success #Grind",
            "💎 {quote}\n\n🎯 This is your sign. Take action. Create momentum.\n\n#Motivated #Unstoppable #Dreams",
        ],
        "philosophy": [
            "🧠 {quote}\n\n💭 Deep thoughts for deep growth. What does this mean to you?\n\n#Philosophy #Wisdom #Reflection",
            "🌌 {quote}\n\n✍️ Some truths hit different. Sit with this one.\n\n#Mindfulness #Wisdom #Truth",
            "📖 {quote}\n\n🤔 The best philosophies make us see ourselves differently.\n\n#Philosophy #ThoughtProvoking #Growth",
        ],
        "hustle": [
            "🏃‍♂️ {quote}\n\n⏰ No time for excuses. The grind waits for no one.\n\n#Hustle #Grind #NoExcuses",
            "💼 {quote}\n\n🔥 While others sleep, you build. That's the difference.\n\n#Entrepreneur #HustleHard #Success",
            "🎬 {quote}\n\n💪 Results speak louder than words. Keep pushing.\n\n#Dedicated #Results #GrindMode",
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

    @classmethod
    def from_config(cls):
        """Create provider from configuration."""
        config = get_config_instance()
        llm_config = config.get("llm", {})

        provider = llm_config.get("provider", "openai").lower()
        api_key = llm_config.get("api_key") or ""
        model = llm_config.get("model", "gpt-4o-mini")
        temperature = llm_config.get("caption_temperature", 0.8)

        generator = None

        if provider == "openai":
            try:
                generator = OpenAIGenerator(
                    api_key=api_key or "",
                    model=model,
                    temperature=temperature
                )
                logger.info("Using OpenAI as primary generator")
            except ImportError:
                logger.warning("OpenAI not available, will use fallback")
        elif provider == "anthropic":
            try:
                generator = AnthropicGenerator(
                    api_key=api_key or "",
                    model=model
                )
                logger.info("Using Anthropic as primary generator")
            except ImportError:
                logger.warning("Anthropic not available, will use fallback")

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
            return caption
        except Exception as e:
            logger.warning(f"Primary generator failed, using fallback: {e}")
            try:
                return self.fallback.generate(
                    quote=quote,
                    theme=theme,
                    music_energy=music_energy
                )
            except Exception as e2:
                logger.error(f"Fallback generator also failed: {e2}")
                # Last resort: quote + minimal caption
                return f'"{quote}"\n\n#ReelQuote #Motivation'
