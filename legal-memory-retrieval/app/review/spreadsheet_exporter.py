"""
Spreadsheet Exporter: Generates styled multi-sheet Excel (.xlsx) and CSV workbooks for Tabular Reviews.
Clean-room independent implementation.
"""

import io
from typing import Any, Dict, List
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


class SpreadsheetExporter:
    """Exports structured review matrices into professional legal-grade Excel workbooks."""

    @staticmethod
    def export_xlsx(
        title: str,
        columns: List[Dict[str, Any]],
        rows: List[Dict[str, Any]],
        cells: Dict[str, Dict[str, Any]],
    ) -> bytes:
        wb = openpyxl.Workbook()
        
        # --- Sheet 1: Matrix Review ---
        ws_matrix = wb.active
        ws_matrix.title = "Review Matrix"
        ws_matrix.views.sheetView[0].showGridLines = True

        # Styles
        header_fill = PatternFill(start_color="1A1D20", end_color="1A1D20", fill_type="solid")
        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell_font = Font(name="Arial", size=10)
        border_thin = Side(border_style="thin", color="E0E0E0")
        cell_border = Border(top=border_thin, left=border_thin, right=border_thin, bottom=border_thin)

        # Title Row
        ws_matrix.merge_cells("A1:E1")
        title_cell = ws_matrix["A1"]
        title_cell.value = f"FirmOS Legal Intelligence — {title}"
        title_cell.font = Font(name="Arial", size=14, bold=True, color="1A1D20")
        title_cell.alignment = Alignment(vertical="center")
        ws_matrix.row_dimensions[1].height = 30

        # Header row (Row 3)
        headers = ["Document ID", "Title / Matter"] + [col["label"] for col in columns]
        for col_idx, h_text in enumerate(headers, 1):
            c = ws_matrix.cell(row=3, column=col_idx, value=h_text)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = cell_border
        ws_matrix.row_dimensions[3].height = 28

        # Data rows
        citations_data: List[Dict[str, Any]] = []
        for r_idx, row in enumerate(rows, 4):
            doc_id = row.get("document_id", "")
            doc_title = row.get("title", doc_id)

            c_id = ws_matrix.cell(row=r_idx, column=1, value=doc_id)
            c_id.font = Font(name="Arial", size=10, bold=True)
            c_id.border = cell_border

            c_title = ws_matrix.cell(row=r_idx, column=2, value=doc_title)
            c_title.font = cell_font
            c_title.border = cell_border

            doc_cells = cells.get(doc_id, {})
            for c_idx, col in enumerate(columns, 3):
                col_id = col["id"]
                cell_val = doc_cells.get(col_id, {})
                ans_text = cell_val.get("value", "—")
                confidence = cell_val.get("confidence", 1.0)
                cited_chunks = cell_val.get("citations", [])

                c_data = ws_matrix.cell(row=r_idx, column=c_idx, value=ans_text)
                c_data.font = cell_font
                c_data.border = cell_border
                c_data.alignment = Alignment(vertical="top", wrap_text=True)

                if cited_chunks:
                    for chunk in cited_chunks:
                        citations_data.append({
                            "doc_id": doc_id,
                            "column": col["label"],
                            "value": ans_text,
                            "chunk_id": chunk,
                            "reasoning": cell_val.get("reasoning", ""),
                        })

            ws_matrix.row_dimensions[r_idx].height = 24

        # Auto-adjust column widths
        for col in ws_matrix.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_matrix.column_dimensions[col_letter].width = min(max(max_len + 4, 15), 45)

        # --- Sheet 2: Citations & Evidence ---
        if citations_data:
            ws_citations = wb.create_sheet(title="Evidence & Citations")
            ws_citations.views.sheetView[0].showGridLines = True
            c_headers = ["Document ID", "Review Field", "Extracted Value", "Source Chunk ID", "Reasoning Trace"]
            for col_idx, h_text in enumerate(c_headers, 1):
                c = ws_citations.cell(row=1, column=col_idx, value=h_text)
                c.fill = header_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = cell_border

            for idx, cit in enumerate(citations_data, 2):
                ws_citations.cell(row=idx, column=1, value=cit["doc_id"]).border = cell_border
                ws_citations.cell(row=idx, column=2, value=cit["column"]).border = cell_border
                ws_citations.cell(row=idx, column=3, value=cit["value"]).border = cell_border
                ws_citations.cell(row=idx, column=4, value=cit["chunk_id"]).border = cell_border
                ws_citations.cell(row=idx, column=5, value=cit["reasoning"]).border = cell_border

            for col in ws_citations.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws_citations.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 60)

        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()
