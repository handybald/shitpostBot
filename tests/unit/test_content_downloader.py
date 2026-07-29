from src.services.content_downloader import ContentDownloader


def test_best_portrait_file_prefers_1080p():
    files = [
        {"width": 1920, "height": 1080},  # landscape, should be skipped
        {"width": 480, "height": 854},  # portrait but low-res
        {"width": 1080, "height": 1920},  # portrait 1080p - should win
    ]
    best = ContentDownloader._best_portrait_file(files)
    assert best == {"width": 1080, "height": 1920}


def test_best_portrait_file_falls_back_to_720p():
    files = [
        {"width": 480, "height": 854},
        {"width": 720, "height": 1280},
    ]
    best = ContentDownloader._best_portrait_file(files)
    assert best == {"width": 720, "height": 1280}


def test_best_portrait_file_falls_back_to_first_when_no_portrait():
    files = [{"width": 1920, "height": 1080}]
    best = ContentDownloader._best_portrait_file(files)
    assert best == {"width": 1920, "height": 1080}


def test_best_portrait_file_empty_list():
    assert ContentDownloader._best_portrait_file([]) is None
