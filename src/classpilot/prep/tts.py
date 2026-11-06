"""TTS cleanup: Markdown, backticks, and code symbols spelled out in words or removed.

One rule table serves two uses (STAGES Stage 6):
- `tts_issues(text)`: the script lint. A generated script fails its structure check
  when any rule matches, and the rule names go back to the generator as feedback.
- `clean_for_tts(text)`: the fallback text. It applies every rule, then turns line
  breaks into sentence breaks, so raw slide text can be read aloud.

The rules are deliberately small and predictable; they do not try to read code the way a
person would ("order_id" becomes "order id", "{{ source('shop') }}" becomes
"source shop").
"""

import re
from collections.abc import Callable

Replacement = str | Callable[[re.Match], str]

FILE_EXTENSIONS = ("sql", "py", "yml", "yaml", "csv", "json", "md", "txt")


BULLETS = "-*+•○◦▪■►▶➢"


def _spell(letters: str) -> str:
    return " ".join(letters.lower())


# (name, pattern, replacement), applied in this order. Markdown first, then code symbols.
RULES: list[tuple[str, re.Pattern, Replacement]] = [
    ("code fence", re.compile(r"```[a-zA-Z]*"), " "),
    ("URL", re.compile(r"https?://\S+|\bwww\.\S+"), ""),
    ("backtick", re.compile(r"`"), ""),
    ("Markdown image", re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    ("Markdown link", re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    ("Markdown heading", re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE), ""),
    # Slide text has bullets on their own line ("•\nIntroduction") or before the item.
    ("Markdown bullet", re.compile(rf"^[ \t]*[{BULLETS}][ \t]*$", re.MULTILINE), ""),
    ("Markdown bullet", re.compile(rf"^[ \t]*[{BULLETS}][ \t]+", re.MULTILINE), ""),
    ("Markdown emphasis", re.compile(r"(\*\*|__)(\S(?:.*?\S)?)\1"), r"\2"),
    ("Markdown emphasis", re.compile(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])"), r"\1"),
    ("template braces", re.compile(r"\{\{|\}\}|\{%|%\}"), " "),
    (
        "file extension",
        re.compile(rf"(?<=\w)\.({'|'.join(FILE_EXTENSIONS)})\b", re.IGNORECASE),
        lambda m: f" dot {_spell(m.group(1))}",
    ),
    ("underscore", re.compile(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])"), " "),
    ("comparison", re.compile(r">="), " greater than or equal to "),
    ("comparison", re.compile(r"<="), " less than or equal to "),
    ("comparison", re.compile(r"!=|<>"), " not equal to "),
    ("arrow", re.compile(r"->|=>|→"), " to "),
    ("equals sign", re.compile(r"==?"), " equals "),
    ("comparison", re.compile(r">"), " greater than "),
    ("comparison", re.compile(r"<"), " less than "),
    ("percent sign", re.compile(r"(?<=\d)\s?%"), " percent"),
    ("ampersand", re.compile(r"&"), " and "),
    ("plus sign", re.compile(r"\+"), " plus "),
    ("star", re.compile(r"(?<=\s)\*(?=\s|$)|^\*(?=\s)", re.MULTILINE), " star "),
    ("slash", re.compile(r"(?<=\w)/(?=\w)"), " slash "),
    # Paired quotes only, so apostrophes ("it's", "students' answers") stay.
    ("quote", re.compile(r"(?<![A-Za-z])'([^'\s][^'\n]*?)'(?![A-Za-z])"), r"\1"),
    ("bracket", re.compile(r"[()\[\]{}]"), " "),
    ("symbol", re.compile(r"[|\\^~$@#*]"), " "),
    ("semicolon", re.compile(r";"), ","),
]

SENTENCE_END = re.compile(r"[.!?:,]$")


def _line_key(line: str) -> str:
    return " ".join(line.split()).lower()


def template_lines(texts: list[str], min_share: float = 0.5, min_count: int = 3) -> set[str]:
    """Lines that appear on at least `min_share` of the pages (and on `min_count`): the
    deck's footer or header, such as the course name and the term."""
    counts: dict[str, int] = {}
    for text in texts:
        for key in {_line_key(line) for line in text.splitlines() if line.strip()}:
            counts[key] = counts.get(key, 0) + 1
    needed = max(min_count, min_share * len(texts))
    return {key for key, n in counts.items() if n >= needed}


def strip_lines(text: str, drop: set[str]) -> str:
    """Remove template lines (`template_lines`) and lines that hold only a page number."""
    kept = [
        line
        for line in text.splitlines()
        if _line_key(line) not in drop and not line.strip().isdigit()
    ]
    return "\n".join(kept)


def _apply_rules(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for name, pattern, replacement in RULES:
        text, count = pattern.subn(replacement, text)
        if count and name not in found:
            found.append(name)
    return text, found


def strip_emphasis(text: str) -> str:
    """Generated text without Markdown bold or italics (book titles were often in *...*,
    Stage 9). Removing the markers changes no words, so code does it instead of a retry."""
    for name, pattern, replacement in RULES:
        if name == "Markdown emphasis":
            text = pattern.sub(replacement, text)
    return text


def tts_issues(text: str) -> list[str]:
    """Names of the rules that change the text: what TTS would read wrongly. Empty: clean."""
    return _apply_rules(text)[1]


def clean_for_tts(text: str) -> str:
    """Text that TTS can read aloud: rules applied, one line per sentence joined."""
    text, _ = _apply_rules(text)
    sentences = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            continue
        sentences.append(line if SENTENCE_END.search(line) else f"{line}.")
    joined = " ".join(sentences)
    joined = re.sub(r"\s+([.,!?:])", r"\1", joined)
    joined = re.sub(r"\.{2,}", ".", joined).strip()
    return re.sub(r"[,:]$", ".", joined)
