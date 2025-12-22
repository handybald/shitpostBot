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
        """Generate a two-part quote: hook (4 sec) + payoff (remaining time).

        Perfect for reels where first 3 seconds must grab attention.
        Returns dict with 'hook' (4 seconds) and 'payoff' (6-9 seconds).
        """
        if not self.client:
            return self._fallback_two_part_quote()

        try:
            # Vary the emphasis to get different types of hooks
            hook_styles = [
                "Something that seems obvious but people get wrong",
                "A counterintuitive truth about how the world actually works",
                "Something people are too afraid to say out loud",
                "A shocking observation about human nature",
                "A hidden reason why most people fail"
            ]
            hook_style = random.choice(hook_styles)

            prompt = f"""Generate a two-part "redpill" quote for a short video reel (10-13 seconds total).

DIVERSITY REQUIREMENT:
Hook style should be: {hook_style}
Make it ORIGINAL - not a recycled quote you've seen before.
Avoid: "success is lonely", "most people are sheep", "discipline wins", "comfort kills you"

Structure:
1. HOOK (first part, 4 seconds): A provocative/curious statement that makes people stop scrolling
   - 6-10 words
   - Should make viewers curious for the payoff
   - No complete thought, end with implied continuation
   - MUST BE UNIQUE and not overused
   - Examples: "Everything you know is wrong because...", "The truth they hide from you is...", "Most people are slaves and don't realize..."

2. PAYOFF (second part, 6-9 seconds): The powerful truth/realization
   - 15-25 words
   - Must be profound and thought-provoking
   - Completes the hook's promise
   - Genuine insight, not buzzwords
   - Examples: "...you're chasing someone else's dream instead of building your own empire", "...they profit from your ignorance and compliance"

Format your response EXACTLY as JSON:
{{
    "hook": "Your hook text here",
    "payoff": "Your payoff text here"
}}

Generate ONLY the JSON, nothing else."""

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
7. "music_search_terms": Array of 3-5 search terms to find the perfect phonk music (e.g., ["aggressive phonk", "drift phonk bass boosted", "brazilian phonk 808"])
8. "video_search_terms": Array of 3-5 search terms to find the perfect background video (e.g., ["night city drive 4k", "tokyo drift aesthetic", "urban cyberpunk"])

