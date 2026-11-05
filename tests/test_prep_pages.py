"""Image-page flag and alignment check (prep/pages.py), on hand-made geometry and text."""

import pytest

from classpilot.prep.pages import (
    AlignmentError,
    PageGeometry,
    PageSignals,
    check_alignment,
    classify,
    page_signals,
    shared_keys,
    union_area,
    words,
)
from classpilot.settings import ImagePageSettings, ParseSettings

FOOTER = (0.0, 0.0, 1.0, 0.05)
LOGO = (0.9, 0.9, 1.0, 1.0)


def signals(text=200, image=0.0, drawing=0.0):
    return PageSignals(
        text_chars=text, image_count=0, image_area=image, drawing_area=drawing, shared_objects=0
    )


def test_union_area_counts_overlap_once():
    assert union_area([]) == 0
    assert union_area([(0, 0, 0.5, 0.5)]) == pytest.approx(0.25)
    assert union_area([(0, 0, 0.5, 0.5), (0.25, 0.25, 0.75, 0.75)]) == pytest.approx(0.4375)


def test_shared_objects_are_removed_before_measuring():
    pages = [PageGeometry(100, images=[LOGO], drawings=[FOOTER]) for _ in range(4)]
    pages[2].images.append((0.1, 0.1, 0.7, 0.7))
    shared = shared_keys(pages)
    assert len(shared) == 2
    plain = page_signals(pages[0], shared)
    assert (plain.image_area, plain.drawing_area, plain.shared_objects) == (0, 0, 2)
    picture = page_signals(pages[2], shared)
    assert picture.image_area == pytest.approx(0.36)
    assert picture.image_count == 1


def test_objects_on_few_pages_or_short_files_are_kept():
    pages = [PageGeometry(100, drawings=[FOOTER]) for _ in range(2)]
    assert shared_keys(pages) == set()  # fewer than 3 pages
    pages = [PageGeometry(100, drawings=[FOOTER] if i < 3 else []) for i in range(5)]
    assert shared_keys(pages) == set()  # on 3 of 5 pages, below 0.8


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (signals(image=0.10), ("image", "image_area")),
        (signals(drawing=0.30), ("image", "drawing_area")),
        (signals(image=0.02), ("unsure", "some_image_area")),
        (signals(drawing=0.10), ("unsure", "some_drawing_area")),
        (signals(text=5), ("unsure", "little_text")),
        (signals(image=0.019, drawing=0.099), ("text", "text_only")),
    ],
)
def test_classify(page, expected):
    assert classify(page, ImagePageSettings()) == expected


def test_words_fold_ligatures_and_case():
    assert words("The ﬁle is Final, a b") == {"the", "file", "is", "final"}


def test_alignment_passes_and_skips_short_slides():
    report = check_alignment(
        ["Bronze keeps raw data", "Hi", "Gold layer"],
        ["Bronze keeps raw data\nfooter", "", "gold LAYER aggregates"],
        ParseSettings(),
    )
    assert report.ok
    assert [p.overlap for p in report.pages] == [1.0, None, None]


def test_alignment_count_mismatch_is_an_error():
    with pytest.raises(AlignmentError, match="2 slides but the PDF has 3 pages") as err:
        check_alignment(["a b c", "d e f"], ["a b c", "d e f", "g h i"], ParseSettings())
    assert not err.value.report.ok


def test_alignment_text_mismatch_names_the_pages():
    slides = ["bronze keeps raw data", "silver cleans records", "gold serves aggregates"]
    pdf = ["bronze keeps raw data", "gold serves aggregates", "silver cleans records"]
    with pytest.raises(AlignmentError, match=r"pages \[2, 3\]") as err:
        check_alignment(slides, pdf, ParseSettings())
    assert err.value.report.mismatched == [2, 3]
