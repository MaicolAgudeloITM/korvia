import zipfile
from io import BytesIO
from unittest.mock import patch

import pymupdf as fitz
from docx import Document
from openpyxl import Workbook
from PIL import Image
from pptx import Presentation

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


def make_odf(body: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
        f"<office:body>{body}</office:body>"
        "</office:document-content>"
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("content.xml", xml)
    return output.getvalue()


def test_text_data_formats_keep_line_reference() -> None:
    cases = {
        "notas.txt": b"El filtro cada seis meses.",
        "notas.log": b"El filtro cada seis meses.",
        "notas.json": b'{"frecuencia": "seis meses"}',
        "notas.xml": b"<raiz><frecuencia>seis meses</frecuencia></raiz>",
        "notas.yaml": b"frecuencia: seis meses\n",
        "notas.yml": b"frecuencia: seis meses\n",
    }

    for filename, content in cases.items():
        result = process_document(filename, content)
        assert result.extraction_method == "text", filename
        assert "seis meses" in result.chunks[0].text, filename
        assert result.chunks[0].sources == ("línea 1",), filename


def test_csv_and_tsv_become_rows() -> None:
    csv_result = process_document(
        "historial.csv", b"Maquina,Frecuencia\nPrensa A,seis meses\n"
    )
    tsv_result = process_document(
        "historial.tsv", b"Maquina\tFrecuencia\nPrensa A\tseis meses\n"
    )

    assert csv_result.chunks[0].text == "Maquina | Frecuencia\nPrensa A | seis meses"
    assert csv_result.chunks[0].sources == ("fila 1", "fila 2")
    assert "Prensa A | seis meses" in tsv_result.chunks[0].text


def test_html_de_una_sola_linea_extrae_texto_y_cita_la_linea() -> None:
    content = (
        b"<html><head><style>.filtro{color:red}</style>"
        b"<script>no sirve</script></head><body>"
        b"<h1>Mantenimiento</h1><p>El filtro cada seis meses.</p>"
        b"</body></html>"
    )

    result = process_document("manual.html", content)

    assert "no sirve" not in result.chunks[0].text
    assert "color:red" not in result.chunks[0].text
    assert "Mantenimiento" in result.chunks[0].text
    assert "El filtro cada seis meses." in result.chunks[0].text
    assert result.chunks[0].sources == ("línea 1",)


def test_html_removes_tags_and_scripts() -> None:
    content = (
        b"<html>\n"
        b"<script>no sirve</script>\n"
        b"<h1>Mantenimiento</h1>\n"
        b"<p>El filtro <b>cada seis meses</b>.</p>\n"
        b"</html>\n"
    )

    result = process_document("manual.html", content)

    assert "no sirve" not in result.chunks[0].text
    assert "Mantenimiento" in result.chunks[0].text
    assert "cada seis meses" in result.chunks[0].text
    assert "línea 3" in result.chunks[0].sources


def test_rtf_strips_control_words() -> None:
    result = process_document("notas.rtf", b"{\\rtf1\\ansi El filtro cada seis meses.}")

    assert "El filtro cada seis meses." in result.chunks[0].text


def test_pptx_extracts_slides_and_tables() -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(0, 0, 100, 100).text_frame.text = "El filtro cada seis meses."
    table_shape = slide.shapes.add_table(1, 2, 0, 100, 200, 50)
    table_shape.table.cell(0, 0).text = "Frecuencia"
    table_shape.table.cell(0, 1).text = "seis meses"
    output = BytesIO()
    presentation.save(output)

    result = process_document("charla.pptx", output.getvalue())

    assert result.extraction_method == "text"
    assert "diapositiva 1" in result.chunks[0].sources
    assert "Frecuencia | seis meses" in result.chunks[0].text
    assert "diapositiva 1, tabla, fila 1" in result.chunks[0].sources


def test_odt_extracts_paragraphs() -> None:
    body = "<office:text><text:p>El filtro cada seis meses.</text:p></office:text>"

    result = process_document("notas.odt", make_odf(body))

    assert result.chunks[0].text == "El filtro cada seis meses."
    assert result.chunks[0].sources == ("párrafo 1",)


def test_ods_extracts_rows() -> None:
    body = (
        '<office:spreadsheet><table:table table:name="Mantenimientos">'
        "<table:table-row>"
        "<table:table-cell><text:p>Maquina</text:p></table:table-cell>"
        "<table:table-cell><text:p>seis meses</text:p></table:table-cell>"
        "</table:table-row></table:table></office:spreadsheet>"
    )

    result = process_document("historial.ods", make_odf(body))

    assert "Maquina | seis meses" in result.chunks[0].text
    assert "hoja Mantenimientos, fila 1" in result.chunks[0].sources


def test_odp_extracts_slides() -> None:
    body = (
        '<office:presentation><draw:page draw:name="1">'
        "<text:p>El filtro cada seis meses.</text:p>"
        "</draw:page></office:presentation>"
    )

    result = process_document("charla.odp", make_odf(body))

    assert result.chunks[0].text == "El filtro cada seis meses."
    assert result.chunks[0].sources == ("diapositiva 1",)


def test_image_uses_ocr_and_keeps_reference() -> None:
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")

    with patch(
        "korvia.document_processing._recognize_image",
        return_value="Texto leido de la imagen",
    ):
        result = process_document("foto.png", output.getvalue())

    assert result.extraction_method == "ocr"
    assert result.chunks[0].text == "Texto leido de la imagen"
    assert result.chunks[0].sources == ("imagen (OCR)",)


def test_unsupported_format_is_rejected() -> None:
    try:
        process_document("programa.exe", b"MZ\x90\x00")
    except UnsupportedDocumentType as exc:
        assert ".pdf" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazar el formato CSV.")
