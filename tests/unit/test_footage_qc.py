from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FootageQCLog, Video
from src.processors.footage_qc import FootageQC, QCThresholds


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def candidate(tmp_path):
    path = tmp_path / "candidate.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def make_qc(**threshold_overrides) -> FootageQC:
    thresholds = QCThresholds(**threshold_overrides)
    return FootageQC(thresholds=thresholds, gemini_client=None)


def test_technical_reject_is_always_hard_even_in_shadow_mode(session, candidate, monkeypatch):
    qc = make_qc(shadow_mode=True)
    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": False, "reason": "resolution_too_low", "info": {}})

    result = qc.evaluate(candidate, theme="sigma_mindset", vibe_description="urban night", session=session)

    assert result.accepted is False
    assert result.reason == "resolution_too_low"
    # hard rejects delete the file even in shadow mode
    assert not candidate.exists()


def test_watermark_is_hard_reject_even_in_shadow_mode(session, candidate, monkeypatch):
    qc = make_qc(shadow_mode=True)
    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": True, "reason": None, "info": {}})
    monkeypatch.setattr(qc, "extract_sample_frames", lambda p, count=4: [])
    monkeypatch.setattr(qc, "compute_motion_score", lambda frames: 0.5)
    monkeypatch.setattr(qc, "compute_phash", lambda f: None)
    monkeypatch.setattr(
        qc, "score_with_vision",
        lambda frames, vibe: {
            "relevance": 9.0, "aesthetic": 9.0, "crop_fit": 9.0,
            "watermark_detected": True, "nsfw_risk": 0.0, "vision_scored": True,
        },
    )

    result = qc.evaluate(candidate, theme="sigma_mindset", vibe_description="urban night", session=session)

    assert result.accepted is False
    assert result.reason == "watermark_detected"


def test_shadow_mode_relaxes_soft_composite_rejection(session, candidate, monkeypatch):
    """A clip that would fail the composite-score bar still gets accepted
    while shadow_mode is on, but the real would-be decision is still logged."""
    qc = make_qc(shadow_mode=True, composite_accept_threshold=0.9)
    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": True, "reason": None, "info": {}})
    monkeypatch.setattr(qc, "extract_sample_frames", lambda p, count=4: [])
    monkeypatch.setattr(qc, "compute_motion_score", lambda frames: 0.5)
    monkeypatch.setattr(qc, "compute_phash", lambda f: None)
    monkeypatch.setattr(
        qc, "score_with_vision",
        lambda frames, vibe: {
            "relevance": 6.0, "aesthetic": 6.0, "crop_fit": 6.0,
            "watermark_detected": False, "nsfw_risk": 0.0, "vision_scored": True,
        },
    )

    result = qc.evaluate(candidate, theme="sigma_mindset", vibe_description="urban night", session=session)

    assert result.accepted is True  # shadow mode let it through
    assert result.shadow_mode is True
    assert candidate.exists()  # not deleted, since effectively accepted

    log = session.query(FootageQCLog).one()
    assert log.decision == "rejected"  # the real, unenforced decision is preserved in the audit log


def test_vision_scoring_fails_open_on_client_error(session, candidate, monkeypatch):
    """If the Gemini call blows up, the candidate should fall back to
    neutral scores instead of being rejected for an unrelated API error."""
    qc = make_qc()

    class ExplodingClient:
        class models:
            @staticmethod
            def generate_content(model, contents):
                raise RuntimeError("network blip")

    qc._gemini_client = ExplodingClient()
    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": True, "reason": None, "info": {}})
    monkeypatch.setattr(qc, "extract_sample_frames", lambda p, count=4: [Path("/tmp/does-not-matter.jpg")])
    monkeypatch.setattr(qc, "compute_motion_score", lambda frames: 0.5)
    monkeypatch.setattr(qc, "compute_phash", lambda f: None)
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"fake")

    scores = qc.score_with_vision([Path("/tmp/does-not-matter.jpg")], "urban night")

    assert scores["vision_scored"] is False
    assert scores["watermark_detected"] is False
    assert scores["relevance"] >= 6.0  # neutral, not punitive


def test_duplicate_detection_rejects_hard_regardless_of_shadow_mode(session, candidate, monkeypatch):
    qc = make_qc(shadow_mode=True)
    session.add(Video(filename="existing.mp4", theme="sigma_mindset", qc_status="accepted", phash="0" * 16))
    session.commit()

    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": True, "reason": None, "info": {}})
    monkeypatch.setattr(qc, "extract_sample_frames", lambda p, count=4: [Path("/tmp/f.jpg")])
    monkeypatch.setattr(qc, "compute_motion_score", lambda frames: 0.5)
    monkeypatch.setattr(qc, "compute_phash", lambda f: "0" * 16)  # identical hash -> duplicate
    monkeypatch.setattr(qc, "is_duplicate", lambda phash, theme, session: True)

    result = qc.evaluate(candidate, theme="sigma_mindset", vibe_description="urban night", session=session)

    assert result.accepted is False
    assert result.reason == "duplicate_of_existing_clip"


def test_accepted_candidate_keeps_file_on_disk(session, candidate, monkeypatch):
    qc = make_qc(shadow_mode=False, composite_accept_threshold=0.5)
    monkeypatch.setattr(qc, "check_technical", lambda p: {"ok": True, "reason": None, "info": {}})
    monkeypatch.setattr(qc, "extract_sample_frames", lambda p, count=4: [])
    monkeypatch.setattr(qc, "compute_motion_score", lambda frames: 0.5)
    monkeypatch.setattr(qc, "compute_phash", lambda f: None)
    monkeypatch.setattr(
        qc, "score_with_vision",
        lambda frames, vibe: {
            "relevance": 9.0, "aesthetic": 9.0, "crop_fit": 9.0,
            "watermark_detected": False, "nsfw_risk": 0.0, "vision_scored": True,
        },
    )

    result = qc.evaluate(candidate, theme="sigma_mindset", vibe_description="urban night", session=session)

    assert result.accepted is True
    assert candidate.exists()


def test_pool_health_reports_below_floor(session):
    qc = make_qc(pool_floor_per_theme=3)
    session.add(Video(filename="a.mp4", theme="sigma_mindset", qc_status="accepted"))
    session.commit()

    health = qc.check_pool_health("sigma_mindset", session)

    assert health.accepted_count == 1
    assert health.healthy is False
