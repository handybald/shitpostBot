"""
ElevenLabs text-to-speech provider.

Generates voiceover audio together with word-level timestamps, which is
what lets the Remotion renderer sync captions to the actual spoken audio
instead of a hardcoded duration/timing (the root cause of the old
pipeline's pacing problems).
"""

import base64
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


@dataclass
class WordTiming:
    text: str
    start: float
    end: float

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "start": self.start, "end": self.end}


@dataclass
class VoiceoverResult:
    audio_path: Path
    words: List[WordTiming]
    duration: float


class TTSProviderError(Exception):
    """Raised when voiceover generation fails."""


class ElevenLabsTTSProvider:
    """Generates voiceover audio + word-level timestamps via ElevenLabs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        output_dir: Optional[Path] = None,
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID")
        self.model_id = model_id
        self.output_dir = output_dir or Path("data/output/voiceover")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.is_configured():
            logger.warning(
                "ElevenLabs not fully configured (need ELEVENLABS_API_KEY and "
                "ELEVENLABS_VOICE_ID) - TTS generation will fail until set"
            )

    @classmethod
    def from_config(cls) -> "ElevenLabsTTSProvider":
        from src.utils.config_loader import get_config_instance

        config = get_config_instance()
        tts_config = config.get("tts", {})
        return cls(
            voice_id=tts_config.get("voice_id"),
            model_id=tts_config.get("model_id", DEFAULT_MODEL_ID),
            output_dir=Path(tts_config.get("output_dir", "data/output/voiceover")),
        )

    def is_configured(self) -> bool:
        placeholder = "your_elevenlabs_api_key_here"
        return bool(self.api_key) and self.api_key != placeholder and bool(self.voice_id)

    def generate(self, text: str, output_filename: Optional[str] = None) -> VoiceoverResult:
        """
        Generate voiceover audio with word-level timestamps.

        Uses ElevenLabs' /text-to-speech/{voice_id}/with-timestamps endpoint,
        which returns base64-encoded audio plus character-level alignment.
        Word timings are derived from the character timings by grouping on
        whitespace.
        """
        if not self.is_configured():
            raise TTSProviderError(
                "ElevenLabs is not configured (missing ELEVENLABS_API_KEY or "
                "ELEVENLABS_VOICE_ID)"
            )

        text = text.strip()
        if not text:
            raise TTSProviderError("Cannot generate voiceover for empty text")

        url = f"{ELEVENLABS_API_BASE}/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        logger.info(f"Requesting ElevenLabs voiceover ({len(text)} chars)")
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            raise TTSProviderError(f"ElevenLabs request failed: {e}") from e

        data = response.json()
        if "audio_base64" not in data or "alignment" not in data:
            raise TTSProviderError(f"Unexpected ElevenLabs response shape: {list(data.keys())}")

        audio_bytes = base64.b64decode(data["audio_base64"])

        if output_filename is None:
            output_filename = f"voiceover_{random.randint(100000, 999999)}.mp3"
        audio_path = self.output_dir / output_filename
        audio_path.write_bytes(audio_bytes)

        alignment = data["alignment"]
        words = characters_to_words(
            alignment["characters"],
            alignment["character_start_times_seconds"],
            alignment["character_end_times_seconds"],
        )

        if not words:
            raise TTSProviderError("ElevenLabs returned no usable word alignment")

        duration = words[-1].end
        logger.info(
            f"Voiceover generated: {audio_path.name} "
            f"({duration:.1f}s, {len(words)} words)"
        )

        return VoiceoverResult(audio_path=audio_path, words=words, duration=duration)


def characters_to_words(
    characters: List[str],
    start_times: List[float],
    end_times: List[float],
) -> List[WordTiming]:
    """Group ElevenLabs' character-level alignment into word-level timings."""
    words: List[WordTiming] = []
    current_chars: List[str] = []
    current_start: Optional[float] = None
    current_end: Optional[float] = None

    for char, start, end in zip(characters, start_times, end_times):
        if char.isspace():
            if current_chars:
                words.append(
                    WordTiming(text="".join(current_chars), start=current_start, end=current_end)
                )
                current_chars = []
                current_start = None
            continue

        if current_start is None:
            current_start = start
        current_chars.append(char)
        current_end = end

    if current_chars:
        words.append(WordTiming(text="".join(current_chars), start=current_start, end=current_end))

    return words
