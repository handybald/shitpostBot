"""
Video generation processor - renders reels via the Remotion renderer.

This replaces the old raw-ffmpeg filter-graph composition (hardcoded 13s
duration, hand-escaped ASS subtitle strings, two divergent
generate/generate_two_part code paths with different encoder settings).
Composition now lives in `renderer/` (Remotion/TypeScript); this module's
job is just staging assets and invoking that renderer as a subprocess.

Duration is no longer a parameter here - it falls out of however long the
voiceover actually is (see renderer/src/Reel.tsx calculateReelMetadata).
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.tts_provider import VoiceoverResult
from src.utils.config_loader import get_config_instance
from src.utils.logger import get_logger

logger = get_logger(__name__)

RENDERER_DIR = Path(__file__).parent.parent.parent / "renderer"
MIN_CLIP_SEGMENT_SECONDS = 2.0


class VideoGenerationError(Exception):
    """Raised when the Remotion render subprocess fails."""


@dataclass
class ThemeStyle:
    accent_color: str = "#FFD700"
    base_color: str = "#FFFFFF"
    font_family: str = "Impact, Haettenschweiler, sans-serif"
    contrast: float = 1.15
    brightness: float = 0.0


class VideoGenerator:
    """Renders reels by staging assets and invoking the Remotion renderer."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        theme_style: Optional[ThemeStyle] = None,
        music_volume: float = 0.22,
        max_words_per_line: int = 4,
    ):
        self.output_dir = output_dir or Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.theme_style = theme_style or ThemeStyle()
        self.music_volume = music_volume
        self.max_words_per_line = max_words_per_line

        self._check_renderer_available()

    @classmethod
    def from_config(cls) -> "VideoGenerator":
        config = get_config_instance()
        video_config = config.get("video", {})
        theme_style = ThemeStyle(
            accent_color=video_config.get("accent_color", "#FFD700"),
            base_color=video_config.get("base_color", "#FFFFFF"),
            font_family=video_config.get("font_name", "Impact") + ", Haettenschweiler, sans-serif",
            contrast=float(video_config.get("contrast", 1.15)),
            brightness=float(video_config.get("brightness", 0.0)),
        )
        return cls(
            output_dir=Path(video_config.get("output_dir", "data/output")),
            theme_style=theme_style,
            music_volume=float(video_config.get("music_volume", 0.22)),
            max_words_per_line=int(video_config.get("max_words_per_line", 4)),
        )

    @staticmethod
    def _check_renderer_available() -> None:
        """
        Fail fast and clearly if the renderer isn't set up, instead of
        letting a cryptic subprocess error surface three steps later.
        """
        if not RENDERER_DIR.exists():
            raise VideoGenerationError(f"Renderer directory not found: {RENDERER_DIR}")
        if not (RENDERER_DIR / "node_modules").exists():
            raise VideoGenerationError(
                f"Renderer dependencies not installed - run `npm install` in {RENDERER_DIR}"
            )
        if shutil.which("npx") is None:
            raise VideoGenerationError("npx not found on PATH - Node.js is required to render reels")

    def generate(
        self,
        background_clips: List[Path],
        voiceover: VoiceoverResult,
        caption: str,
        music_path: Optional[Path] = None,
        output_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Render a reel.

        Args:
            background_clips: QC-accepted clips to sequence across the
                voiceover's duration (in order).
            voiceover: TTS result (audio path + word-level timestamps) -
                this is what determines the render's total duration.
            caption: Instagram caption for the post (stored in metadata,
                not burned into the video).
            music_path: Optional background music, auto-ducked under the
                voiceover by the renderer.
            output_filename: Optional custom output filename.

        Returns:
            Dict with output_path, duration, file_size, metadata - same
            shape the orchestrator/quality checker already expect.
        """
        if not background_clips:
            raise VideoGenerationError("At least one background clip is required")
        if not voiceover.words:
            raise VideoGenerationError("Voiceover has no word timestamps - cannot time the render")

        if output_filename is None:
            import random
            output_filename = f"reel_{random.randint(100000, 999999)}.mp4"
        output_path = self.output_dir / output_filename

        staging_dir = Path(tempfile.mkdtemp(prefix="reel_render_"))
        try:
            props = self._stage_assets_and_build_props(
                staging_dir, background_clips, voiceover, music_path
            )
            props_path = staging_dir / "props.json"
            props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")

            self._invoke_remotion_render(output_path, props_path, staging_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        duration, file_size = self._probe_output(output_path)

        metadata = {
            "output": output_path.as_posix(),
            "background_clips": [c.name for c in background_clips],
            "voiceover_text": " ".join(w.text for w in voiceover.words),
            "caption": caption,
            "duration": duration,
            "file_size": file_size,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        sidecar_path = output_path.with_suffix(".meta.json")
        try:
            sidecar_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not write metadata sidecar: {e}")

        logger.info(f"Reel rendered: {output_path.name} ({duration:.1f}s)")

        return {
            "output_path": output_path,
            "duration": duration,
            "file_size": file_size,
            "metadata": metadata,
        }

    def _stage_assets_and_build_props(
        self,
        staging_dir: Path,
        background_clips: List[Path],
        voiceover: VoiceoverResult,
        music_path: Optional[Path],
    ) -> Dict[str, Any]:
        public_dir = staging_dir / "public"
        public_dir.mkdir(parents=True, exist_ok=True)

        total_duration = voiceover.words[-1].end
        segment_duration = self._allocate_segment_duration(len(background_clips), total_duration)
        clips_to_use = background_clips[: self._max_usable_clips(total_duration)] or background_clips[:1]

        staged_clips = []
        for i, clip_path in enumerate(clips_to_use):
            staged_name = f"bg_{i}{clip_path.suffix}"
            shutil.copy(clip_path, public_dir / staged_name)
            staged_clips.append({
                "src": staged_name,
                "startFrom": 0,
                "durationInSeconds": segment_duration,
            })

        voiceover_staged_name = f"voiceover{voiceover.audio_path.suffix}"
        shutil.copy(voiceover.audio_path, public_dir / voiceover_staged_name)

        music_staged_name = None
        if music_path is not None:
            music_staged_name = f"music{music_path.suffix}"
            shutil.copy(music_path, public_dir / music_staged_name)

        return {
            "fps": 30,
            "width": 1080,
            "height": 1920,
            "backgroundClips": staged_clips,
            "voiceoverSrc": voiceover_staged_name,
            "words": [w.to_dict() for w in voiceover.words],
            "musicSrc": music_staged_name,
            "musicVolume": self.music_volume,
            "musicFadeSeconds": 1.5,
            "outroPaddingSeconds": 0.6,
            "theme": {
                "accentColor": self.theme_style.accent_color,
                "baseColor": self.theme_style.base_color,
                "fontFamily": self.theme_style.font_family,
                "contrast": self.theme_style.contrast,
                "brightness": self.theme_style.brightness,
            },
            "maxWordsPerLine": self.max_words_per_line,
        }

    @staticmethod
    def _max_usable_clips(total_duration: float) -> int:
        return max(1, int(total_duration // MIN_CLIP_SEGMENT_SECONDS))

    @staticmethod
    def _allocate_segment_duration(clip_count: int, total_duration: float) -> float:
        clip_count = max(1, clip_count)
        return max(MIN_CLIP_SEGMENT_SECONDS, total_duration / clip_count)

    @staticmethod
    def _invoke_remotion_render(output_path: Path, props_path: Path, public_dir_parent: Path) -> None:
        cmd = [
            "npx", "remotion", "render", "src/index.tsx", "Reel",
            output_path.as_posix(),
            f"--props={props_path.as_posix()}",
            f"--public-dir={(public_dir_parent / 'public').as_posix()}",
        ]
        logger.info("Rendering reel via Remotion...")
        result = subprocess.run(
            cmd, cwd=RENDERER_DIR.as_posix(), capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise VideoGenerationError(f"Remotion render failed:\n{result.stderr[-4000:]}")

    @staticmethod
    def _probe_output(output_path: Path) -> tuple:
        duration = 0.0
        try:
            cmd_probe = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output_path.as_posix(),
            ]
            result = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=30)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
        except Exception as e:
            logger.warning(f"Could not determine video duration: {e}")

        file_size = 0
        try:
            file_size = output_path.stat().st_size
        except Exception as e:
            logger.warning(f"Could not determine file size: {e}")

        return duration, file_size
