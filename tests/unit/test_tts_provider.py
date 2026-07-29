from src.services.tts_provider import characters_to_words


def test_characters_to_words_groups_on_whitespace():
    text = "Get up now"
    characters = list(text)
    start_times = [i * 0.1 for i in range(len(characters))]
    end_times = [(i + 1) * 0.1 for i in range(len(characters))]

    words = characters_to_words(characters, start_times, end_times)

    assert [w.text for w in words] == ["Get", "up", "now"]
    assert words[0].start == 0.0
    assert words[0].end == end_times[2]  # end of "t" in "Get"
    assert words[-1].end == end_times[-1]


def test_characters_to_words_handles_trailing_and_leading_spaces():
    characters = list(" hi there ")
    start_times = [i * 0.1 for i in range(len(characters))]
    end_times = [(i + 1) * 0.1 for i in range(len(characters))]

    words = characters_to_words(characters, start_times, end_times)

    assert [w.text for w in words] == ["hi", "there"]


def test_characters_to_words_empty_input():
    assert characters_to_words([], [], []) == []
