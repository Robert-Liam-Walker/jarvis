from jarvis import extract

CATALOG = {
    "notepad": {"launch": "notepad", "exe": "notepad.exe", "title": "Notepad"},
    "chrome": {"launch": "chrome", "exe": "chrome.exe", "title": "Google Chrome"},
    "vscode": {"launch": "code", "exe": "Code.exe", "title": "Visual Studio Code"},
}


def test_open_app_splits_app_and_remainder():
    assert extract.split_open_app("open notepad and write hello") == ("notepad", "write hello")
    assert extract.split_open_app("Open up Chrome, then go to github") == ("chrome", "go to github")
    assert extract.split_open_app("launch notepad") == ("notepad", "")
    assert extract.split_open_app("please start the calculator app") == ("calculator", "")


def test_non_open_utterance_passes_through():
    assert extract.split_open_app("type hello world") == (None, "type hello world")
    assert extract.split_open_app("save the file") == (None, "save the file")


def test_text_candidates_prefer_quotes_then_verb_tail():
    assert extract.text_candidates('write "hello there" in notepad')[0] == "hello there"
    assert extract.text_candidates("write hello")[0] == "hello"
    assert extract.text_candidates("type hello world into the search box")[:2] == [
        "hello world into the search box",
        "hello world",
    ]
    assert extract.text_candidates("save the file") == []


def test_switch_target():
    assert extract.switch_target("switch back to notepad") == "notepad"
    assert extract.switch_target("go to the chrome window") == "chrome window"
    assert extract.switch_target("open chrome") is None


def test_app_candidates_exact_then_loose():
    assert extract.app_candidates("notepad", CATALOG) == ["notepad"]
    assert extract.app_candidates("google chrome", CATALOG) == ["chrome"]
    assert extract.app_candidates("code", CATALOG) == ["vscode"]
    assert extract.app_candidates("photoshop", CATALOG) == []
