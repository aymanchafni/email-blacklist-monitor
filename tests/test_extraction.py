import io
import shutil

import pandas as pd
import pytest

from blacklist_monitor.extraction import extract_text, is_supported
from blacklist_monitor.matching import Blacklist

BL = Blacklist(pd.DataFrame([{"first_name": "Jane", "last_name": "Example", "cin": "ZZ000001", "imm": "99999-A-01"}]))


def test_excel_attachment_is_read_and_matched():
    # Previously openpyxl was missing from requirements: every .xlsx silently produced "".
    buf = io.BytesIO()
    df = pd.DataFrame({"Prénom": ["Bob", "Jane"], "Nom": ["Other", "Example"], "Montant": [10, 20]})
    df.to_excel(buf, index=False)
    text = extract_text(buf.getvalue(), "list.xlsx")
    assert [m.field for m in BL.find_matches(text)] == ["full_name"]


def test_csv_attachment_any_delimiter():
    text = extract_text("nom;prenom;cin\nExample;Jane;zz000001\n".encode(), "export.csv")
    assert sorted(m.field for m in BL.find_matches(text)) == ["cin", "full_name"]


def test_pdf_attachment():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Vehicle registration: 99999-A-01")
    text = extract_text(doc.tobytes(), "report.pdf")
    assert [m.field for m in BL.find_matches(text)] == ["imm"]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_image_attachment_ocr():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(img).text((20, 40), "CIN ZZ000001", fill="black", font_size=48)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert [m.field for m in BL.find_matches(extract_text(buf.getvalue(), "scan.png"))] == ["cin"]


def test_supported_types():
    assert is_supported("A.PDF") and is_supported("b.xlsx") and is_supported("c.jpeg")
    assert not is_supported("d.docx")
