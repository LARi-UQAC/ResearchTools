"""
_fixtures - synthetic OOXML parts for the paper2talk offline tests.

Building a .pptx by hand in the test keeps the suite offline: no PowerPoint, no
LibreOffice, no template file on disk, and every structural defect the validator is
supposed to catch can be injected deliberately.

Not a test module: the leading underscore keeps it out of discovery.
"""
from __future__ import annotations

import os
import sys
import zipfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

EMU_PER_INCH = 914400


def slide_xml(body: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{NS_P}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
        f"<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>"
    )


def notes_xml(text: str, slide_number: str = "7") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:notes xmlns:p="{NS_P}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p>"
        f'<a:fld id="{{1}}" type="slidenum"><a:t>{slide_number}</a:t></a:fld>'
        f"<a:t>{text}</a:t></a:p></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:notes>"
    )


def pic_xml(name: str = "Picture 1", x_in: float = 1.0, y_in: float = 2.0,
            w_in: float = 4.0, h_in: float = 3.0, rid: str = "rId2",
            src_rect: dict | None = None) -> str:
    rect = ""
    if src_rect:
        attrs = " ".join(f'{k}="{v}"' for k, v in src_rect.items())
        rect = f"<a:srcRect {attrs}/>"
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="4" name="{name}"/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/>{rect}</p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{int(x_in * EMU_PER_INCH)}" '
        f'y="{int(y_in * EMU_PER_INCH)}"/>'
        f'<a:ext cx="{int(w_in * EMU_PER_INCH)}" cy="{int(h_in * EMU_PER_INCH)}"/>'
        "</a:xfrm></p:spPr></p:pic>"
    )


def sp_xml(name: str = "Body 1", text: str = "hello", sz: int = 1600,
           bold: bool = False, algn: str = "l", x_in: float = 0.5,
           y_in: float = 1.0, w_in: float = 9.0, h_in: float = 1.0,
           autofit: bool = False) -> str:
    fit = '<a:normAutofit fontScale="70000"/>' if autofit else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="5" name="{name}"/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{int(x_in * EMU_PER_INCH)}" '
        f'y="{int(y_in * EMU_PER_INCH)}"/>'
        f'<a:ext cx="{int(w_in * EMU_PER_INCH)}" cy="{int(h_in * EMU_PER_INCH)}"/>'
        f"</a:xfrm></p:spPr><p:txBody><a:bodyPr>{fit}</a:bodyPr>"
        f'<a:p><a:pPr algn="{algn}"/>'
        f'<a:r><a:rPr lang="en-US" sz="{sz}" b="{1 if bold else 0}">'
        f'<a:latin typeface="Calibri"/></a:rPr><a:t>{text}</a:t></a:r></a:p>'
        "</p:txBody></p:sp>"
    )


def graphic_frame_xml() -> str:
    return (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="9" name="Chart 1"/>'
        "</p:nvGraphicFramePr><a:graphic><a:graphicData/></a:graphic></p:graphicFrame>"
    )


def equation_run_xml() -> str:
    """A run carrying a superscript baseline, which is how an equation is faked."""
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="7" name="Equation"/></p:nvSpPr><p:txBody>'
        '<a:p><a:r><a:rPr sz="1800" baseline="30000"/><a:t>x2</a:t></a:r></a:p>'
        "</p:txBody></p:sp>"
    )


def _rels(entries: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>'
        for rid, typ, target in entries
    )
    return f'<?xml version="1.0"?><Relationships xmlns="{NS_REL}">{body}</Relationships>'


