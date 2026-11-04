"""Small text helpers for word-overlap similarity (no ML dependencies).

Used by the protected-question rule and by the mock adapters. Cortex Search
replaces the retrieval part in cortex mode; the protected check stays a rule.
"""

import re

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "do",
    "does",
    "did",
    "we",
    "you",
    "i",
    "me",
    "my",
    "our",
    "your",
    "they",
    "them",
    "can",
    "could",
    "should",
    "would",
    "will",
    "what",
    "why",
    "how",
    "which",
    "when",
    "where",
    "who",
    "so",
    "not",
    "no",
    "into",
    "than",
    "then",
    "there",
    "here",
    "about",
    "also",
    "any",
    "all",
    "some",
    "such",
    "just",
    "has",
    "have",
    "had",
    "use",
    "using",
    "used",
    "get",
    "please",
    "tell",
    "explain",
    "one",
    "two",
    "three",
    "s",
}


def normalize(word: str) -> str:
    # Very light stemming: "errors" -> "error", "layers" -> "layer".
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return [normalize(w) for w in words if w not in STOPWORDS]


def jaccard(a: str, b: str) -> float:
    set_a, set_b = set(content_words(a)), set(content_words(b))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def coverage(query: str, text: str) -> float:
    """Share of the query's content words that appear in text."""
    query_words = set(content_words(query))
    if not query_words:
        return 0.0
    return len(query_words & set(content_words(text))) / len(query_words)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
