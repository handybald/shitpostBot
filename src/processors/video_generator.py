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
import random
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

    @staticmethod
    def _generate_random_white_color() -> str:
        """Generate random white-ish color in ASS BGR format (&HBBGGRR).

        Returns colors in range:
        - R: 200-255 (bright red component)
        - G: 200-255 (bright green component)
        - B: 200-255 (bright blue component)

        This creates various pale/light colors near white.
        Format: &H00BBGGRR (in BGR order with transparency 00)
        """
        r = random.randint(200, 255)
        g = random.randint(200, 255)
        b = random.randint(200, 255)
        # ASS uses BGR format, so convert RGB to BGR
        return f"&H00{b:02X}{g:02X}{r:02X}"

    def _create_ass_subtitle(self, quote: str, ass_path: Path) -> None:
        quote = " ".join(quote.strip().split())

        lines = textwrap.wrap(
            quote,
            width=26,
            break_long_words=False,
            break_on_hyphens=False
        )
        wrapped = r"\N".join(lines)

        fontsize = 82
        if len(lines) > 4:
            fontsize = 72
        if len(lines) > 5:
            fontsize = 62

        ass_content = f"""[Script Info]
        Title: Quote Overlay
        ScriptType: v4.00+
        PlayResX: 1080
        PlayResY: 1920
        WrapStyle: 2
        ScaledBorderAndShadow: yes

        [V4+ Styles]
        Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
        Style: Default,Impact,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,5,90,90,0,1

        [Events]
        Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        Dialogue: 0,0:00:00.00,0:00:10.00,Default,,0,0,0,,{{\\q2\\fad(600,600)\\t(0,300,\\fscx105\\fscy105)}}{wrapped}
        """
        ass_path.write_text(ass_content, encoding="utf-8")

    def _create_two_part_ass_subtitle(self, hook: str, payoff: str, ass_path: Path) -> None:
        """Create ASS subtitle for two-part quote: hook (0-4.5s) + payoff (4.5-13s).

        Hook: Starts at 0.2s, ends at 4.5s with eye-catching color (randomized white-ish)
        Payoff: Starts at 4.5s, ends at 13s with dynamic animated style
        - Color shift: Magenta → Cyan transition (smooth, readable)
        - Scale pulse: Grows to 112% then returns to 100%
        - Heavy glow/shadow (3px border, 4px shadow) for visibility on any background
        Animations:
          * 0-700ms: Fade in + grow to 112% + magenta color
          * 700-3500ms: Smooth color transition from magenta to cyan
          * 3500-5500ms: Shrink back to normal size (creates rhythm)
        Timing is designed for a 13-second reel with proper transitions.
        """
        hook = " ".join(hook.strip().split())
        payoff = " ".join(payoff.strip().split())

        hook_lines = textwrap.wrap(hook, width=18, break_long_words=False, break_on_hyphens=False)
        hook_wrapped = r"\N".join(hook_lines)

        payoff_lines = textwrap.wrap(payoff, width=20, break_long_words=False, break_on_hyphens=False)
        payoff_wrapped = r"\N".join(payoff_lines)

        # Increased font sizes for better visibility on phone (audience feedback: text too small)
        hook_fontsize = 95 if len(hook_lines) <= 2 else 85 if len(hook_lines) <= 3 else 75
        payoff_fontsize = 85 if len(payoff_lines) <= 3 else 75 if len(payoff_lines) <= 4 else 65

        # Generate random white-ish colors for hook (changes each reel)
        hook_color = self._generate_random_white_color()

        ass_content = f"""[Script Info]
        Title: Two-Part Quote
        ScriptType: v4.00+
        PlayResX: 1080
        PlayResY: 1920
        WrapStyle: 2
        ScaledBorderAndShadow: yes

        [V4+ Styles]
        Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
        Style: Hook,Impact,{hook_fontsize},{hook_color},&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,3,2,60,60,150,1
        Style: Payoff,Impact,{payoff_fontsize},&H00FFFFFF,&H000000FF,&H00FF6600,&H64000000,-1,0,0,0,100,100,0,0,1,5,4,2,60,60,250,1

        [Events]
        Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        Dialogue: 0,0:00:0.00,0:00:4.50,Hook,,0,0,0,,{{\\q2\\fad(100,200)\\t(0,1500,\\fscx105\\fscy105)\\t(3000,4500,\\fscx100\\fscy100)}}{hook_wrapped}
        Dialogue: 1,0:00:4.50,0:00:13.00,Payoff,,0,0,0,,{{\\q2\\bord4\\shad5\\fad(200,400)\\t(0,600,\\fscx110\\fscy110)\\t(3500,5500,\\fscx100\\fscy100)}}{payoff_wrapped}
        """
        ass_path.write_text(ass_content, encoding="utf-8")
    def _ffmpeg_filter_escape(self, s: str) -> str:
        # minimal set that commonly breaks filter args
        return (s.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace(",", "\\,")
                .replace("'", "\\'"))
    def _build_video_filter_with_text(self, quote: str, ass_file_path: Path) -> str:
        self._create_ass_subtitle(quote, ass_file_path)
        ass = self._ffmpeg_filter_escape(ass_file_path.as_posix())

        return (
                "format=yuv420p,"  # <--- CRITICAL: Force format before scaling
                "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"subtitles=filename='{ass}'," # Ensure single quotes around path
                "format=yuv420p"  # Confirm output format for the encoder
            )
    def _build_video_filter_with_ass(self, ass_file_path: Path) -> str:
        ass = self._ffmpeg_filter_escape(ass_file_path.as_posix())
        return (
                "format=yuv420p,"  # <--- CRITICAL: Force format before scaling
                "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"subtitles=filename='{ass}'," # Ensure single quotes around path
                "format=yuv420p"  # Confirm output format for the encoder
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

        try:
            import tempfile
            # Create temp file for ASS subtitle
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8') as tf:
                text_file = Path(tf.name)
            
            # Build filters with text overlay
            video_filter = self._build_video_filter_with_text(quote, text_file)
            audio_filter = self._build_audio_filter()

            try:
                # FFmpeg command - apply video effects with text and audio processing
                logger.info("Combining video, music, and text overlay")
                logger.info(f"Quote: {quote}")

                # Build filter chains properly - use semicolon to separate independent chains
                video_filter_chain = f"[0:v]{video_filter}[v]"
                audio_filter_chain = f"[1:a]{audio_filter}[a]"
                
                cmd = [
                    "/usr/bin/ffmpeg", "-y",
                    "-i", video_path.as_posix(),
                    "-i", music_path.as_posix(),
                    "-filter_complex",
                    f"{video_filter_chain};{audio_filter_chain}",
                    "-map", "[v]",  # Use filtered video with text overlay
                    "-map", "[a]",  # Use filtered audio
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k",
                    "-shortest",
                    output_path.as_posix()
                ]

                logger.info(f"Running ffmpeg...")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                logger.info(f"Video generated: {output_path.name}")

            finally:
                # Clean up temp text file
                if text_file.exists():
                    text_file.unlink()

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

    def generate_two_part(
        self,
        video_path: Path,
        music_path: Path,
        hook: str,
        payoff: str,
        caption: str,
        output_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a reel with two-part quote (hook + payoff).

        Args:
            video_path: Path to vertical video clip
            music_path: Path to audio track
            hook: First part of quote (4 seconds, eye-catching)
            payoff: Second part of quote (rest of video, powerful)
            caption: Caption for the post
            output_filename: Optional custom output filename

        Returns:
            Dict with generated reel metadata
        """
        import random
        import os

        if output_filename is None:
            random_id = random.randint(100000, 999999)
            output_filename = f"reel_{random_id}.mp4"

        output_path = self.output_dir / output_filename

        logger.info(f"Generating two-part video: {video_path.name}")
        logger.info(f"Music: {music_path.name}")
        logger.info(f"Hook: {hook[:50]}...")
        logger.info(f"Payoff: {payoff[:50]}...")

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8') as tf:
                text_file = Path(tf.name)

            self._create_two_part_ass_subtitle(hook, payoff, text_file)
            
            # FFmpeg requires colons in Windows paths to be escaped within filters
            ass_path_escaped = text_file.as_posix().replace(":", "\\:")
            audio_filter = self._build_audio_filter()

            # Define the explicit video chain
            # 1. Start with format to lock the colors
            # 2. Scale and Pad
            # 3. Apply subtitles
            video_filter_str = (
                "format=rgb24,"                   # 1. Standardize input immediately
                "scale=w=1080:h=1920:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black," # 3. Pad to vertical
                
                f"subtitles=filename='{ass_path_escaped}'," # 5. Burn subtitles
                "format=rgb24"                    # 7. Final hand-off to encoder
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path.as_posix(),
                "-i", music_path.as_posix(),
                "-filter_complex", f"[0:v]{video_filter_str}[v_out];[1:a]{audio_filter}[a_out]",
                "-map", "[v_out]",
                "-map", "[a_out]",
                "-c:v", "libx264",
                "-preset", "medium",       # 'medium' is safer than 'ultrafast' for preventing strips
                "-crf", "18",              # Very high quality (lower = better, 18 is near-lossless)
                # "-pix_fmt", "yuv420p",     # Standard format for maximum compatibility
                "-shortest",
                "-t", "13",
                output_path.as_posix()
            ]

            logger.info("Running fixed ffmpeg mapping...")
            subprocess.run(cmd, capture_output=True, text=True, check=True)

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise Exception(f"Video generation failed: {e.stderr}")
        except Exception as e:
            logger.error(f"Unexpected error during video generation: {e}")
            raise
        finally:
            if text_file.exists():
                text_file.unlink()

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
        full_quote = f"{hook} {payoff}"
        metadata = {
            "output": output_path.as_posix(),
            "stock_video": video_path.name,
            "music": music_path.name,
            "quote": full_quote,
            "hook": hook,
            "payoff": payoff,
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

        logger.info(f"✅ Two-part reel generated successfully")

        return {
            "output_path": output_path,
            "duration": duration,
            "file_size": file_size,
            "metadata": metadata
        }
