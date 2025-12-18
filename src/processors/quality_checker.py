"""
Video quality verification and assessment.

Validates:
- File integrity and format
- Duration bounds
- File size constraints
- Video codec and resolution
"""

import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class QualityChecker:
    """Verify and assess video quality."""

    def __init__(
        self,
        min_duration: float = 15.0,
        max_duration: float = 180.0,
        min_file_size: int = 1_000_000,  # 1MB
        max_file_size: int = 500_000_000,  # 500MB
        expected_width: int = 1080,
        expected_height: int = 1920,
    ):
        """
        Initialize quality checker.

        Args:
            min_duration: Minimum video duration in seconds
            max_duration: Maximum video duration in seconds
            min_file_size: Minimum file size in bytes
            max_file_size: Maximum file size in bytes
            expected_width: Expected video width
            expected_height: Expected video height
        """
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_file_size = min_file_size
        self.max_file_size = max_file_size
        self.expected_width = expected_width
        self.expected_height = expected_height

    def get_video_info(self, video_path: Path) -> Optional[Dict[str, Any]]:
        """
        Get detailed video information using ffprobe.

        Args:
            video_path: Path to video file

        Returns:
            Dict with video metadata, or None if extraction fails
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_format", "-show_streams",
                "-print_format", "json",
                video_path.as_posix()
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=True
            )
            return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None

    def extract_video_stream(
        self,
        info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract video stream info from ffprobe output."""
        streams = info.get("streams", [])
        for stream in streams:
            if stream.get("codec_type") == "video":
                return stream
        return None

    def extract_audio_stream(
        self,
        info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract audio stream info from ffprobe output."""
        streams = info.get("streams", [])
        for stream in streams:
            if stream.get("codec_type") == "audio":
                return stream
        return None

    def check_integrity(self, video_path: Path) -> Dict[str, Any]:
        """
        Check video file integrity.

        Args:
            video_path: Path to video file

        Returns:
            Dict with check results and quality score 0-1
        """
        logger.info(f"Checking video integrity: {video_path.name}")

        checks = {
            "file_exists": False,
            "file_readable": False,
            "format_valid": False,
            "has_video_stream": False,
            "has_audio_stream": False,
            "duration_ok": False,
            "file_size_ok": False,
            "resolution_ok": False,
            "codec_ok": False,
        }

        issues = []
        quality_score = 1.0

        # File existence
        if not video_path.exists():
            issues.append("File does not exist")
            logger.error(f"Video file not found: {video_path}")
            return {"checks": checks, "issues": issues, "quality_score": 0.0}

        checks["file_exists"] = True

        # File readability
        try:
            file_size = video_path.stat().st_size
            checks["file_readable"] = True
        except Exception as e:
            issues.append(f"File not readable: {e}")
            logger.error(f"Cannot read file: {e}")
            return {"checks": checks, "issues": issues, "quality_score": 0.0}

        # File size check
        if not (self.min_file_size <= file_size <= self.max_file_size):
            size_mb = file_size / (1024 * 1024)
            issues.append(
                f"File size {size_mb:.1f}MB outside range "
                f"({self.min_file_size/1024/1024:.0f}MB - {self.max_file_size/1024/1024:.0f}MB)"
            )
            quality_score -= 0.2
        else:
            checks["file_size_ok"] = True

        # Get format info
        info = self.get_video_info(video_path)
        if info is None:
            issues.append("Could not extract video metadata")
            logger.warning("FFprobe failed")
            return {"checks": checks, "issues": issues, "quality_score": max(quality_score, 0.3)}

        checks["format_valid"] = True

        # Video stream
        video_stream = self.extract_video_stream(info)
        if video_stream is None:
            issues.append("No video stream found")
            quality_score -= 0.3
        else:
            checks["has_video_stream"] = True

            # Resolution
            width = video_stream.get("width")
            height = video_stream.get("height")
            if width == self.expected_width and height == self.expected_height:
                checks["resolution_ok"] = True
            else:
                issues.append(
                    f"Resolution {width}x{height} (expected {self.expected_width}x{self.expected_height})"
                )
                quality_score -= 0.15

            # Codec
            codec = video_stream.get("codec_name", "").lower()
            if codec in ("h264", "libx264"):
                checks["codec_ok"] = True
            else:
                issues.append(f"Codec {codec} (expected h264)")
                quality_score -= 0.1

            # Duration
            duration = float(video_stream.get("duration", 0))
            if not duration and info.get("format"):
                duration = float(info["format"].get("duration", 0))

            if self.min_duration <= duration <= self.max_duration:
                checks["duration_ok"] = True
            else:
                issues.append(
                    f"Duration {duration:.1f}s outside range "
                    f"({self.min_duration}s - {self.max_duration}s)"
                )
                quality_score -= 0.2

        # Audio stream
        audio_stream = self.extract_audio_stream(info)
        if audio_stream:
            checks["has_audio_stream"] = True
        else:
            issues.append("No audio stream found (will use silence)")
            quality_score -= 0.1

        # Clamp quality score
        quality_score = max(0.0, min(1.0, quality_score))

        logger.info(f"Quality check complete: score={quality_score:.2f}")

        return {
            "file_path": video_path.as_posix(),
            "file_size": file_size,
            "checks": checks,
            "issues": issues,
            "quality_score": quality_score,
        }

    def is_acceptable(
        self,
        video_path: Path,
        min_quality_score: float = 0.7,
    ) -> bool:
        """
        Determine if video is acceptable for use.

        Args:
            video_path: Path to video file
            min_quality_score: Minimum acceptable quality score

        Returns:
            True if video passes quality checks
        """
        result = self.check_integrity(video_path)
        is_acceptable = result["quality_score"] >= min_quality_score

        if not is_acceptable:
            logger.warning(f"Video rejected (score {result['quality_score']:.2f}): {result['issues']}")
        else:
            logger.info(f"Video acceptable (score {result['quality_score']:.2f})")

        return is_acceptable
