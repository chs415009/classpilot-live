"""Offline: page count, text layer, and image-page signals for the slide PDF (PyMuPDF),
plus PNG rendering of every page to outputs/probes/slides/ (gitignored).

History only: needs `pip install pymupdf` (AGPL-3.0, removed from the project
dependencies in Stage 4) and the Stage 1 materials file `materials/L1_slide.pdf`."""

import json

import pymupdf
from common import OUT_DIR, save

from classpilot.settings import PROJECT_ROOT

PDF = PROJECT_ROOT / "materials" / "L1_slide.pdf"
PNG_DIR = OUT_DIR / "slides"
PNG_DIR.mkdir(parents=True, exist_ok=True)

doc = pymupdf.open(PDF)
rows = []
for page in doc:
    text = page.get_text().strip()
    images = page.get_images(full=True)
    area = page.rect.width * page.rect.height
    image_area = sum(r.width * r.height for img in images for r in page.get_image_rects(img[0]))
    drawings = page.get_drawings()
    drawing_area = sum(d["rect"].width * d["rect"].height for d in drawings)
    pix = page.get_pixmap(dpi=144)
    png = PNG_DIR / f"p{page.number:02d}.png"
    pix.save(png)
    rows.append(
        {
            "index": page.number,
            "text_chars": len(text),
            "text_head": text[:60],
            "images": len(images),
            "image_area_frac": round(image_area / area, 3),
            "drawings": len(drawings),
            "drawing_area_frac": round(min(drawing_area / area, 9.99), 3),
            "png": png.name,
            "png_kb": round(png.stat().st_size / 1024),
            "px": [pix.width, pix.height],
        }
    )
print("page_count:", doc.page_count)
print(save("pages", {"page_count": doc.page_count, "pages": rows}))
for r in rows:
    print(
        json.dumps(
            {
                k: r[k]
                for k in (
                    "index",
                    "text_chars",
                    "images",
                    "image_area_frac",
                    "drawings",
                    "drawing_area_frac",
                    "png_kb",
                    "px",
                )
            }
        ),
        "|",
        repr(r["text_head"][:40]),
    )
