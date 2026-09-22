"""Code-side candidate extraction from an utterance. Jev chooses; code proposes."""

from __future__ import annotations

import re

_QUOTED = re.compile(r"[\"“”']([^\"“”']{1,400})[\"“”']")
_TYPE_VERBS = r"(?:write|type|enter|put|insert|say|saying|that says|reading|with the text|text)"
_AFTER_VERB = re.compile(rf"\b{_TYPE_VERBS}\b\s*[:,]?\s*(.+)$", re.IGNORECASE)
_TRAILING_LOCATION = re.compile(r"\s+(?:in|into|inside|on|to)\s+(?:the\s+)?[\w .-]{1,40}$", re.IGNORECASE)
_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:open(?:\s+up)?|launch|start|run)\s+(?:the\s+)?"
    r"([\w .+-]{1,40}?)(?:\s+app(?:lication)?)?(?=\s*,|\s+(?:and|then)\b|\s*$)",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"^\s*,?\s*(?:and then|and|then)?\s*", re.IGNORECASE)
_SWITCH = re.compile(r"^\s*(?:switch|go|change)\s+(?:back\s+)?to\s+(?:the\s+)?(.+?)\s*$", re.IGNORECASE)


def text_candidates(utterance: str) -> list[str]:
    """Strings the user may want typed, most literal first. Empty when the utterance carries none."""
    found: list[str] = []
    for match in _QUOTED.finditer(utterance):
        found.append(match.group(1).strip())
    match = _AFTER_VERB.search(utterance)
    if match:
        tail = match.group(1).strip().rstrip(".")
        stripped = _TRAILING_LOCATION.sub("", tail).strip()
        for candidate in (tail, stripped):
            if candidate and candidate not in found:
                found.append(candidate)
    return found


def split_open_app(utterance: str) -> tuple[str | None, str]:
    """('notepad', 'write hello') for 'open notepad and write hello'. (None, utterance) otherwise."""
    match = _OPEN.match(utterance)
    if not match:
        return None, utterance.strip()
    app = match.group(1).strip().lower()
    remainder = _SPLIT.sub("", utterance[match.end() :], count=1).strip(" ,.")
    return app, remainder


def switch_target(utterance: str) -> str | None:
    match = _SWITCH.match(utterance)
    return match.group(1).strip().lower() if match else None


def app_candidates(name: str, catalog: dict[str, dict[str, str]]) -> list[str]:
    """Catalog keys whose name, exe or title contains the spoken name, exact key first."""
    name = name.lower().strip()
    if not name:
        return []
    exact = [key for key in catalog if key == name]
    loose = [
        key
        for key, spec in catalog.items()
        if key not in exact
        and (name in key or key in name or name in spec.get("title", "").lower() or name in spec.get("exe", "").lower())
    ]
    return exact + loose
