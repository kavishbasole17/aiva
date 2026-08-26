"""Renders a persisted EvaluationReport.payload into a downloadable PDF or
Excel file. Pure functions over the payload dict — no DB access here, so
these are trivially unit-testable on a fixed fixture payload.
"""

import io
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def render_pdf(payload: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(f"Evaluation report — {payload['candidate_email']}", styles["Title"]),
        Paragraph(f"Requisition: {payload['requisition_title']}", styles["Normal"]),
        Spacer(1, 0.2 * inch),
        Paragraph(
            f"Overall score: {payload['overall_score']} — "
            f"{str(payload['verdict']).replace('_', ' ').title()}",
            styles["Heading2"],
        ),
        Spacer(1, 0.15 * inch),
    ]

    table_data = [["Component", "Score", "Detail"]]
    for component in payload["components"]:
        table_data.append(
            [str(component["name"]).title(), str(component["score"]), component["detail"]]
        )
    table = Table(table_data, colWidths=[1.3 * inch, 0.8 * inch, 4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0a2f5c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    if payload.get("narrative"):
        story.append(Paragraph("Narrative", styles["Heading3"]))
        story.append(Paragraph(str(payload["narrative"]), styles["Normal"]))
        story.append(Spacer(1, 0.15 * inch))

    for label, key in (("Strengths", "strengths"), ("Concerns", "concerns")):
        items = payload.get(key)
        if items:
            story.append(Paragraph(label, styles["Heading3"]))
            for item in items:
                story.append(Paragraph(f"• {item}", styles["Normal"]))
            story.append(Spacer(1, 0.15 * inch))

    doc.build(story)
    return buffer.getvalue()


def render_xlsx(payload: dict[str, Any]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("openpyxl Workbook() has no active worksheet")
    sheet.title = "Evaluation"
    sheet.append(["Candidate", payload["candidate_email"]])
    sheet.append(["Requisition", payload["requisition_title"]])
    sheet.append(["Overall score", payload["overall_score"]])
    sheet.append(["Verdict", payload["verdict"]])
    sheet.append([])
    sheet.append(["Component", "Score", "Detail"])
    for component in payload["components"]:
        sheet.append([component["name"], component["score"], component["detail"]])

    if payload.get("narrative"):
        sheet.append([])
        sheet.append(["Narrative", payload["narrative"]])

    for label, key in (("Strengths", "strengths"), ("Concerns", "concerns")):
        items = payload.get(key)
        if items:
            sheet.append([])
            sheet.append([label])
            for item in items:
                sheet.append([item])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


__all__ = ["render_pdf", "render_xlsx"]
