"""
Audio processing utilities for music curation and analysis.

Handles:
- Audio feature extraction (spectral analysis)
- Bass detection and scoring
- Music suitability filtering
- Audio quality assessment
"""

from pathlib import Path
from typing import Optional, Dict, Any
import json

try:
    import numpy as np
    import librosa
except ImportError:
    np = None
    librosa = None

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AudioProcessor:
    """Process and analyze audio tracks."""

    def __init__(
        self,
        low_cutoff: float = 150.0,
        min_low_ratio: float = 0.12,
        max_centroid: float = 2500.0,
        min_duration: float = 5.0,
    ):
        """
        Initialize audio processor.

        Args:
            low_cutoff: Frequency cutoff for bass band (Hz)
            min_low_ratio: Minimum ratio of low-band energy to keep track
            max_centroid: Maximum spectral centroid to keep track
            min_duration: Minimum track duration in seconds
        """
        if librosa is None or np is None:
            raise ImportError(
                "librosa and numpy required for audio processing. "
                "Install with: pip install librosa numpy"
            )

        self.low_cutoff = low_cutoff
        self.min_low_ratio = min_low_ratio
        self.max_centroid = max_centroid
        self.min_duration = min_duration
        logger.info("Audio processor initialized")

    def analyze_track(self, audio_path: Path) -> Optional[Dict[str, float]]:
        """
        Analyze audio track for bass and spectral characteristics.

        Args:
            audio_path: Path to audio file

        Returns:
            Dict with 'low_ratio' and 'centroid', or None if invalid

        Raises:
            Exception: If analysis fails
        """
        try:
            logger.debug(f"Analyzing audio: {audio_path.name}")

            # Load audio
            y, sr = librosa.load(audio_path.as_posix(), mono=True)

            # Check minimum duration
            duration = len(y) / sr
            if duration < self.min_duration:
                logger.debug(f"Track too short: {duration:.1f}s")
                return None

            # Spectral analysis
            S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)) ** 2
            freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)

            # Low-frequency energy ratio
            total_energy = S.sum()
            low_mask = freqs <= self.low_cutoff
            low_energy = S[low_mask, :].sum()
            low_ratio = float(low_energy / (total_energy + 1e-12))

            # Spectral centroid
            centroid = float(librosa.feature.spectral_centroid(S=S, sr=sr).mean())

            logger.debug(
                f"Audio analysis - low_ratio: {low_ratio:.3f}, centroid: {centroid:.0f}Hz"
            )

            return {
                "low_ratio": low_ratio,
                "centroid": centroid,
                "duration": duration,
                "sample_rate": sr,
            }

        except Exception as e:
            logger.error(f"Error analyzing {audio_path.name}: {e}")
            return None

    def is_suitable_track(
        self,
        audio_path: Path,
        low_ratio: Optional[float] = None,
        centroid: Optional[float] = None,
    ) -> bool:
        """
        Check if track meets suitability criteria.

        Args:
            audio_path: Path to audio file
            low_ratio: Override minimum low ratio threshold
            centroid: Override maximum centroid threshold

        Returns:
            True if track is suitable for the project
        """
        low_ratio = low_ratio or self.min_low_ratio
        centroid = centroid or self.max_centroid

        analysis = self.analyze_track(audio_path)
        if analysis is None:
            return False

        is_bassy = analysis["low_ratio"] >= low_ratio
        is_not_bright = analysis["centroid"] <= centroid

        suitable = is_bassy and is_not_bright
        logger.debug(
            f"{audio_path.name}: bassy={is_bassy}, not_bright={is_not_bright}, suitable={suitable}"
        )

        return suitable

    def batch_analyze(
        self,
        audio_dir: Path,
        output_report: Optional[Path] = None,
        filter_suitable: bool = False,
    ) -> list:
        """
        Analyze multiple audio files.

        Args:
            audio_dir: Directory containing audio files
            output_report: Optional path to save JSON report
            filter_suitable: Only return suitable tracks

        Returns:
            List of analysis results
        """
        audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))
        audio_files += list(audio_dir.glob("*.m4a")) + list(audio_dir.glob("*.aac"))

        logger.info(f"Analyzing {len(audio_files)} audio files from {audio_dir.name}")

        results = []
        for audio_path in audio_files:
            analysis = self.analyze_track(audio_path)

            if analysis is None:
                continue

            suitable = (
                analysis["low_ratio"] >= self.min_low_ratio
                and analysis["centroid"] <= self.max_centroid
            )

            if filter_suitable and not suitable:
                continue

            result = {
                "file": audio_path.name,
                "path": audio_path.as_posix(),
                "suitable": suitable,
                **analysis,
            }
            results.append(result)

        logger.info(f"Analysis complete: {len(results)} files processed")

        if output_report:
            try:
                output_report.write_text(
                    json.dumps(results, indent=2),
                    encoding="utf-8"
                )
                logger.info(f"Report saved: {output_report}")
            except Exception as e:
                logger.error(f"Could not save report: {e}")

        return results

    def get_energy_level(self, analysis: Dict[str, float]) -> str:
        """
        Estimate energy level from spectral analysis.

        Args:
            analysis: Dict from analyze_track()

        Returns:
            "high", "medium", or "low"
        """
        centroid = analysis.get("centroid", 2000)

        if centroid > 2000:
            return "high"
        elif centroid > 1000:
            return "medium"
        else:
            return "low"
