"""
Video generation processor for creating reels from content assets.

Handles:
- Video composition with ffmpeg
- ASS subtitle rendering
- Audio processing (bass boost, compression, loudness)
- Visual effects (dizzy, vignette, black & white)
- Metadata tracking
"""

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance

logger = get_logger(__name__)


class VideoGenerator:
    """Generate reels from video, music, and quote assets."""

    def __init__(
        self,
        output_dir: Path = None,
        font_name: str = "Impact",
        dizzy_rot_amp: float = 0.008,
        dizzy_drift_amp: int = 8,
        dizzy_crop_pad: int = 80,
        contrast: float = 1.20,
        brightness: float = 0.00,
        bass_boost_db: float = 7,
        bass_freq: float = 90,
        comp_threshold: float = -16,
        comp_ratio: float = 6.0,
        comp_attack: float = 5,
        comp_release: float = 80,
        limiter: float = -0.3,
        target_lufs: float = -14,
    ):
        """
        Initialize video generator with processing parameters.

        Args:
            output_dir: Directory for generated videos
            font_name: Font for text overlay
            dizzy_rot_amp: Rotation amplitude
            dizzy_drift_amp: Drift amplitude in pixels
            dizzy_crop_pad: Crop padding for dizzy effect
            contrast: Video contrast
            brightness: Video brightness
            bass_boost_db: Bass boost in dB
            bass_freq: Bass frequency center
            comp_threshold: Compressor threshold
            comp_ratio: Compressor ratio
            comp_attack: Compressor attack time
            comp_release: Compressor release time
            limiter: Limiter ceiling
            target_lufs: Target loudness in LUFS
        """
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(exist_ok=True)

        # Video effects
        self.font_name = font_name
        self.dizzy_rot_amp = dizzy_rot_amp
        self.dizzy_drift_amp = dizzy_drift_amp
        self.dizzy_crop_pad = dizzy_crop_pad
        self.contrast = contrast
        self.brightness = brightness

        # Audio processing
        self.bass_boost_db = bass_boost_db
        self.bass_freq = bass_freq
        self.comp_threshold = comp_threshold
        self.comp_ratio = comp_ratio
        self.comp_attack = comp_attack
        self.comp_release = comp_release
        self.limiter = limiter
        self.target_lufs = target_lufs

    @classmethod
    def from_config(cls):
        """Create generator from configuration."""
        config = get_config_instance()
        video_config = config.get("video", {})
        audio_config = config.get("audio", {})

        return cls(
            output_dir=Path(video_config.get("output_dir", "output")),
            font_name=video_config.get("font_name", "Impact"),
            dizzy_rot_amp=float(video_config.get("dizzy_rot_amp", 0.008)),
            dizzy_drift_amp=int(video_config.get("dizzy_drift_amp", 8)),
            dizzy_crop_pad=int(video_config.get("dizzy_crop_pad", 80)),
            contrast=float(video_config.get("contrast", 1.20)),
            brightness=float(video_config.get("brightness", 0.00)),
            bass_boost_db=float(audio_config.get("bass_boost_db", 7)),
            bass_freq=float(audio_config.get("bass_freq", 90)),
            comp_threshold=float(audio_config.get("comp_threshold", -16)),
            comp_ratio=float(audio_config.get("comp_ratio", 6.0)),
            comp_attack=float(audio_config.get("comp_attack", 5)),
            comp_release=float(audio_config.get("comp_release", 80)),
            limiter=float(audio_config.get("limiter", -0.3)),
            target_lufs=float(audio_config.get("target_lufs", -14)),
        )

    def _build_video_filter(self) -> str:
        """Build ffmpeg video filter chain for effects."""
        vignette_angle = "PI/4"

        return (
            # Fit inside 1080x1920, center-pad
            "scale=1080:1920:flags=lanczos:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
            # Black & white with contrast/brightness
            f"eq=saturation=0:contrast={self.contrast}:brightness={self.brightness},format=gray,"
            # Vignette
            f"vignette=angle={vignette_angle},"
            # Dizzy drift crop
            f"crop=iw-{self.dizzy_crop_pad*2}:ih-{self.dizzy_crop_pad*2}:"
            f"x={self.dizzy_crop_pad}+{self.dizzy_drift_amp}*sin(2*PI*t):"
            f"y={self.dizzy_crop_pad}+{self.dizzy_drift_amp}*cos(2*PI*t),"
            # Gentle wobble
            f"rotate={self.dizzy_rot_amp}*sin(2*PI*t):fillcolor=black,"
            # Soften and lock size
            "boxblur=1:1,"
            "scale=1080:1920:flags=lanczos"
        )

    def _build_audio_filter(self) -> str:
        """Build ffmpeg audio filter chain for processing."""
        return (
            f"equalizer=f={self.bass_freq}:t=q:w=1.2:g={self.bass_boost_db},"
            f"equalizer=f=60:t=q:w=1.0:g={self.bass_boost_db/2},"
            f"acompressor=threshold={self.comp_threshold}dB:ratio={self.comp_ratio}:"
            f"attack={self.comp_attack}:release={self.comp_release},"
            f"alimiter=limit={self.limiter}dB,"
            f"loudnorm=I={self.target_lufs}:TP=-1.0:LRA=7.0:dual_mono=true"
        )

    def _make_ass_subtitle(self, quote: str, ass_path: Path) -> None:
        """Create ASS subtitle file for quote overlay."""
        # Uppercase, wrap to 28-34 chars per line, max 3 lines
        core = quote.split("—")[0].strip().upper()
        wrapped = textwrap.wrap(core, width=28)
        wrapped = wrapped[:3]
        text = r"\N".join(wrapped)  # ASS newline

        # ASS template: big bold white, black outline, animated scale punch
        ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BIG,{self.font_name},82,&H00FFFFFF,&H000000FF,&H00000000,&H66000000,1,0,0,0,100,100,0,0,1,4,2,2,60,60,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.30,9:59:59.00,BIG,,0000,0000,0000,,{{\\an2\\pos(540,1500)\\move(540,1500,540,1485,300,3000)\\fad(200,400)\\bord4\\shad2\\blur1\\1c&HFFFFFF&\\3c&H000000&\\fsp2\\t(300,1000,\\fscx110\\fscy110)\\t(1000,2000,\\fscx100\\fscy100)}}{text}
