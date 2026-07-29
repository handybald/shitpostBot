import shutil
import subprocess

import pytest

from src.processors.video_generator import VideoGenerator, VideoGenerationError
from src.services.tts_provider import VoiceoverResult, WordTiming


def test_allocate_segment_duration_splits_evenly():
    assert VideoGenerator._allocate_segment_duration(2, 10.0) == 5.0


def test_allocate_segment_duration_respects_minimum():
    # 5 clips over 3 seconds would be 0.6s/clip, below the 2s floor
    assert VideoGenerator._allocate_segment_duration(5, 3.0) == 2.0


def test_max_usable_clips_caps_by_duration():
    assert VideoGenerator._max_usable_clips(1.0) == 1  # never zero
    assert VideoGenerator._max_usable_clips(10.0) == 5  # 10s / 2s min segment


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
@pytest.mark.skipif(shutil.which("npx") is None, reason="requires node/npx")
def test_generate_end_to_end_with_synthetic_assets(tmp_path):
    """
    Exercises the real Remotion render subprocess (not mocked) with
    synthetic ffmpeg-generated clips/audio, to catch integration breakage
    between the Python staging logic and the renderer's expected props
    shape - the kind of bug unit tests with mocks would miss entirely.
    """
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    voiceover_audio = tmp_path / "voiceover.m4a"

    for path, filt in [
        (clip1, "testsrc2=size=1080x1920:rate=30:duration=3"),
        (clip2, "mandelbrot=size=1080x1920:rate=30"),
    ]:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", filt]
        if "mandelbrot" in filt:
            cmd += ["-t", "3"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path.as_posix()]
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
         "-c:a", "aac", voiceover_audio.as_posix()],
        capture_output=True, check=True, timeout=30,
    )

    voiceover = VoiceoverResult(
        audio_path=voiceover_audio,
        words=[
            WordTiming(text="Testing", start=0.0, end=0.5),
            WordTiming(text="the", start=0.5, end=0.7),
            WordTiming(text="pipeline.", start=0.7, end=1.3),
        ],
        duration=1.3,
    )

    generator = VideoGenerator(output_dir=tmp_path / "output")
    result = generator.generate(
        background_clips=[clip1, clip2],
        voiceover=voiceover,
        caption="test caption",
        music_path=None,
    )

    assert result["output_path"].exists()
    assert result["duration"] > 0
    assert result["file_size"] > 0
