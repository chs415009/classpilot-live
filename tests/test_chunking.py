"""Chunking (prep/chunking.py): stable ids, required fields, empty pages, splitting."""

from classpilot.prep.chunking import chunk_file, clean_text, split_text
from classpilot.prep.records import ParsedFile, ParsedPage
from classpilot.prep.vision import VisionDescription


def page(index, text="", notes=None, vision=None):
    return ParsedPage(
        page_index=index,
        page_id=f"deck1-p{index:02d}",
        text_layer=text,
        notes=notes,
        llm_description=vision,
        image_flag="image" if vision else "text",
        parse_method="local_text+vision" if vision else "local_text",
    )


def parsed(*pages):
    return ParsedFile(
        file_id="f" * 64,
        source_id="deck1",
        kind="slides",
        format="pptx",
        original_name="deck1.pptx",
        stage_path="ffff/original.pptx",
        page_count=len(pages),
        pages=list(pages),
    )


VISION = VisionDescription(
    slide_text="Bronze Silver Gold",
    diagram_description="Three boxes connected by arrows from left to right.",
    key_concepts=["data flow", " "],
)
DECK = parsed(
    page(1, "Medallion Architecture", notes="Welcome."),
    page(2, ""),  # empty
    page(3, "Data Flow", vision=VISION),
    page(4, "", vision=VISION),  # image only
)


def test_same_input_same_ids():
    first = [c.chunk_id for c in chunk_file(DECK, 1500)]
    assert first == [c.chunk_id for c in chunk_file(DECK.model_copy(deep=True), 1500)]
    assert first == ["deck1-p01-c1", "deck1-p03-c1", "deck1-p03-c2", "deck1-p04-c1"]


def test_every_chunk_has_source_page_and_origin_and_starts_with_its_slide_id():
    for chunk in chunk_file(DECK, 1500):
        assert chunk.source_id == "deck1" and chunk.page_index >= 1
        assert chunk.origin in ("text_layer", "llm_description")
        assert chunk.chunk_id.startswith(chunk.page_id + "-c")
        assert chunk.page_id == f"deck1-p{chunk.page_index:02d}"


def test_empty_pages_give_no_chunks():
    assert not [c for c in chunk_file(DECK, 1500) if c.page_index == 2]
    assert chunk_file(parsed(page(1, "  \n\n "), page(2, "![img-0.jpeg](img-0.jpeg)")), 1500) == []


def test_notes_join_the_text_and_vision_is_a_separate_chunk():
    chunks = {c.chunk_id: c for c in chunk_file(DECK, 1500)}
    assert chunks["deck1-p01-c1"].text == "Medallion Architecture\n\nSpeaker notes: Welcome."
    vision = chunks["deck1-p03-c2"]
    assert vision.origin == "llm_description"
    assert vision.text == (
        "Three boxes connected by arrows from left to right.\n\nKey concepts: data flow"
    )
    # A page without its own text gets the vision slide_text first.
    assert chunks["deck1-p04-c1"].text.startswith("Bronze Silver Gold\n\n")


def test_long_text_is_split_within_the_limit_and_keeps_every_word():
    words = [f"word{i}" for i in range(600)]
    text = "\n\n".join(" ".join(words[i : i + 50]) for i in range(0, 600, 50))
    pieces = split_text(text, 300)
    assert all(len(p) <= 300 for p in pieces)
    assert " ".join(pieces).split() == words
    one_line = " ".join(words)
    assert all(len(p) <= 300 for p in split_text(one_line, 300))


def test_long_page_chunks_are_numbered_in_order():
    long = "\n\n".join(f"Paragraph {i} " + "x" * 90 for i in range(30))
    chunks = chunk_file(parsed(page(1, long)), 500)
    assert [c.chunk_id for c in chunks] == [f"deck1-p01-c{i}" for i in range(1, len(chunks) + 1)]
    assert len(chunks) > 1 and all(len(c.text) <= 500 for c in chunks)


def test_clean_text_removes_image_markers_and_extra_blank_lines():
    assert clean_text("# Title\n\n\n\n![img-0.jpeg](img-0.jpeg)\ntext  \n") == "# Title\n\ntext"
