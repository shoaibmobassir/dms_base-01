"""
Generation tools: generate_docx and generate_excel callable by the LLM agent.
Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import io
import os
import uuid
from typing import Any

from app.config import settings


def generate_docx(title: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Generate a Word (.docx) document from structured section content.
    Returns a download URL and document metadata.
    """
    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt, Inches
    except ImportError:
        return {"error": "python-docx not installed. Cannot generate DOCX files."}

    doc = DocxDocument()
    # Title
    doc.add_heading(title, level=0)

    for section in sections:
        page_break = section.get("pageBreak", False)
        if page_break:
            doc.add_page_break()

        heading = section.get("heading")
        level = section.get("level", 1)
        if heading:
            doc.add_heading(heading, level=min(level, 3))

        content = section.get("content", "")
        if content:
            for para_text in content.split("\n\n"):
                para_text = para_text.strip()
                if para_text:
                    doc.add_paragraph(para_text)

        # Tables
        table_data = section.get("table")
        if table_data:
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            if headers:
                table = doc.add_table(rows=1 + len(rows), cols=len(headers))
                table.style = "Light Grid Accent 1"
                for i, header in enumerate(headers):
                    table.rows[0].cells[i].text = header
                for row_idx, row in enumerate(rows):
                    for col_idx, cell_val in enumerate(row):
                        if col_idx < len(headers):
                            table.rows[row_idx + 1].cells[col_idx].text = str(cell_val)

    # Save to object store
    filename = f"{title.replace(' ', '_')}.docx"
    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    file_path = _save_generated_file(doc_id, filename, doc)

    download_url = f"/api/documents/{doc_id}/download"
    return {
        "filename": filename,
        "download_url": download_url,
        "document_id": doc_id,
        "version_id": version_id,
        "event": {
            "type": "doc_created",
            "filename": filename,
            "download_url": download_url,
            "document_id": doc_id,
            "version_id": version_id,
        },
    }


def generate_excel(title: str, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Generate an Excel (.xlsx) workbook from structured sheet data.
    Returns a download URL and document metadata.
    """
    try:
        import openpyxl
    except ImportError:
        return {"error": "openpyxl not installed. Cannot generate Excel files."}

    wb = openpyxl.Workbook()
    # Remove default sheet
    if wb.active:
        wb.remove(wb.active)

    for sheet_data in sheets:
        ws = wb.create_sheet(title=sheet_data.get("name", "Sheet"))
        columns = sheet_data.get("columns", [])
        rows = sheet_data.get("rows", [])

        # Header row
        for col_idx, col_name in enumerate(columns, 1):
            ws.cell(row=1, column=col_idx, value=col_name)

        # Data rows
        for row_idx, row in enumerate(rows, 2):
            for col_idx, cell_val in enumerate(row, 1):
                ws.cell(row=row_idx, column=col_idx, value=cell_val)

    filename = f"{title.replace(' ', '_')}.xlsx"
    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    # Save to object store
    output_dir = os.path.join(settings.object_store_root, "generated")
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{doc_id}_{filename}")
    wb.save(file_path)

    download_url = f"/api/documents/{doc_id}/download"
    return {
        "filename": filename,
        "download_url": download_url,
        "document_id": doc_id,
        "version_id": version_id,
        "event": {
            "type": "doc_created",
            "filename": filename,
            "download_url": download_url,
            "document_id": doc_id,
            "version_id": version_id,
        },
    }


def _save_generated_file(doc_id: str, filename: str, doc: Any) -> str:
    """Save a generated DOCX file to the local object store."""
    output_dir = os.path.join(settings.object_store_root, "generated")
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{doc_id}_{filename}")
    doc.save(file_path)
    return file_path
