from jarvis.voice.listener import strip_wake_phrase


def test_wake_phrase_is_stripped_only_at_the_start():
    assert strip_wake_phrase("Hey Jarvis! Open Notepad and write hello.") == "Open Notepad and write hello."
    assert strip_wake_phrase("jarvis, volume up") == "volume up"
    assert strip_wake_phrase("Okay Jarvis open chrome") == "open chrome"
    assert strip_wake_phrase("open chrome") == "open chrome"
    assert strip_wake_phrase("tell jarvis hello") == "tell jarvis hello"
