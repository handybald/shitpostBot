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
    video_description: str = ""  # Detailed visual description for custom video generation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "caption": self.caption,
            "theme": self.theme,
            "music_vibe": self.music_vibe,
            "video_style": self.video_style,
            "hashtags": self.hashtags,
            "music_search_terms": self.music_search_terms,
            "video_search_terms": self.video_search_terms,
            "video_description": self.video_description
        }


@dataclass
class BeatSheet:
    """
    A structured script for the voiceover pipeline, replacing the old flat
    single-quote prompt. `full_voiceover_text` is what gets sent to TTS -
    duration is whatever that ends up being once spoken, not a fixed 13s.
    hook/body/payoff are kept separately only so the renderer can style them
    differently (e.g. a punchier hook color) if desired.
    """
    hook: str
    body: str
    payoff: str
    caption: str
    theme: str
    music_mood: str
    video_search_terms: List[str]
    music_search_terms: List[str]
    hashtags: List[str]

    @property
    def full_voiceover_text(self) -> str:
        return " ".join(part.strip() for part in [self.hook, self.body, self.payoff] if part.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hook": self.hook,
            "body": self.body,
            "payoff": self.payoff,
            "full_voiceover_text": self.full_voiceover_text,
            "caption": self.caption,
            "theme": self.theme,
            "music_mood": self.music_mood,
            "video_search_terms": self.video_search_terms,
            "music_search_terms": self.music_search_terms,
            "hashtags": self.hashtags,
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
        "high_value_mindset",
        "sigma_gaming"
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

    def generate_beat_sheet(self, theme: Optional[str] = None) -> BeatSheet:
        """
        Generate a structured hook/body/payoff script meant to be *spoken*
        by TTS, not burned onto screen as static ASS timing. This is what
        drives duration in the new pipeline - there's no fixed reel length,
        the render is exactly as long as this script takes to say.
        """
        if not self.client:
            return self._fallback_beat_sheet(theme)

        theme = theme or random.choice(self.CONTENT_THEMES)
        music_vibe = self.suggest_phonk_music_vibe(theme)
        video_style = self.suggest_video_style(theme, music_vibe["style"])

        try:
            prompt = f"""Write a spoken-word script for a short vertical video reel (theme: {theme}).

This will be read aloud by a text-to-speech voice, NOT displayed as static
text - so it must sound natural when spoken, with real sentence rhythm, not
a choppy list of fragments.

Structure (write as one flowing script, but return the three parts separately):
1. HOOK (first ~2 seconds spoken, 3-8 words): a direct, provocative opening
   line that stops someone mid-scroll. A statement or accusation, not a
   question.
2. BODY (~4-10 seconds spoken, 1-2 short sentences): develops the hook -
   the reasoning or the specific example.
3. PAYOFF (~2-4 seconds spoken, 3-10 words): the memorable, quotable
   conclusion - what people would screenshot or repeat.

Total spoken length should land naturally between 15-30 seconds when read
aloud at a normal pace (roughly 45-90 words total across all three parts).

Be ORIGINAL - avoid recycled generic motivational lines like "success is
lonely" or "discipline over motivation". Make it specific and vivid.

Respond with ONLY this JSON, no markdown, no explanation:
{{
    "hook": "...",
    "body": "...",
    "payoff": "...",
    "caption": "Instagram caption for this post, max 150 chars, include 2-3 relevant hashtags",
    "video_search_terms": ["term1", "term2", "term3"],
    "music_search_terms": ["term1", "term2"],
    "hashtags": ["#tag1", "#tag2", "#tag3"]
}}"""

            response = self.genai_client.models.generate_content(
                model=self.model_name, contents=prompt
            )
            beat_sheet = self._parse_beat_sheet(response.text, theme, music_vibe, video_style)
            logger.info(f"Generated beat sheet ({theme}): {beat_sheet.hook[:40]}...")
            return beat_sheet

        except Exception as e:
            logger.error(f"Beat sheet generation failed: {e}")
            return self._fallback_beat_sheet(theme)

    def _parse_beat_sheet(
        self, response_text: str, theme: str, music_vibe: Dict[str, Any], video_style: str
    ) -> BeatSheet:
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse beat sheet JSON: {e}")
            return self._fallback_beat_sheet(theme)

        caption = self._sanitize_caption(data.get("caption", ""))
        hashtags = data.get("hashtags", [])
        if isinstance(hashtags, list) and len(hashtags) > 3:
            hashtags = hashtags[:3]

        return BeatSheet(
            hook=data.get("hook", "").strip(),
            body=data.get("body", "").strip(),
            payoff=data.get("payoff", "").strip(),
            caption=caption,
            theme=theme,
            music_mood=music_vibe["style"],
            video_search_terms=data.get("video_search_terms") or [video_style.replace("_", " ")],
            music_search_terms=data.get("music_search_terms") or music_vibe["example_keywords"],
            hashtags=hashtags,
        )

    def _fallback_beat_sheet(self, theme: Optional[str] = None) -> BeatSheet:
        """Used when Gemini is unavailable or returns something unparseable."""
        theme = theme or random.choice(self.CONTENT_THEMES)
        music_vibe = self.suggest_phonk_music_vibe(theme)
        video_style = self.suggest_video_style(theme, music_vibe["style"])

        fallback_scripts = [
            {
                "hook": "Nobody is coming to save you.",
                "body": "The people you're waiting on are busy building their own lives.",
                "payoff": "Get up and build it yourself.",
            },
            {
                "hook": "Comfort is quietly killing your potential.",
                "body": "Every day you choose the easy path, someone else chooses the hard one and passes you.",
                "payoff": "Growth only lives outside your comfort zone.",
            },
            {
                "hook": "Most people quit right before it gets good.",
                "body": "The results you want are hiding behind the exact discomfort you're avoiding right now.",
                "payoff": "One more rep. One more day. That's the whole game.",
            },
        ]
        script = random.choice(fallback_scripts)

        return BeatSheet(
            hook=script["hook"],
            body=script["body"],
            payoff=script["payoff"],
            caption=f"{script['payoff']} #{theme.replace('_', '')} #motivation",
            theme=theme,
            music_mood=music_vibe["style"],
            video_search_terms=[video_style.replace("_", " ")],
            music_search_terms=music_vibe["example_keywords"],
            hashtags=[f"#{theme.replace('_', '')}", "#motivation", "#mindset"],
        )

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

    def generate_two_part_quote(self) -> Dict[str, str]:
        """Generate a two-part quote: hook (3 sec) + payoff (remaining time).

        Perfect for reels where first 3 seconds must grab attention.
        Returns dict with 'hook' (3 seconds) and 'payoff' (6-10 seconds).
        """
        if not self.client:
            return self._fallback_two_part_quote()

        try:
            # Create DIRECT, ACCUSATORY hooks that stop the scroll immediately
            # Format: "You're doing X" or "X is killing you" or "Nobody talks about Y"
            hook_styles = [
                "Start with a direct accusation like 'You're poor because...' or 'You'll die because...'",
                "Make a bold statement: 'Men who [do specific thing]...' or 'Rich people know...'",
                "Start with what people WON'T admit: 'Nobody wants to say it but...' or 'They'll never tell you...'",
                "Use 'comfort is' format: 'Comfort is killing you' or 'Comfort is your greatest enemy'",
                "Direct observation about failure: 'You fail because...' or 'Most people never...'"
            ]
            hook_style = random.choice(hook_styles)

            prompt = f"""Generate a two-part "redpill" quote for a short video reel (10-13 seconds total).

HOOK STYLE REQUIREMENT: {hook_style}

CRITICAL FOR STOPPING SCROLL:
- HOOK must be a DIRECT STATEMENT or ACCUSATION, not a question
- 2-6 words MAXIMUM (MUST be readable in 3 seconds)
- Examples of POWERFUL hooks:
  * "You'll die satisfying others"
  * "Comfort is killing you"
  * "No one is coming to save you"
  * "You're poor because you think like them"
  * "Rich people never say this"
- Examples of WEAK hooks (avoid):
  * "Something changes when..."
  * "Wait until you see this..."
  * "You need to know..."

ORIGINALITY: Make it FRESH - avoid recycled quotes like "success is lonely", "most people are sheep", "discipline wins"

Structure:
1. HOOK (first 3 seconds): 
   - {hook_style}
   - 2-6 words maximum
   - Provocative/accusatory statement
   - Makes viewers pause and want to know more

2. PAYOFF (last 7-10 seconds):
   - Explains WHY or shows CONSEQUENCE in fewest words possible
   - 3-8 words MAXIMUM (ultra-short, brutal, unforgettable)
   - One devastating truth or consequence
   - Must hit hard and be memorable

Format your response EXACTLY as JSON (no markdown, no explanations):
{{
    "hook": "Your hook text here (2-6 words)",
    "payoff": "Your payoff text here (3-8 words ONLY)"
}}"""

            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            
            import json
            response_text = response.text.strip()
            # Extract JSON if wrapped in markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(response_text)
            logger.info(f"Generated two-part quote - Hook: {data['hook'][:40]}...")
            return data

        except Exception as e:
            logger.error(f"Failed to generate two-part quote: {e}")
            return self._fallback_two_part_quote()

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
            "aggressive_bass_heavy": ["sports_car_footage", "urban_night_drive", "gym_motivation", "predator_hunting"],
            "dark_atmospheric": ["city_lights", "rain_aesthetic", "urban_night_drive"],
            "ambient_phonk": ["nature_solitude", "abstract_geometric", "rain_aesthetic"],
            "minimal_phonk": ["nature_solitude", "city_lights", "abstract_geometric"]
        }

        options = suggestions.get(music_vibe, self.VIDEO_STYLES)
        return random.choice(options)

    def _build_generation_prompt(self, theme: Optional[str], style: str) -> str:
        """Build comprehensive generation prompt for Gemini."""
        theme = theme or random.choice(self.CONTENT_THEMES)

        # Add variation instruction to avoid repeated quotes
        variation_instructions = [
            "Be VERY CREATIVE and ORIGINAL - avoid common motivational clichés.",
            "Create something UNIQUE - not the typical 'hustle' or 'grind' quotes everyone uses.",
            "Generate FRESH insight - challenge common beliefs in an unexpected way.",
            "Write CONTROVERSIAL yet thoughtful - provoke real thinking, not just agreement.",
            "Create something SPECIFIC and CONCRETE - avoid generic 'success' platitudes."
        ]
        variation_hint = random.choice(variation_instructions)

        # Pick a specific caption style for this generation (not rotate)
        caption_style_options = [
            ("QUESTION", "Ask the audience a relatable question like: 'Does this happen to you?', 'Who can relate?', 'Are you ready?' - MUST include 2-3 hashtags at the end"),
            ("CTA", "Use a call-to-action: 'Send this to someone who needs it', 'Tag a friend', 'Share if you agree', 'Who else feels this?' - MUST include 2-3 hashtags at the end"),
            ("STATEMENT", "Make a powerful statement - MUST include 2-3 hashtags (#sigmamindset #redpillreality #motivation)")
        ]
        selected_style_name, selected_style_desc = random.choice(caption_style_options)

        return f"""Generate a complete Instagram Reel content package for a {style} post.

Theme: {theme}
Style: {style}

{self._get_theme_guidance(theme)}

CRITICAL REQUIREMENT FOR VARIETY:
{variation_hint}
Do NOT generate quotes similar to: "success is lonely", "comfort kills ambition", "everyone else is wrong", "discipline wins".
Generate something FRESH and SPECIFIC to this theme.

Generate a JSON response with:
1. "prompt": A powerful 10-15 word quote/truth bomb (redpill style, no fluff, MUST BE ORIGINAL)
2. "caption": Instagram caption under 150 chars using {selected_style_name} STYLE:
   {selected_style_desc}
   CRITICAL: Must include 2-3 hashtags. Make it authentic and engaging, NOT generic.
3. "theme": The theme category
4. "music_vibe": Phonk music style description
5. "video_style": Background video description
6. "hashtags": Array of MAXIMUM 3 relevant hashtags
7. "music_search_terms": Array of 3-5 search terms to find the perfect phonk music (e.g., ["brazilian phonk dance mixed", "troll phonk bass boosted 808", "hardstyle gym remix", "distorted drift phonk", "aggressive techno phonk"])
8. "video_search_terms": Array of 3-5 STRIKING search terms - MUST include animals, nature power, or extreme action. NO generic city/dark themes. Use: lions, tigers, eagles, sharks, storms, fire, volcanoes, explosions, racing, fighting. Examples: ["lion hunting predator 4k", "tiger roaring intense wild", "eagle diving attack", "storm lightning power", "motorcycle racing speed", "boxer fighting intense"]
9. "video_description": Detailed visual description for video editor (e.g., "Close-up of lion's eyes, slow-motion, then cut to tiger roaring, dramatic lighting, fire in background"). This helps create custom visuals.

Requirements:
- Quote must be POWERFUL, ORIGINAL, and thought-provoking
- Caption should be authentic and engaging
- Focus on hard truths that aren't overused
- Avoid generic "sigma mindset" buzzwords
- No cringe or corporate speak
- Music search terms should be EXCITING and HIGH-ENERGY:
  * Focus on: Brazilian Phonk, Hardstyle, Gym Phonk, Techno, Distorted Bass
  * Avoid: Low energy "lofi" or "chill" beats unless theme forces it
  * Examples: "brazilian phonk montage", "hardstyle zyzz", "sigma grindset music"
- Video search terms should be DIVERSE and specific, searchable on YouTube/stock sites
  * Vary the aesthetic: urban, nature, luxury, minimal, action, abstract, etc.
  * Different locations and scenes
  * Mix lighting: night, daylight, neon, sunset, rain, etc.
- CRITICAL: Generate quotes that feel FRESH and UNIQUE, not recycled wisdom

Output ONLY valid JSON, no explanations:"""

    def _sanitize_caption(self, caption: str) -> str:
        """
        Ensure caption has 2-3 hashtags and is under 150 chars.

        Args:
            caption: Raw caption from API

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
        # Preserve hashtags by truncating only the main text portion
        if len(caption) > 150:
            # Find where hashtags start
            hashtag_match = re.search(r'\s(#\w+.*?)$', caption)
            if hashtag_match:
                # Separate main text and hashtags
                hashtags_portion = hashtag_match.group(1)
                main_text = caption[:hashtag_match.start()].strip()
                # Truncate main text to fit within limit, leaving room for hashtags
                max_main_len = 150 - len(hashtags_portion) - 4  # -4 for space + "..."
                if max_main_len > 10:  # Ensure we have at least some text
                    main_text = main_text[:max_main_len].rsplit(' ', 1)[0].strip() + '...'
                    caption = main_text + " " + hashtags_portion
                else:
                    # Not enough room, just keep hashtags
                    caption = hashtags_portion
            else:
                # No hashtags found, truncate normally
                caption = caption[:150].rsplit(' ', 1)[0].strip() + '...'

        return caption.strip()

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

            # Sanitize caption to ensure max 3 hashtags and 150 chars
            caption = self._sanitize_caption(data.get("caption", ""))

            # Limit hashtags array to maximum 3
            hashtags = data.get("hashtags", [])
            if isinstance(hashtags, list) and len(hashtags) > 3:
                hashtags = hashtags[:3]

            return ContentSuggestion(
                prompt=data.get("prompt", ""),
                caption=caption,
                theme=data.get("theme", "general"),
                music_vibe=data.get("music_vibe", "aggressive_bass_heavy"),
                video_style=data.get("video_style", "urban_night_drive"),
                hashtags=hashtags,
                music_search_terms=data.get("music_search_terms", ["phonk music", "bass boosted phonk"]),
                video_search_terms=data.get("video_search_terms", ["aesthetic video", "urban night"]),
                video_description=data.get("video_description", "")
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
            "The successful do what the unsuccessful won't",
            "You're not behind, you're just not finished yet",
            "Comparison is the thief of your own journey",
            "The system rewards action, not intention",
            "Your network determines your net worth",
            "Most dreams die between the idea and the attempt",
            "Patience is not inaction, it's strategic waiting",
            "Fear is just data telling you something matters",
            "Your past does not equal your future",
            "Money is just concentrated attention and effort",
            "Boredom is a sign you're not growing anymore"
        ]
        return random.choice(prompts)

    def _fallback_two_part_quote(self) -> Dict[str, str]:
        """Fallback two-part quotes when API is unavailable."""
        two_part_quotes = [
            {
                "hook": "They don't want you...",
                "payoff": "...to know real power comes from seeing the world as it is."
            },
            {
                "hook": "Success isn't luck...",
                "payoff": "...it's preparation meeting opportunity. Create your own reality."
            },
            {
                "hook": "Your biggest enemy...",
                "payoff": "...is the person you were yesterday. Be better."
            },
            {
                "hook": "Money buys freedom...",
                "payoff": "...don't let anyone tell you it doesn't matter."
            },
            {
                "hook": "Winners do this...",
                "payoff": "...what losers refuse to do. Discipline over motivation."
            },
            {
                "hook": "The system is rigged...",
                "payoff": "...to keep you poor. Break the mold."
            },
            {
                "hook": "Comfort kills you...",
                "payoff": "...growth only happens when you're in pain."
            },
            {
                "hook": "You have time...",
                "payoff": "...you just waste it. Be obsessed with progress."
            },
            {
                "hook": "You're not ready...",
                "payoff": "...and you never will be. Start anyway."
            },
            {
                "hook": "Self-sabotage is...",
                "payoff": "...choosing comfort over growth. Choose pain."
            },
            {
                "hook": "Social media lies...",
                "payoff": "...don't compare your life to their highlights."
            },
            {
                "hook": "Passion is fake...",
                "payoff": "...discipline is real. Do what is valuable."
            },
            {
                "hook": "You fear success...",
                "payoff": "...because it requires you to change."
            },
            {
                "hook": "Ignorance is expensive...",
                "payoff": "...invest in your mind or pay the price."
            },
            {
                "hook": "Stop waiting...",
                "payoff": "...no one is coming to save you."
            }
        ]
        return random.choice(two_part_quotes)

    def _get_theme_guidance(self, theme: str) -> str:
        """Get specific guidance for each theme."""
        guidance_map = {
            "sigma_gaming": "Theme Guidance: Sigma Gaming - Strategic mindset through competitive gaming metaphors\n"
                           "- Hook: Reference chess moves, racing strategy, competitive advantage, game tactics\n"
                           "- Payoff: Connect gaming wisdom to real-life strategic thinking and winning mindset\n"
                           "- Tone: Competitive, strategic, focused, disciplined, high-stakes\n"
                           "- Examples: 'Think 3 moves ahead', 'Winners study the opponent', 'Strategy beats luck', 'Every decision is a move on the board'",
            "redpill_reality": "Theme Guidance: Redpill Reality - Awakening to harsh truths\n"
                              "- Hook: Reveal uncomfortable truths people ignore\n"
                              "- Payoff: The deeper reality beneath comfortable lies\n"
                              "- Tone: Direct, no-nonsense, eye-opening",
            "sigma_mindset": "Theme Guidance: Sigma Mindset - Independent, strategic, disciplined\n"
                            "- Hook: Challenge conventional thinking\n"
                            "- Payoff: The sigma way of achieving mastery\n"
                            "- Tone: Strong, independent, high-value",
        }
        return guidance_map.get(theme, f"Theme Guidance: {theme.replace('_', ' ').title()}\n- Focus on authenticity and originality for this theme")

    def _fallback_content_idea(
        self,
        theme: Optional[str] = None,
        style: str = "redpill_motivational"
    ) -> ContentSuggestion:
        """Fallback content generation without API."""
        theme = theme or random.choice(self.CONTENT_THEMES)
        prompt = self._fallback_redpill_prompt()

        # Fallback captions with engagement styles (questions, CTAs, statements)
        captions = [
            # QUESTION style
            f"Does this resonate with you? {prompt} #Motivation #Reality",
            f"Who can relate? {prompt} #Truth #Mindset",
            f"Are you ready for this? {prompt} #SigmaMindset #Success",
            # CTA style
            f"Tag someone who needs to hear this: {prompt} 💯",
            f"Send this to someone who's sleeping on their potential {prompt} 🐺",
            f"Share with a friend who gets it: {prompt} #RedPill",
            # STATEMENT style
            f"{prompt} 💪 #Motivation #Mindset #Success",
            f"Real talk: {prompt} 🔥 #RedPill #Truth #Growth",
            f"{prompt} ⚡ Time to level up. #Hustle #Grind #Win",
            f"Facts: {prompt} 🎯 #SigmaMindset #HighValue #Boss"
        ]

        # Fallback music and video search terms - EXPANDED for diversity
        # IMPORTANT: Music searches emphasize hard-hitting beats, no soft intros
        music_searches = {
            "redpill_reality": [
                "brazilian phonk intense dance", "troll phonk 808 cowbell", "aggressive drift phonk bass",
                "hardstyle gym remix zyzz", "dark techno aggressive", "distorted phonk montage"
            ],
            "sigma_mindset": [
                "magna phonk slow reverb", "memphis doomshop phonk", "sigma grindset music hard",
                "sahara phonk remix", "kordhell style phonk", "rave phonk high energy"
            ],
            "stoic_philosophy": [
                "slowed reverb phonk atmospheric", "wave phonk hard", "dramatic cinematic bass",
                "epic orchestral trap remix", "hans zimmer style bass boosted", "dark ambient intense"
            ],
            "monk_mode": [
                "focused dark techno", "deep house focus mix", "minimal techno driving",
                "cyberpunk midtempo bass", "dark synthwave aggressive", "night drive phonk"
            ],
            "financial_freedom": [
                "luxury lifestyle beat trap", "wolf of wall street phonk", "billionaire mindset music",
                "success motivation epic beat", "winning anthem hardstyle", "victory lap trap beat"
            ],
            "self_improvement": [
                "zyzz hardstyle motivation", "tevvez legend style", "gym workout intense phonk",
                "david goggins style music", "can't be touched remix", "energy surge hard bass"
            ],
            "brutal_truth": [
                "dark horror phonk", "scary garry style phonk", "murder in my mind vibes",
                "doomsday aggressive phonk", "distorted bass warning", "siren head phonk"
            ],
            "high_value_mindset": [
                "metamorphosis phonk", "clean luxury trap beat", "gentlemen style phonk",
                "james bond style trap remix", "matrix theme remix bass", "top g music theme"
            ],
            "sigma_gaming": [
                "doom eternal metal remix", "cyberpunk combat music", "boss battle electronic intense",
                "high octane racing music", "fps gaming montage music", "dubstep hard drop 2024"
            ]
        }

        video_searches = {
            "redpill_reality": [
                "lion eyes close up predator", "tiger roaring intense wild",
                "eagle hunting soaring 4k", "fire explosion bright intense",
                "storm lightning striking power", "hurricane wind force nature",
                "shark attacking wildlife dramatic", "volcano erupting lava power"
            ],
            "sigma_mindset": [
                "lion hunting power predator", "wolf pack running wild",
                "fighter boxing intense combat", "samurai sword sharp action",
                "eagle diving fast hunter", "motorcycle racing extreme speed",
                "rock climbing intense challenge", "weightlifter lifting maximum power"
            ],
            "stoic_philosophy": [
                "mountains snow peak vast", "ocean waves massive crashing",
                "ancient ruins power history", "forest ancient trees majesty",
                "river flowing powerful nature", "thunder storm dark power",
                "eagle soaring freedom", "bear standing strength wild"
            ],
            "monk_mode": [
                "meditation zen focus peace", "candle flame glowing", "forest silence nature",
                "waterfall flowing peaceful", "sunrise dawn calm quiet",
                "book pages turning knowledge", "empty temple silence"
            ],
            "financial_freedom": [
                "money rain falling gold", "diamonds sparkling wealth luxury",
                "sports car racing fast", "mansion rooms opulent luxury",
                "private jet interior exclusive", "yacht ocean luxury lifestyle",
                "stock market rising up", "gold bars stacked wealth"
            ],
            "self_improvement": [
                "gym training intense workout", "athlete running sprinting fast",
                "boxer fighting intense combat", "martial artist kicking power",
                "mountain climber ascending", "swimmer diving power water",
                "sunrise motivation dawn", "fire burning intense energy"
            ],
            "brutal_truth": [
                "fire burning bright intense", "storm dark ominous power",
                "lightning strike electricity", "snake predator danger",
                "volcano erupting power", "earthquake shaking ground",
                "tornado spinning force", "tsunami wave power"
            ],
            "high_value_mindset": [
                "luxury car sports fast", "mansion opulent interior", "diamonds sparkling",
                "yacht ocean premium", "private jet luxury", "gold luxury wealth",
                "private pool exclusive", "champagne luxury celebration"
            ],
            "sigma_gaming": [
                "gaming intense focused player", "esports championship winning moment",
                "racing game cockpit view", "strategy game intense play",
                "fighting game combat intense", "chess player thinking focus",
                "poker professional intense", "competitive gaming victory"
            ]
        }

        # Randomly pick from available search terms for this theme (for diversity)
        theme_music_terms = music_searches.get(theme, ["phonk music", "bass boosted"])
        theme_video_terms = video_searches.get(theme, ["aesthetic video", "4k background"])

        # Select random subset of search terms to ensure variety across runs
        selected_music_terms = random.sample(theme_music_terms, min(3, len(theme_music_terms)))
        selected_video_terms = random.sample(theme_video_terms, min(3, len(theme_video_terms)))

        return ContentSuggestion(
            prompt=prompt,
            caption=random.choice(captions),
            theme=theme,
            music_vibe=random.choice(self.PHONK_VIBES),
            video_style=random.choice(self.VIDEO_STYLES),
            hashtags=["#Motivation", "#Mindset", "#Success"],
            music_search_terms=selected_music_terms,
            video_search_terms=selected_video_terms,
            video_description=f"Striking {theme} visuals: {', '.join(selected_video_terms)}"
        )


def create_gemini_generator() -> GeminiContentGenerator:
    """Factory function to create Gemini generator."""
    return GeminiContentGenerator()