def build_pptx(path: str, slides: list[dict], sld_size_in: tuple[float, float] = (10.0, 7.5),
               charts: dict[str, str] | None = None,
               master_background: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a minimal but structurally valid .pptx from slide descriptions, so
        the offline tests can exercise the readers and the validator.

    Inputs:
        path (str): destination .pptx
        slides (list): one dict per slide, keys:
            body (str)          the spTree content
            notes (str)         notes text, or None for no notes part
            notes_part (int)    force the notesSlideN number (to shuffle it)
            media (bool)        declare an image relationship for the picture
            dangling (bool)     omit the relationship the body references
        sld_size_in (tuple): slide size in inches
        charts (dict): part name -> xml, added under ppt/charts/
        master_background (str): media file name to reference from the master

    Outputs:
        path (str): the file written
    --------------------------------------------------------------------------
    """
    cx, cy = (int(v * EMU_PER_INCH) for v in sld_size_in)
    charts = charts or {}
    overrides = []
    with zipfile.ZipFile(path, "w") as z:
        sld_ids = []
        pres_rels = [("rId100", "http://schemas.openxmlformats.org/officeDocument/2006/"
                      "relationships/slideMaster", "slideMasters/slideMaster1.xml")]
        for i, spec in enumerate(slides, 1):
            part = f"ppt/slides/slide{i}.xml"
            z.writestr(part, slide_xml(spec.get("body", "")))
            overrides.append((part, "application/vnd.openxmlformats-officedocument."
                                    "presentationml.slide+xml"))
            entries = []
            if spec.get("media") and not spec.get("dangling"):
                entries.append(("rId2",
                                "http://schemas.openxmlformats.org/officeDocument/2006/"
                                "relationships/image", "../media/image1.png"))
            notes_no = spec.get("notes_part", i)
            if spec.get("notes") is not None:
                npart = f"ppt/notesSlides/notesSlide{notes_no}.xml"
                z.writestr(npart, notes_xml(spec["notes"]))
                overrides.append((npart, "application/vnd.openxmlformats-officedocument."
                                         "presentationml.notesSlide+xml"))
                entries.append(("rId3",
                                "http://schemas.openxmlformats.org/officeDocument/2006/"
                                "relationships/notesSlide",
                                f"../notesSlides/notesSlide{notes_no}.xml"))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", _rels(entries))
            rid = f"rId{200 + i}"
            sld_ids.append(rid)
            pres_rels.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/"
                              "relationships/slide", f"slides/slide{i}.xml"))

        for name, xml in charts.items():
            part = f"ppt/charts/{name}"
            z.writestr(part, xml)
            overrides.append((part, "application/vnd.openxmlformats-officedocument."
                                    "drawingml.chart+xml"))

        bg = ""
        master_rels = []
        if master_background:
            bg = ('<p:cSld><p:spTree><p:pic><p:blipFill>'
                  '<a:blip r:embed="rId7"/></p:blipFill></p:pic></p:spTree></p:cSld>')
            master_rels.append(("rId7", "http://schemas.openxmlformats.org/officeDocument/"
                                "2006/relationships/image", f"../media/{master_background}"))
            z.writestr(f"ppt/media/{master_background}", b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        else:
            bg = "<p:cSld><p:spTree/></p:cSld>"
        z.writestr("ppt/slideMasters/slideMaster1.xml",
                   f'<p:sldMaster xmlns:p="{NS_P}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
                   f"{bg}</p:sldMaster>")
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels(master_rels))
        overrides.append(("ppt/slideMasters/slideMaster1.xml",
                          "application/vnd.openxmlformats-officedocument."
                          "presentationml.slideMaster+xml"))

        z.writestr("ppt/slideLayouts/slideLayout1.xml",
                   f'<p:sldLayout xmlns:p="{NS_P}" xmlns:a="{NS_A}">'
                   '<p:cSld name="Title and Content"><p:spTree/></p:cSld></p:sldLayout>')
        overrides.append(("ppt/slideLayouts/slideLayout1.xml",
                          "application/vnd.openxmlformats-officedocument."
                          "presentationml.slideLayout+xml"))

        sld_id_list = "".join(
            f'<p:sldId id="{256 + i}" r:id="{rid}"/>' for i, rid in enumerate(sld_ids)
        )
        z.writestr(
            "ppt/presentation.xml",
            f'<?xml version="1.0"?><p:presentation xmlns:p="{NS_P}" xmlns:a="{NS_A}" '
            f'xmlns:r="{NS_R}"><p:sldIdLst>{sld_id_list}</p:sldIdLst>'
            f'<p:sldSz cx="{cx}" cy="{cy}"/></p:presentation>',
        )
        overrides.append(("ppt/presentation.xml", "application/vnd.openxmlformats-"
                          "officedocument.presentationml.presentation.main+xml"))
        z.writestr("ppt/_rels/presentation.xml.rels", _rels(pres_rels))

        parts = "".join(
            f'<Override PartName="/{name}" ContentType="{ctype}"/>'
            for name, ctype in overrides
        )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="rels" ContentType='
            '"application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            f"{parts}</Types>",
        )
    return path


def model(slides: list[dict], **meta) -> dict:
    """A talk_model.json dict with sane defaults, for the model and notes tests."""
    base_meta = {"title": "T", "authors": ["A"], "audience": "field",
                 "aspect": "4:3", "minutes": 13, "notes_lang": "en"}
    base_meta.update(meta)
    return {"meta": base_meta, "palette": {"brand": "5A7210"}, "slides": slides}
