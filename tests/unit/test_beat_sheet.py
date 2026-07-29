from src.services.gemini_content_generator import BeatSheet, GeminiContentGenerator


def test_beat_sheet_full_voiceover_text_joins_nonempty_parts():
    beat_sheet = BeatSheet(
        hook="Nobody is coming to save you.",
        body="",
        payoff="Get up and build it yourself.",
        caption="cap",
        theme="sigma_mindset",
        music_mood="dark_atmospheric",
        video_search_terms=["urban night"],
        music_search_terms=["phonk"],
        hashtags=["#sigma"],
    )

    assert beat_sheet.full_voiceover_text == "Nobody is coming to save you. Get up and build it yourself."


def test_fallback_beat_sheet_has_nonempty_hook_and_payoff():
    generator = GeminiContentGenerator(api_key=None)  # forces fallback path
    beat_sheet = generator._fallback_beat_sheet(theme="monk_mode")

    assert beat_sheet.theme == "monk_mode"
    assert beat_sheet.hook
    assert beat_sheet.payoff
    assert len(beat_sheet.full_voiceover_text) > 0
    assert len(beat_sheet.hashtags) <= 3


def test_parse_beat_sheet_extracts_markdown_wrapped_json():
    generator = GeminiContentGenerator(api_key=None)
    raw = '''```json
{
    "hook": "You are wasting your mornings.",
    "body": "Every scroll session is an hour you will never get back.",
    "payoff": "Protect your first hour like your life depends on it.",
    "caption": "Protect your mornings #discipline #focus",
    "video_search_terms": ["sunrise city"],
    "music_search_terms": ["ambient phonk"],
    "hashtags": ["#discipline", "#focus", "#extra", "#toomany"]
}
```'''
    music_vibe = generator.suggest_phonk_music_vibe("monk_mode")
    beat_sheet = generator._parse_beat_sheet(raw, "monk_mode", music_vibe, "nature_solitude")

    assert beat_sheet.hook == "You are wasting your mornings."
    assert beat_sheet.payoff.startswith("Protect your first hour")
    assert len(beat_sheet.hashtags) == 3  # truncated to max 3
