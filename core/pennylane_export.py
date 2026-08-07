"""Génère le classeur Excel au format d'import avancé Pennylane."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.converter import PENNYLANE_COLUMNS, ConversionResult


def build_pennylane_workbook(resultats: list[ConversionResult]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Import Pennylane"

    header_font = Font(bold=True, color="FFFFFF", name="Arial")
    header_fill = PatternFill("solid", fgColor="1F4E5F")
    for c, name in enumerate(PENNYLANE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    row_idx = 2
    for res in resultats:
        for ligne in res.lignes:
            for c, name in enumerate(PENNYLANE_COLUMNS, start=1):
                val = ligne.get(name, "")
                cell = ws.cell(row=row_idx, column=c, value=val if val != "" else None)
                cell.font = Font(name="Arial", size=10)
                if name in ("Débit et/ou Crédit", "Crédit") and isinstance(val, (int, float)) and val:
                    cell.number_format = "#,##0.00"
            row_idx += 1

    widths = [10, 10, 14, 30, 26, 12, 10, 24, 14, 12, 10, 20, 14, 14, 10, 12, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
