"""Extracción local de texto y fragmentos con referencias al documento de origen."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md"}


class DocumentProcessingError(ValueError):
    """El documento no se pudo leer o no contiene texto utilizable."""


class UnsupportedDocumentType(DocumentProcessingError):
    """El formato no está soportado por el prototipo."""


class OCRUnavailableError(RuntimeError):
    """Se necesita OCR, pero Tesseract no está disponible o mal configurado."""


class OCRProcessingError(RuntimeError):
    """Tesseract está disponible, pero no pudo reconocer una página."""


@dataclass(frozen=True)
class TextBlock:
    text: str
    source: str


@dataclass(frozen=True)
class TextChunk:
    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ProcessedDocument:
    extraction_method: str
    blocks: tuple[TextBlock, ...]
    chunks: tuple[TextChunk, ...]
    warnings: tuple[str, ...]


def process_document(
    filename: str,
    content: bytes,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
) -> ProcessedDocument:
    """Extrae PDF, Word, Excel o Markdown y devuelve fragmentos con referencias."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedDocumentType(f"Formato no soportado. Usa: {allowed}.")
    if not content:
        raise DocumentProcessingError("El archivo está vacío.")

    warnings: list[str] = []
    methods: set[str] = set()
    if extension == ".pdf":
        blocks = _extract_pdf(content, methods, warnings)
    elif extension == ".docx":
        blocks = _extract_docx(content)
        methods.add("text")
    elif extension == ".md":
        blocks = _extract_markdown(content, warnings)
        methods.add("text")
    else:
        blocks = _extract_xlsx(content)
        methods.add("text")

    chunks = chunk_blocks(blocks, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not blocks:
        warnings.append("No se encontró texto legible en el documento.")

    extraction_method = "+".join(sorted(methods)) if methods else "none"
    return ProcessedDocument(
        extraction_method=extraction_method,
        blocks=tuple(blocks),
        chunks=tuple(chunks),
        warnings=tuple(warnings),
    )


def _extract_pdf(
    content: bytes,
    methods: set[str],
    warnings: list[str],
) -> list[TextBlock]:
    try:
        import pymupdf as fitz

        pdf = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise DocumentProcessingError("No pude abrir el PDF. Verifica que el archivo sea válido.") from exc

    blocks: list[TextBlock] = []
    try:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                methods.add("text")
                blocks.append(TextBlock(text=text, source=f"página {page_number}"))
                continue

            text = _ocr_pdf_page(page).strip()
            if text:
                methods.add("ocr")
                blocks.append(TextBlock(text=text, source=f"página {page_number} (OCR)"))
            else:
                warnings.append(f"No se pudo extraer texto de la página {page_number}.")
    finally:
        pdf.close()
    return blocks


def _ocr_pdf_page(page: object) -> str:
    try:
        import pymupdf as fitz
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailableError(
            "Este PDF parece escaneado. Para leerlo instala PyMuPDF, Pillow, pytesseract y Tesseract OCR."
        ) from exc

    command = os.getenv("TESSERACT_CMD")
    if command:
        pytesseract.pytesseract.tesseract_cmd = command

    languages = os.getenv("KORVIA_OCR_LANGUAGES", "spa+eng")
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        return pytesseract.image_to_string(image, lang=languages)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRUnavailableError(
            "Este PDF parece escaneado, pero no encuentro Tesseract OCR. Instálalo y verifica los idiomas español e inglés."
        ) from exc
    except pytesseract.TesseractError as exc:
        raise OCRProcessingError(
            "Tesseract no pudo leer la página. Verifica que tenga instalados los idiomas configurados."
        ) from exc


def _extract_docx(content: bytes) -> list[TextBlock]:
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(BytesIO(content))
        blocks: list[TextBlock] = []
        paragraph_number = 0
        table_number = 0

        # Recorre párrafos y tablas en el orden en que aparecen en Word.
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph_number += 1
                text = Paragraph(child, document).text.strip()
                if text:
                    blocks.append(TextBlock(text, f"párrafo {paragraph_number}"))
            elif child.tag == qn("w:tbl"):
                table_number += 1
                table = Table(child, document)
                for row_number, row in enumerate(table.rows, start=1):
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    text = " | ".join(value for value in cells if value)
                    if text:
                        blocks.append(
                            TextBlock(text, f"tabla {table_number}, fila {row_number}")
                        )
        return blocks
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("No pude abrir el archivo Word. Verifica que sea un DOCX válido.") from exc


def _extract_xlsx(content: bytes) -> list[TextBlock]:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        blocks: list[TextBlock] = []
        try:
            for sheet in workbook.worksheets:
                for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                    if values:
                        blocks.append(
                            TextBlock(" | ".join(values), f"hoja {sheet.title}, fila {row_number}")
                        )
        finally:
            workbook.close()
        return blocks
    except Exception as exc:
        raise DocumentProcessingError("No pude abrir el archivo Excel. Verifica que sea un XLSX válido.") from exc


def _extract_markdown(content: bytes, warnings: list[str]) -> list[TextBlock]:
    """Lee un .md como texto plano y guarda el número de línea de cada fragmento."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append("El archivo no estaba en UTF-8; se leyó con otra codificación.")
        text = content.decode("cp1252", errors="replace")

    blocks: list[TextBlock] = []
    in_comment = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if in_comment:
            if "-->" in value:
                in_comment = False
            continue
        if value.startswith("<!--"):
            in_comment = "-->" not in value
            continue
        if not value or value.startswith("```"):
            continue
        clean = _clean_markdown_line(value)
        if clean:
            blocks.append(TextBlock(text=clean, source=f"línea {line_number}"))
    return blocks


def _clean_markdown_line(text: str) -> str:
    """Quita los signos de formato de Markdown sin borrar el contenido."""
    if re.fullmatch(r"[#>*+\-_`\s]+", text):
        return ""
    text = re.sub(r"^#{1,6}\s+", "", text)
    text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", text)
    text = re.sub(r"^>\s?", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("__", "").replace("`", "").strip()


def chunk_blocks(
    blocks: Iterable[TextBlock],
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
) -> list[TextChunk]:
    """Agrupa texto sin perder la referencia a página, párrafo, tabla u hoja."""
    if chunk_size < 1:
        raise ValueError("chunk_size debe ser mayor que cero.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap debe ser cero o menor que chunk_size.")

    chunks: list[TextChunk] = []
    pending: list[TextBlock] = []
    pending_length = 0

    def flush() -> None:
        nonlocal pending, pending_length
        if not pending:
            return
        text = "\n".join(block.text for block in pending)
        sources = tuple(dict.fromkeys(block.source for block in pending))
        chunks.append(TextChunk(text=text, sources=sources))
        pending = []
        pending_length = 0

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if len(text) > chunk_size:
            flush()
            for part in _split_long_text(text, chunk_size, chunk_overlap):
                chunks.append(TextChunk(text=part, sources=(block.source,)))
            continue

        extra_length = len(text) + (1 if pending else 0)
        if pending and pending_length + extra_length > chunk_size:
            flush()
        pending.append(TextBlock(text, block.source))
        pending_length += len(text) + (1 if len(pending) > 1 else 0)

    flush()
    return chunks


def _split_long_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return parts