Requirements:
- Quote must be POWERFUL, ORIGINAL, and thought-provoking
- Caption should be authentic and engaging
- Focus on hard truths that aren't overused
- Avoid generic "sigma mindset" buzzwords
- No cringe or corporate speak
- Music search terms should be DIVERSE and specific (mix of genres, moods, styles - not just phonk)
  * Include varied genres: phonk, trap, lofi, hip hop, instrumental, electronic, etc.
  * Different moods: aggressive, calm, inspirational, dark, uplifting
  * Real searchable terms that will return different results each time
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
        if len(caption) > 150:
            caption = caption[:150].rsplit(' ', 1)[0].rstrip('#').strip() + '...'

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
                "hook": "They don't want you to know this because...",
                "payoff": "...once you understand it, you can't be controlled. Real power comes from seeing the world as it is, not as they want you to see it."
            },
            {
                "hook": "Everyone thinks success requires luck, but the truth is...",
                "payoff": "...luck is just preparation meeting opportunity. While 99% wait for the perfect moment, the 1% create their own reality through relentless action."
            },
            {
                "hook": "Your biggest competition isn't the guy next to you...",
                "payoff": "...it's the guy you were yesterday. The only race that matters is becoming your highest self. Everything else is just noise."
            },
            {
                "hook": "They say money doesn't matter, but deep down they know...",
                "payoff": "...freedom is built on a foundation of financial independence. Without it, you're just another worker bee in someone else's hive."
            },
            {
                "hook": "Most people will never understand what separates winners from losers...",
                "payoff": "...it's not talent, it's the willingness to do what others won't when others are sleeping. Consistency over intensity, always."
            },
            {
                "hook": "The system isn't broken, it's working exactly as designed...",
                "payoff": "...to keep you dependent and obedient. Real freedom requires you to break the mold and build your own path."
            },
            {
                "hook": "Your comfort zone is slowly killing your potential because...",
                "payoff": "...growth only happens at the edge of what scares you. The more uncomfortable the journey, the more valuable the destination."
            },
            {
                "hook": "Everyone has the same 24 hours but only the elite use them differently...",
                "payoff": "...they don't waste time on distractions. They're obsessed with progress, addicted to improvement, and allergic to mediocrity."
            },
            {
                "hook": "You think you're not ready, but reality is...",
                "payoff": "...readiness is a myth. The people who win started before they felt ready. Confidence comes from action, not preparation."
            },
            {
                "hook": "Most people sabotage themselves without knowing it because...",
                "payoff": "...mediocrity is comfortable. The pain of growth scares them more than the pain of regret. You have to choose which pain you'll accept."
            },
            {
                "hook": "Social media shows you everyone's best life but hides...",
                "payoff": "...the struggles that made them. Don't compare your reality to someone else's highlight reel. Your only competition is yesterday's version of you."
            },
            {
                "hook": "People say follow your passion, but that's incomplete advice because...",
                "payoff": "...passion without discipline is just a hobby. Real wealth comes from doing what's valuable, not just what feels good."
            },
            {
                "hook": "Your biggest fear isn't failure, it's actually...",
                "payoff": "...success. Because success demands you become someone new. Most people choose the familiar pain over the uncomfortable transformation."
            },
            {
                "hook": "Education doesn't cost money, ignorance does, because...",
                "payoff": "...every wrong decision based on lack of knowledge costs you time and opportunity. Your greatest investment is in understanding how things actually work."
            },
            {
                "hook": "You're waiting for permission that will never come because...",
                "payoff": "...no one is going to hand you success. The people who matter are too busy building their own empires to care about stopping you."
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
        music_searches = {
            "redpill_reality": [
                "aggressive phonk", "drift phonk bass", "brazilian phonk",
                "hard trap beats", "dark trap instrumental", "boom bap hip hop"
            ],
            "sigma_mindset": [
                "dark phonk", "memphis phonk", "sigma phonk",
                "underground trap", "chicago footwork", "memphis blues"
            ],
            "stoic_philosophy": [
                "ambient phonk", "chill phonk beats", "lo-fi phonk",
                "ambient electronic", "meditation music", "zen instrumental"
            ],
            "monk_mode": [
                "minimal phonk", "deep phonk", "focus phonk",
                "lo-fi hip hop", "study beats", "focus music"
            ],
            "financial_freedom": [
                "aggressive beats", "motivational hip hop", "success soundtrack",
                "power music", "gym beats", "pump up music"
            ],
            "self_improvement": [
                "inspirational instrumental", "epic strings", "cinematic music",
                "dramatic orchestral", "powerful soundtrack", "hero music"
            ],
            "brutal_truth": [
                "heavy bass trap", "dark music", "intense beat",
                "aggressive instrumental", "raw beats", "street music"
            ],
            "high_value_mindset": [
                "luxury beats", "premium music", "classy instrumental",
                "sophisticated jazz", "smooth trap", "elite music"
            ],
            "sigma_gaming": [
                "aggressive phonk beat dark", "drift phonk racing music", "dark trap beat intense",
                "sigma grindset phonk", "competitive gaming soundtrack", "motivational trap beat"
            ]
        }

        video_searches = {
            "redpill_reality": [
                "night city drive 4k", "urban aesthetic", "cyberpunk city",
                "tokyo night drive", "street racing", "city lights at night"
            ],
            "sigma_mindset": [
                "luxury lifestyle", "supercar driving", "business success",
                "rich lifestyle", "exotic cars", "mansion interior"
            ],
            "stoic_philosophy": [
                "nature solitude 4k", "meditation visuals", "ancient architecture",
                "mountain scenery", "peaceful lake", "zen garden"
            ],
            "monk_mode": [
                "minimal aesthetic", "focus visuals", "monochrome abstract",
                "empty room", "library", "calm workspace"
            ],
            "financial_freedom": [
                "money and success", "business office", "stock market",
                "financial growth", "entrepreneur lifestyle", "wealth symbols"
            ],
            "self_improvement": [
                "gym training", "meditation practice", "personal growth",
                "healthy lifestyle", "motivation montage", "sports training"
            ],
            "brutal_truth": [
                "dark aesthetic", "urban grit", "raw reality",
                "street life", "hard truth", "reality check"
            ],
            "high_value_mindset": [
                "premium lifestyle", "luxury brands", "exclusive club",
                "first class", "vip treatment", "high society"
            ],
            "sigma_gaming": [
                "chess strategy game 4k cinematic", "racing simulator cockpit view night",
                "poker professional tournament cinematic", "esports competitive gaming intense",
                "strategy game warfare tactical", "driving game drift mountain road"
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
            video_search_terms=selected_video_terms
        )


def create_gemini_generator() -> GeminiContentGenerator:
    """Factory function to create Gemini generator."""
    return GeminiContentGenerator()
