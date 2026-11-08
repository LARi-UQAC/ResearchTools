"""
Purpose: Build fictitious student-report PDFs for testing PDF scripts.
"""
from pathlib import Path
from typing import TypedDict
import fitz


class PageData(TypedDict, total=False):
    text: str
    image: bool
    vector_chart: bool
    logo: bool
    caption: str
    font_size: int


class ImageInfo(TypedDict):
    page: int
    width: int
    height: int


# Constantes pour les dimensions et couleurs (R0)
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 50
MARGIN_TOP = 50
FONT_SIZE_DEFAULT = 11
FONT_SIZE_CAPTION = 10
FONT_SIZE_LABEL = 10
LINE_SPACING = 10

IMAGE_WIDTH = 600
IMAGE_HEIGHT = 400
IMAGE_MARGIN_BOTTOM = 20

VECTOR_LINE_WIDTH = 1
VECTOR_LINE_WIDTH_ACCENT = 2
VECTOR_CHART_HEIGHT = 320

LOGO_SIZE = 40
LOGO_MARGIN_BOTTOM = 10

# Constantes pour les pixmaps (entiers 0-255)
PIXMAP_WHITE = 255
PIXMAP_BLUE = (0, 0, 255)
PIXMAP_RED = (255, 0, 0)

# Constantes pour les dessins vectoriels (flottants 0.0-1.0)
VECTOR_BLACK = (0.0, 0.0, 0.0)
VECTOR_BLUE = (0.0, 0.0, 1.0)


def make_report(path: Path, pages: list[PageData]) -> Path:
    """
    Purpose: Write a PDF with one page per dict in the pages list.
    Inputs:
        path: Path - the file path to write.
        pages: list[PageData] - list of page dictionaries.
    Outputs: Path - the path to the created PDF file.
    Raises:
        ValueError: if the pages list is empty.
    """
    if not pages:
        raise ValueError("Cannot create a PDF with zero pages")
    
    doc = fitz.open()

    for page_data in pages:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

        y_pos = MARGIN_TOP

        if "text" in page_data and page_data["text"]:
            font_size = page_data.get("font_size", FONT_SIZE_DEFAULT)
            page.insert_text((MARGIN_LEFT, y_pos), page_data["text"], fontsize=font_size)
            y_pos += font_size + LINE_SPACING

        if "image" in page_data and page_data["image"]:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT))
            pix.clear_with(PIXMAP_WHITE)
            for y in range(IMAGE_HEIGHT):
                for x in range(IMAGE_WIDTH):
                    if 1 < x < 5 and 1 < y < 3:
                        pix.set_pixel(x, y, PIXMAP_BLUE)
            page.insert_image(fitz.Rect(MARGIN_LEFT, y_pos, MARGIN_LEFT + IMAGE_WIDTH, y_pos + IMAGE_HEIGHT), pixmap=pix)
            y_pos += IMAGE_HEIGHT + IMAGE_MARGIN_BOTTOM

        if "vector_chart" in page_data and page_data["vector_chart"]:
            page.draw_line(fitz.Point(MARGIN_LEFT, y_pos + 100), fitz.Point(550, y_pos + 100), color=VECTOR_BLACK, width=VECTOR_LINE_WIDTH)
            page.draw_line(fitz.Point(MARGIN_LEFT, y_pos + 100), fitz.Point(MARGIN_LEFT, y_pos + 300), color=VECTOR_BLACK, width=VECTOR_LINE_WIDTH)
            page.draw_line(fitz.Point(MARGIN_LEFT, y_pos + 150), fitz.Point(550, y_pos + 150), color=VECTOR_BLUE, width=VECTOR_LINE_WIDTH_ACCENT)
            page.insert_text((MARGIN_LEFT, y_pos + VECTOR_CHART_HEIGHT), "Chart", fontsize=FONT_SIZE_LABEL)
            y_pos += VECTOR_CHART_HEIGHT

        if "logo" in page_data and page_data["logo"]:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, LOGO_SIZE, LOGO_SIZE))
            pix.clear_with(PIXMAP_WHITE)
            for y in range(LOGO_SIZE):
                for x in range(LOGO_SIZE):
                    pix.set_pixel(x, y, PIXMAP_RED)
            page.insert_image(fitz.Rect(MARGIN_LEFT, y_pos, MARGIN_LEFT + LOGO_SIZE, y_pos + LOGO_SIZE), pixmap=pix)
            y_pos += LOGO_SIZE + LOGO_MARGIN_BOTTOM

        if "caption" in page_data and page_data["caption"]:
            page.insert_text((MARGIN_LEFT, y_pos), page_data["caption"], fontsize=FONT_SIZE_CAPTION)

    doc.save(str(path))
    doc.close()
    return path


def image_info(path: Path) -> list[ImageInfo]:
    """
    Purpose: Return info about embedded images in the PDF for testing.
    Inputs:
        path: Path - the file path to the PDF.
    Outputs:
        list[ImageInfo] - list of dicts with page, width, height for each embedded image.
    """
    doc = fitz.open(str(path))
    images = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        for img in page.get_image_info():
            images.append({
                "page": page_num,
                "width": img["width"],
                "height": img["height"]
            })
    doc.close()
    return images
