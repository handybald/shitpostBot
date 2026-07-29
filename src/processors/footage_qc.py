"""
Footage QC decision tree.

Every downloaded stock-video candidate goes through this before it's usable
in a reel. Design goals (from real failure modes of naive quality gates):

- Hard rejects are reserved for things that are genuinely non-negotiable
  (corrupt file, watermark, NSFW/brand-safety risk). Everything else
  (relevance, aesthetics, crop fit, motion) is a *soft* weighted score used
  to rank candidates, not a binary pass/fail — so an unusually strict batch
  doesn't zero out the whole pool.
- `shadow_mode` runs the full pipeline and logs what it *would* decide
  without actually rejecting anything, so thresholds can be calibrated
  against real score distributions before being enforced.
- The vision-scoring step (Gemini) fails open: if the API call itself
  errors, the candidate falls back to technical-only checks instead of
  being rejected for a reason unrelated to its actual quality.
- Every candidate, accepted or rejected, is logged to FootageQCLog with its
  scores and reason, so rejection patterns are auditable instead of a black
  box.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.database.models import FootageQCLog, Video
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class QCThresholds:
    min_short_side_px: int = 1080
    min_duration_seconds: float = 3.0
    min_fps: float = 24.0

    min_relevance_score: float = 6.0  # 0-10, soft
    min_aesthetic_score: float = 5.0  # 0-10, soft
    min_crop_fit_score: float = 5.0  # 0-10, soft
    nsfw_risk_reject_at: float = 5.0  # 0-10, hard reject at/above this
    min_static_motion_score: float = 0.02  # below this = too static, soft

    dedup_max_hamming_distance: int = 6  # phash distance below which we treat as duplicate

    # Composite score weights (relevance/aesthetic/crop-fit/motion), soft factors only
    weight_relevance: float = 0.4
    weight_aesthetic: float = 0.3
    weight_crop_fit: float = 0.2
    weight_motion: float = 0.1

    composite_accept_threshold: float = 0.55  # on the weighted 0-1 composite

    pool_floor_per_theme: int = 5  # alert if accepted pool for a theme drops below this

    shadow_mode: bool = False  # log-only, never reject, for threshold calibration


@dataclass
class QCResult:
    accepted: bool
    reason: str
    composite_score: Optional[float]
    scores: Dict[str, Any] = field(default_factory=dict)
    phash: Optional[str] = None
    shadow_mode: bool = False


@dataclass
class PoolHealth:
    theme: str
    accepted_count: int
    floor: int

    @property
    def healthy(self) -> bool:
        return self.accepted_count >= self.floor


class FootageQC:
    """Runs candidate footage through the QC decision tree."""

    def __init__(
        self,
        thresholds: Optional[QCThresholds] = None,
        gemini_client: Any = None,
        gemini_model: str = "gemini-2.5-flash",
    ):
        self.thresholds = thresholds or QCThresholds()
        self._gemini_client = gemini_client
        self._gemini_model = gemini_model

    @classmethod
    def from_config(cls) -> "FootageQC":
        from src.utils.config_loader import get_config_instance

        config = get_config_instance()
        qc_config = config.get("footage_qc", {})
        thresholds = QCThresholds(
            min_short_side_px=int(qc_config.get("min_short_side_px", 1080)),
            min_duration_seconds=float(qc_config.get("min_duration_seconds", 3.0)),
            min_fps=float(qc_config.get("min_fps", 24.0)),
            min_relevance_score=float(qc_config.get("min_relevance_score", 6.0)),
            min_aesthetic_score=float(qc_config.get("min_aesthetic_score", 5.0)),
            min_crop_fit_score=float(qc_config.get("min_crop_fit_score", 5.0)),
            nsfw_risk_reject_at=float(qc_config.get("nsfw_risk_reject_at", 5.0)),
            min_static_motion_score=float(qc_config.get("min_static_motion_score", 0.02)),
            dedup_max_hamming_distance=int(qc_config.get("dedup_max_hamming_distance", 6)),
            composite_accept_threshold=float(qc_config.get("composite_accept_threshold", 0.55)),
            pool_floor_per_theme=int(qc_config.get("pool_floor_per_theme", 5)),
            shadow_mode=bool(qc_config.get("shadow_mode", False)),
        )

        gemini_client = None
        gemini_model = qc_config.get("vision_model", "gemini-2.5-flash")
        try:
            import os

            api_key = os.getenv("GEMINI_API_KEY")
            if api_key and api_key != "your_gemini_api_key_here":
                from google import genai

                gemini_client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.warning(f"Gemini vision scoring unavailable: {e}")

        return cls(thresholds=thresholds, gemini_client=gemini_client, gemini_model=gemini_model)

    # ------------------------------------------------------------------
    # Stage 1: hard technical gate
    # ------------------------------------------------------------------
    def check_technical(self, video_path: Path) -> Dict[str, Any]:
        """Returns {"ok": bool, "reason": str|None, "info": {...}}."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate,duration",
                "-of", "json", video_path.as_posix(),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or not result.stdout.strip():
                return {"ok": False, "reason": "corrupt_or_unreadable", "info": {}}

            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if not streams:
                return {"ok": False, "reason": "no_video_stream", "info": {}}

            stream = streams[0]
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            duration = float(stream.get("duration", 0) or 0)

            fps = 0.0
            frame_rate_raw = stream.get("avg_frame_rate", "0/0")
            if "/" in frame_rate_raw:
                num, denom = frame_rate_raw.split("/")
                if float(denom) > 0:
                    fps = float(num) / float(denom)

            info = {"width": width, "height": height, "duration": duration, "fps": fps}

            short_side = min(width, height)
            if short_side < self.thresholds.min_short_side_px:
                return {"ok": False, "reason": "resolution_too_low", "info": info}
            if duration < self.thresholds.min_duration_seconds:
                return {"ok": False, "reason": "duration_too_short", "info": info}
            if fps < self.thresholds.min_fps:
                return {"ok": False, "reason": "framerate_too_low", "info": info}

            return {"ok": True, "reason": None, "info": info}

        except Exception as e:
            logger.warning(f"Technical check failed for {video_path.name}: {e}")
            return {"ok": False, "reason": "technical_check_error", "info": {}}

    # ------------------------------------------------------------------
    # Stage 2: sample frames + motion + perceptual hash
    # ------------------------------------------------------------------
    def extract_sample_frames(self, video_path: Path, count: int = 4) -> List[Path]:
        """Extracts `count` evenly-spaced frames as JPEGs into a temp dir."""
        out_dir = Path(tempfile.mkdtemp(prefix="footage_qc_"))
        cmd = [
            "ffmpeg", "-y", "-i", video_path.as_posix(),
            "-vf", f"select='not(mod(n\\,{max(1, 30 // count)}))'",
            "-frames:v", str(count), "-vsync", "vfr", "-q:v", "3",
            (out_dir / "frame_%02d.jpg").as_posix(),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        except Exception as e:
            logger.warning(f"Frame extraction failed for {video_path.name}: {e}")
            return []
        return sorted(out_dir.glob("frame_*.jpg"))

    def compute_motion_score(self, frame_paths: List[Path]) -> float:
        """
        Cheap proxy for "is anything actually happening in this clip":
        mean normalized pixel difference between consecutive sampled frames.
        Not a substitute for real optical-flow stabilization analysis, but
        catches near-static/boring clips (and totally frozen/broken ones)
        without extra heavy dependencies.
        """
        if len(frame_paths) < 2:
            return 0.0
        try:
            from PIL import Image
            import numpy as np

            diffs = []
            prev = None
            for path in frame_paths:
                img = Image.open(path).convert("L").resize((160, 284))
                arr = np.asarray(img, dtype=np.float32) / 255.0
                if prev is not None:
                    diffs.append(float(np.mean(np.abs(arr - prev))))
                prev = arr
            return sum(diffs) / len(diffs) if diffs else 0.0
        except Exception as e:
            logger.warning(f"Motion score computation failed: {e}")
            return self.thresholds.min_static_motion_score  # neutral, don't punish on tooling error

    def compute_phash(self, frame_path: Path) -> Optional[str]:
        try:
            import imagehash
            from PIL import Image

            return str(imagehash.phash(Image.open(frame_path)))
        except Exception as e:
            logger.warning(f"Perceptual hash computation failed: {e}")
            return None

    def is_duplicate(self, phash: str, theme: str, session) -> bool:
        if not phash:
            return False
        try:
            import imagehash

            candidate = imagehash.hex_to_hash(phash)
            existing = (
                session.query(Video.phash)
                .filter(Video.theme == theme, Video.qc_status == "accepted", Video.phash.isnot(None))
                .all()
            )
            for (existing_hash,) in existing:
                if existing_hash and (candidate - imagehash.hex_to_hash(existing_hash)) <= self.thresholds.dedup_max_hamming_distance:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Dedup check failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Stage 3: vision relevance/aesthetic/safety scoring (fails open)
    # ------------------------------------------------------------------
    def score_with_vision(self, frame_paths: List[Path], vibe_description: str) -> Dict[str, Any]:
        """
        Returns a dict with relevance/aesthetic/crop_fit scores (0-10),
        watermark_detected (bool) and nsfw_risk (0-10). On any failure
        (no client configured, API error, bad JSON), fails open with
        neutral pass-through scores rather than rejecting the candidate.
        """
        neutral = {
            "relevance": 7.0, "aesthetic": 7.0, "crop_fit": 7.0,
            "watermark_detected": False, "nsfw_risk": 0.0,
            "vision_scored": False,
        }

        if not self._gemini_client or not frame_paths:
            return neutral

        try:
            from google.genai import types

            parts = []
            for frame_path in frame_paths:
                parts.append(
                    types.Part.from_bytes(data=frame_path.read_bytes(), mime_type="image/jpeg")
                )

            prompt = f"""You are grading stock video frames for a vertical (9:16) short-form
reel with this intended vibe: "{vibe_description}".

Rate the footage shown in these {len(frame_paths)} sampled frames on:
- relevance: 0-10, how well it matches the intended vibe/theme
- aesthetic: 0-10, cinematic/visual quality
- crop_fit: 0-10, would the main subject survive being center-cropped to a
  9:16 vertical frame without losing the point of the shot
- watermark_detected: true/false, any visible watermark, logo, or text overlay baked into the footage
- nsfw_risk: 0-10, how risky this would be to post on a mainstream platform (violence, nudity, gore)

Respond with ONLY this JSON, no markdown, no explanation:
{{"relevance": <0-10>, "aesthetic": <0-10>, "crop_fit": <0-10>, "watermark_detected": <true|false>, "nsfw_risk": <0-10>}}"""

            contents = parts + [prompt]
            response = self._gemini_client.models.generate_content(
                model=self._gemini_model, contents=contents
            )

            response_text = response.text.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)
            return {
                "relevance": float(data.get("relevance", 7.0)),
                "aesthetic": float(data.get("aesthetic", 7.0)),
                "crop_fit": float(data.get("crop_fit", 7.0)),
                "watermark_detected": bool(data.get("watermark_detected", False)),
                "nsfw_risk": float(data.get("nsfw_risk", 0.0)),
                "vision_scored": True,
            }
        except Exception as e:
            logger.warning(f"Vision scoring failed, failing open: {e}")
            return neutral

    # ------------------------------------------------------------------
    # Orchestrating entrypoint
    # ------------------------------------------------------------------
    def evaluate(
        self,
        candidate_path: Path,
        theme: str,
        vibe_description: str,
        session,
        source: str = "unknown",
    ) -> QCResult:
        t = self.thresholds

        technical = self.check_technical(candidate_path)
        if not technical["ok"]:
            # Unusable regardless of calibration state — always enforced.
            return self._finalize(
                candidate_path, theme, source, session,
                accepted=False, reason=technical["reason"], composite_score=None, scores=technical["info"],
                hard=True,
            )

        frames = self.extract_sample_frames(candidate_path)
        motion_score = self.compute_motion_score(frames)
        phash = self.compute_phash(frames[len(frames) // 2]) if frames else None

        if phash and self.is_duplicate(phash, theme, session):
            # Duplicates never help regardless of calibration state.
            return self._finalize(
                candidate_path, theme, source, session,
                accepted=False, reason="duplicate_of_existing_clip", composite_score=None,
                scores={"motion_score": motion_score}, phash=phash, hard=True,
            )

        vision = self.score_with_vision(frames, vibe_description)

        # Hard safety rejects — never soft-scored, never relaxed by shadow_mode
        # calibration logic (shadow_mode still logs but this decision matters
        # for legal/brand-safety reasons, not just quality tuning).
        hard_reject_reason = None
        if vision["watermark_detected"]:
            hard_reject_reason = "watermark_detected"
        elif vision["nsfw_risk"] >= t.nsfw_risk_reject_at:
            hard_reject_reason = "nsfw_risk_too_high"

        motion_score_normalized = min(1.0, motion_score / max(t.min_static_motion_score * 5, 1e-6))
        composite = (
            t.weight_relevance * (vision["relevance"] / 10.0)
            + t.weight_aesthetic * (vision["aesthetic"] / 10.0)
            + t.weight_crop_fit * (vision["crop_fit"] / 10.0)
            + t.weight_motion * motion_score_normalized
        )

        scores = {
            "relevance": vision["relevance"],
            "aesthetic": vision["aesthetic"],
            "crop_fit": vision["crop_fit"],
            "nsfw_risk": vision["nsfw_risk"],
            "watermark_detected": vision["watermark_detected"],
            "motion_score": motion_score,
            "vision_scored": vision["vision_scored"],
            "technical": technical["info"],
        }

        # Only these two are "soft" — judgment calls whose thresholds are what
        # shadow_mode exists to calibrate. Safety hard-rejects are handled
        # below with hard=True and are never relaxed by shadow_mode.
        if motion_score < t.min_static_motion_score:
            accepted, reason, hard = False, "too_static", False
        elif composite < t.composite_accept_threshold:
            accepted, reason, hard = False, "composite_score_below_threshold", False
        else:
            accepted, reason, hard = True, "accepted", False

        if hard_reject_reason:
            # Safety/legal reject always wins and is always enforced, even in
            # shadow mode — this isn't a threshold to calibrate.
            accepted, reason, hard = False, hard_reject_reason, True

        return self._finalize(
            candidate_path, theme, source, session,
            accepted=accepted, reason=reason, composite_score=composite, scores=scores, phash=phash,
            hard=hard,
        )

    def _finalize(
        self,
        candidate_path: Path,
        theme: str,
        source: str,
        session,
        accepted: bool,
        reason: str,
        composite_score: Optional[float],
        scores: Dict[str, Any],
        phash: Optional[str] = None,
        hard: bool = False,
    ) -> QCResult:
        shadow = self.thresholds.shadow_mode
        # In shadow mode, soft (quality-judgment) rejections are logged but
        # not enforced, so thresholds can be validated against live traffic
        # before they're allowed to starve the pipeline. Hard rejects
        # (technical validity, dedup, safety) are always enforced — shadow
        # mode is for calibrating opinions, not bypassing correctness/safety.
        effective_accepted = accepted if hard else (True if shadow else accepted)

        log_entry = FootageQCLog(
            filename=candidate_path.name,
            source=source,
            theme=theme,
            decision="accepted" if accepted else "rejected",
            reason=reason,
            composite_score=composite_score,
            scores=json.dumps(scores, default=str),
            shadow_mode=shadow,
        )
        session.add(log_entry)
        session.commit()

        shadow_note = f"shadow, real={'accept' if accepted else 'reject'}" if shadow else reason
        logger.info(
            f"QC {'accepted' if effective_accepted else 'rejected'} ({shadow_note}): "
            f"{candidate_path.name} theme={theme} composite={composite_score}"
        )

        if not effective_accepted:
            try:
                candidate_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Could not delete rejected candidate {candidate_path}: {e}")

        return QCResult(
            accepted=effective_accepted,
            reason=reason,
            composite_score=composite_score,
            scores=scores,
            phash=phash,
            shadow_mode=shadow,
        )

    # ------------------------------------------------------------------
    # Pool health / circuit breaker
    # ------------------------------------------------------------------
    def check_pool_health(self, theme: str, session) -> PoolHealth:
        count = (
            session.query(Video)
            .filter(Video.theme == theme, Video.qc_status == "accepted")
            .count()
        )
        return PoolHealth(theme=theme, accepted_count=count, floor=self.thresholds.pool_floor_per_theme)
