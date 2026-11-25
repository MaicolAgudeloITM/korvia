from io import BytesIO
from unittest.mock import patch

import pymupdf as fitz
from docx import Document
from openpyxl import Workbook

from korvia.document_processing import (
    TextBlock,
    UnsupportedDocumentType,
    chunk_blocks,
    process_document,
)


def make_pdf(text: str | None = None) -> bytes:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_pdf_extracts_text_and_page_reference() -> None:
    result = process_document("manual.pdf", make_pdf("Revisar el equipo cada 500 horas."))

    assert result.extraction_method == "text"
    assert result.chunks[0].text == "Revisar el equipo cada 500 horas."
    assert result.chunks[0].sources == ("página 1",)


def test_scanned_pdf_uses_ocr_and_keeps_page_reference() -> None:
    with patch("korvia.document_processing._ocr_pdf_page", return_value="Texto reconocido por OCR"):
        result = process_document("escaneo.pdf", make_pdf())

    assert result.extraction_method == "ocr"
    assert result.chunks[0].text == "Texto reconocido por OCR"
    assert result.chunks[0].sources == ("página 1 (OCR)",)


def test_docx_extracts_paragraphs_and_table_rows() -> None:
    document = Document()
    document.add_paragraph("Procedimiento de mantenimiento")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Frecuencia"
    table.cell(0, 1).text = "500 horas"
    output = BytesIO()
    document.save(output)

    result = process_document("manual.docx", output.getvalue())

    assert result.extraction_method == "text"
    assert "Procedimiento de mantenimiento" in result.chunks[0].text
    assert "Frecuencia | 500 horas" in result.chunks[0].text
    assert result.chunks[0].sources == ("párrafo 1", "tabla 1, fila 1")


def test_xlsx_keeps_sheet_and_row_reference() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Mantenimientos"
    sheet.append(["Máquina", "Último mantenimiento"])
    sheet.append(["Prensa A", "2026-10-15"])
    output = BytesIO()
    workbook.save(output)

    result = process_document("historial.xlsx", output.getvalue())

    assert "Prensa A | 2026-10-15" in result.chunks[0].text
    assert "hoja Mantenimientos, fila 2" in result.chunks[0].sources


def test_markdown_extracts_lines_without_format_marks() -> None:
    content = (
        "# Mantenimiento\n\n"
        "El filtro **cada seis meses**.\n"
        "- Revisar [manual](https://ejemplo.com/docs).\n"
    )

    result = process_document("manual.md", content.encode("utf-8"))

    assert result.extraction_method == "text"
    assert result.chunks[0].text == (
        "Mantenimiento\nEl filtro cada seis meses.\nRevisar manual."
    )
    assert result.chunks[0].sources == ("línea 1", "línea 3", "línea 4")
    assert "https" not in result.chunks[0].text


def test_markdown_accepts_bom_and_warns_on_other_encoding() -> None:
    result = process_document("notas.md", b"\xef\xbb\xbf# Instalaci\xc3\xb3n\nEl filtro.")

    assert "Instalación" in result.chunks[0].text

    result = process_document("notas.md", "El café".encode("cp1252"))

    assert "café" in result.chunks[0].text
    assert any("codificación" in warning for warning in result.warnings)


def test_markdown_without_text_reports_warning() -> None:
    result = process_document("vacio.md", b"\n# \n<!-- solo un comentario -->\n")

    assert result.chunks == ()
    assert any("texto legible" in warning for warning in result.warnings)


def test_long_text_is_split_and_retains_source() -> None:
    chunks = chunk_blocks(
        [TextBlock("palabra " * 100, "página 4")],
        chunk_size=80,
        chunk_overlap=10,
    )

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 80 for chunk in chunks)
    assert all(chunk.sources == ("página 4",) for chunk in chunks)


def test_unsupported_format_is_rejected() -> None:
    try:
        process_document("datos.csv", b"a,b\n1,2")
    except UnsupportedDocumentType as exc:
        assert ".pdf" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazar el formato CSV.")