"""
        ass_path.write_text(ass_content, encoding="utf-8")
        logger.debug(f"ASS subtitle created: {ass_path.name}")

    def generate(
        self,
        video_path: Path,
        music_path: Path,
        quote: str,
        caption: str,
        output_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a reel from video, music, and quote.

        Args:
            video_path: Path to vertical video clip
            music_path: Path to audio track
            quote: Quote text for overlay
            caption: Caption for the post
            output_filename: Optional custom output filename

        Returns:
            Dict with generated reel metadata including:
            - output_path: Path to generated video
            - duration: Video duration in seconds
            - file_size: File size in bytes
            - metadata: Metadata dict for database storage

        Raises:
            Exception: If video generation fails
        """
        import random
        import os

        # Determine output filename
        if output_filename is None:
            random_id = random.randint(100000, 999999)
            output_filename = f"reel_{random_id}.mp4"

        output_path = self.output_dir / output_filename

        logger.info(f"Generating video: {video_path.name}")
        logger.info(f"Music: {music_path.name}")
        logger.info(f"Quote: {quote[:60]}...")

        video_filter = self._build_video_filter()
        audio_filter = self._build_audio_filter()

        try:
            with tempfile.TemporaryDirectory() as td:
                ass_path = Path(td) / "quote.ass"
                self._make_ass_subtitle(quote, ass_path)

                # FFmpeg command
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path.as_posix(),
                    "-i", music_path.as_posix(),
                    "-filter_complex",
                    f"[0:v]{video_filter},ass='{ass_path.as_posix()}'[v];[1:a]{audio_filter}[a]",
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-profile:v", "high", "-level", "4.1",
                    "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    output_path.as_posix()
                ]

                logger.info(f"Running ffmpeg...")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                logger.info(f"Video generated: {output_path.name}")

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise Exception(f"Video generation failed: {e.stderr}")
        except Exception as e:
            logger.error(f"Unexpected error during video generation: {e}")
            raise

        # Extract duration
        try:
            cmd_probe = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output_path.as_posix()
            ]
            result = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=30)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
        except Exception as e:
            logger.warning(f"Could not determine video duration: {e}")
            duration = 0.0

        # Get file size
        try:
            file_size = output_path.stat().st_size
        except Exception as e:
            logger.warning(f"Could not determine file size: {e}")
            file_size = 0

        # Metadata
        metadata = {
            "output": output_path.as_posix(),
            "stock_video": video_path.name,
            "music": music_path.name,
            "quote": quote,
            "caption": caption,
            "duration": duration,
            "file_size": file_size,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

        # Write sidecar metadata file
        sidecar_path = output_path.with_suffix(".meta.json")
        try:
            sidecar_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.debug(f"Metadata sidecar written: {sidecar_path.name}")
        except Exception as e:
            logger.warning(f"Could not write metadata sidecar: {e}")

        logger.info(f"✅ Reel generated successfully")

        return {
            "output_path": output_path,
            "duration": duration,
            "file_size": file_size,
            "metadata": metadata
        }

    def generate_from_combination(
        self,
        combination,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate video from a ContentCombination object.

        Args:
            combination: ContentCombination with video, music, quote
            caption: Optional custom caption (defaults to quote)

        Returns:
            Generated video metadata dict
        """
        if caption is None:
            caption = combination.quote.text[:150]

        return self.generate(
            video_path=Path(combination.video.filename),
            music_path=Path(combination.music.filename),
            quote=combination.quote.text,
            caption=caption,
        )
